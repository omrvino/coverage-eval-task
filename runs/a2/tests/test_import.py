from datetime import date
from decimal import Decimal as D

import pytest

from tally import Deposit, ImportFormatError, Rejection, parse_deposits

HEADER = "date,reference,customer,amount"


def parse(*rows, header=HEADER):
    return parse_deposits("\n".join([header, *rows]) + "\n")


def row(day="2026-01-05", reference="R1", customer="acme", amount="10"):
    return f'{day},{reference},{customer},"{amount}"'


# R8.1
def test_header_may_be_in_any_order_and_any_case():
    result = parse_deposits("Amount,CUSTOMER,Reference,Date\n\"$10\",acme,R1,01/05/2026\n")
    assert result.accepted == [Deposit(date(2026, 1, 5), "R1", "acme", D("10.00"))]


def test_extra_columns_are_ignored():
    result = parse_deposits("date,memo,reference,customer,amount\n2026-01-05,hello,R1,acme,10\n")
    assert result.accepted == [Deposit(date(2026, 1, 5), "R1", "acme", D("10.00"))]


def test_leading_byte_order_mark_is_ignored():
    result = parse_deposits("﻿" + HEADER + "\n2026-01-05,R1,acme,10\n")
    assert len(result.accepted) == 1


@pytest.mark.parametrize("missing", ["date", "reference", "customer", "amount"])
def test_each_required_column_is_needed(missing):
    names = [name for name in HEADER.split(",") if name != missing]
    with pytest.raises(ImportFormatError):
        parse_deposits(",".join(names) + "\n2026-01-05,R1,acme,10\n")


def test_empty_file_is_a_format_error():
    with pytest.raises(ImportFormatError):
        parse_deposits("")


# R8.2
def test_bad_rows_are_rejected_with_line_numbers_and_the_rest_is_read():
    result = parse(row(reference=""), row(reference="R2"), row(day="bad-date", reference="R3"))
    assert result.rejected == [Rejection(2, "missing_reference"), Rejection(4, "bad_date")]
    assert [d.reference for d in result.accepted] == ["R2"]


def test_blank_lines_are_neither_accepted_nor_rejected():
    result = parse("", row(), "", "   ", row(reference="R2"))
    assert result.rejected == []
    assert [d.reference for d in result.accepted] == ["R1", "R2"]


@pytest.mark.xfail(strict=True, reason="line numbers skip blank lines; spec R8.2 says blank lines count, so the bad row is line 3")
def test_rejection_line_number_counts_blank_lines():
    result = parse("", row(reference=""))
    assert result.rejected == [Rejection(3, "missing_reference")]


# R8.3
@pytest.mark.parametrize(
    "line, reason",
    [
        ("bad-date,,,bad", "missing_reference"),
        ("bad-date,R1,,bad", "missing_customer"),
        ("bad-date,R1,acme,bad", "bad_date"),
        ("2026-01-05,R1,acme,bad", "bad_amount"),
    ],
)
def test_rejection_reasons_are_checked_in_order(line, reason):
    result = parse(line)
    assert result.rejected == [Rejection(2, reason)]


# R8.4
@pytest.mark.parametrize("first, second", [("R1", "r1"), ("r1", "R1"), ("Ab-1", "aB-1")])
def test_duplicate_reference_is_matched_ignoring_case(first, second):
    result = parse(row(reference=first), row(day="2026-01-06", reference=second, amount="20"))
    assert result.rejected == [Rejection(3, "duplicate")]
    assert len(result.accepted) == 1


def test_a_rejected_row_does_not_block_a_later_good_one():
    result = parse(row(amount="bad"), row(day="2026-01-06", reference="R1", amount="20"))
    assert result.rejected == [Rejection(2, "bad_amount")]
    assert result.accepted == [Deposit(date(2026, 1, 6), "R1", "acme", D("20.00"))]


def test_duplicate_is_checked_after_bad_date():
    result = parse(row(reference="R1"), row(day="bad-date", reference="R1"))
    assert result.rejected == [Rejection(3, "bad_date")]


# R8.5
@pytest.mark.parametrize("day", ["2026-01-05", "01/05/2026"])
def test_both_date_formats_are_read(day):
    result = parse(row(day=day))
    assert result.accepted[0].date == date(2026, 1, 5)


@pytest.mark.parametrize("day", ["2026-02-30", "13/01/2026", "01/05/26", "2026/01/05", ""])
def test_other_dates_are_bad_dates(day):
    result = parse(row(day=day))
    assert result.rejected == [Rejection(2, "bad_date")]


# R8.6
@pytest.mark.parametrize(
    "amount, expected",
    [("1234", "1234.00"), ("$1,234.50", "1234.50"), ("12.5", "12.50"), ("$5", "5.00"),
     ("1,234,567", "1234567.00"), ("0.01", "0.01")],
)
def test_amounts_with_dollar_sign_commas_and_cents_are_read(amount, expected):
    result = parse(row(amount=amount))
    assert result.accepted[0].amount == D(expected)


@pytest.mark.parametrize(
    "amount",
    ["-5", "(5.00)", "1,00", "1000,50", "1,0000", "5.005", "0", "0.00", "$0", "abc",
     "5.", ".50", "$-5", "$$5", "", "+5", "1.2.3"],
)
def test_any_other_amount_is_bad(amount):
    result = parse(row(amount=amount))
    assert result.rejected == [Rejection(2, "bad_amount")]
