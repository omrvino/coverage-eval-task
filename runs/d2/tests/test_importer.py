from datetime import date
from decimal import Decimal

import pytest

from tally import Deposit, ImportFormatError, parse_deposits

D = Decimal
HEADER = "date,reference,customer,amount"


def read(*rows):
    return "\n".join([HEADER, *rows]) + "\n"


def test_accepts_good_rows_with_dollar_signs_and_commas():
    result = parse_deposits(read('2026-01-05,R1,Acme,"$1,234.5"', "01/06/2026,R2,Bolt,75"))
    assert result.accepted == [
        Deposit(date(2026, 1, 5), "R1", "Acme", D("1234.50")),
        Deposit(date(2026, 1, 6), "R2", "Bolt", D("75.00")),
    ]
    assert result.rejected == []


def test_header_order_case_bom_and_extra_columns():
    text = "﻿Amount, Customer ,REFERENCE,Date,Memo\n40.00,Acme,R1,2026-01-05,lunch\n"
    result = parse_deposits(text)
    assert result.accepted == [Deposit(date(2026, 1, 5), "R1", "Acme", D("40.00"))]


@pytest.mark.parametrize("text", ["", "date,reference,amount\n1,2,3\n"])
def test_missing_columns_is_a_format_error(text):
    with pytest.raises(ImportFormatError):
        parse_deposits(text)


def test_each_bad_row_is_rejected_with_its_reason_and_line():
    result = parse_deposits(read(
        "2026-01-05,,Acme,10",
        "2026-01-05,R2,,10",
        "2026-13-05,R3,Acme,10",
        "2026-01-05,R4,Acme,-10",
        "2026-01-05,R5,Acme,10",
        "2026-01-06,r5,Acme,10",
    ))
    assert [(r.line, r.reason) for r in result.rejected] == [
        (2, "missing_reference"),
        (3, "missing_customer"),
        (4, "bad_date"),
        (5, "bad_amount"),
        (7, "duplicate"),
    ]
    assert [d.reference for d in result.accepted] == ["R5"]


def test_missing_reference_wins_over_other_problems():
    result = parse_deposits(read("not-a-date,,,nope"))
    assert [r.reason for r in result.rejected] == ["missing_reference"]


@pytest.mark.parametrize("amount", ["-5", "(5.00)", "1,00", "0", "abc", "1.234", ""])
def test_bad_amounts_are_rejected(amount):
    result = parse_deposits(read(f'2026-01-05,R1,Acme,"{amount}"'))
    assert [r.reason for r in result.rejected] == ["bad_amount"]


def test_bad_date_formats_are_rejected():
    result = parse_deposits(read("2026/01/05,R1,Acme,10"))
    assert [r.reason for r in result.rejected] == ["bad_date"]


def test_amount_forms_that_are_accepted():
    result = parse_deposits(read('2026-01-05,R1,Acme,"$5"', "2026-01-05,R2,Acme,12.5"))
    assert [d.amount for d in result.accepted] == [D("5.00"), D("12.50")]


def test_rejected_row_does_not_block_a_later_good_one():
    result = parse_deposits(read("2026-01-05,R9,Acme,-1", "2026-01-05,R9,Acme,10"))
    assert [r.reason for r in result.rejected] == ["bad_amount"]
    assert [d.reference for d in result.accepted] == ["R9"]


def test_blank_lines_are_neither_accepted_nor_rejected():
    text = HEADER + "\n\n2026-01-05,R1,Acme,10\n   ,  ,  ,  \n2026-01-06,R2,Acme,10\n"
    result = parse_deposits(text)
    assert [d.reference for d in result.accepted] == ["R1", "R2"]
    assert result.rejected == []
