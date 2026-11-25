"""SPEC section 8: bank import."""

from datetime import date
from decimal import Decimal

import pytest

from helpers import D
from tally import ImportFormatError, parse_deposits

HEADER = "date,reference,customer,amount\n"


def accepted(result):
    return [(d.date, d.reference, d.customer, d.amount) for d in result.accepted]


def rejected(result):
    return [(r.line, r.reason) for r in result.rejected]


def row(when="2026-01-05", reference="R1", customer="acme", amount="10.00"):
    return f"{when},{reference},{customer},{amount}\n"


GOOD = (date(2026, 1, 5), "R1", "acme", D("10.00"))


# -- R8.1 ------------------------------------------------------------------


@pytest.mark.parametrize("text", [
    "date,reference,customer,amount\n2026-01-05,R1,acme,10.00\n",
    "date,reference,customer,amount\n2026-01-05,R1,acme,10.00",
    "date,reference,customer,amount\r\n2026-01-05,R1,acme,10.00\r\n",
    "amount,customer,reference,date\n10.00,acme,R1,2026-01-05\n",
    "Date,REFERENCE,Customer,aMOUNT\n2026-01-05,R1,acme,10.00\n",
    "bank,date,reference,memo,customer,amount,x\nB,2026-01-05,R1,hi,acme,10.00,\n",
    "﻿date,reference,customer,amount\n2026-01-05,R1,acme,10.00\n",
    "﻿AMOUNT,customer,reference,date,x\n10.00,acme,R1,2026-01-05,y\n",
], ids=["plain", "no final newline", "crlf", "any order", "any case", "extra columns",
        "byte order mark", "all at once"])
def test_r8_1_headers_that_work(text):
    result = parse_deposits(text)
    assert accepted(result) == [GOOD]
    assert rejected(result) == []


@pytest.mark.parametrize("header", [
    "", "\n", "foo,bar\n",
    "reference,customer,amount\n", "date,customer,amount\n", "date,reference,amount\n",
    "date,reference,customer\n", "dates,reference,customer,amount\n",
    "date;reference;customer;amount\n",
], ids=repr)
def test_r8_1_missing_columns(header):
    with pytest.raises(ImportFormatError):
        parse_deposits(header + (row() if header else ""))


def test_r8_1_header_only():
    result = parse_deposits(HEADER)
    assert (accepted(result), rejected(result)) == ([], [])


def test_r8_1_quoted_cells():
    result = parse_deposits(HEADER + '2026-01-05,R1,"Smith, Jones & Co","$1,234.50"\n')
    assert accepted(result) == [(date(2026, 1, 5), "R1", "Smith, Jones & Co", D("1234.50"))]


# -- R8.2 ------------------------------------------------------------------


def test_r8_2_bad_rows_do_not_stop_the_file():
    text = HEADER + row(amount="x") + row(reference="R2") + row(when="soon", reference="R3") + row(
        reference="R4")
    result = parse_deposits(text)
    assert [d.reference for d in result.accepted] == ["R2", "R4"]
    assert rejected(result) == [(2, "bad_amount"), (4, "bad_date")]


def test_r8_2_trailing_blank_lines_are_ignored():
    result = parse_deposits(HEADER + row() + row(amount="x") + "\n\n")
    assert accepted(result) == [GOOD]
    assert rejected(result) == [(3, "bad_amount")]


def test_r8_2_blank_lines_are_neither_accepted_nor_rejected():
    result = parse_deposits(HEADER + "\n" + row() + "\n\n" + row(reference="R2") + "\n")
    assert [d.reference for d in result.accepted] == ["R1", "R2"]
    assert rejected(result) == []


R8_2 = pytest.mark.xfail(strict=True, reason="R8.2: blank lines are left out of line numbers")


@R8_2
@pytest.mark.parametrize("text, expected", [
    (HEADER + "\n" + row(amount="x"), [(3, "bad_amount")]),
    (HEADER + row() + "\n\n" + row(reference="") + "\n" + row(when="x"),
     [(5, "missing_reference"), (7, "bad_date")]),
    ((HEADER + "\n" + row(customer="")).replace("\n", "\r\n"), [(3, "missing_customer")]),
], ids=["one", "several", "crlf"])
def test_r8_2_blank_lines_count_in_line_numbers(text, expected):
    assert rejected(parse_deposits(text)) == expected


@pytest.mark.xfail(strict=True, reason="R8.2: rows are counted instead of lines in the file")
def test_r8_2_line_numbers_after_a_cell_that_spans_lines():
    text = (
        "date,reference,customer,amount,memo\n"
        '2026-01-05,R1,acme,10.00,"two\nlines"\n'
        "2026-01-05,R2,acme,x,\n"
    )
    assert rejected(parse_deposits(text)) == [(4, "bad_amount")]


# -- R8.3 ------------------------------------------------------------------


@pytest.mark.parametrize("bad, reason", [
    (row(reference=""), "missing_reference"),
    (row(reference="  "), "missing_reference"),
    (row(customer=""), "missing_customer"),
    (row(customer="  "), "missing_customer"),
    (row(when=""), "bad_date"),
    (row(amount=""), "bad_amount"),
    (row(), "duplicate"),
    # first match wins
    (row(reference="", customer="", when="x", amount="x"), "missing_reference"),
    (row(reference="", amount="x"), "missing_reference"),
    (row(customer="", when="x", amount="x"), "missing_customer"),
    (row(when="x", amount="x"), "bad_date"),
    # cells missing at the end of the row
    ("2026-01-05\n", "missing_reference"),
    ("2026-01-05,R9\n", "missing_customer"),
    ("2026-01-05,R9,acme\n", "bad_amount"),
])
def test_r8_3_reasons(bad, reason):
    """R1 was already accepted, so every row that names it is a duplicate as well."""
    result = parse_deposits(HEADER + row() + bad)
    assert accepted(result) == [GOOD]
    assert rejected(result) == [(3, reason)]


# -- R8.4 ------------------------------------------------------------------


def test_r8_4_duplicates_ignore_case():
    text = HEADER + row(reference="Ab-1") + row(reference="aB-1", customer="other", amount="5")
    result = parse_deposits(text)
    assert [(d.reference, d.customer) for d in result.accepted] == [("Ab-1", "acme")]
    assert rejected(result) == [(3, "duplicate")]


def test_r8_4_every_later_copy_is_a_duplicate():
    result = parse_deposits(HEADER + row() * 3)
    assert len(result.accepted) == 1
    assert rejected(result) == [(3, "duplicate"), (4, "duplicate")]


@pytest.mark.parametrize("bad, reason", [
    (row(customer=""), "missing_customer"), (row(when="x"), "bad_date"),
    (row(amount="-1"), "bad_amount"),
])
def test_r8_4_rejected_row_does_not_block_a_later_good_one(bad, reason):
    result = parse_deposits(HEADER + bad + row() + row())
    assert accepted(result) == [GOOD]
    assert rejected(result) == [(2, reason), (4, "duplicate")]


def test_r8_4_files_are_independent():
    for _ in range(2):
        assert accepted(parse_deposits(HEADER + row())) == [GOOD]


# -- R8.5 ------------------------------------------------------------------


@pytest.mark.parametrize("text, expected", [
    ("2026-01-05", date(2026, 1, 5)),
    ("01/05/2026", date(2026, 1, 5)),  # month first
    ("12/31/2025", date(2025, 12, 31)),
    ("2028-02-29", date(2028, 2, 29)),
    ("02/29/2028", date(2028, 2, 29)),
])
def test_r8_5_dates(text, expected):
    assert [d.date for d in parse_deposits(HEADER + row(when=text)).accepted] == [expected]


@pytest.mark.parametrize("text", [
    "31/12/2025", "2026-13-01", "2026-02-29", "02/30/2026", "2026/01/05", "01-05-2026",
    "01/05/26", "20260105", "Jan 5 2026", "2026-01-05T00:00", "2026-01-05 x", "today", "0",
])
def test_r8_5_bad_dates(text):
    assert rejected(parse_deposits(HEADER + row(when=text))) == [(2, "bad_date")]


# -- R8.6 ------------------------------------------------------------------


def amount_row(text):
    return HEADER + f'2026-01-05,R1,acme,"{text}"\n'


@pytest.mark.parametrize("text, expected", [
    ("10", "10.00"), ("10.5", "10.50"), ("10.55", "10.55"), ("0.01", "0.01"),
    ("$10", "10.00"), ("$10.55", "10.55"), ("1,000", "1000.00"), ("12,345.60", "12345.60"),
    ("$1,234,567.89", "1234567.89"), ("999,999", "999999.00"), ("1234567.89", "1234567.89"),
])
def test_r8_6_amounts(text, expected):
    (deposit,) = parse_deposits(amount_row(text)).accepted
    assert isinstance(deposit.amount, Decimal)
    assert deposit.amount == D(expected)


@pytest.mark.parametrize("text", [
    "0", "0.00", "$0", "-5", "-5.00", "$-5", "-$5", "(5.00)", "($5)", "5-",
    "1,00", "10,00.00", "1,0000", "1,23,456", "1234,567", ",100", "100,", "1,,000", "1,000,",
    "1.005", "1.000", "0.001", "1.2.3", "1.00,000",
    "$$5", "5$", "USD 5", "5 USD", "1e3", "abc", "$", ".", "NaN", "inf", "1 000", "1_000",
])
def test_r8_6_bad_amounts(text):
    result = parse_deposits(amount_row(text))
    assert accepted(result) == []
    assert rejected(result) == [(2, "bad_amount")]
