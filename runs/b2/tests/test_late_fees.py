from datetime import date

import pytest

from helpers import D, DUE, JAN5, events, fee_total, invoice, late, ledger_with
from tally import Line

# Default invoice: 1000.00, NET 30 from Monday 2026-01-05, due Wednesday 2026-02-04.
# One fee period on 1000.00 is 15.00 and the cap is 100.00.


def one(price="1000.00", **kwargs):
    return ledger_with(invoice(price=price, **kwargs))


# R5.1 ---------------------------------------------------------------------

@pytest.mark.parametrize("days", [-30, -1, 0, 1, 4])
def test_no_fee_while_five_days_late_or_less(days):
    ledger = one()
    ledger.assess_late_fees(late(days))
    assert events(ledger, "fee") == []
    assert ledger.invoices["INV-1"].balance == D("1000.00")


@pytest.mark.xfail(strict=True, reason="a fee is charged on day 5; the spec says from day 6")
def test_no_fee_on_exactly_five_days_late():
    ledger = one()
    ledger.assess_late_fees(late(5))
    assert events(ledger, "fee") == []
    assert ledger.invoices["INV-1"].balance == D("1000.00")


def test_fee_starts_on_day_six():
    ledger = one()
    ledger.assess_late_fees(late(6))
    assert fee_total(ledger) == D("15.00")


def test_first_assessment_covers_the_whole_time_since_the_due_date():
    ledger = one()
    ledger.assess_late_fees(late(100))
    assert fee_total(ledger) == D("60.00")      # four periods


# R5.2 ---------------------------------------------------------------------

@pytest.mark.parametrize("days, fee", [
    (6, "15.00"), (15, "15.00"), (30, "15.00"),
    (31, "30.00"), (45, "30.00"), (60, "30.00"),
    (61, "45.00"), (90, "45.00"), (91, "60.00"), (120, "60.00"), (121, "75.00"),
])
def test_one_fee_per_started_30_day_period(days, fee):
    ledger = one()
    ledger.assess_late_fees(late(days))
    assert fee_total(ledger) == D(fee)
    assert ledger.invoices["INV-1"].balance == D("1000.00") + D(fee)


def test_fee_event_carries_date_invoice_and_customer():
    ledger = one()
    ledger.assess_late_fees(late(10))
    [event] = events(ledger, "fee")
    assert (event.date, event.ref, event.customer, event.amount) == (late(10), "INV-1", "acme", D("15.00"))


def test_fee_counts_from_the_due_date_after_a_weekend_roll():
    # NET 5 from Mon Jan 5 is Saturday; the due date is Monday Jan 12.
    ledger = ledger_with(invoice(terms="NET 5", price="1000.00"))
    ledger.assess_late_fees(date(2026, 1, 12) + (late(4) - DUE))
    assert events(ledger, "fee") == []
    ledger.assess_late_fees(date(2026, 1, 12) + (late(6) - DUE))
    assert fee_total(ledger) == D("15.00")


# R5.3 ---------------------------------------------------------------------

@pytest.mark.parametrize("price, fee", [
    ("100.00", "5.00"), ("300.00", "5.00"), ("333.33", "5.00"),
    ("340.00", "5.10"), ("400.00", "6.00"), ("2000.00", "30.00"), ("12345.67", "185.19"),
])
def test_fee_is_one_and_a_half_percent_with_a_five_dollar_minimum(price, fee):
    ledger = one(price)
    ledger.assess_late_fees(late(10))
    assert fee_total(ledger) == D(fee)


def test_fee_includes_tax_in_the_principal():
    ledger = ledger_with(invoice(price="1000.00", tax_rate=10))      # 1100.00 -> 16.50
    ledger.assess_late_fees(late(10))
    assert fee_total(ledger) == D("16.50")


def test_fee_is_taken_on_the_principal_still_owed_on_the_day():
    ledger = one()
    ledger.receive("P1", "acme", "400.00", late(2))
    ledger.assess_late_fees(late(10))                                 # 1.5% of 600.00
    assert fee_total(ledger) == D("9.00")


def test_late_fees_never_earn_late_fees():
    ledger = one()
    ledger.assess_late_fees(late(10))
    ledger.assess_late_fees(late(40))
    assert fee_total(ledger) == D("30.00")          # not 15.00 + 15.23


def test_later_periods_use_the_principal_owed_at_that_time():
    ledger = one()
    ledger.assess_late_fees(late(10))                                 # 15.00
    ledger.receive("P1", "acme", "515.00", late(12))                  # fee 15.00 + 500.00
    ledger.assess_late_fees(late(40))                                 # 1.5% of 500.00
    assert fee_total(ledger) == D("22.50")
    assert ledger.invoices["INV-1"].balance == D("507.50")


def test_the_minimum_fee_applies_to_every_period():
    ledger = one("100.00")
    ledger.assess_late_fees(late(10))
    ledger.assess_late_fees(late(40))
    assert fee_total(ledger) == D("10.00")


def test_fee_assessed_for_two_periods_at_once_charges_each():
    ledger = one("400.00")
    ledger.assess_late_fees(late(40))
    assert fee_total(ledger) == D("12.00")


# R5.4 ---------------------------------------------------------------------

@pytest.mark.parametrize("days", [181, 211, 400, 3000])
def test_fees_never_exceed_ten_percent_of_the_invoice_total(days):
    ledger = one()
    ledger.assess_late_fees(late(days))
    assert fee_total(ledger) == D("100.00")


def test_cap_applies_across_assessments_and_to_the_final_period_partly():
    ledger = one()
    for days in (10, 40, 70, 100, 130, 160):
        ledger.assess_late_fees(late(days))
    assert fee_total(ledger) == D("90.00")
    ledger.assess_late_fees(late(190))
    assert fee_total(ledger) == D("100.00")
    ledger.assess_late_fees(late(400))
    assert fee_total(ledger) == D("100.00")
    assert len(events(ledger, "fee")) == 7


def test_cap_is_on_the_invoice_total_including_tax():
    ledger = ledger_with(invoice(price="100.00", tax_rate=10))        # total 110.00, cap 11.00
    ledger.assess_late_fees(late(70))                                 # 3 x 5.00 = 15.00
    assert fee_total(ledger) == D("11.00")


def test_cap_beats_the_minimum_fee_on_tiny_invoices():
    ledger = one("20.00")                                             # cap 2.00
    ledger.assess_late_fees(late(10))
    assert fee_total(ledger) == D("2.00")


def test_fees_already_paid_still_count_towards_the_cap():
    ledger = one("100.00")
    ledger.assess_late_fees(late(10))                                 # 5.00
    ledger.receive("P1", "acme", "5.00", late(11))                    # pays the fee only
    ledger.assess_late_fees(late(100))
    assert fee_total(ledger) == D("10.00")


# R5.5 ---------------------------------------------------------------------

def test_assessing_twice_charges_each_period_once():
    ledger = one()
    ledger.assess_late_fees(late(40))
    ledger.assess_late_fees(late(40))
    ledger.assess_late_fees(late(35))
    assert fee_total(ledger) == D("30.00")
    assert len(events(ledger, "fee")) == 1
    ledger.assess_late_fees(late(61))
    assert fee_total(ledger) == D("45.00")
    assert len(events(ledger, "fee")) == 2


def test_assessing_for_several_invoices_charges_each_one():
    ledger = ledger_with(invoice("INV-1"), invoice("INV-2", price="2000.00"),
                         invoice("INV-3", customer="other", price="400.00"))
    ledger.assess_late_fees(late(10))
    by_ref = {e.ref: e.amount for e in events(ledger, "fee")}
    assert by_ref == {"INV-1": D("5.00"), "INV-2": D("30.00"), "INV-3": D("6.00")}


# invoices that are not charged --------------------------------------------

def test_paid_invoices_are_not_charged():
    ledger = one()
    ledger.receive("P1", "acme", "1000.00", late(1))
    ledger.assess_late_fees(late(100))
    assert events(ledger, "fee") == []


def test_void_and_draft_invoices_are_not_charged():
    ledger = ledger_with(invoice("VOID"))
    ledger.void("VOID", DUE)
    ledger.add(invoice("DRAFT"))
    ledger.assess_late_fees(late(100))
    assert events(ledger, "fee") == []


def test_an_invoice_paid_before_it_is_late_is_not_charged():
    ledger = ledger_with(invoice(lines=[Line("a", 1, "1000.00")]))
    ledger.receive("P1", "acme", "1000.00", JAN5)
    ledger.assess_late_fees(late(50))
    assert events(ledger, "fee") == []


# R5.6 ---------------------------------------------------------------------

def test_disputed_invoice_is_charged_nothing():
    ledger = one()
    ledger.dispute("INV-1")
    ledger.assess_late_fees(late(40))
    assert events(ledger, "fee") == []
    assert ledger.invoices["INV-1"].balance == D("1000.00")


def test_periods_assessed_while_disputed_stay_waived_after_resolving():
    ledger = one()
    ledger.dispute("INV-1")
    ledger.assess_late_fees(late(40))                 # periods 1 and 2 waived
    ledger.resolve("INV-1")
    ledger.assess_late_fees(late(40))
    assert fee_total(ledger) == 0
    ledger.assess_late_fees(late(70))                 # period 3 is charged
    assert fee_total(ledger) == D("15.00")


def test_waiver_only_covers_periods_assessed_during_the_dispute():
    ledger = one()
    ledger.assess_late_fees(late(10))                 # 15.00
    ledger.dispute("INV-1")
    ledger.assess_late_fees(late(70))                 # periods 2 and 3 waived
    ledger.resolve("INV-1")
    ledger.assess_late_fees(late(70))
    assert fee_total(ledger) == D("15.00")
    ledger.assess_late_fees(late(100))                # period 4
    assert fee_total(ledger) == D("30.00")


def test_a_dispute_that_never_saw_an_assessment_waives_nothing():
    ledger = one()
    ledger.dispute("INV-1")
    ledger.resolve("INV-1")
    ledger.assess_late_fees(late(40))
    assert fee_total(ledger) == D("30.00")
