from datetime import date
from decimal import Decimal

import pytest

from tally import ConflictError, Invoice, Ledger, Line, StoreError, load, save

D = Decimal


def sample_ledger():
    ledger = Ledger(holidays=[date(2026, 2, 4)])
    ledger.add(Invoice("INV-1", "acme", date(2026, 1, 5), "NET 30", [
        Line("widgets", 3, "19.99", discount_pct="10"),
        Line("freight", 1, "12.50", taxable=False),
    ], tax_rate="8.25"))
    ledger.issue("INV-1")
    ledger.add(Invoice("INV-2", "bolt", date(2026, 2, 1), "2/10 NET 30", [Line("w", 1, "100.00")]))
    ledger.issue("INV-2")
    ledger.receive("P1", "acme", "40.00", date(2026, 1, 20))
    ledger.receive("B1", "bolt", "98.00", date(2026, 2, 5))
    ledger.assess_late_fees(date(2026, 2, 20))
    return ledger


def test_load_after_save_gives_back_the_same_ledger(tmp_path):
    path = tmp_path / "ledger.json"
    ledger = sample_ledger()
    assert save(ledger, path, 0) == 1

    loaded, version = load(path)
    assert version == 1
    assert loaded.holidays == ledger.holidays
    assert loaded.invoices == ledger.invoices
    assert loaded.payments == ledger.payments
    assert loaded.credits == ledger.credits
    assert loaded.events == ledger.events


def test_save_returns_and_stores_incrementing_versions(tmp_path):
    path = tmp_path / "ledger.json"
    ledger = sample_ledger()
    assert save(ledger, path, 0) == 1
    assert save(ledger, path, 1) == 2
    assert load(path)[1] == 2


def test_save_refuses_a_stale_version_and_leaves_the_file_alone(tmp_path):
    path = tmp_path / "ledger.json"
    ledger = sample_ledger()
    save(ledger, path, 0)
    before = path.read_bytes()
    with pytest.raises(ConflictError):
        save(ledger, path, 0)
    with pytest.raises(ConflictError):
        save(ledger, path, 5)
    assert path.read_bytes() == before


def test_new_file_expects_version_zero(tmp_path):
    path = tmp_path / "ledger.json"
    with pytest.raises(ConflictError):
        save(sample_ledger(), path, 1)
    assert not path.exists()


def test_save_leaves_no_extra_files(tmp_path):
    path = tmp_path / "ledger.json"
    save(sample_ledger(), path, 0)
    save(sample_ledger(), path, 1)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["ledger.json"]


def test_failed_save_keeps_the_old_file_and_removes_its_temp_file(tmp_path):
    path = tmp_path / "ledger.json"
    ledger = sample_ledger()
    save(ledger, path, 0)
    before = path.read_bytes()

    ledger.credits["acme"] = object()  # cannot be written as JSON
    with pytest.raises(TypeError):
        save(ledger, path, 1)

    assert path.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["ledger.json"]


def test_save_over_a_file_that_is_not_a_ledger_is_refused(tmp_path):
    path = tmp_path / "ledger.json"
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(StoreError):
        save(sample_ledger(), path, 0)


@pytest.mark.parametrize("text", ["not json", "[]", '{"schema": 2, "version": 1}', '{"version": 1}'])
def test_load_refuses_files_that_are_not_schema_1_json(tmp_path, text):
    path = tmp_path / "ledger.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(StoreError):
        load(path)
