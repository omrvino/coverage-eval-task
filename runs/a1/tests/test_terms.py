from datetime import date
from decimal import Decimal

import pytest

from tally import Terms, TermsError, parse_terms

XFAIL_DEADLINE_WEEKEND = pytest.mark.xfail(
    strict=True,
    reason="R2.4: the discount deadline is rolled past weekends and holidays; the spec says it does not move",
)


def test_net_days_are_calendar_days():
    assert parse_terms("NET 30").due_date(date(2026, 1, 5)) == date(2026, 2, 4)
    assert parse_terms("NET 0").due_date(date(2026, 1, 5)) == date(2026, 1, 5)


@pytest.mark.parametrize(
    "invoice_day, due",
    [
        (date(2026, 3, 10), date(2026, 3, 31)),
        (date(2026, 3, 25), date(2026, 3, 31)),
        (date(2026, 3, 26), date(2026, 4, 30)),
        # Jan 31 2027 is a Sunday, so the due date moves to Monday Feb 1.
        (date(2026, 12, 26), date(2027, 2, 1)),
    ],
)
def test_eom_is_month_end_or_next_month_end_from_the_26th(invoice_day, due):
    assert parse_terms("EOM").due_date(invoice_day) == due


@pytest.mark.parametrize("invoice_day", [date(2026, 1, 8), date(2026, 1, 9)])
def test_due_date_on_a_weekend_moves_to_the_next_business_day(invoice_day):
    # Jan 8 + 30 is Saturday Feb 7, Jan 9 + 30 is Sunday Feb 8.
    assert parse_terms("NET 30").due_date(invoice_day) == date(2026, 2, 9)


def test_holidays_are_skipped_like_weekends():
    terms = parse_terms("NET 28")
    assert terms.due_date(date(2026, 1, 5)) == date(2026, 2, 2)
    assert terms.due_date(date(2026, 1, 5), {date(2026, 2, 2), date(2026, 2, 3)}) == date(2026, 2, 4)


def test_discount_deadline_is_invoice_date_plus_discount_days():
    assert parse_terms("2/10 NET 30").discount_deadline(date(2026, 1, 5)) == date(2026, 1, 15)
    assert parse_terms("NET 30").discount_deadline(date(2026, 1, 5)) is None


@XFAIL_DEADLINE_WEEKEND
def test_discount_deadline_on_a_weekend_stays_on_that_day():
    # Jan 7 + 10 days is Saturday Jan 17.
    assert parse_terms("2/10 NET 30").discount_deadline(date(2026, 1, 7)) == date(2026, 1, 17)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("NET 30", Terms(30)),
        ("  net 30 ", Terms(30)),
        ("\tNet 30\n", Terms(30)),
        ("EOM", Terms(None)),
        (" eom ", Terms(None)),
        ("2/10 NET 30", Terms(30, Decimal(2), 10)),
        ("2/10 net 30", Terms(30, Decimal(2), 10)),
        (" 2/10 NET 30 ", Terms(30, Decimal(2), 10)),
        ("2/10 NET 10", Terms(10, Decimal(2), 10)),
        ("99/10 NET 30", Terms(30, Decimal(99), 10)),
    ],
)
def test_terms_ignore_case_and_surrounding_spaces(text, expected):
    assert parse_terms(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        "NET",
        "NET x",
        "30",
        "PAY ON RECEIPT",
        "EOM 30",
        "2/10",
        "2/10 NET",
        "100/10 NET 30",
        "150/10 NET 30",
        "2/31 NET 30",
        "2/10 NET 5",
    ],
)
def test_unknown_or_impossible_terms_raise(text):
    with pytest.raises(TermsError):
        parse_terms(text)
