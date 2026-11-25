"""SPEC section 9: storage."""

import json
from datetime import date
from decimal import Decimal as D

import pytest

from helpers import JAN_5, balances, invoice, issue, ledger_with, state
from tally import (
    ConflictError,
    Event,
    Ledger,
    Line,
    PaymentError,
    StoreError,
    aging,
    load,
    save,
    statement,
)

LATE = date(2026, 2, 20)  # 16 days after the 4 February due date


@pytest.fixture
def path(tmp_path):
    return tmp_path / "ledger.json"


def names(folder):
    return [p.name for p in folder.iterdir()]


def busy():
    """A ledger that has been through everything."""
    ledger = Ledger([date(2026, 7, 3), date(2026, 12, 25)])
    issue(
        ledger,
        "INV-1",
        terms=" 2/10 net 30 ",
        tax_rate="8.25",
        lines=[
            Line("Café work", "2.5", "99.99", "12.5"),
            Line("postage", 1, "0.3333333333333333333", taxable=False),
        ],
    )
    issue(ledger, "INV-2", "1000.00")
    issue(ledger, "INV-3", "70.00", tax_rate="10", tax_exempt=True, customer="Ünited")
    issue(ledger, "INV-4", "12.34")
    issue(ledger, "INV-5", "55.55")
    ledger.add(invoice("INV-6", "5.00", "EOM"))
    ledger.dispute("INV-4")
    ledger.void("INV-5", date(2026, 1, 6))
    ledger.receive("P1", "acme", ledger.invoices["INV-1"].total - D("4.38"), date(2026, 1, 7))
    ledger.receive("P2", "Ünited", "100.10", date(2026, 1, 8))
    ledger.assess_late_fees(LATE)
    ledger.receive("P3", "acme", "20.00", LATE)
    ledger.receive("P4", "acme", "33.00", LATE)
    ledger.reverse("P4", LATE)
    return ledger


# -- round trip ---------------------------------------------------------------


def test_busy_ledger_covers_every_kind_of_record():
    ledger = busy()
    assert {e.kind for e in ledger.events} == {
        "invoice", "fee", "payment", "discount", "reversal", "void",
    }
    assert {i.status for i in ledger.invoices.values()} == {"draft", "open", "paid", "void"}
    assert ledger.credit("Ünited") == D("30.10")


def test_load_after_save_gives_back_the_same_ledger(path):
    ledger = busy()
    before = state(ledger)
    save(ledger, path, 0)
    loaded, version = load(path)
    assert version == 1
    assert state(loaded) == before
    assert state(ledger) == before


def test_empty_ledger_round_trip(path):
    save(Ledger(), path, 0)
    loaded, version = load(path)
    assert (state(loaded), version) == (state(Ledger()), 1)


def test_amounts_come_back_exact(path):
    ledger = Ledger()
    issue(ledger, lines=[Line("a", "0.1", "12345678901234.5678", "0.05")], tax_rate="7.125")
    ledger.receive("P1", "other", "0.10", JAN_5)
    save(ledger, path, 0)
    loaded, _ = load(path)
    line = loaded.invoices["INV-1"].lines[0]
    found = [line.quantity, line.unit_price, line.discount_pct, loaded.invoices["INV-1"].tax_rate]
    assert all(isinstance(value, D) for value in found)
    assert found == [D("0.1"), D("12345678901234.5678"), D("0.05"), D("7.125")]
    for amount in (loaded.credit("other"), loaded.payments["P1"].amount, -loaded.events[-1].amount):
        assert isinstance(amount, D)
        assert amount == D("0.10")


def test_order_of_events_is_kept(path):
    ledger = ledger_with(invoice("INV-9"), invoice("INV-1"), invoice("INV-5"))
    for key in ("P2", "P1", "P3"):
        ledger.receive(key, "acme", "1.00", JAN_5)
    save(ledger, path, 0)
    assert [e.ref for e in load(path)[0].events] == ["INV-9", "INV-1", "INV-5", "P2", "P1", "P3"]


def test_loaded_ledger_reports_the_same(path):
    ledger = busy()
    save(ledger, path, 0)
    loaded, _ = load(path)
    for customer in ("acme", "Ünited"):
        assert aging(loaded, customer, LATE) == aging(ledger, customer, LATE)
        ours, theirs = (statement(x, customer, date(2026, 1, 1), LATE) for x in (ledger, loaded))
        assert (theirs.opening, theirs.closing) == (ours.opening, ours.closing)
        assert [(n.kind, n.ref, n.balance) for n in theirs.lines] == [
            (n.kind, n.ref, n.balance) for n in ours.lines
        ]


def test_loaded_ledger_carries_on_where_it_left_off(path):
    save(busy(), path, 0)
    loaded, _ = load(path)
    before = state(loaded)

    # Fee periods already charged, payment ids already used, reversals already made.
    loaded.assess_late_fees(LATE)
    loaded.receive("P3", "acme", "20.00", LATE)
    for refused in (
        lambda: loaded.receive("P4", "acme", "33.00", LATE),
        lambda: loaded.receive("P3", "acme", "21.00", LATE),
        lambda: loaded.reverse("P4", LATE),
    ):
        with pytest.raises(PaymentError):
            refused()
    assert state(loaded) == before

    loaded.reverse("P3", LATE)
    made = loaded.invoices["INV-2"]
    assert (made.fees_due, made.principal_due) == (D("15.00"), D("1000.00"))
    loaded.assess_late_fees(date(2026, 3, 7))  # 31 days late
    assert loaded.invoices["INV-2"].fees == D("30.00")


def test_periods_waived_by_a_dispute_stay_waived_after_loading(path):
    ledger = ledger_with(invoice(price="1000.00"))
    ledger.dispute("INV-1")
    ledger.assess_late_fees(LATE)
    save(ledger, path, 0)
    loaded, _ = load(path)
    loaded.resolve("INV-1")
    loaded.assess_late_fees(LATE)
    assert loaded.invoices["INV-1"].fees == D("0.00")


def test_loaded_holidays_and_credit_are_used(path):
    ledger = Ledger([date(2026, 2, 4)])
    ledger.receive("P1", "acme", "30.00", JAN_5)
    ledger.add(invoice())
    save(ledger, path, 0)
    loaded, _ = load(path)
    loaded.issue("INV-1")
    assert loaded.invoices["INV-1"].due == date(2026, 2, 5)
    loaded.apply_credit("acme", JAN_5)
    assert balances(loaded) == {"INV-1": D("70.00")}


# -- versions -----------------------------------------------------------------


def test_each_save_adds_one_to_the_version(path):
    ledger = ledger_with(invoice())
    for version in (1, 2, 3):
        assert save(ledger, path, version - 1) == version
        assert load(path)[1] == version


def test_path_may_be_text(path):
    assert save(ledger_with(invoice()), str(path), 0) == 1
    assert balances(load(str(path))[0]) == {"INV-1": D("100.00")}


def test_save_replaces_the_old_content(path):
    save(busy(), path, 0)
    save(ledger_with(invoice("ONLY")), path, 1)
    assert list(load(path)[0].invoices) == ["ONLY"]
    assert names(path.parent) == ["ledger.json"]


@pytest.mark.parametrize("expected", [0, 1, 3])
def test_wrong_version_is_a_conflict_and_leaves_the_file_alone(path, expected):
    save(ledger_with(invoice()), path, 0)
    save(ledger_with(invoice()), path, 1)
    before = path.read_bytes()
    with pytest.raises(ConflictError):
        save(ledger_with(invoice("INV-2")), path, expected)
    assert path.read_bytes() == before
    assert names(path.parent) == ["ledger.json"]


def test_new_file_expects_version_0(path):
    with pytest.raises(ConflictError):
        save(Ledger(), path, 1)
    assert names(path.parent) == []


# -- failures -----------------------------------------------------------------


class Unsavable:
    """Nothing can turn this into text, so a save that reaches it must fail."""

    def _refuse(self, *args):
        raise RuntimeError("cannot be saved")

    __str__ = __repr__ = __format__ = _refuse


def _bad_event(ledger):
    ledger.events.append(Event(JAN_5, "acme", "payment", "P9", Unsavable()))


def _bad_credit(ledger):
    ledger.credits["zeta"] = Unsavable()


@pytest.mark.parametrize("spoil", [_bad_event, _bad_credit])
def test_failed_save_leaves_the_existing_file_and_no_other(path, spoil):
    save(busy(), path, 0)
    before = path.read_bytes()
    ledger = busy()
    spoil(ledger)
    with pytest.raises(Exception):
        save(ledger, path, 1)
    assert path.read_bytes() == before
    assert names(path.parent) == ["ledger.json"]


@pytest.mark.parametrize("spoil", [_bad_event, _bad_credit])
def test_failed_first_save_leaves_no_file(path, spoil):
    ledger = busy()
    spoil(ledger)
    with pytest.raises(Exception):
        save(ledger, path, 0)
    assert names(path.parent) == []


def test_save_that_cannot_put_the_file_in_place_leaves_no_extra_file(path):
    path.mkdir()  # a folder is in the way
    with pytest.raises(Exception):
        save(busy(), path, 0)
    assert names(path.parent) == ["ledger.json"]
    assert names(path) == []


def test_saving_again_after_a_failure_works(path):
    save(ledger_with(invoice()), path, 0)
    broken = busy()
    _bad_event(broken)
    with pytest.raises(Exception):
        save(broken, path, 1)
    assert save(ledger_with(invoice("INV-2")), path, 1) == 2


# -- bad files ----------------------------------------------------------------

NOT_A_LEDGER = {
    "empty": "",
    "words": "not json",
    "cut short": '{"schema": 1, "version"',
    "csv": "date,amount\n1,2\n",
    "list": "[]",
    "number": "1",
    "null": "null",
    "text": '"text"',
    "no schema": "{}",
    "schema 2": '{"schema": 2, "version": 1}',
    "schema 0": '{"schema": 0, "version": 1}',
    "schema text": '{"schema": "1", "version": 1}',
    "schema null": '{"schema": null, "version": 1}',
}
bad_files = pytest.mark.parametrize("text", NOT_A_LEDGER.values(), ids=NOT_A_LEDGER.keys())


@bad_files
def test_loading_anything_else_is_a_store_error(path, text):
    path.write_text(text, encoding="utf-8")
    with pytest.raises(StoreError):
        load(path)


@bad_files
def test_saving_over_anything_else_is_a_store_error(path, text):
    path.write_text(text, encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(StoreError):
        save(Ledger(), path, 1)
    assert path.read_bytes() == before
    assert names(path.parent) == ["ledger.json"]


@pytest.mark.xfail(strict=True, reason="R9.4: a file that is not UTF-8 text raises UnicodeDecodeError")
@pytest.mark.parametrize("content", [b"\xff\xfe\x00\x81", b"\x89PNG\r\n\x1a\n"], ids=["bytes", "png"])
def test_loading_a_binary_file_is_a_store_error(path, content):
    path.write_bytes(content)
    with pytest.raises(StoreError):
        load(path)


def test_a_saved_file_with_another_schema_is_a_store_error(path):
    save(busy(), path, 0)
    data = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps({**data, "schema": 2}), encoding="utf-8")
    with pytest.raises(StoreError):
        load(path)
