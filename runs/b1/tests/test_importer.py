from datetime import date
from decimal import Decimal

import pytest

from tally import Deposit, ImportFormatError, parse_deposits

D = Decimal
HEADER = "date,reference,customer,amount\n"


def reasons(result):
    return [(r.line, r.reason) for r in result.rejected]


# -- R8.1 ------------------------------------------------------------------

def test_a_good_file_is_read():
    result = parse_deposits(HEADER + '2026-01-05,R1,acme,100.50\n2026-01-06,R2,other,"$1,200.00"\n')
    assert result.rejected == []
    assert result.accepted == [
        Deposit(date(2026, 1, 5), "R1", "acme", D("100.50")),
        Deposit(date(2026, 1, 6), "R2", "other", D("1200.00")),
    ]


def test_columns_may_come_in_any_order_and_any_case_with_extras():
    text = "Amount,Memo,CUSTOMER,Reference,Date\n12.50,rent,acme,R1,2026-01-05\n"
    result = parse_deposits(text)
    assert result.accepted == [Deposit(date(2026, 1, 5), "R1", "acme", D("12.50"))]


def test_a_leading_byte_order_mark_is_ignored():
    result = parse_deposits(chr(0xFEFF) + HEADER + "2026-01-05,R1,acme,5\n")
    assert [d.reference for d in result.accepted] == ["R1"]


@pytest.mark.parametrize("header", [
    "reference,customer,amount", "date,customer,amount", "date,reference,amount",
    "date,reference,customer", "", "a,b,c,d", "date reference customer amount",
])
def test_a_missing_header_column_is_a_format_error(header):
    with pytest.raises(ImportFormatError):
        parse_deposits(header + "\n2026-01-05,R1,acme,5\n")


def test_empty_text_is_a_format_error():
    with pytest.raises(ImportFormatError):
        parse_deposits("")


def test_a_header_only_file_has_nothing_in_it():
    result = parse_deposits(HEADER)
    assert result.accepted == [] and result.rejected == []


def test_extra_cells_beyond_the_header_are_ignored():
    result = parse_deposits(HEADER + "2026-01-05,R1,acme,5,surplus,more\n")
    assert len(result.accepted) == 1


# -- R8.2 ------------------------------------------------------------------

def test_a_bad_row_is_rejected_with_its_line_number_and_the_rest_is_read():
    text = HEADER + (
        "2026-01-05,R1,acme,5\n"      # line 2
        "2026-01-05,R2,acme,oops\n"   # line 3
        "2026-01-05,R3,acme,7\n"      # line 4
    )
    result = parse_deposits(text)
    assert [d.reference for d in result.accepted] == ["R1", "R3"]
    assert reasons(result) == [(3, "bad_amount")]


def test_the_header_is_line_1():
    result = parse_deposits(HEADER + ",R1,acme,5\n")
    assert reasons(result) == [(2, "bad_date")]


def test_blank_lines_are_neither_accepted_nor_rejected():
    result = parse_deposits(HEADER + "\n\n2026-01-05,R1,acme,5\n\n")
    assert len(result.accepted) == 1
    assert result.rejected == []


@pytest.mark.xfail(strict=True, reason="blank lines are not counted in the line numbers of later rows")
def test_blank_lines_count_in_line_numbers():
    text = HEADER + (
        "\n"                           # line 2
        "2026-01-05,R1,acme,oops\n"    # line 3
        "\n"                           # line 4
        "\n"                           # line 5
        "2026-01-05,R2,acme,oops\n"    # line 6
    )
    assert reasons(parse_deposits(text)) == [(3, "bad_amount"), (6, "bad_amount")]


def test_windows_line_endings_are_read():
    result = parse_deposits("date,reference,customer,amount\r\n2026-01-05,R1,acme,5\r\n2026-01-05,R2,acme,x\r\n")
    assert len(result.accepted) == 1
    assert reasons(result) == [(3, "bad_amount")]


def test_the_last_line_needs_no_newline():
    result = parse_deposits(HEADER + "2026-01-05,R1,acme,5")
    assert len(result.accepted) == 1


# -- R8.3 ------------------------------------------------------------------

@pytest.mark.parametrize("row, reason", [
    ("2026-01-05,,acme,5", "missing_reference"),
    ("2026-01-05,   ,acme,5", "missing_reference"),
    ("2026-01-05,R1,,5", "missing_customer"),
    ("2026-01-05,R1,  ,5", "missing_customer"),
    ("tomorrow,R1,acme,5", "bad_date"),
    (",R1,acme,5", "bad_date"),
    ("2026-01-05,R1,acme,five", "bad_amount"),
    ("2026-01-05,R1,acme,", "bad_amount"),
    ("2026-01-05,R1", "missing_customer"),
    ("2026-01-05", "missing_reference"),
])
def test_each_rejection_reason(row, reason):
    result = parse_deposits(HEADER + row + "\n")
    assert result.accepted == []
    assert reasons(result) == [(2, reason)]


@pytest.mark.parametrize("row, reason", [
    ("bad,,,bad", "missing_reference"),
    ("bad,R1,,bad", "missing_customer"),
    ("bad,R1,acme,bad", "bad_date"),
    ("2026-01-05,R1,acme,bad", "bad_amount"),
])
def test_first_matching_reason_wins(row, reason):
    result = parse_deposits(HEADER + "2026-01-01,R0,acme,1\n" + row + "\n")
    assert reasons(result) == [(3, reason)]


def test_duplicate_comes_after_the_other_reasons():
    text = HEADER + "2026-01-05,R1,acme,5\n2026-01-05,R1,acme,bad\n2026-01-05,R1,,5\nbad,R1,acme,5\n"
    assert reasons(parse_deposits(text)) == [(3, "bad_amount"), (4, "missing_customer"), (5, "bad_date")]


# -- R8.4 ------------------------------------------------------------------

def test_a_repeated_reference_is_a_duplicate_ignoring_case():
    text = HEADER + "2026-01-05,Ref-1,acme,5\n2026-01-06,REF-1,other,9\n2026-01-07,ref-1,acme,1\n"
    result = parse_deposits(text)
    assert [d.reference for d in result.accepted] == ["Ref-1"]
    assert reasons(result) == [(3, "duplicate"), (4, "duplicate")]


def test_a_rejected_row_does_not_block_a_later_good_one():
    text = HEADER + "2026-01-05,R1,acme,bad\n2026-01-05,R1,acme,5\n2026-01-05,R1,acme,6\n"
    result = parse_deposits(text)
    assert reasons(result) == [(2, "bad_amount"), (4, "duplicate")]
    assert result.accepted == [Deposit(date(2026, 1, 5), "R1", "acme", D("5.00"))]


def test_different_references_are_not_duplicates():
    result = parse_deposits(HEADER + "2026-01-05,R1,acme,5\n2026-01-05,R2,acme,5\n")
    assert len(result.accepted) == 2


# -- R8.5 ------------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("2026-01-05", date(2026, 1, 5)),
    ("01/05/2026", date(2026, 1, 5)),
    ("12/31/2026", date(2026, 12, 31)),
    ("2028-02-29", date(2028, 2, 29)),
])
def test_both_date_formats(text, expected):
    result = parse_deposits(HEADER + f"{text},R1,acme,5\n")
    assert result.accepted[0].date == expected


@pytest.mark.parametrize("text", [
    "13/01/2026", "2026/01/05", "01-05-2026", "2026-13-01", "2026-02-30", "2027-02-29",
    "5 Jan 2026", "20260105", "01/05/26", "2026-01-05T10:00", "garbage",
])
def test_other_dates_are_bad(text):
    result = parse_deposits(HEADER + f"{text},R1,acme,5\n")
    assert reasons(result) == [(2, "bad_date")]


# -- R8.6 ------------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("5", "5.00"),
    ("5.5", "5.50"),
    ("5.25", "5.25"),
    ("$5.25", "5.25"),
    ('"1,234"', "1234.00"),
    ('"$1,234.50"', "1234.50"),
    ('"1,234,567.89"', "1234567.89"),
    ("1234567.89", "1234567.89"),
    ("0.01", "0.01"),
])
def test_good_amounts(text, expected):
    result = parse_deposits(HEADER + f"2026-01-05,R1,acme,{text}\n")
    assert result.rejected == []
    assert result.accepted[0].amount == D(expected)
    assert result.accepted[0].amount.as_tuple().exponent == -2


@pytest.mark.parametrize("text", [
    "0", "0.00", "$0", "-5", "-5.00", "$-5", "-$5", '"(5.00)"', "(5.00)",
    "5.001", "5.123", '"12,34"', '"1,2345"', '"1234,567"', '",123"', '"1,23"', '"1,000,00"',
    "abc", "5abc", "$$5", "5$", "1e3", "5.", "1.2.3", "NaN", "inf", "5 000",
])
def test_bad_amounts(text):
    result = parse_deposits(HEADER + f"2026-01-05,R1,acme,{text}\n")
    assert result.accepted == []
    assert reasons(result) == [(2, "bad_amount")]
