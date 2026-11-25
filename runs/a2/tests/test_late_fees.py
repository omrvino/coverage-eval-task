from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from tally import Invoice, Ledger, Line

DAY = date(2026, 1, 5)  # NET 30: due Feb 4


def ledger_for(price="1000.00"):
    ledger = Ledger()
    ledger.add(Invoice("INV-1", "acme", DAY, "NET 30", [Line("work", 1, price)]))
    ledger.issue("INV-1")
    return ledger


def days_after_due(ledger, days):
    return ledger.invoices["INV-1"].due + timedelta(days=days)


# R5.1
@pytest.mark.parametrize("days", [1, 2, 3, 4])
def test_no_fee_within_the_grace_days(days):
    ledger = ledger_for()
    ledger.assess_late_fees(days_after_due(ledger, days))
    assert ledger.invoices["INV-1"].fees == D("0")


def test_fee_starts_from_day_six():
    ledger = ledger_for()
    ledger.assess_late_fees(days_after_due(ledger, 6))
    assert ledger.invoices["INV-1"].fees == D("15.00")


@pytest.mark.xfail(strict=True, reason="fee is charged 5 days late; spec R5.1 says no fee while an invoice is 5 days late or less")
def test_no_fee_at_exactly_five_days_late():
    ledger = ledger_for()
    ledger.assess_late_fees(days_after_due(ledger, 5))
    assert ledger.invoices["INV-1"].fees == D("0")


# R5.2
@pytest.mark.parametrize("days, periods", [(6, 1), (30, 1), (31, 2), (60, 2), (61, 3)])
def test_one_fee_per_30_day_period_started_after_due(days, periods):
    ledger = ledger_for()
    ledger.assess_late_fees(days_after_due(ledger, days))
    assert ledger.invoices["INV-1"].fees == D("15.00") * periods


# R5.3
def test_fee_is_one_and_a_half_percent_of_principal_still_owed():
    ledger = ledger_for("1000.00")
    ledger.receive("P1", "acme", "400", date(2026, 1, 15))  # principal left: 600
    ledger.assess_late_fees(days_after_due(ledger, 6))
    assert ledger.invoices["INV-1"].fees == D("9.00")


def test_minimum_fee_per_period_is_five_dollars():
    ledger = ledger_for("100.00")
    ledger.assess_late_fees(days_after_due(ledger, 6))
    assert ledger.invoices["INV-1"].fees == D("5.00")


def test_late_fees_never_earn_late_fees():
    ledger = ledger_for("1000.00")
    ledger.assess_late_fees(days_after_due(ledger, 6))  # 15.00
    ledger.assess_late_fees(days_after_due(ledger, 31))  # second period on principal only
    assert ledger.invoices["INV-1"].fees == D("30.00")


# R5.4
def test_late_fees_never_exceed_ten_percent_of_the_total():
    ledger = ledger_for("100.00")  # cap 10.00
    ledger.assess_late_fees(days_after_due(ledger, 6))
    ledger.assess_late_fees(days_after_due(ledger, 36))
    assert ledger.invoices["INV-1"].fees == D("10.00")
    ledger.assess_late_fees(days_after_due(ledger, 66))
    ledger.assess_late_fees(days_after_due(ledger, 200))
    assert ledger.invoices["INV-1"].fees == D("10.00")


def test_cap_applies_when_many_periods_are_due_at_once():
    ledger = ledger_for("1000.00")  # cap 100.00; seven periods would be 105.00
    ledger.assess_late_fees(days_after_due(ledger, 186))
    assert ledger.invoices["INV-1"].fees == D("100.00")


# R5.5
def test_assessing_twice_charges_each_period_once():
    ledger = ledger_for()
    ledger.assess_late_fees(days_after_due(ledger, 6))
    ledger.assess_late_fees(days_after_due(ledger, 6))
    assert ledger.invoices["INV-1"].fees == D("15.00")
    ledger.assess_late_fees(days_after_due(ledger, 31))
    assert ledger.invoices["INV-1"].fees == D("30.00")


# R5.6
def test_disputed_invoice_is_charged_nothing_and_its_periods_stay_waived():
    ledger = ledger_for()
    ledger.dispute("INV-1")
    ledger.assess_late_fees(days_after_due(ledger, 40))
    assert ledger.invoices["INV-1"].fees == D("0")
    ledger.resolve("INV-1")
    ledger.assess_late_fees(days_after_due(ledger, 40))
    assert ledger.invoices["INV-1"].fees == D("0")
    ledger.assess_late_fees(days_after_due(ledger, 70))  # only the third period is new
    assert ledger.invoices["INV-1"].fees == D("15.00")


def test_nothing_is_charged_before_the_due_date():
    ledger = ledger_for()
    ledger.assess_late_fees(DAY)
    assert ledger.invoices["INV-1"].fees == D("0")
