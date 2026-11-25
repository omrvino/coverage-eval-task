from datetime import date
from decimal import Decimal

import pytest

from tally import ConflictError, Invoice, Ledger, Line, StoreError, load, save
from tally import store

D = Decimal


def busy_ledger():
    ledger = Ledger(holidays=[date(2026, 1, 12)])
    ledger.add(Invoice(
        "INV-1", "acme", date(2026, 1, 5), "2/10 NET 30",
        [Line("work", D("2.5"), "40.25", discount_pct="10"), Line("parts", 1, "19.99", taxable=False)],
        tax_rate="8.25",
    ))
    ledger.issue("INV-1")
    ledger.add(Invoice("INV-2", "beta", date(2026, 1, 6), "NET 30", [Line("a", 1, "100.00")]))
    ledger.issue("INV-2")
    ledger.add(Invoice("DRAFT", "acme", date(2026, 1, 7), "NET 30", [Line("x", 1, "5")]))
    ledger.receive("P1", "acme", "60.00", date(2026, 1, 15))
    ledger.receive("P2", "gamma", "25.00", date(2026, 1, 15))  # no invoices, so credit
    ledger.assess_late_fees(date(2026, 2, 20))
    ledger.void("INV-2", date(2026, 2, 21))
    return ledger


def test_load_after_save_gives_back_the_same_ledger(tmp_path):
    ledger = busy_ledger()
    path = tmp_path / "ledger.json"
    assert save(ledger, path, 0) == 1
    loaded, version = load(path)
    assert version == 1
    assert loaded.holidays == ledger.holidays
    assert loaded.invoices == ledger.invoices
    assert loaded.payments == ledger.payments
    assert loaded.credits == ledger.credits
    assert loaded.events == ledger.events


def test_amounts_survive_the_round_trip_exactly(tmp_path):
    ledger = busy_ledger()
    path = tmp_path / "ledger.json"
    save(ledger, path, 0)
    loaded, _ = load(path)
    assert loaded.invoices["INV-1"].total == ledger.invoices["INV-1"].total
    assert loaded.invoices["INV-1"].lines[0].quantity == D("2.5")
    assert loaded.credits["gamma"] == D("25.00")
    assert loaded.invoices["DRAFT"].due is None


def test_save_and_load_accept_plain_strings(tmp_path):
    path = str(tmp_path / "ledger.json")
    assert save(Ledger(), path, 0) == 1
    loaded, version = load(path)
    assert version == 1
    assert loaded.invoices == {}


def test_each_save_adds_one_to_the_version(tmp_path):
    path = tmp_path / "ledger.json"
    ledger = Ledger()
    assert save(ledger, path, 0) == 1
    assert save(ledger, path, 1) == 2
    assert load(path)[1] == 2


def test_stale_or_wrong_expected_version_is_a_conflict_and_leaves_the_file_alone(tmp_path):
    path = tmp_path / "ledger.json"
    save(Ledger(), path, 0)
    before = path.read_bytes()
    with pytest.raises(ConflictError):
        save(Ledger(), path, 0)
    with pytest.raises(ConflictError):
        save(Ledger(), path, 5)
    assert path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]


def test_a_new_file_expects_version_zero(tmp_path):
    with pytest.raises(ConflictError):
        save(Ledger(), tmp_path / "ledger.json", 1)
    assert list(tmp_path.iterdir()) == []


def test_failed_save_leaves_the_existing_file_untouched(tmp_path, monkeypatch):
    path = tmp_path / "ledger.json"
    ledger = busy_ledger()
    save(ledger, path, 0)
    before = path.read_bytes()

    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(store.json, "dump", fail)
    with pytest.raises(OSError):
        save(ledger, path, 1)
    monkeypatch.undo()
    assert path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]


def test_failed_first_save_leaves_no_file_behind(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(store.json, "dump", fail)
    with pytest.raises(OSError):
        save(Ledger(), tmp_path / "ledger.json", 0)
    monkeypatch.undo()
    assert list(tmp_path.iterdir()) == []


def test_file_that_is_not_json_is_a_store_error(tmp_path):
    path = tmp_path / "ledger.json"
    path.write_text("not json at all", encoding="utf-8")
    with pytest.raises(StoreError):
        load(path)
    with pytest.raises(StoreError):
        save(Ledger(), path, 0)


@pytest.mark.parametrize("content", ["[]", '{"schema": 2, "version": 1}', '{"version": 1}'])
def test_file_with_an_unknown_schema_is_a_store_error(tmp_path, content):
    path = tmp_path / "ledger.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(StoreError):
        load(path)


@pytest.mark.xfail(strict=True, reason="R9.4: a file that is not JSON should raise StoreError, not UnicodeDecodeError")
def test_binary_file_is_a_store_error(tmp_path):
    path = tmp_path / "ledger.json"
    path.write_bytes(b"\xff\xfe\x00\x01")
    with pytest.raises(StoreError):
        load(path)
