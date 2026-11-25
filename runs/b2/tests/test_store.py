import json
from dataclasses import asdict
from datetime import date
from decimal import Decimal

import pytest

from helpers import D, JAN5, events, invoice, late, ledger_with, load_ledger
from tally import (ConflictError, Event, Ledger, Line, StoreError, load, save,
                   statement)


def rich_ledger():
    """A ledger that has been through most things."""
    ledger = Ledger(holidays=[date(2026, 2, 16), date(2026, 1, 19)])
    ledger.add(invoice("INV-1", terms="2/10 NET 30", tax_rate="8.25", lines=[
        Line("widgets", "3", "19.99", "10"),
        Line("service", "1.5", "0.1234567891", taxable=False),
        Line("credit", 1, "-5.00"),
    ]))
    ledger.add(invoice("INV-2", price="1234567890123456.78", day=date(2026, 1, 8)))
    ledger.add(invoice("INV-3", customer="other", terms="EOM", price="250.00", tax_exempt=True))
    ledger.add(invoice("INV-4", price="10.00"))                 # stays a draft
    for number in ("INV-1", "INV-2", "INV-3"):
        ledger.issue(number)
    ledger.receive("P1", "acme", "50.00", date(2026, 1, 10))
    ledger.receive("P2", "other", "300.00", date(2026, 1, 11))   # leaves 50.00 credit
    ledger.receive("P3", "acme", "5.00", date(2026, 1, 12))
    ledger.reverse("P3", date(2026, 1, 13))
    ledger.dispute("INV-2")
    ledger.assess_late_fees(date(2026, 4, 1))
    return ledger


def view(value):
    """Plain, exactly comparable form of a ledger (Decimals kept exact as text)."""
    def plain(item):
        if isinstance(item, Decimal):
            return str(item)
        if isinstance(item, dict):
            return {k: plain(v) for k, v in item.items()}
        if isinstance(item, (list, tuple)):
            return [plain(v) for v in item]
        return item
    return plain({
        "holidays": sorted(value.holidays),
        "invoices": {k: asdict(v) for k, v in value.invoices.items()},
        "payments": {k: asdict(v) for k, v in value.payments.items()},
        "credits": dict(value.credits),
        "events": [asdict(e) for e in value.events],
    })


# R9.1 ---------------------------------------------------------------------

def test_load_gives_back_the_same_ledger(tmp_path):
    ledger = rich_ledger()
    path = tmp_path / "ledger.json"
    save(ledger, path, 0)
    loaded = load_ledger(path)
    assert view(loaded) == view(ledger)
    assert loaded.holidays == ledger.holidays
    assert loaded.credit("other") == D("50.00")


def test_round_trip_keeps_exact_amounts_and_types(tmp_path):
    ledger = rich_ledger()
    path = tmp_path / "ledger.json"
    save(ledger, path, 0)
    loaded = load_ledger(path)
    big = loaded.invoices["INV-2"]
    assert big.total == D("1234567890123456.78")
    line = loaded.invoices["INV-1"].lines[1]
    assert line.unit_price == D("0.1234567891")
    assert isinstance(loaded.invoices["INV-1"].date, date)
    assert isinstance(loaded.events[0].date, date)
    assert isinstance(loaded.events[0], Event)
    assert loaded.invoices["INV-1"].lines[0].taxable is True
    assert loaded.invoices["INV-1"].lines[1].taxable is False
    assert loaded.invoices["INV-3"].tax_exempt is True


def test_a_loaded_ledger_keeps_working_the_same_way(tmp_path):
    original = rich_ledger()
    path = tmp_path / "ledger.json"
    save(original, path, 0)
    loaded = load_ledger(path)
    for ledger in (original, loaded):
        ledger.receive("P9", "acme", "100.00", date(2026, 4, 5))
        ledger.assess_late_fees(date(2026, 8, 1))
    assert view(loaded) == view(original)
    assert statement(loaded, "acme", date(2026, 1, 1), date(2026, 12, 31)) == \
        statement(original, "acme", date(2026, 1, 1), date(2026, 12, 31))


def test_an_empty_ledger_round_trips(tmp_path):
    path = tmp_path / "empty.json"
    save(Ledger(), path, 0)
    loaded = load_ledger(path)
    assert view(loaded) == view(Ledger())


def test_reversed_payments_and_disputes_survive(tmp_path):
    path = tmp_path / "ledger.json"
    save(rich_ledger(), path, 0)
    loaded = load_ledger(path)
    assert loaded.payments["P3"].reversed is True
    assert loaded.payments["P1"].reversed is False
    assert loaded.invoices["INV-2"].disputed is True
    assert loaded.invoices["INV-4"].status == "draft"
    assert [e.kind for e in loaded.events] == [e.kind for e in rich_ledger().events]


def test_save_accepts_a_text_path(tmp_path):
    path = str(tmp_path / "ledger.json")
    assert save(ledger_with(invoice()), path, 0) == 1
    assert load_ledger(path).invoices["INV-1"].total == D("100.00")


# R9.2 ---------------------------------------------------------------------

def test_versions_count_up_from_zero(tmp_path):
    path = tmp_path / "ledger.json"
    ledger = ledger_with(invoice())
    assert save(ledger, path, 0) == 1
    assert save(ledger, path, 1) == 2
    assert save(ledger, path, 2) == 3
    version = load(path)[1]
    assert version == 3


def test_load_reports_the_version(tmp_path):
    path = tmp_path / "ledger.json"
    save(Ledger(), path, 0)
    result = load(path)
    assert isinstance(result, tuple) and result[1] == 1


@pytest.mark.parametrize("expected", [1, 2, -1, 99])
def test_a_new_file_only_accepts_version_zero(tmp_path, expected):
    path = tmp_path / "ledger.json"
    with pytest.raises(ConflictError):
        save(Ledger(), path, expected)
    assert not path.exists()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("expected", [0, 1, 3, -1])
def test_a_wrong_version_raises_and_leaves_the_file_alone(tmp_path, expected):
    path = tmp_path / "ledger.json"
    save(ledger_with(invoice()), path, 0)
    save(ledger_with(invoice()), path, 1)                      # now at version 2
    before = path.read_bytes()
    other = ledger_with(invoice("OTHER", price="5.00"))
    with pytest.raises(ConflictError):
        save(other, path, expected)
    assert path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]
    assert load(path)[1] == 2


def test_a_stale_writer_cannot_overwrite_a_newer_save(tmp_path):
    path = tmp_path / "ledger.json"
    save(Ledger(), path, 0)
    first = ledger_with(invoice("A"))
    second = ledger_with(invoice("B"))
    assert save(first, path, 1) == 2
    with pytest.raises(ConflictError):
        save(second, path, 1)
    assert set(load_ledger(path).invoices) == {"A"}


# R9.3 ---------------------------------------------------------------------

def broken_ledger():
    ledger = ledger_with(invoice())
    ledger.events.append(Event(JAN5, "acme", "payment", "X", object()))     # cannot be written
    return ledger


def test_a_failed_save_leaves_the_existing_file_untouched(tmp_path):
    path = tmp_path / "ledger.json"
    save(ledger_with(invoice("GOOD")), path, 0)
    before = path.read_bytes()
    with pytest.raises(Exception):
        save(broken_ledger(), path, 1)
    assert path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]
    assert load(path)[1] == 1
    assert save(ledger_with(invoice("AGAIN")), path, 1) == 2


def test_a_failed_first_save_leaves_no_file_behind(tmp_path):
    path = tmp_path / "ledger.json"
    with pytest.raises(Exception):
        save(broken_ledger(), path, 0)
    assert list(tmp_path.iterdir()) == []


# R9.4 ---------------------------------------------------------------------

@pytest.mark.parametrize("content", [
    "this is not json", "", "{", "[1, 2", "[]", "42", "null", '"text"',
    '{"version": 1}', '{"schema": 2, "version": 1}', '{"schema": "1", "version": 1}',
    '{"schema": null}', '{"schema": 0}',
])
def test_a_file_that_is_not_a_schema_1_ledger_raises(tmp_path, content):
    path = tmp_path / "ledger.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(StoreError):
        load(path)


@pytest.mark.xfail(strict=True, reason="a file that is not even text raises UnicodeDecodeError")
def test_a_binary_file_raises_store_error(tmp_path):
    path = tmp_path / "ledger.json"
    path.write_bytes(bytes([0xFF, 0xFE, 0x00, 0x80, 0x81, 0xC0]))
    with pytest.raises(StoreError):
        load(path)


def test_saved_file_is_json_with_schema_1(tmp_path):
    path = tmp_path / "ledger.json"
    save(Ledger(), path, 0)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema"] == 1
