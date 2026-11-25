import json
import os
from datetime import date

import pytest

from tally import ConflictError, Invoice, Ledger, Line, StoreError, load, save


def sample_ledger():
    ledger = Ledger(holidays=[date(2026, 2, 2)])
    ledger.add(
        Invoice(
            "INV-1",
            "acme",
            date(2026, 1, 5),
            "2/10 NET 30",
            [
                Line("work", 3, "33.33", discount_pct="5"),
                Line("credit", 1, "-10.00", taxable=False),
            ],
            tax_rate="8.25",
        )
    )
    ledger.issue("INV-1")
    ledger.receive("P1", "acme", "92.00", date(2026, 1, 10))  # discount taken, 0.87 left as credit
    ledger.add(Invoice("INV-2", "acme", date(2026, 1, 20), "NET 30", [Line("retainer", 1, "100.00")]))
    ledger.issue("INV-2")
    ledger.assess_late_fees(date(2026, 3, 15))
    ledger.receive("P2", "acme", "50.00", date(2026, 3, 16))
    ledger.reverse("P2", date(2026, 3, 17))
    ledger.apply_credit("acme", date(2026, 3, 18))
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


def test_a_new_file_expects_version_zero_and_each_save_adds_one(tmp_path):
    path = tmp_path / "ledger.json"
    assert save(Ledger(), path, 0) == 1
    assert save(Ledger(), path, 1) == 2
    assert load(path)[1] == 2


def test_save_with_a_stale_version_raises_and_leaves_the_file_alone(tmp_path):
    path = tmp_path / "ledger.json"
    save(Ledger(), path, 0)
    before = path.read_bytes()
    with pytest.raises(ConflictError):
        save(sample_ledger(), path, 0)
    assert path.read_bytes() == before


def test_save_expecting_a_version_for_a_missing_file_raises_and_creates_nothing(tmp_path):
    path = tmp_path / "ledger.json"
    with pytest.raises(ConflictError):
        save(Ledger(), path, 3)
    assert not path.exists()


def test_failed_save_over_an_existing_file_keeps_the_file_and_leaves_no_extra_file(tmp_path):
    path = tmp_path / "ledger.json"
    save(Ledger(), path, 0)
    before = path.read_bytes()
    names = sorted(os.listdir(tmp_path))

    broken = Ledger()
    broken.credits["acme"] = object()  # cannot be written as JSON, so the write fails part way
    with pytest.raises(TypeError):
        save(broken, path, 1)

    assert path.read_bytes() == before
    assert sorted(os.listdir(tmp_path)) == names


def test_failed_first_save_leaves_no_file_and_no_extra_file(tmp_path):
    path = tmp_path / "ledger.json"
    broken = Ledger()
    broken.credits["acme"] = object()
    with pytest.raises(TypeError):
        save(broken, path, 0)
    assert os.listdir(tmp_path) == []


def test_load_refuses_a_file_that_is_not_json(tmp_path):
    path = tmp_path / "ledger.json"
    path.write_text("this is not a ledger", encoding="utf-8")
    with pytest.raises(StoreError):
        load(path)


@pytest.mark.xfail(
    strict=True,
    reason="R9.4: a file that is not UTF-8 text raises UnicodeDecodeError instead of StoreError",
)
def test_load_refuses_a_file_that_is_not_text(tmp_path):
    path = tmp_path / "ledger.json"
    path.write_bytes(b"\xff\xfe\x00\x81 garbage")
    with pytest.raises(StoreError):
        load(path)


@pytest.mark.parametrize(
    "document",
    [
        {"schema": 2, "version": 1},
        {"version": 1},
        [],
        None,
    ],
)
def test_load_refuses_a_file_that_is_not_schema_one(tmp_path, document):
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(StoreError):
        load(path)


def test_save_refuses_to_build_on_a_file_that_is_not_a_ledger(tmp_path):
    path = tmp_path / "ledger.json"
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(StoreError):
        save(Ledger(), path, 0)
