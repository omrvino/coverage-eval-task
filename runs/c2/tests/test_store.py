"""SPEC section 9: storage."""

import json
from datetime import date
from decimal import Decimal

import pytest

from helpers import DUE, JAN_5, D, balances, days, events, issue_all, issued, make_invoice, snapshot
from tally import (
    ConflictError, Ledger, Line, PaymentError, StoreError, aging, load, save, statement,
)

HOLIDAYS = [date(2026, 12, 25), date(2026, 1, 1), date(2026, 3, 9)]
ZOE = "Zoë & Söhne"


def busy_ledger():
    """One of everything the ledger can hold."""
    ledger = issued(
        make_invoice("A", "1000.00", terms="2/10 NET 30", tax_rate="8.25"),
        make_invoice("B", "1000.00", terms="NET 60"),
        make_invoice("C", "10.10", terms="EOM", customer=ZOE, tax_exempt=True, tax_rate="7.125"),
        make_invoice("V", "12.34", terms="NET 90"),
        make_invoice("X", "500.00", terms="NET 31", lines=[
            Line("hours", "1.3333333", "99.99", "12.5", True),
            Line("travel", 2, "45.45", taxable=False),
            Line("credit", 1, "-5.05"),
        ]),
        holidays=HOLIDAYS,
    )
    ledger.receive("P1", "acme", "1062.50", JAN_5 + days(3))  # pays A less its discount
    ledger.receive("P2", ZOE, "10.40", JAN_5 + days(4))  # leaves 0.30 credit
    ledger.receive("P3", "acme", "0.10", JAN_5 + days(5))
    ledger.reverse("P3", JAN_5 + days(6))
    ledger.void("V", JAN_5 + days(7))
    ledger.dispute("X")
    ledger.assess_late_fees(DUE + days(40))  # charges B, waives two periods of X
    ledger.receive("P4", "acme", "1.11", DUE + days(41))  # part of B's fee
    ledger.add(make_invoice("DRAFT", "3.33"))
    return ledger


@pytest.fixture
def path(tmp_path):
    return tmp_path / "ledger.json"


def names(folder):
    return sorted(p.name for p in folder.iterdir())


def reload(ledger, path):
    save(ledger, path, 0)
    return load(path)[0]


# -- R9.1 ------------------------------------------------------------------


def test_the_busy_ledger_really_holds_one_of_everything():
    ledger = busy_ledger()
    assert {i.status for i in ledger.invoices.values()} == {"draft", "open", "paid", "void"}
    assert {kind for _, kind, _ in events(ledger)} == {
        "invoice", "fee", "payment", "discount", "reversal", "void"}
    assert ledger.credit(ZOE) == D("0.30")
    assert ledger.invoices["B"].fees_due == D("13.89")


def test_r9_1_round_trip(path):
    ledger = busy_ledger()
    version = save(ledger, path, 0)
    loaded, loaded_version = load(path)
    assert loaded_version == version
    assert snapshot(loaded) == snapshot(ledger)
    assert set(loaded.holidays) == set(HOLIDAYS)


def test_r9_1_round_trip_of_an_empty_ledger(path):
    assert snapshot(reload(Ledger(), path)) == snapshot(Ledger())


def test_r9_1_amounts_stay_exact_decimals(path):
    ledger = Ledger()
    for i in range(10):
        ledger.receive(f"P{i}", "acme", "0.10", JAN_5)
    ledger.add(make_invoice(lines=[Line("item", "0.1234567890123456789", "12345678901234.56")]))
    loaded = reload(ledger, path)
    assert loaded.credit("acme") == D("1.00")
    assert isinstance(loaded.credit("acme"), Decimal)
    assert all(isinstance(e.amount, Decimal) for e in loaded.events)
    assert all(isinstance(p.amount, Decimal) for p in loaded.payments.values())
    line = loaded.invoices["INV-1"].lines[0]
    assert (line.quantity, line.unit_price) == (D("0.1234567890123456789"), D("12345678901234.56"))


def test_r9_1_saving_does_not_change_the_ledger(path):
    ledger = busy_ledger()
    before = snapshot(ledger)
    save(ledger, path, 0)
    assert snapshot(ledger) == before


def continue_working(ledger):
    """Use everything a ledger has to remember."""
    ledger.assess_late_fees(DUE + days(41))  # periods already charged
    ledger.receive("P1", "acme", "1062.50", DUE)  # already received
    with pytest.raises(PaymentError):
        ledger.receive("P3", "acme", "0.10", DUE)  # reversed
    ledger.resolve("X")
    ledger.assess_late_fees(DUE + days(45))  # periods waived under dispute
    ledger.reverse("P4", DUE + days(46))
    issue_all(ledger, make_invoice("H", "5.00", on=date(2026, 2, 7), terms="NET 30"))
    ledger.receive("P5", "acme", "700.00", DUE + days(47))
    issue_all(ledger, make_invoice("C2", "1.00", customer=ZOE))
    ledger.apply_credit(ZOE, DUE + days(47))
    ledger.assess_late_fees(DUE + days(100))


def test_r9_1_a_loaded_ledger_carries_on_the_same(path):
    original = busy_ledger()
    loaded = reload(original, path)
    continue_working(original)
    continue_working(loaded)
    assert snapshot(loaded) == snapshot(original)
    end = DUE + days(100)
    assert aging(loaded, "acme", end) == aging(original, "acme", end)
    assert statement(loaded, "acme", JAN_5, end).closing == statement(
        original, "acme", JAN_5, end).closing


def test_r9_1_holidays_still_move_due_dates_after_loading(path):
    loaded = reload(Ledger(HOLIDAYS), path)
    issue_all(loaded, make_invoice(on=date(2026, 2, 7)))  # 30 days on is a holiday
    assert loaded.invoices["INV-1"].due == date(2026, 3, 10)


def test_r9_1_fees_are_not_charged_again_after_loading(path):
    ledger = issued(make_invoice(price="1000.00"))
    ledger.assess_late_fees(DUE + days(10))
    loaded = reload(ledger, path)
    loaded.assess_late_fees(DUE + days(10))
    assert balances(loaded) == {"INV-1": D("1015.00")}
    assert len(events(loaded, "fee")) == 1


def test_r9_1_waived_periods_stay_waived_after_loading(path):
    ledger = issued(make_invoice(price="1000.00"))
    ledger.dispute("INV-1")
    ledger.assess_late_fees(DUE + days(40))
    loaded = reload(ledger, path)
    loaded.resolve("INV-1")
    loaded.assess_late_fees(DUE + days(40))
    assert balances(loaded) == {"INV-1": D("1000.00")}


def test_r9_1_payment_can_be_reversed_after_loading(path):
    ledger = issued(make_invoice("INV-1", "1000.00"))
    ledger.assess_late_fees(DUE + days(10))
    ledger.receive("P1", "acme", "1020.00", DUE + days(10))
    loaded = reload(ledger, path)
    loaded.reverse("P1", DUE + days(12))
    invoice = loaded.invoices["INV-1"]
    assert (invoice.principal_due, invoice.fees_due) == (D("1000.00"), D("15.00"))
    assert loaded.credit("acme") == 0


# -- R9.2 ------------------------------------------------------------------


def test_r9_2_versions_count_up(path):
    ledger = Ledger()
    for expected in range(4):
        assert save(ledger, path, expected) == expected + 1
        assert load(path)[1] == expected + 1


def test_r9_2_save_replaces_the_content(path):
    ledger = busy_ledger()
    save(ledger, path, 0)
    continue_working(ledger)
    save(ledger, path, 1)
    assert snapshot(load(path)[0]) == snapshot(ledger)


@pytest.mark.parametrize("expected", [0, 1, 3, -1])
def test_r9_2_conflict_leaves_the_file_alone(path, expected):
    save(Ledger(), path, 0)
    save(Ledger(), path, 1)
    before = path.read_bytes()
    with pytest.raises(ConflictError):
        save(busy_ledger(), path, expected)
    assert path.read_bytes() == before
    assert names(path.parent) == [path.name]


@pytest.mark.parametrize("expected", [1, 2, -1])
def test_r9_2_new_file_expects_version_0(path, expected):
    with pytest.raises(ConflictError):
        save(Ledger(), path, expected)
    assert names(path.parent) == []


def test_r9_2_files_have_their_own_versions(path):
    save(Ledger(), path, 0)
    assert save(Ledger(), path.with_name("other.json"), 0) == 1


def test_r9_2_second_writer_loses(path):
    save(issued(make_invoice()), path, 0)
    (first, seen), (second, _) = load(path), load(path)
    first.receive("P1", "acme", "10.00", JAN_5)
    second.receive("P2", "acme", "20.00", JAN_5)
    save(first, path, seen)
    with pytest.raises(ConflictError):
        save(second, path, seen)
    assert list(load(path)[0].payments) == ["P1"]


# -- R9.3 ------------------------------------------------------------------


def unsaveable():
    """A large ledger whose last invoice holds something no file can."""
    ledger = issued(*(make_invoice(f"INV-{i}") for i in range(300)))
    ledger.invoices["INV-299"].lines[0].description = object()
    return ledger


def test_r9_3_failed_save_leaves_the_old_file(path):
    save(busy_ledger(), path, 0)
    before = path.read_bytes()
    with pytest.raises(Exception):
        save(unsaveable(), path, 1)
    assert path.read_bytes() == before
    assert names(path.parent) == [path.name]
    assert save(busy_ledger(), path, 1) == 2  # and the next save still works


def test_r9_3_failed_first_save_leaves_nothing(path):
    with pytest.raises(Exception):
        save(unsaveable(), path, 0)
    assert names(path.parent) == []


def test_r9_3_nothing_is_left_when_the_target_cannot_be_written(path):
    path.mkdir()  # a folder is in the way
    with pytest.raises(Exception):
        save(busy_ledger(), path, 0)
    assert names(path.parent) == [path.name]
    assert names(path) == []


def test_r9_3_successful_save_leaves_only_the_file(path):
    save(busy_ledger(), path, 0)
    save(busy_ledger(), path, 1)
    assert names(path.parent) == [path.name]


# -- R9.4 ------------------------------------------------------------------

NOT_A_LEDGER = [
    "", "hello", "{", '{"schema": 1', "date,amount\n", "<html></html>",  # not JSON
    "[]", "{}", "null", "1", '"schema"', "[1]",
    '{"schema": 2, "version": 1}', '{"schema": 0, "version": 1}', '{"schema": null}',
    '{"version": 1}',
]


@pytest.mark.parametrize("content", NOT_A_LEDGER, ids=repr)
def test_r9_4_load_refuses_other_files(path, content):
    path.write_text(content, encoding="utf-8")
    with pytest.raises(StoreError):
        load(path)


@pytest.mark.parametrize("expected", [0, 1])
@pytest.mark.parametrize("content", ["hello", "[]", '{"schema": 2, "version": 1}'], ids=repr)
def test_r9_4_save_refuses_to_replace_other_files(path, content, expected):
    path.write_text(content, encoding="utf-8")
    with pytest.raises(StoreError):
        save(Ledger(), path, expected)
    assert path.read_text(encoding="utf-8") == content


def test_r9_4_schema_of_a_real_file_is_checked(path):
    save(busy_ledger(), path, 0)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema"] == 1
    path.write_text(json.dumps({**data, "schema": 2}), encoding="utf-8")
    with pytest.raises(StoreError):
        load(path)


def test_r9_4_truncated_file(path):
    save(busy_ledger(), path, 0)
    text = path.read_text(encoding="utf-8")
    path.write_text(text[: len(text) // 2], encoding="utf-8")
    with pytest.raises(StoreError):
        load(path)


@pytest.mark.xfail(strict=True, reason="R9.4: a file that is not UTF-8 raises UnicodeDecodeError")
@pytest.mark.parametrize("content", [
    b"\xff\xfe{\x00}\x00", b"\x89PNG\r\n\x1a\n\x00", b'"caf\xe9"',
], ids=["utf-16", "png", "latin-1"])
def test_r9_4_binary_file(path, content):
    path.write_bytes(content)
    with pytest.raises(StoreError):
        load(path)
