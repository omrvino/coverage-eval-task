from datetime import date
from decimal import Decimal as D

import pytest

from tally import TermsError, parse_terms

JAN5 = date(2026, 1, 5)  # a Monday


# R2.1
def test_net_days_are_calendar_days_after_the_invoice_date():
    assert parse_terms("NET 30").due_date(JAN5) == date(2026, 2, 4)
    assert parse_terms("NET 45").due_date(JAN5) == date(2026, 2, 19)
    assert parse_terms("NET 0").due_date(date(2026, 1, 6)) == date(2026, 1, 6)


# R2.2
@pytest.mark.parametrize(
    "invoice_day, due",
    [
        (date(2026, 3, 5), date(2026, 3, 31)),
        (date(2026, 3, 25), date(2026, 3, 31)),
        (date(2026, 3, 26), date(2026, 4, 30)),
        (date(2028, 2, 25), date(2028, 2, 29)),
        (date(2028, 2, 26), date(2028, 3, 31)),
    ],
)
def test_eom_is_end_of_month_or_end_of_next_month_from_the_26th(invoice_day, due):
    assert parse_terms("EOM").due_date(invoice_day) == due


# R2.3
@pytest.mark.parametrize("invoice_day", [date(2026, 1, 7), date(2026, 1, 8)])
def test_weekend_due_date_moves_forward_to_monday(invoice_day):
    # Jan 10 is a Saturday and Jan 11 a Sunday
    assert parse_terms("NET 3").due_date(invoice_day) == date(2026, 1, 12)


def test_eom_due_date_on_a_weekend_moves_forward():
    # Jan 31 2026 is a Saturday
    assert parse_terms("EOM").due_date(date(2026, 1, 15)) == date(2026, 2, 2)


def test_holiday_due_date_moves_to_the_next_day_that_is_neither():
    terms = parse_terms("NET 30")
    assert terms.due_date(JAN5, {date(2026, 2, 4)}) == date(2026, 2, 5)
    assert terms.due_date(JAN5, {date(2026, 2, 4), date(2026, 2, 5)}) == date(2026, 2, 6)


# R2.4
def test_discount_deadline_is_invoice_date_plus_discount_days():
    assert parse_terms("2/10 NET 30").discount_deadline(JAN5) == date(2026, 1, 15)


@pytest.mark.xfail(strict=True, reason="discount_deadline rolls a weekend deadline forward; spec R2.4 says it does not move")
def test_discount_deadline_does_not_move_for_a_weekend():
    # Jan 8 + 10 days is Sunday Jan 18
    assert parse_terms("2/10 NET 30").discount_deadline(date(2026, 1, 8)) == date(2026, 1, 18)


@pytest.mark.xfail(strict=True, reason="discount_deadline rolls a holiday deadline forward; spec R2.4 says it does not move")
def test_discount_deadline_does_not_move_for_a_holiday():
    assert parse_terms("2/10 NET 30").discount_deadline(JAN5, {date(2026, 1, 15)}) == date(2026, 1, 15)


# R2.5
@pytest.mark.parametrize("text", ["NET 30", "net 30", "  Net 30  ", "NET 30 "])
def test_net_terms_ignore_case_and_surrounding_spaces(text):
    assert parse_terms(text).due_date(JAN5) == date(2026, 2, 4)


@pytest.mark.parametrize("text", ["eom", "  EOM ", "Eom"])
def test_eom_terms_ignore_case_and_surrounding_spaces(text):
    assert parse_terms(text).due_date(date(2026, 3, 5)) == date(2026, 3, 31)


@pytest.mark.parametrize("text", ["2/10 net 30", "  2/10 NET 30  "])
def test_discount_terms_ignore_case_and_surrounding_spaces(text):
    terms = parse_terms(text)
    assert terms.due_date(JAN5) == date(2026, 2, 4)
    assert terms.discount_deadline(JAN5) == date(2026, 1, 15)


@pytest.mark.parametrize(
    "text",
    ["", "NET", "NET thirty", "30", "EOM 30", "2/10 EOM", "2/10", "NET -5",
     "100/10 NET 30", "150/5 NET 30", "2/31 NET 30", "monthly"],
)
def test_unknown_or_impossible_terms_raise(text):
    with pytest.raises(TermsError):
        parse_terms(text)


def test_discount_window_equal_to_net_days_is_allowed():
    assert parse_terms("2/30 NET 30").discount_deadline(JAN5) == date(2026, 2, 4)


def test_discount_just_under_100_percent_is_allowed():
    assert parse_terms("99.9/10 NET 30").discount_deadline(JAN5) == date(2026, 1, 15)
