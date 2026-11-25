from datetime import date, timedelta
from decimal import Decimal

import pytest

from tally import Event, Invoice, Ledger, Line, aging, statement

D = Decimal


def add_invoice(ledger, number, price, terms="NET 30", day=date(2026, 1, 5), customer="acme"):
    ledger.add(Invoice(number, customer, day, terms, [Line("work", 1, price)]))
    ledger.issue(number)


def zeros_except(report, name):
    return all(value == 0 for key, value in report.items() if key != name)


@pytest.mark.parametrize(
    "days_past_due, bucket",
    [(-3, "current"), (0, "current"), (1, "1-30"), (30, "1-30"), (31, "31-60"), (60, "31-60"),
     (61, "61-90"), (90, "61-90"), (91, "91+"), (400, "91+")],
)
def test_open_invoice_lands_in_its_bucket_by_days_past_due(days_past_due, bucket):
    ledger = Ledger()
    add_invoice(ledger, "INV-1", "100.00")
    due = ledger.invoices["INV-1"].due
    report = aging(ledger, "acme", due + timedelta(days=days_past_due))
    assert report[bucket] == D("100.00")
    assert zeros_except(report, bucket)


def test_report_has_every_bucket_and_disputed():
    report = aging(Ledger(), "acme", date(2026, 1, 1))
    assert list(report) == ["current", "1-30", "31-60", "61-90", "91+", "disputed"]


def test_disputed_invoice_goes_in_disputed_whatever_its_age():
    ledger = Ledger()
    add_invoice(ledger, "INV-1", "100.00")
    ledger.dispute("INV-1")
    report = aging(ledger, "acme", date(2026, 12, 1))
    assert report["disputed"] == D("100.00")
    assert zeros_except(report, "disputed")


def test_drafts_void_and_paid_invoices_are_left_out():
    ledger = Ledger()
    ledger.add(Invoice("DRAFT", "acme", date(2026, 1, 5), "NET 30", [Line("x", 1, "10")]))
    add_invoice(ledger, "VOID", "20.00")
    ledger.void("VOID", date(2026, 1, 6))
    add_invoice(ledger, "PAID", "30.00")
    ledger.receive("P1", "acme", "30.00", date(2026, 1, 6))
    report = aging(ledger, "acme", date(2026, 6, 1))
    assert all(value == 0 for value in report.values())


def test_other_customers_are_left_out():
    ledger = Ledger()
    add_invoice(ledger, "INV-B", "70.00", customer="beta")
    report = aging(ledger, "acme", date(2026, 6, 1))
    assert all(value == 0 for value in report.values())


def test_balance_includes_late_fees():
    ledger = Ledger()
    add_invoice(ledger, "INV-1", "100.00")
    due = ledger.invoices["INV-1"].due
    ledger.assess_late_fees(due + timedelta(days=6))  # one minimum fee of 5.00
    report = aging(ledger, "acme", due + timedelta(days=6))
    assert report["1-30"] == D("105.00")


def test_credit_never_reduces_disputed():
    ledger = Ledger()
    ledger.receive("P0", "acme", "100.00", date(2026, 1, 2))  # no invoices yet, so this is credit
    add_invoice(ledger, "DISP", "100.00")
    ledger.dispute("DISP")
    add_invoice(ledger, "CUR", "100.00")
    report = aging(ledger, "acme", date(2026, 2, 1))  # CUR is not yet due
    assert report["disputed"] == D("100.00")
    assert report["current"] == D("0.00")


def test_credit_left_over_shows_as_a_negative_current_amount():
    ledger = Ledger()
    ledger.receive("P0", "acme", "150.00", date(2026, 1, 2))
    add_invoice(ledger, "CUR", "100.00")
    report = aging(ledger, "acme", date(2026, 2, 1))
    assert report["current"] == D("-50.00")
    assert zeros_except(report, "current")


@pytest.mark.xfail(strict=True, reason="R6.3: credit reduces the oldest bucket first, not the newest")
def test_credit_reduces_the_oldest_bucket_first():
    ledger = Ledger()
    ledger.receive("P0", "acme", "50.00", date(2026, 1, 2))  # no invoices yet, so this is credit
    add_invoice(ledger, "NEW", "100.00")  # due Feb 4, 25 days late on Mar 1
    add_invoice(ledger, "OLD", "100.00", day=date(2025, 10, 1))  # due Oct 31 2025, 121 days late on Mar 1
    report = aging(ledger, "acme", date(2026, 3, 1))
    assert report["91+"] == D("50.00")
    assert report["1-30"] == D("100.00")


def test_statement_lists_activity_with_running_balance():
    ledger = Ledger()
    add_invoice(ledger, "INV-1", "100.00")
    add_invoice(ledger, "BETA", "70.00", customer="beta")
    ledger.receive("P1", "acme", "40.00", date(2026, 1, 20))
    report = statement(ledger, "acme", date(2026, 1, 1), date(2026, 1, 31))
    assert report.opening == D("0.00")
    assert [(l.date, l.kind, l.ref, l.amount, l.balance) for l in report.lines] == [
        (date(2026, 1, 5), "invoice", "INV-1", D("100.00"), D("100.00")),
        (date(2026, 1, 20), "payment", "P1", D("-40.00"), D("60.00")),
    ]
    assert report.closing == D("60.00")


def test_period_includes_first_and_last_day_and_opening_is_everything_before():
    ledger = Ledger()
    add_invoice(ledger, "INV-1", "100.00")  # dated Jan 5
    ledger.receive("P1", "acme", "40.00", date(2026, 1, 20))
    inclusive = statement(ledger, "acme", date(2026, 1, 5), date(2026, 1, 20))
    assert inclusive.opening == D("0.00")
    assert len(inclusive.lines) == 2
    later = statement(ledger, "acme", date(2026, 1, 6), date(2026, 1, 31))
    assert later.opening == D("100.00")
    assert [l.kind for l in later.lines] == ["payment"]
    assert later.closing == D("60.00")


def test_signs_for_payments_reversals_and_voids():
    ledger = Ledger()
    add_invoice(ledger, "INV-1", "100.00")
    ledger.receive("P1", "acme", "40.00", date(2026, 1, 20))
    ledger.reverse("P1", date(2026, 1, 21))
    ledger.void("INV-1", date(2026, 1, 22))
    report = statement(ledger, "acme", date(2026, 1, 1), date(2026, 1, 31))
    assert [(l.kind, l.amount, l.balance) for l in report.lines] == [
        ("invoice", D("100.00"), D("100.00")),
        ("payment", D("-40.00"), D("60.00")),
        ("reversal", D("40.00"), D("100.00")),
        ("void", D("-100.00"), D("0.00")),
    ]
    assert report.closing == D("0.00")


def test_same_day_activity_is_ordered_invoice_fee_payment_discount_reversal_void():
    ledger = Ledger()
    day = date(2026, 3, 1)
    # Logged out of order on purpose; the statement must still sort them.
    for kind in ["void", "reversal", "discount", "payment", "fee", "invoice"]:
        ledger.events.append(Event(day, "acme", kind, "R", D("1.00")))
    report = statement(ledger, "acme", day, day)
    assert [l.kind for l in report.lines] == ["invoice", "fee", "payment", "discount", "reversal", "void"]
    assert [l.balance for l in report.lines] == [D(n) for n in range(1, 7)]
    assert report.closing == D("6.00")


def test_empty_period_closes_at_the_opening_balance():
    ledger = Ledger()
    add_invoice(ledger, "INV-1", "100.00")
    report = statement(ledger, "acme", date(2026, 3, 1), date(2026, 3, 31))
    assert report.opening == D("100.00")
    assert report.lines == []
    assert report.closing == D("100.00")
