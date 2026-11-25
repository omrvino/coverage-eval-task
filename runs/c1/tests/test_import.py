"""SPEC section 8: bank import."""

from datetime import date
from decimal import Decimal as D

import pytest

from tally import ImportFormatError, parse_deposits

HEADER = "date,reference,customer,amount"
JAN_5 = date(2026, 1, 5)
GOOD = "2026-01-05,R1,acme,10.00"
GOOD_DEPOSIT = (JAN_5, "R1", "acme", D("10.00"))


def parse(*rows, header=HEADER):
    return parse_deposits("\n".join([header, *rows]) + "\n")


def accepted(result):
    return [(d.date, d.reference, d.customer, d.amount) for d in result.accepted]


def rejected(result):
    return [(r.line, r.reason) for r in result.rejected]


# -- header -------------------------------------------------------------------


def test_good_row():
    result = parse(GOOD)
    assert accepted(result) == [GOOD_DEPOSIT]
    assert rejected(result) == []


def test_header_only():
    result = parse()
    assert (accepted(result), rejected(result)) == ([], [])


def test_columns_in_any_order():
    result = parse("10.00,acme,2026-01-05,R1", header="amount,customer,date,reference")
    assert accepted(result) == [GOOD_DEPOSIT]


@pytest.mark.parametrize(
    "header",
    ["DATE,REFERENCE,CUSTOMER,AMOUNT", "Date,Reference,Customer,Amount", "dAtE,reference,CUSTOMER,Amount"],
)
def test_header_in_any_case(header):
    assert accepted(parse(GOOD, header=header)) == [GOOD_DEPOSIT]


def test_extra_columns_are_ignored():
    result = parse(
        "x,2026-01-05,note,R1,acme,10.00,",
        header="bank,date,memo,reference,customer,amount,branch",
    )
    assert accepted(result) == [GOOD_DEPOSIT]
    assert rejected(result) == []


def test_leading_byte_order_mark_is_ignored():
    result = parse(GOOD, header="\N{ZERO WIDTH NO-BREAK SPACE}" + HEADER)
    assert accepted(result) == [GOOD_DEPOSIT]


@pytest.mark.parametrize(
    "header",
    [
        "reference,customer,amount",
        "date,customer,amount",
        "date,reference,amount",
        "date,reference,customer",
        "date,reference,customer,amounts",
        "2026-01-05,R1,acme,10.00",
    ],
)
def test_missing_column_is_a_format_error(header):
    with pytest.raises(ImportFormatError):
        parse(GOOD, header=header)


def test_empty_file_is_a_format_error():
    with pytest.raises(ImportFormatError):
        parse_deposits("")


# -- rows and line numbers ----------------------------------------------------


def test_bad_rows_are_rejected_with_their_line_and_the_rest_is_read():
    result = parse(
        "nonsense,R1,acme,10.00",
        "2026-01-05,R2,acme,20.00",
        "2026-01-05,R3,acme,zero",
        "2026-01-06,R4,bob,30.00",
    )
    assert accepted(result) == [
        (JAN_5, "R2", "acme", D("20.00")),
        (date(2026, 1, 6), "R4", "bob", D("30.00")),
    ]
    assert rejected(result) == [(2, "bad_date"), (4, "bad_amount")]


def test_blank_lines_are_neither_accepted_nor_rejected():
    result = parse("", GOOD, "", "", "2026-01-05,R2,acme,20.00", "")
    assert [d.reference for d in result.accepted] == ["R1", "R2"]
    assert rejected(result) == []


@pytest.mark.xfail(strict=True, reason="R8.2: blank lines are not counted in line numbers")
def test_blank_lines_count_in_line_numbers():
    result = parse("", "bad,R1,acme,10.00", "", "", "2026-01-05,R2,acme,none")
    assert rejected(result) == [(3, "bad_date"), (6, "bad_amount")]


def test_windows_line_endings():
    result = parse_deposits("\r\n".join([HEADER, GOOD, "bad,R2,acme,1.00", ""]))
    assert accepted(result) == [GOOD_DEPOSIT]
    assert rejected(result) == [(3, "bad_date")]


# -- reasons ------------------------------------------------------------------


@pytest.mark.parametrize(
    "row, reason",
    [
        ("2026-01-05,,acme,10.00", "missing_reference"),
        ("2026-01-05,R1,,10.00", "missing_customer"),
        (",R1,acme,10.00", "bad_date"),
        ("2026-01-05,R1,acme,", "bad_amount"),
        # First match wins.
        ("bad,,,bad", "missing_reference"),
        ("2026-01-05,,,10.00", "missing_reference"),
        ("bad,R1,,bad", "missing_customer"),
        ("bad,R1,acme,bad", "bad_date"),
        # Rows that stop short.
        ("2026-01-05", "missing_reference"),
        ("2026-01-05,R1", "missing_customer"),
        ("2026-01-05,R1,acme", "bad_amount"),
    ],
)
def test_reason(row, reason):
    result = parse(row)
    assert accepted(result) == []
    assert rejected(result) == [(2, reason)]


@pytest.mark.parametrize(
    "row, reason",
    [
        ("2026-01-05,R1,,10.00", "missing_customer"),
        ("bad,R1,acme,10.00", "bad_date"),
        ("2026-01-05,R1,acme,bad", "bad_amount"),
        ("2026-01-05,R1,acme,10.00", "duplicate"),
    ],
)
def test_duplicate_is_the_last_reason(row, reason):
    result = parse(GOOD, row)
    assert accepted(result) == [GOOD_DEPOSIT]
    assert rejected(result) == [(3, reason)]


# -- duplicates ---------------------------------------------------------------


@pytest.mark.parametrize("again", ["ref-1", "REF-1", "Ref-1"])
def test_duplicate_reference_ignores_case(again):
    result = parse("2026-01-05,Ref-1,acme,10.00", f"2026-01-06,{again},bob,20.00")
    assert accepted(result) == [(JAN_5, "Ref-1", "acme", D("10.00"))]
    assert rejected(result) == [(3, "duplicate")]


def test_every_later_copy_is_a_duplicate():
    result = parse(GOOD, GOOD, "2026-01-05,R2,acme,1.00", GOOD)
    assert rejected(result) == [(3, "duplicate"), (5, "duplicate")]


def test_rejected_row_does_not_block_a_later_good_one():
    result = parse("bad,R1,acme,10.00", "2026-01-05,R1,acme,bad", "2026-01-05,R1,,10.00", GOOD, GOOD)
    assert accepted(result) == [GOOD_DEPOSIT]
    assert rejected(result) == [
        (2, "bad_date"), (3, "bad_amount"), (4, "missing_customer"), (6, "duplicate"),
    ]


def test_files_do_not_share_references():
    assert accepted(parse(GOOD)) == accepted(parse(GOOD)) == [GOOD_DEPOSIT]


# -- dates --------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("2026-03-04", date(2026, 3, 4)),
        ("03/04/2026", date(2026, 3, 4)),
        ("12/31/2026", date(2026, 12, 31)),
        ("2028-02-29", date(2028, 2, 29)),
    ],
)
def test_date_formats(text, expected):
    assert [d.date for d in parse(f"{text},R1,acme,10.00").accepted] == [expected]


@pytest.mark.parametrize(
    "text",
    [
        "2026-13-01", "2026-02-30", "2027-02-29", "13/01/2026", "31/12/2026", "02/30/2026",
        "2026/01/05", "01-05-2026", "05.01.2026", "01/05/26", "26-01-05", "20260105",
        "Jan 5 2026", "2026-01-05T00:00", "today",
    ],
)
def test_other_dates_are_bad(text):
    assert rejected(parse(f"{text},R1,acme,10.00")) == [(2, "bad_date")]


# -- amounts ------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("10", "10.00"), ("10.5", "10.50"), ("10.55", "10.55"), ("0.01", "0.01"),
        ("$10.00", "10.00"), ("$5", "5.00"), ("1234.56", "1234.56"), ("1000000", "1000000.00"),
        ("1,234.56", "1234.56"), ("12,345", "12345.00"), ("123,456.7", "123456.70"),
        ("1,234,567.89", "1234567.89"), ("$1,234.00", "1234.00"),
    ],
)
def test_amounts(text, expected):
    result = parse(f'2026-01-05,R1,acme,"{text}"')
    assert [d.amount for d in result.accepted] == [D(expected)]
    amount = result.accepted[0].amount
    assert isinstance(amount, D)
    assert amount.as_tuple().exponent == -2


@pytest.mark.parametrize(
    "text",
    [
        "0", "0.00", "$0.00", "-10.00", "-$10.00", "$-10.00", "(10.00)", "($10.00)", "10.00-",
        "10.001", "10.000", "1,23", "12,34.00", "1,2345", "1234,567", ",123", "123,", "1,,234",
        "1,234,56", "1.234,56", "1.2.3", "$", "$$5", "5$", "abc", "10 00", "10.00 USD", "1e3",
        "NaN", "Infinity", "10,0.00", "10.5,000", "EUR 5",
    ],
)
def test_other_amounts_are_bad(text):
    result = parse(f'2026-01-05,R1,acme,"{text}"')
    assert accepted(result) == []
    assert rejected(result) == [(2, "bad_amount")]
