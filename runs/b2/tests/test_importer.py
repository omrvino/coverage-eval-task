from datetime import date
from decimal import Decimal

import pytest

from tally import Deposit, ImportFormatError, parse_deposits

HEADER = "date,reference,customer,amount"


def csv_text(*rows, header=HEADER, newline="\n"):
    return newline.join([header, *rows]) + newline


def reasons(result):
    return [(r.line, r.reason) for r in result.rejected]


# R8.1 ---------------------------------------------------------------------

def test_a_good_row_is_accepted_with_all_its_fields():
    result = parse_deposits(csv_text("2026-01-05,REF1,acme,100.50"))
    assert result.rejected == []
    [deposit] = result.accepted
    assert isinstance(deposit, Deposit)
    assert deposit.date == date(2026, 1, 5)
    assert deposit.reference == "REF1"
    assert deposit.customer == "acme"
    assert deposit.amount == Decimal("100.50")
    assert deposit.amount.as_tuple().exponent == -2


def test_columns_can_come_in_any_order_and_any_case():
    text = "AMOUNT, Customer ,Reference,DATE\n12.00,acme,R1,2026-01-05\n"
    [deposit] = parse_deposits(text).accepted
    assert (deposit.date, deposit.reference, deposit.customer, deposit.amount) == (
        date(2026, 1, 5), "R1", "acme", Decimal("12.00"))


def test_extra_columns_are_ignored():
    text = "note,date,reference,bank,customer,amount\nhi,2026-01-05,R1,xyz,acme,5\n"
    result = parse_deposits(text)
    assert result.rejected == []
    assert result.accepted[0].amount == Decimal("5.00")
    assert result.accepted[0].reference == "R1"


def test_a_leading_byte_order_mark_is_ignored():
    text = chr(0xFEFF) + csv_text("2026-01-05,R1,acme,5.00")
    result = parse_deposits(text)
    assert len(result.accepted) == 1 and result.rejected == []


@pytest.mark.parametrize("missing", ["date", "reference", "customer", "amount"])
def test_each_required_column_is_needed(missing):
    columns = [c for c in HEADER.split(",") if c != missing]
    with pytest.raises(ImportFormatError):
        parse_deposits(",".join(columns) + "\n" + ",".join("x" for _ in columns) + "\n")


@pytest.mark.parametrize("text", ["", "\n", "   \n", "a,b,c,d\n", "date,reference,customer\n"])
def test_a_bad_header_raises(text):
    with pytest.raises(ImportFormatError):
        parse_deposits(text)


def test_header_only_file_is_an_empty_result():
    result = parse_deposits(HEADER + "\n")
    assert result.accepted == [] and result.rejected == []
    assert parse_deposits(HEADER).accepted == []


def test_windows_line_endings_work():
    result = parse_deposits(csv_text("2026-01-05,R1,acme,5", "2026-01-06,R2,acme,6", newline="\r\n"))
    assert [d.reference for d in result.accepted] == ["R1", "R2"]


def test_quoted_fields_may_contain_commas():
    result = parse_deposits(csv_text('2026-01-05,R1,"Acme, Inc.","1,234.50"'))
    [deposit] = result.accepted
    assert deposit.customer == "Acme, Inc."
    assert deposit.amount == Decimal("1234.50")


# R8.2 ---------------------------------------------------------------------

def test_rejections_carry_the_line_number_with_the_header_as_line_one():
    result = parse_deposits(csv_text(
        "2026-01-05,R1,acme,5",
        "2026-01-05,,acme,5",
        "2026-01-05,R3,acme,5",
        "nope,R4,acme,5",
    ))
    assert [d.reference for d in result.accepted] == ["R1", "R3"]
    assert reasons(result) == [(3, "missing_reference"), (5, "bad_date")]


def test_the_rest_of_the_file_is_still_read_after_a_bad_row():
    result = parse_deposits(csv_text("bad,R1,acme,5", "2026-01-05,R2,acme,5", "2026-01-05,R3,acme,x"))
    assert [d.reference for d in result.accepted] == ["R2"]
    assert reasons(result) == [(2, "bad_date"), (4, "bad_amount")]


@pytest.mark.xfail(strict=True, reason="blank lines are not counted in the line numbers")
def test_blank_lines_count_in_line_numbers():
    text = HEADER + "\n\n2026-01-05,R1,acme,5\n\n\n2026-01-05,,acme,5\n2026-01-05,R3,acme,x\n"
    result = parse_deposits(text)
    assert [d.reference for d in result.accepted] == ["R1"]
    assert reasons(result) == [(6, "missing_reference"), (7, "bad_amount")]


def test_blank_lines_are_neither_accepted_nor_rejected():
    text = HEADER + "\n\n2026-01-05,R1,acme,5\n\n\n2026-01-06,R2,acme,6\n\n"
    result = parse_deposits(text)
    assert [d.reference for d in result.accepted] == ["R1", "R2"]
    assert result.rejected == []


# R8.3 ---------------------------------------------------------------------

@pytest.mark.parametrize("row, reason", [
    (",R1,acme,5", "bad_date"),
    ("2026-01-05,,acme,5", "missing_reference"),
    ("2026-01-05,R1,,5", "missing_customer"),
    ("2026-13-45,R1,acme,5", "bad_date"),
    ("2026-01-05,R1,acme,", "bad_amount"),
    ("2026-01-05,R1,acme,abc", "bad_amount"),
    ("2026-01-05", "missing_reference"),
    ("2026-01-05,R1", "missing_customer"),
    ("2026-01-05,R1,acme", "bad_amount"),
])
def test_each_rejection_reason(row, reason):
    result = parse_deposits(csv_text(row))
    assert result.accepted == []
    assert reasons(result) == [(2, reason)]


@pytest.mark.parametrize("row, reason", [
    ("bad,,,bad", "missing_reference"),
    ("bad,R1,,bad", "missing_customer"),
    ("bad,R1,acme,bad", "bad_date"),
    ("2026-01-05,R1,acme,bad", "bad_amount"),
])
def test_first_matching_reason_wins(row, reason):
    assert reasons(parse_deposits(csv_text(row))) == [(2, reason)]


def test_a_duplicate_with_a_bad_amount_is_reported_as_bad_amount():
    result = parse_deposits(csv_text("2026-01-05,R1,acme,5", "2026-01-05,R1,acme,oops"))
    assert reasons(result) == [(3, "bad_amount")]


# R8.4 ---------------------------------------------------------------------

def test_duplicate_references_are_rejected_ignoring_case():
    result = parse_deposits(csv_text(
        "2026-01-05,Ref-1,acme,5",
        "2026-01-06,REF-1,other,6",
        "2026-01-07,ref-1,acme,7",
        "2026-01-08,REF-2,acme,8",
    ))
    assert [d.reference for d in result.accepted] == ["Ref-1", "REF-2"]
    assert reasons(result) == [(3, "duplicate"), (4, "duplicate")]


def test_a_rejected_row_does_not_block_a_later_good_one():
    result = parse_deposits(csv_text(
        "bad,R1,acme,5",
        "2026-01-05,R1,acme,5",
        "2026-01-06,r1,acme,6",
    ))
    assert [d.reference for d in result.accepted] == ["R1"]
    assert reasons(result) == [(2, "bad_date"), (4, "duplicate")]


def test_a_row_rejected_for_a_missing_customer_does_not_claim_its_reference():
    result = parse_deposits(csv_text("2026-01-05,R1,,5", "2026-01-05,R1,acme,5"))
    assert len(result.accepted) == 1
    assert reasons(result) == [(2, "missing_customer")]


# R8.5 ---------------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("2026-01-05", date(2026, 1, 5)),
    ("01/05/2026", date(2026, 1, 5)),
    ("12/31/2026", date(2026, 12, 31)),
    ("2028-02-29", date(2028, 2, 29)),
])
def test_both_date_formats_are_read(text, expected):
    [deposit] = parse_deposits(csv_text(f"{text},R1,acme,5")).accepted
    assert deposit.date == expected


@pytest.mark.parametrize("text", [
    "2026-02-30", "2027-02-29", "2026-13-01", "13/01/2026", "05-01-2026", "2026/01/05",
    "Jan 5 2026", "20260105", "2026-1-5x", "01/05/26", "31/12/2026", "tomorrow",
])
def test_other_dates_are_bad_dates(text):
    assert reasons(parse_deposits(csv_text(f"{text},R1,acme,5"))) == [(2, "bad_date")]


# R8.6 ---------------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("100", "100.00"), ("100.5", "100.50"), ("100.50", "100.50"), ("$100.00", "100.00"),
    ("$5", "5.00"), ("0.01", "0.01"), ("1,234", "1234.00"), ("1,234.56", "1234.56"),
    ("$1,234,567.89", "1234567.89"), ("999", "999.00"), ("12,345", "12345.00"),
])
def test_good_amounts(text, expected):
    [deposit] = parse_deposits(csv_text(f'2026-01-05,R1,acme,"{text}"')).accepted
    assert deposit.amount == Decimal(expected)
    assert deposit.amount.as_tuple().exponent == -2


@pytest.mark.parametrize("text", [
    "0", "0.00", "$0", "-5", "-5.00", "$-5", "-$5", "(5.00)", "1.234", "1.2345",
    "12,34", "1,23,456", ",100", "1234,567", "1,2345", "1,000,00", "abc", "5 dollars",
    "$", "$$5", "5.", "1e3", "NaN", "Infinity", "1 000", "+5", "5,",
])
def test_bad_amounts(text):
    result = parse_deposits(csv_text(f'2026-01-05,R1,acme,"{text}"'))
    assert result.accepted == []
    assert reasons(result) == [(2, "bad_amount")]
