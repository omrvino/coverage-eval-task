import json
import os
from datetime import date, timedelta
from decimal import Decimal

import pytest

from tally import (ConflictError, Invoice, Ledger, Line, StoreError, TallyError, aging,
                   load, save, statement)

from helpers import D0, issued, make_invoice

D = Decimal


def rich_ledger():
    """Holidays, taxed and discounted lines, fees, a discount, credit, a reversal, a void."""
    ledger = Ledger([date(2026, 12, 25), date(2026, 1, 1)])
    lines = [Line("widgets", "2.5", "19.99", discount_pct="12.5"), Line("fee", 1, "5.00", taxable=False)]
    ledger.add(make_invoice("INV-1", terms="2/10 NET 30", lines=lines, tax_rate="8.25"))
    ledger.add(make_invoice("INV-2", price="1234.56", due=D0 + timedelta(days=7)))
    ledger.add(make_invoice("INV-3", customer="other", price="10.00", tax_exempt=True))
    ledger.add(make_invoice("INV-4", price="40.00"))
    ledger.add(make_invoice("INV-5", terms="EOM"))                 # stays a draft
    for number in ("INV-1", "INV-2", "INV-3", "INV-4"):
        ledger.issue(number)
    ledger.void("INV-4", D0)
    ledger.receive("P1", "acme", "50.00", date(2026, 2, 5))
    ledger.receive("P2", "acme", "200.00", date(2026, 2, 12))
    ledger.reverse("P2", date(2026, 2, 13))
    ledger.receive("P3", "acme", "600.00", date(2026, 3, 1))
    ledger.receive("P4", "zed", "25.00", date(2026, 3, 1))        # credit with nothing to pay
    ledger.assess_late_fees(D0 + timedelta(days=40))
    ledger.dispute("INV-3")
    return ledger


def same_ledger(a, b):
    assert a.holidays == b.holidays
    assert a.invoices == b.invoices
    assert a.payments == b.payments
    assert a.credits == b.credits
    assert a.events == b.events
    assert list(a.invoices) == list(b.invoices)
    assert list(a.payments) == list(b.payments)
    # exact amounts, including the number of places
    assert [str(e.amount) for e in a.events] == [str(e.amount) for e in b.events]
    assert {k: str(v) for k, v in a.credits.items()} == {k: str(v) for k, v in b.credits.items()}
    for number, inv in a.invoices.items():
        other = b.invoices[number]
        assert (str(inv.total), str(inv.balance), inv.status) == (
            str(other.total), str(other.balance), other.status)


# -- R9.1 ------------------------------------------------------------------

def test_load_gives_back_the_same_ledger(tmp_path):
    ledger = rich_ledger()
    path = tmp_path / "ledger.json"
    save(ledger, path, 0)
    loaded, version = load(path)
    assert version == 1
    same_ledger(ledger, loaded)


def test_the_rich_ledger_has_what_the_round_trip_test_needs():
    ledger = rich_ledger()
    assert ledger.credit("zed") > 0
    assert any(p.reversed for p in ledger.payments.values())
    assert any(i.fees for i in ledger.invoices.values())
    assert {i.status for i in ledger.invoices.values()} >= {"draft", "open", "void"}
    assert {e.kind for e in ledger.events} >= {"invoice", "payment", "reversal", "void", "fee"}


def test_loaded_ledger_behaves_like_the_original(tmp_path):
    ledger = rich_ledger()
    path = tmp_path / "ledger.json"
    save(ledger, path, 0)
    loaded, _ = load(path)
    on = D0 + timedelta(days=100)
    assert aging(loaded, "acme", on) == aging(ledger, "acme", on)
    assert statement(loaded, "acme", date(2026, 1, 1), on) == statement(ledger, "acme", date(2026, 1, 1), on)
    for each in (ledger, loaded):
        each.assess_late_fees(on)
        each.receive("P9", "acme", "75.00", on)
    same_ledger(ledger, loaded)


def test_an_empty_ledger_round_trips(tmp_path):
    path = tmp_path / "empty.json"
    save(Ledger(), path, 0)
    loaded, version = load(path)
    assert (version, loaded.invoices, loaded.payments, loaded.credits, loaded.events) == (1, {}, {}, {}, [])
    assert loaded.holidays == frozenset()


def test_amounts_keep_their_exact_digits(tmp_path):
    ledger = issued(make_invoice(price="0.07", tax_rate=D("0.125")))
    ledger.receive("P1", "acme", "0.01", D0)
    path = tmp_path / "ledger.json"
    save(ledger, path, 0)
    loaded, _ = load(path)
    assert str(loaded.payments["P1"].amount) == "0.01"
    assert loaded.invoices["INV-1"].tax_rate == D("0.125")
    assert loaded.invoices["INV-1"].balance == D("0.06")


# -- R9.2 ------------------------------------------------------------------

def test_a_new_file_expects_version_zero_and_each_save_adds_one(tmp_path):
    path = tmp_path / "ledger.json"
    ledger = Ledger()
    assert save(ledger, path, 0) == 1
    assert save(ledger, path, 1) == 2
    assert save(ledger, str(path), 2) == 3          # a plain string path works too
    assert load(path)[1] == 3


def test_a_saved_change_is_what_the_next_load_sees(tmp_path):
    path = tmp_path / "ledger.json"
    ledger = Ledger()
    save(ledger, path, 0)
    ledger.receive("P1", "acme", "5.00", D0)
    save(ledger, path, 1)
    loaded, version = load(path)
    assert version == 2
    assert loaded.credit("acme") == D("5.00")


@pytest.mark.parametrize("expected", [-1, 1, 2, 7])
def test_a_new_file_with_the_wrong_version_is_a_conflict_and_nothing_is_written(tmp_path, expected):
    path = tmp_path / "ledger.json"
    with pytest.raises(ConflictError):
        save(Ledger(), path, expected)
    assert os.listdir(tmp_path) == []


@pytest.mark.parametrize("expected", [0, 1, 3, 99])
def test_a_stale_or_wrong_version_is_a_conflict_and_leaves_the_file_alone(tmp_path, expected):
    path = tmp_path / "ledger.json"
    save(Ledger(), path, 0)
    save(Ledger(), path, 1)                         # version 2 now
    before = path.read_bytes()
    changed = rich_ledger()
    with pytest.raises(ConflictError):
        save(changed, path, expected)
    assert path.read_bytes() == before
    assert os.listdir(tmp_path) == ["ledger.json"]


def test_conflict_error_is_a_store_error():
    assert issubclass(ConflictError, StoreError)
    assert issubclass(StoreError, TallyError)


# -- R9.3 ------------------------------------------------------------------

def test_a_failed_save_leaves_the_existing_file_and_folder_untouched(tmp_path):
    path = tmp_path / "ledger.json"
    save(rich_ledger(), path, 0)
    before = path.read_bytes()
    broken = rich_ledger()
    broken.credits["acme"] = object()               # cannot be written as JSON
    with pytest.raises(Exception) as caught:
        save(broken, path, 1)
    assert not isinstance(caught.value, ConflictError)
    assert path.read_bytes() == before
    assert os.listdir(tmp_path) == ["ledger.json"]
    assert load(path)[1] == 1


def test_a_failed_first_save_leaves_no_file_behind(tmp_path):
    path = tmp_path / "ledger.json"
    broken = Ledger()
    broken.credits["acme"] = object()
    with pytest.raises(Exception):
        save(broken, path, 0)
    assert os.listdir(tmp_path) == []


def test_a_save_leaves_only_the_ledger_file(tmp_path):
    path = tmp_path / "ledger.json"
    save(Ledger(), path, 0)
    save(Ledger(), path, 1)
    assert os.listdir(tmp_path) == ["ledger.json"]


# -- R9.4 ------------------------------------------------------------------

@pytest.mark.parametrize("content", [
    "this is not json", "", "{", "{'schema': 1}", "NaN garbage",
])
def test_text_that_is_not_json_is_a_store_error(tmp_path, content):
    path = tmp_path / "bad.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(StoreError):
        load(path)


@pytest.mark.parametrize("content", [
    "[]", "null", "5", '"text"', "{}", '{"schema": 2, "version": 1}', '{"schema": "1"}',
    '{"schema": 0}', '{"version": 3}',
])
def test_json_that_is_not_schema_1_is_a_store_error(tmp_path, content):
    path = tmp_path / "bad.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(StoreError):
        load(path)


def test_saving_over_a_file_that_is_not_a_ledger_is_a_store_error_and_keeps_it(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("hello", encoding="utf-8")
    with pytest.raises(StoreError):
        save(Ledger(), path, 0)
    assert path.read_text(encoding="utf-8") == "hello"
    assert os.listdir(tmp_path) == ["notes.txt"]


def test_another_schema_in_an_existing_file_is_a_store_error_on_save(tmp_path):
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps({"schema": 2, "version": 0}), encoding="utf-8")
    with pytest.raises(StoreError):
        save(Ledger(), path, 0)


@pytest.mark.xfail(strict=True, reason="a file that is not text raises UnicodeDecodeError instead of StoreError")
def test_a_binary_file_is_a_store_error(tmp_path):
    path = tmp_path / "bad.bin"
    path.write_bytes(bytes([0xFF, 0xFE, 0x00, 0x80]))
    with pytest.raises(StoreError):
        load(path)
