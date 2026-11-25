from datetime import date
from decimal import Decimal

import pytest

from tally import Terms, TermsError, parse_terms


def test_parse_net_ignores_case_and_spaces():
    assert parse_terms("  net 30 ") == Terms(net_days=30)
    assert parse_terms("NET30").net_days == 30


def test_parse_eom_ignores_case():
    assert parse_terms(" eom ") == Terms(net_days=None)


def test_parse_discount_terms():
    assert parse_terms("2/10 NET 30") == Terms(net_days=30, discount_pct=Decimal(2), discount_days=10)
    assert parse_terms("2.5 / 10 net 30").discount_pct == Decimal("2.5")


@pytest.mark.parametrize("text", ["", "NET", "2/10", "100/10 NET 30", "2/40 NET 30", "monthly"])
def test_parse_rejects_unknown_or_impossible_terms(text):
    with pytest.raises(TermsError):
        parse_terms(text)


def test_net_due_date_rolls_off_a_weekend():
    # 2026-01-01 is a Thursday, so NET 2 lands on Saturday 2026-01-03.
    assert parse_terms("NET 2").due_date(date(2026, 1, 1)) == date(2026, 1, 5)


def test_net_due_date_rolls_past_holidays():
    holidays = {date(2026, 2, 4), date(2026, 2, 5)}
    assert parse_terms("NET 30").due_date(date(2026, 1, 5), holidays) == date(2026, 2, 6)


def test_eom_due_date_is_end_of_same_month_before_cutoff():
    assert parse_terms("EOM").due_date(date(2026, 3, 5)) == date(2026, 3, 31)


def test_eom_invoice_on_or_after_the_26th_is_due_end_of_next_month():
    assert parse_terms("EOM").due_date(date(2026, 2, 26)) == date(2026, 3, 31)
    assert parse_terms("EOM").due_date(date(2026, 3, 26)) == date(2026, 4, 30)


def test_eom_in_december_rolls_into_next_year():
    # Jan 31 2027 is a Sunday, so the due date moves to Monday Feb 1.
    assert parse_terms("EOM").due_date(date(2026, 12, 26)) == date(2027, 2, 1)


def test_discount_deadline_is_discount_days_after_invoice():
    terms = parse_terms("2/10 NET 30")
    assert terms.discount_deadline(date(2026, 1, 5)) == date(2026, 1, 15)


def test_no_discount_deadline_without_a_discount():
    assert parse_terms("NET 30").discount_deadline(date(2026, 1, 5)) is None
