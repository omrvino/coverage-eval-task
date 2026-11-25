from datetime import date, timedelta
from decimal import Decimal

import pytest

from tally import Event, Invoice, Ledger, Line

D = Decimal


def ledger_with(price="1000.00", number="INV-1"):
    ledger = Ledger()
    ledger.add(Invoice(number, "acme", date(2026, 1, 5), "NET 30", [Line("work", 1, price)]))
    ledger.issue(number)
    return ledger


def assess(ledger, days, number="INV-1"):
    """Assess late fees on the invoice's due date plus ``days``."""
    return ledger.assess_late_fees(ledger.invoices[number].due + timedelta(days=days))


@pytest.mark.parametrize("days", [-10, 0, 4])
def test_no_fee_up_to_five_days_late(days):
    ledger = ledger_with()
    assert assess(ledger, days) == {}
    assert ledger.invoices["INV-1"].fees == D("0.00")


@pytest.mark.xfail(strict=True, reason="R5.1: no fee while an invoice is 5 days late or less")
def test_no_fee_on_day_five():
    ledger = ledger_with()
    assert assess(ledger, 5) == {}


@pytest.mark.parametrize(
    "days, expected",
    [(6, "15.00"), (30, "15.00"), (31, "30.00"), (60, "30.00"), (61, "45.00")],
)
def test_one_fee_for_each_thirty_day_period_started(days, expected):
    ledger = ledger_with()
    assess(ledger, days)
    assert ledger.invoices["INV-1"].fees == D(expected)


def test_fee_is_logged_as_a_fee_event():
    ledger = ledger_with()
    day = ledger.invoices["INV-1"].due + timedelta(days=6)
    assert assess(ledger, 6) == {"INV-1": D("15.00")}
    assert ledger.events[-1] == Event(day, "acme", "fee", "INV-1", D("15.00"))


def test_minimum_fee_is_five_dollars():
    ledger = ledger_with("100.00")
    assert assess(ledger, 6) == {"INV-1": D("5.00")}


def test_fees_never_exceed_ten_percent_of_the_total():
    ledger = ledger_with("100.00")
    assert assess(ledger, 91) == {"INV-1": D("10.00")}  # four periods at 5.00 would be 20.00
    assert ledger.invoices["INV-1"].fees == D("10.00")
    assert assess(ledger, 121) == {}  # a fifth period, but the cap is already reached


def test_assessing_twice_charges_each_period_once():
    ledger = ledger_with()
    assess(ledger, 31)
    assert assess(ledger, 31) == {}
    assert ledger.invoices["INV-1"].fees == D("30.00")


def test_new_periods_are_charged_as_they_start():
    ledger = ledger_with()
    assert assess(ledger, 6) == {"INV-1": D("15.00")}
    assert assess(ledger, 31) == {"INV-1": D("15.00")}
    assert ledger.invoices["INV-1"].fees == D("30.00")


def test_fee_uses_the_principal_still_owed_on_the_day_it_is_assessed():
    ledger = ledger_with("1000.00")
    due = ledger.invoices["INV-1"].due
    ledger.receive("P1", "acme", "500.00", due + timedelta(days=10))
    # 1.5 percent of 500.00 is 7.50 per period, and days 31 start period two.
    assert assess(ledger, 31) == {"INV-1": D("15.00")}


def test_paid_and_void_invoices_are_not_charged():
    paid = ledger_with("1000.00")
    paid.receive("P1", "acme", "1000.00", paid.invoices["INV-1"].due)
    assert assess(paid, 31) == {}
    assert paid.invoices["INV-1"].fees == D("0.00")

    voided = ledger_with("1000.00")
    voided.void("INV-1", voided.invoices["INV-1"].due)
    assert assess(voided, 31) == {}


def test_draft_invoices_are_not_charged():
    ledger = Ledger()
    ledger.add(Invoice("INV-1", "acme", date(2026, 1, 5), "NET 30", [Line("work", 1, "1000.00")]))
    assert ledger.assess_late_fees(date(2026, 12, 1)) == {}


def test_periods_assessed_while_disputed_stay_waived_after_resolution():
    ledger = ledger_with()
    ledger.dispute("INV-1")
    assert assess(ledger, 31) == {}
    ledger.resolve("INV-1")
    assert assess(ledger, 31) == {}
    assert assess(ledger, 61) == {"INV-1": D("15.00")}
