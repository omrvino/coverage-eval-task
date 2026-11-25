import csv
import io
from datetime import date
from decimal import Decimal

import pytest

from tally import Deposit, ImportFormatError, Rejection, parse_deposits

D = Decimal
HEADER = ("date", "reference", "customer", "amount")
XFAIL_BLANK_LINES = pytest.mark.xfail(
    strict=True,
    reason="R8.2: blank lines are dropped before numbering, so a rejected row after a blank line gets the wrong line number; the spec counts blank lines",
)


def make(*rows, header=HEADER):
    """Build a CSV text with proper quoting, one row per line, header on line 1."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue()


def reject_reason(row):
    result = parse_deposits(make(row))
    assert result.accepted == []
    assert len(result.rejected) == 1
    return result.rejected[0].reason


def test_accepted_rows_become_deposits():
    result = parse_deposits(make(["2026-01-05", "R1", "acme", "$1,234.50"]))
    assert result.accepted == [Deposit(date(2026, 1, 5), "R1", "acme", D("1234.50"))]
    assert result.rejected == []


def test_header_may_be_in_any_order_and_any_case():
    text = make(["100", "2026-01-05", "R1", "ACME"], header=("AMOUNT", "DATE", "Reference", "customer"))
    result = parse_deposits(text)
    assert result.accepted == [Deposit(date(2026, 1, 5), "R1", "ACME", D("100.00"))]


def test_extra_columns_are_ignored():
    text = make(["see invoice 7", "2026-01-05", "R1", "acme", "10"], header=("memo", "date", "reference", "customer", "amount"))
    assert parse_deposits(text).accepted == [Deposit(date(2026, 1, 5), "R1", "acme", D("10.00"))]


def test_leading_byte_order_mark_is_ignored():
    result = parse_deposits("﻿" + make(["2026-01-05", "R1", "acme", "10"]))
    assert len(result.accepted) == 1


@pytest.mark.parametrize("missing", ["date", "reference", "customer", "amount"])
def test_missing_required_column_is_a_format_error(missing):
    header = tuple(name for name in HEADER if name != missing)
    with pytest.raises(ImportFormatError):
        parse_deposits(make(header=header))


def test_empty_file_is_a_format_error():
    with pytest.raises(ImportFormatError):
        parse_deposits("")


def test_bad_rows_are_rejected_with_their_line_number_and_the_rest_is_read():
    text = make(
        ["2026-01-05", "R1", "acme", "10"],   # line 2
        ["2026-01-06", "R2", "acme", "-5"],   # line 3
        ["2026-01-07", "R3", "acme", "20"],   # line 4
    )
    result = parse_deposits(text)
    assert [d.reference for d in result.accepted] == ["R1", "R3"]
    assert result.rejected == [Rejection(3, "bad_amount")]


def test_blank_lines_are_neither_accepted_nor_rejected():
    text = "date,reference,customer,amount\n\n2026-01-05,R1,acme,10\n\n"
    result = parse_deposits(text)
    assert [d.reference for d in result.accepted] == ["R1"]
    assert result.rejected == []


@XFAIL_BLANK_LINES
def test_line_numbers_count_blank_lines():
    text = "date,reference,customer,amount\n\n2026-01-06,R2,acme,-5\n"  # bad row is on line 3
    assert parse_deposits(text).rejected == [Rejection(3, "bad_amount")]


@pytest.mark.parametrize(
    "row, reason",
    [
        (["2026-01-05", "", "acme", "10"], "missing_reference"),
        (["2026-01-05", "", "", "abc"], "missing_reference"),
        (["2026-01-05", "R1", "", "10"], "missing_customer"),
        (["2026-01-05", "R1", "", "abc"], "missing_customer"),
        (["2026-13-05", "R1", "acme", "10"], "bad_date"),
        (["bad", "R1", "acme", "abc"], "bad_date"),
        (["2026-01-05", "R1", "acme", "0"], "bad_amount"),
    ],
)
def test_rejection_reasons_first_match_wins(row, reason):
    assert reject_reason(row) == reason


@pytest.mark.parametrize("first, second", [("R1", "r1"), ("r1", "R1")])
def test_duplicate_reference_is_rejected_ignoring_case(first, second):
    text = make(["2026-01-05", first, "acme", "10"], ["2026-01-06", second, "acme", "20"])
    assert parse_deposits(text).rejected == [Rejection(3, "duplicate")]


def test_duplicate_with_a_bad_amount_is_reported_as_bad_amount():
    text = make(["2026-01-05", "R1", "acme", "10"], ["2026-01-06", "R1", "acme", "abc"])
    assert parse_deposits(text).rejected == [Rejection(3, "bad_amount")]


def test_rejected_row_does_not_block_a_later_good_row_with_the_same_reference():
    text = make(["2026-01-05", "R1", "acme", "abc"], ["2026-01-06", "R1", "acme", "10"])
    result = parse_deposits(text)
    assert result.rejected == [Rejection(2, "bad_amount")]
    assert [d.reference for d in result.accepted] == ["R1"]


@pytest.mark.parametrize(
    "text, expected",
    [
        ("2026-01-05", date(2026, 1, 5)),
        ("01/05/2026", date(2026, 1, 5)),
    ],
)
def test_accepts_iso_and_us_dates(text, expected):
    assert parse_deposits(make([text, "R1", "acme", "10"])).accepted[0].date == expected


@pytest.mark.parametrize("text", ["05-01-2026", "2026/01/05", "Jan 5 2026", "2026-02-30"])
def test_rejects_other_date_layouts_and_impossible_dates(text):
    assert reject_reason([text, "R1", "acme", "10"]) == "bad_date"


@pytest.mark.parametrize("text", ["2026-1-5", "1/5/2026"])
@pytest.mark.xfail(
    strict=True,
    reason="R8.5: dates are read with strptime, which accepts single-digit fields; the spec allows only YYYY-MM-DD and MM/DD/YYYY",
)
def test_dates_outside_the_two_formats_are_rejected(text):
    assert reject_reason([text, "R1", "acme", "10"]) == "bad_date"


@pytest.mark.parametrize(
    "text, amount",
    [
        ("1234", D("1234.00")),
        ("$1,234.50", D("1234.50")),
        ("0.5", D("0.50")),
        ("$0.01", D("0.01")),
        ("10,000", D("10000.00")),
    ],
)
def test_accepted_amount_formats(text, amount):
    assert parse_deposits(make(["2026-01-05", "R1", "acme", text])).accepted[0].amount == amount


@pytest.mark.parametrize(
    "text",
    ["-5", "-$5", "$-5", "0", "0.00", "(5.00)", "1.234", "abc", "$", "1,00", "1,2345", "1000,00", "$ 5"],
)
def test_other_amount_formats_are_bad_amount(text):
    assert reject_reason(["2026-01-05", "R1", "acme", text]) == "bad_amount"
