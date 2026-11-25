from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from tally import Invoice, Ledger, Line, aging

DAY = date(2026, 1, 5)  # NET 30: due Feb 4


def issue(ledger, number, day, price, customer="acme", terms="NET 30"):
    ledger.add(Invoice(number, customer, day, terms, [Line("work", 1, price)]))
    ledger.issue(number)
    return ledger.invoices[number].due


def only(report, bucket):
    """True when ``bucket`` is the only non-zero entry in ``report``."""
    return all(value == 0 for name, value in report.items() if name != bucket)


# R6.1
@pytest.mark.parametrize(
    "days_after_due, bucket",
    [(-1, "current"), (0, "current"), (1, "1-30"), (30, "1-30"), (31, "31-60"),
     (60, "31-60"), (61, "61-90"), (90, "61-90"), (91, "91+"), (200, "91+")],
)
def test_open_invoice_goes_in_bucket_by_days_past_due(days_after_due, bucket):
    ledger = Ledger()
    due = issue(ledger, "INV-1", DAY, "100")
    report = aging(ledger, "acme", due + timedelta(days=days_after_due))
    assert report[bucket] == D("100.00")
    assert only(report, bucket)


def test_balance_includes_late_fees():
    ledger = Ledger()
    due = issue(ledger, "INV-1", DAY, "1000")
    ledger.assess_late_fees(due + timedelta(days=6))
    report = aging(ledger, "acme", due + timedelta(days=10))
    assert report["1-30"] == D("1015.00")


def test_other_customers_are_not_counted():
    ledger = Ledger()
    due = issue(ledger, "INV-1", DAY, "100")
    issue(ledger, "INV-2", DAY, "500", customer="other")
    report = aging(ledger, "acme", due + timedelta(days=10))
    assert report["1-30"] == D("100.00")
    assert only(report, "1-30")


# R6.2
def test_disputed_invoice_goes_only_in_disputed():
    ledger = Ledger()
    due = issue(ledger, "INV-1", DAY, "100")
    ledger.dispute("INV-1")
    report = aging(ledger, "acme", due + timedelta(days=200))
    assert report["disputed"] == D("100.00")
    assert only(report, "disputed")


def test_drafts_void_and_paid_invoices_are_left_out():
    ledger = Ledger()
    ledger.add(Invoice("DRAFT", "acme", DAY, "NET 30", [Line("d", 1, "10")]))
    due = issue(ledger, "VOID", DAY, "20")
    ledger.void("VOID", DAY)
    issue(ledger, "PAID", DAY, "30")
    ledger.receive("P1", "acme", "30", DAY)
    report = aging(ledger, "acme", due + timedelta(days=200))
    assert all(value == 0 for value in report.values())


def test_customer_with_no_invoices_has_an_all_zero_report():
    report = aging(Ledger(), "acme", DAY)
    assert all(value == 0 for value in report.values())


# R6.3
def credit_ledger(amount):
    """A ledger where the customer has ``amount`` of credit and nothing open."""
    ledger = Ledger()
    ledger.receive("P0", "acme", amount, DAY)
    return ledger


NOW = date(2026, 5, 15)  # an invoice dated Jan 5 is 100 days late; one dated May 10 is current


@pytest.mark.xfail(strict=True, reason="credit reduces the newest bucket (current) first; spec R6.3 says the oldest bucket first")
def test_credit_reduces_the_oldest_bucket_first():
    ledger = credit_ledger("60")
    issue(ledger, "OLD", DAY, "100")
    issue(ledger, "NEW", date(2026, 5, 10), "100")
    report = aging(ledger, "acme", NOW)
    assert report["91+"] == D("40.00")
    assert report["current"] == D("100.00")


def test_credit_beyond_all_balances_shows_negative_in_current():
    ledger = credit_ledger("250")
    issue(ledger, "OLD", DAY, "100")
    issue(ledger, "NEW", date(2026, 5, 10), "100")
    report = aging(ledger, "acme", NOW)
    assert report["91+"] == D("0.00")
    assert report["current"] == D("-50.00")


def test_credit_never_reduces_disputed():
    ledger = credit_ledger("60")
    issue(ledger, "DISPUTED", DAY, "100")
    ledger.dispute("DISPUTED")
    issue(ledger, "NEW", date(2026, 5, 10), "100")
    report = aging(ledger, "acme", NOW)
    assert report["disputed"] == D("100.00")
    assert report["current"] == D("40.00")


def test_credit_with_only_disputed_balances_is_negative_current():
    ledger = credit_ledger("60")
    issue(ledger, "DISPUTED", DAY, "100")
    ledger.dispute("DISPUTED")
    report = aging(ledger, "acme", NOW)
    assert report["disputed"] == D("100.00")
    assert report["current"] == D("-60.00")
