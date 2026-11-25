import os
from datetime import date
from decimal import Decimal as D

import pytest

from tally import ConflictError, Invoice, Ledger, Line, StoreError, load, save

DAY = date(2026, 1, 5)


def sample_ledger():
    ledger = Ledger(holidays=[date(2026, 1, 19), date(2026, 2, 16)])
    ledger.add(Invoice("INV-1", "acme", DAY, "2/10 NET 30",
                       [Line("work", 2, "50.00", "10"), Line("misc", 1, "5.00", taxable=False)],
                       tax_rate="8.25"))
    ledger.issue("INV-1")
    ledger.receive("P1", "acme", "50.00", date(2026, 1, 7))  # partial, no discount
    ledger.add(Invoice("INV-2", "acme", DAY, "NET 30", [Line("late", 1, "1000.00")]))
    ledger.issue("INV-2")
    ledger.assess_late_fees(date(2026, 2, 10))  # a 15.00 fee
    ledger.add(Invoice("INV-3", "acme", DAY, "NET 30", [Line("void", 1, "20.00")]))
    ledger.issue("INV-3")
    ledger.void("INV-3", date(2026, 1, 9))
    ledger.receive("P2", "beta", "12.34", date(2026, 1, 12))  # credit, nothing open for beta
    ledger.receive("P3", "acme", "3.00", date(2026, 1, 13))
    ledger.reverse("P3", date(2026, 1, 14))
    return ledger


# R9.1
def test_load_after_save_gives_back_the_same_ledger(store_dir):
    ledger = sample_ledger()
    path = store_dir / "ledger.json"
    save(ledger, path, 0)
    loaded, version = load(path)
    assert version == 1
    assert loaded.holidays == ledger.holidays
    assert loaded.invoices == ledger.invoices
    assert loaded.payments == ledger.payments
    assert loaded.credits == ledger.credits
    assert loaded.events == ledger.events


def test_amounts_survive_a_round_trip_exactly(store_dir):
    ledger = sample_ledger()
    path = store_dir / "ledger.json"
    save(ledger, path, 0)
    loaded, _ = load(path)
    assert str(loaded.payments["P1"].amount) == "50.00"
    assert str(loaded.credit("beta")) == "12.34"
    assert str(loaded.invoices["INV-1"].tax_rate) == "8.25"


# R9.2
def test_each_save_adds_one_to_the_version(store_dir):
    ledger = sample_ledger()
    path = store_dir / "ledger.json"
    assert save(ledger, path, 0) == 1
    assert save(ledger, path, 1) == 2
    assert load(path)[1] == 2


def test_stale_version_conflicts_and_leaves_the_file_alone(store_dir):
    ledger = sample_ledger()
    path = store_dir / "ledger.json"
    save(ledger, path, 0)
    before = path.read_bytes()
    with pytest.raises(ConflictError):
        save(ledger, path, 0)
    with pytest.raises(ConflictError):
        save(ledger, path, 5)
    assert path.read_bytes() == before


def test_new_file_expects_version_zero(store_dir):
    path = store_dir / "ledger.json"
    with pytest.raises(ConflictError):
        save(sample_ledger(), path, 1)
    assert not path.exists()


# R9.3
def unserializable_ledger():
    ledger = Ledger()
    ledger.add(Invoice("BAD", "acme", DAY, "NET 30", [Line(object(), 1, "10")]))
    ledger.issue("BAD")
    return ledger


def test_failed_save_leaves_existing_file_and_no_extra_file(store_dir):
    path = store_dir / "ledger.json"
    save(sample_ledger(), path, 0)
    before = path.read_bytes()
    with pytest.raises(TypeError):
        save(unserializable_ledger(), path, 1)
    assert path.read_bytes() == before
    assert sorted(os.listdir(store_dir)) == ["ledger.json"]


def test_failed_first_save_creates_no_file(store_dir):
    path = store_dir / "ledger.json"
    with pytest.raises(TypeError):
        save(unserializable_ledger(), path, 0)
    assert os.listdir(store_dir) == []


# R9.4
@pytest.mark.parametrize(
    "content",
    ["not json at all", "", "{'schema': 1}", "[1, 2]", '{"schema": 2, "version": 1}', '{"version": 1}'],
)
def test_file_that_is_not_json_or_not_schema_1_raises_store_error(store_dir, content):
    path = store_dir / "ledger.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(StoreError):
        load(path)
    with pytest.raises(StoreError):
        save(sample_ledger(), path, 0)


@pytest.mark.xfail(strict=True, reason="a file that is not valid UTF-8 raises UnicodeDecodeError instead of StoreError; spec R9.4 says a file that is not JSON raises StoreError")
def test_binary_file_raises_store_error(store_dir):
    path = store_dir / "ledger.json"
    path.write_bytes(b"\xff\xfe\x00\x81binary")
    with pytest.raises(StoreError):
        load(path)
