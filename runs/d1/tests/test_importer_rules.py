from datetime import date
from decimal import Decimal

import pytest

from tally import Deposit, ImportFormatError, parse_deposits

D = Decimal
HEADER = "date,reference,customer,amount\n"


def outcome(text):
    result = parse_deposits(text)
    return [(r.line, r.reason) for r in result.rejected]


def test_reads_a_good_row_with_a_formatted_amount():
    result = parse_deposits(HEADER + '2026-01-05,R1,acme,"$1,234.50"\n')
    assert result.accepted == [Deposit(date(2026, 1, 5), "R1", "acme", D("1234.50"))]
    assert result.rejected == []


def test_columns_may_come_in_any_order_any_case_with_extra_columns_ignored():
    text = ' Amount , Note , Customer ,DATE, Reference \n"$5",x,beta,01/05/2026,R2\n'
    assert parse_deposits(text).accepted == [Deposit(date(2026, 1, 5), "R2", "beta", D("5.00"))]


def test_leading_byte_order_mark_is_ignored():
    result = parse_deposits("﻿" + HEADER + "2026-01-05,R1,acme,10\n")
    assert len(result.accepted) == 1


@pytest.mark.parametrize(
    "header",
    ["date,reference,customer", "reference,customer,amount", "", "\n"],
)
def test_header_missing_a_required_column_is_a_format_error(header):
    with pytest.raises(ImportFormatError):
        parse_deposits(header)


def test_missing_column_error_names_the_column():
    with pytest.raises(ImportFormatError, match="amount"):
        parse_deposits("date,reference,customer\n")


@pytest.mark.parametrize(
    "row, reason",
    [
        ("2026-01-05,,acme,10", "missing_reference"),
        ("2026-01-05,R1,,10", "missing_customer"),
        ("2026-02-30,R1,acme,10", "bad_date"),
        ("January 5,R1,acme,10", "bad_date"),
        ("2026-01-05,R1,acme,-5", "bad_amount"),
        ("2026-01-05,R1,acme,(5.00)", "bad_amount"),
        ('2026-01-05,R1,acme,"1,00"', "bad_amount"),
        ("2026-01-05,R1,acme,0", "bad_amount"),
        ("2026-01-05,R1,acme,5.123", "bad_amount"),
        ("2026-01-05,R1,acme,abc", "bad_amount"),
    ],
)
def test_each_bad_row_is_rejected_with_its_reason(row, reason):
    result = parse_deposits(HEADER + row + "\n")
    assert result.accepted == []
    assert [(r.line, r.reason) for r in result.rejected] == [(2, reason)]


@pytest.mark.parametrize(
    "row, reason",
    [
        ("bad,,,x", "missing_reference"),
        ("bad,R1,,x", "missing_customer"),
        ("bad,R1,acme,x", "bad_date"),
        ("2026-01-05,R1,acme,x", "bad_amount"),
    ],
)
def test_first_failing_check_gives_the_reason(row, reason):
    assert outcome(HEADER + row + "\n") == [(2, reason)]


def test_duplicate_reference_ignoring_case_is_rejected():
    text = HEADER + "2026-01-05,R1,acme,10\n2026-01-06,r1,acme,20\n"
    result = parse_deposits(text)
    assert len(result.accepted) == 1
    assert [(r.line, r.reason) for r in result.rejected] == [(3, "duplicate")]


def test_duplicate_check_comes_after_the_amount_check():
    text = HEADER + "2026-01-05,R1,acme,10\n2026-01-05,R1,acme,x\n"
    assert outcome(text) == [(3, "bad_amount")]


def test_a_rejected_row_does_not_block_a_later_good_one_with_the_same_reference():
    text = HEADER + "2026-01-05,R1,,10\n2026-01-05,R1,acme,10\n"
    result = parse_deposits(text)
    assert [(r.line, r.reason) for r in result.rejected] == [(2, "missing_customer")]
    assert [d.customer for d in result.accepted] == ["acme"]


def test_bad_rows_report_their_line_numbers_and_good_rows_still_load():
    text = HEADER + "2026-01-05,,acme,10\n2026-01-05,R2,acme,10\n2026-01-05,R3,acme,x\n"
    result = parse_deposits(text)
    assert [d.reference for d in result.accepted] == ["R2"]
    assert [(r.line, r.reason) for r in result.rejected] == [(2, "missing_reference"), (4, "bad_amount")]


def test_blank_lines_are_neither_accepted_nor_rejected():
    text = HEADER + "\n2026-01-05,R1,acme,10\n\n  ,  ,  ,\n"
    result = parse_deposits(text)
    assert len(result.accepted) == 1
    assert result.rejected == []


@pytest.mark.xfail(strict=True, reason="R8.2: blank lines count toward line numbers")
def test_line_numbers_count_blank_lines():
    assert outcome(HEADER + "\n2026-01-05,,acme,10\n") == [(3, "missing_reference")]


@pytest.mark.parametrize(
    "text, expected",
    [("$1,000", "1000.00"), ("1000.5", "1000.50"), ("$0.01", "0.01"),
     ("1,234,567.89", "1234567.89"), ("12", "12.00")],
)
def test_amount_formats(text, expected):
    result = parse_deposits(HEADER + f'2026-01-05,R1,acme,"{text}"\n')
    assert result.accepted[0].amount == D(expected)


@pytest.mark.parametrize("text", ["2026-01-05", "01/05/2026"])
def test_both_date_formats_are_read(text):
    result = parse_deposits(HEADER + f"{text},R1,acme,10\n")
    assert result.accepted[0].date == date(2026, 1, 5)


def test_cells_are_trimmed():
    result = parse_deposits(HEADER + "2026-01-05, R1 , acme ,10\n")
    assert result.accepted[0].reference == "R1"
    assert result.accepted[0].customer == "acme"


def test_short_row_is_missing_its_later_columns():
    assert outcome(HEADER + "2026-01-05,R1\n") == [(2, "missing_customer")]


def test_header_only_gives_an_empty_result():
    result = parse_deposits(HEADER)
    assert result.accepted == []
    assert result.rejected == []
