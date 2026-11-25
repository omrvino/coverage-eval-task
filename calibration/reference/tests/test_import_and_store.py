import json
from datetime import date
from decimal import Decimal as D

import pytest

from tally import ConflictError, ImportFormatError, Invoice, Ledger, Line, StoreError, load, parse_deposits, save

HEAD = "date,reference,customer,amount\n"


def reasons(body):
    return [(r.line, r.reason) for r in parse_deposits(HEAD + body).rejected]


def accepted(body):
    return [(d.date, d.reference, d.customer, d.amount) for d in parse_deposits(HEAD + body).accepted]


def test_good_rows():
    assert accepted('2026-01-05,R1,acme,"$1,200.50"\n01/06/2026,R2,acme,7\n') == [
        (date(2026, 1, 5), "R1", "acme", D("1200.50")), (date(2026, 1, 6), "R2", "acme", D("7.00"))]


def test_header_order_case_extras_and_bom():
    text = chr(0xFEFF) + "Date,note,Amount,CUSTOMER,reference\n2026-01-05,hi,5,acme,R1\n"
    assert parse_deposits(text).accepted[0].customer == "acme"
    for bad in ("", "date,reference,customer\n"):
        with pytest.raises(ImportFormatError):
            parse_deposits(bad)


def test_reasons_and_first_match_wins():
    assert reasons("x,,,\nx,R,,\nx,R,acme,x\n2026-01-05,R,acme,x\n") == [
        (2, "missing_reference"), (3, "missing_customer"), (4, "bad_date"), (5, "bad_amount")]


@pytest.mark.xfail(strict=True, reason="R8.2: blank lines not counted")
def test_blank_lines_count():
    assert reasons("\n\n2026-01-05,R,acme,x\n") == [(4, "bad_amount")]


def test_blank_lines_are_not_rows():
    result = parse_deposits(HEAD + "\n2026-01-05,R,acme,5\n , , ,\n")
    assert len(result.accepted) == 1 and result.rejected == []


def test_duplicates_ignore_case_and_rejected_rows():
    body = "2026-01-05,R1,acme,x\n2026-01-05,R1,acme,5\n2026-01-05,r1,acme,6\n"
    assert reasons(body) == [(2, "bad_amount"), (4, "duplicate")]
    assert [a[3] for a in accepted(body)] == [D("5.00")]


@pytest.mark.parametrize("amount", ["0", "0.00", "-5", "(5.00)", "1.234", '"12,34"', '"1,2345"', "abc", "", "$"])
def test_bad_amounts(amount):
    assert reasons(f"2026-01-05,R,acme,{amount}\n") == [(2, "bad_amount")]


def full_ledger():
    ledger = Ledger([date(2026, 1, 19)])
    ledger.add(Invoice("A", "acme", date(2026, 1, 5), "2/10 NET 30", [Line("w", "1.5", "100.00", "5", False)], tax_rate="6"))
    ledger.issue("A")
    ledger.add(Invoice("B", "acme", date(2026, 1, 5), "EOM", [Line("w", 1, "3.10")]))
    ledger.receive("P", "acme", "200.10", date(2026, 1, 8))
    return ledger


def test_round_trip(tmp_path):
    ledger, path = full_ledger(), tmp_path / "l.json"
    assert save(ledger, path, 0) == 1
    back, version = load(path)
    assert version == 1
    for name in ("holidays", "invoices", "payments", "credits", "events"):
        assert getattr(back, name) == getattr(ledger, name)


def test_versions(tmp_path):
    path = tmp_path / "l.json"
    for wrong in (1, 5):
        with pytest.raises(ConflictError):
            save(Ledger(), path, wrong)
    assert save(Ledger(), path, 0) == 1
    assert save(full_ledger(), path, 1) == 2
    before = path.read_bytes()
    for wrong in (0, 1, 3):
        with pytest.raises(ConflictError):
            save(Ledger(), path, wrong)
    assert path.read_bytes() == before


def test_failed_save_changes_nothing(tmp_path):
    path = tmp_path / "l.json"
    save(full_ledger(), path, 0)
    before = path.read_bytes()
    broken = full_ledger()
    broken.credits["acme"] = object()
    with pytest.raises(TypeError):
        save(broken, path, 1)
    assert path.read_bytes() == before
    assert [p.name for p in tmp_path.iterdir()] == ["l.json"]


@pytest.mark.xfail(strict=True, reason="R9.4: UnicodeDecodeError")
def test_binary_file(tmp_path):
    path = tmp_path / "l.json"
    path.write_bytes(b"\xff\xfe\x00")
    with pytest.raises(StoreError):
        load(path)


@pytest.mark.parametrize("text", ["not json", "[]", json.dumps({"schema": 2, "version": 1}), "{}"])
def test_bad_files(tmp_path, text):
    path = tmp_path / "l.json"
    path.write_text(text)
    with pytest.raises(StoreError):
        load(path)
