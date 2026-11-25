from datetime import date
from decimal import Decimal

import pytest

from tally import TermsError, parse_terms


def test_parse_ignores_case_and_surrounding_spaces():
    assert parse_terms("  net 30 ") == parse_terms("NET 30")
    assert parse_terms(" eom ").net_days is None
    assert parse_terms(" 2/10 net 30 ") == parse_terms("2/10 NET 30")


def test_parse_discount_terms():
    terms = parse_terms("2/10 NET 30")
    assert terms.net_days == 30
    assert terms.discount_pct == Decimal("2")
    assert terms.discount_days == 10


def test_parse_fractional_discount_percent():
    assert parse_terms("1.5/10 NET 30").discount_pct == Decimal("1.5")


@pytest.mark.parametrize(
    "text",
    ["", "NET", "COD", "NET thirty", "2/10 EOM", "2 NET 30", "100/10 NET 30", "150/10 NET 30", "2/31 NET 30"],
)
def test_rejects_unknown_or_impossible_terms(text):
    with pytest.raises(TermsError):
        parse_terms(text)


@pytest.mark.parametrize(
    "invoice_date, due",
    [
        (date(2026, 3, 10), date(2026, 3, 31)),
        (date(2026, 3, 26), date(2026, 4, 30)),
        (date(2026, 6, 26), date(2026, 7, 31)),
        (date(2026, 12, 10), date(2026, 12, 31)),
        (date(2026, 12, 26), date(2027, 2, 1)),
        (date(2028, 1, 26), date(2028, 2, 29)),
    ],
)
def test_eom_is_end_of_month_or_end_of_next_month_from_the_26th(invoice_date, due):
    assert parse_terms("EOM").due_date(invoice_date) == due


def test_eom_due_date_on_a_weekend_moves_forward():
    # Jan 31 2026 is a Saturday, so the due date is Monday Feb 2.
    assert parse_terms("EOM").due_date(date(2026, 1, 10)) == date(2026, 2, 2)


def test_weekend_due_date_moves_forward_to_monday():
    # Jan 5 + 5 days is Saturday Jan 10, so the due date is Monday Jan 12.
    assert parse_terms("NET 5").due_date(date(2026, 1, 5)) == date(2026, 1, 12)


def test_holidays_are_skipped_like_weekends():
    holidays = frozenset({date(2026, 1, 12)})
    assert parse_terms("NET 5").due_date(date(2026, 1, 5), holidays) == date(2026, 1, 13)
    chained = frozenset({date(2026, 1, 12), date(2026, 1, 13)})
    assert parse_terms("NET 5").due_date(date(2026, 1, 5), chained) == date(2026, 1, 14)


def test_discount_deadline_is_invoice_date_plus_discount_days():
    assert parse_terms("2/10 NET 30").discount_deadline(date(2026, 1, 5)) == date(2026, 1, 15)


def test_no_discount_means_no_deadline():
    assert parse_terms("NET 30").discount_deadline(date(2026, 1, 5)) is None


@pytest.mark.xfail(strict=True, reason="R2.4: the discount deadline does not move for weekends or holidays")
def test_discount_deadline_does_not_move_for_a_weekend():
    # Jan 5 + 5 days is Saturday Jan 10; the deadline must stay on that day.
    assert parse_terms("2/5 NET 30").discount_deadline(date(2026, 1, 5)) == date(2026, 1, 10)
