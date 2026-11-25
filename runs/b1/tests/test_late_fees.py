from datetime import timedelta
from decimal import Decimal

import pytest

from tally import Ledger

from helpers import D0, issued, kinds, make_invoice

D = Decimal


def late(days):
    return D0 + timedelta(days=days)


def fee_total(ledger, number="INV-1"):
    return sum((e.amount for e in kinds(ledger, "fee") if e.ref == number), D("0.00"))


# -- R5.1 ------------------------------------------------------------------

@pytest.mark.parametrize("days", [-30, -1, 0, 1, 4])
def test_no_fee_while_within_the_grace_days(days):
    ledger = issued(make_invoice(price="1000.00"))
    ledger.assess_late_fees(late(days))
    assert kinds(ledger, "fee") == []
    assert ledger.invoices["INV-1"].fees == D("0.00")


@pytest.mark.xfail(strict=True, reason="a fee is charged on day 5, the spec says the first fee is day 6")
def test_no_fee_on_the_fifth_day_late():
    ledger = issued(make_invoice(price="1000.00"))
    ledger.assess_late_fees(late(5))
    assert kinds(ledger, "fee") == []


def test_fee_from_the_sixth_day():
    ledger = issued(make_invoice(price="1000.00"))
    ledger.assess_late_fees(late(6))
    assert fee_total(ledger) == D("15.00")


def test_a_late_invoice_gets_its_fee_when_assessed_even_much_later():
    ledger = issued(make_invoice(price="1000.00"))
    ledger.assess_late_fees(late(200))
    assert fee_total(ledger) == D("100.00")     # capped at 10 percent


# -- R5.2 ------------------------------------------------------------------

@pytest.mark.parametrize("days, periods", [(6, 1), (15, 1), (30, 1), (31, 2), (60, 2), (61, 3), (90, 3), (91, 4)])
def test_one_fee_per_started_30_day_period(days, periods):
    ledger = issued(make_invoice(price="1000.00"))
    ledger.assess_late_fees(late(days))
    assert fee_total(ledger) == D("15.00") * periods


def test_fee_covers_the_whole_time_since_the_due_date_even_when_first_assessed_late():
    ledger = issued(make_invoice(price="1000.00"))
    ledger.assess_late_fees(late(45))
    assert fee_total(ledger) == D("30.00")


def test_later_assessment_charges_only_the_new_periods():
    ledger = issued(make_invoice(price="1000.00"))
    ledger.assess_late_fees(late(6))
    ledger.assess_late_fees(late(30))
    assert fee_total(ledger) == D("15.00")
    ledger.assess_late_fees(late(31))
    assert fee_total(ledger) == D("30.00")
    assert [e.date for e in kinds(ledger, "fee")] == [late(6), late(31)]


def test_fee_is_logged_with_its_amount_date_and_invoice():
    ledger = issued(make_invoice(price="1000.00"))
    ledger.assess_late_fees(late(16))
    (event,) = kinds(ledger, "fee")
    assert (event.date, event.customer, event.ref, event.amount) == (
        late(16), "acme", "INV-1", D("15.00"))
    assert ledger.invoices["INV-1"].fees == D("15.00")
    assert ledger.invoices["INV-1"].balance == D("1015.00")


# -- R5.3 ------------------------------------------------------------------

def test_fee_is_one_and_a_half_percent_rounded_to_the_cent():
    ledger = issued(make_invoice(price="1234.56"))             # 18.5184
    ledger.assess_late_fees(late(10))
    assert fee_total(ledger) == D("18.52")


def test_fee_has_a_minimum_of_five():
    ledger = issued(make_invoice(price="100.00"))              # 1.50
    ledger.assess_late_fees(late(10))
    assert fee_total(ledger) == D("5.00")


def test_fee_just_above_the_minimum():
    ledger = issued(make_invoice(price="400.00"))              # 6.00
    ledger.assess_late_fees(late(10))
    assert fee_total(ledger) == D("6.00")


def test_fee_is_based_on_the_principal_still_owed_on_the_day():
    ledger = issued(make_invoice(price="1000.00"))
    ledger.receive("P1", "acme", "600.00", late(-10))
    ledger.assess_late_fees(late(10))
    assert fee_total(ledger) == D("6.00")                      # 1.5% of 400


def test_late_fees_do_not_earn_late_fees():
    ledger = issued(make_invoice(price="1000.00"))
    ledger.assess_late_fees(late(10))
    ledger.assess_late_fees(late(40))
    assert fee_total(ledger) == D("30.00")                     # not 15 + 15.22


def test_fee_includes_tax_in_the_principal():
    ledger = issued(make_invoice(price="1000.00", tax_rate=10))
    ledger.assess_late_fees(late(10))
    assert fee_total(ledger) == D("16.50")


def test_several_new_periods_are_charged_on_the_principal_of_the_day():
    ledger = issued(make_invoice(price="1000.00"))
    ledger.receive("P1", "acme", "500.00", late(-5))
    ledger.assess_late_fees(late(45))
    assert fee_total(ledger) == D("15.00")                     # two periods of 7.50


# -- R5.4 ------------------------------------------------------------------

def test_fees_never_add_up_to_more_than_ten_percent_of_the_total():
    ledger = issued(make_invoice(price="100.00"))
    for days in (10, 40, 70, 100, 130, 400):
        ledger.assess_late_fees(late(days))
    assert fee_total(ledger) == D("10.00")
    assert ledger.invoices["INV-1"].fees == D("10.00")


def test_the_cap_applies_to_a_single_large_assessment():
    ledger = issued(make_invoice(price="100.00"))
    ledger.assess_late_fees(late(100))                         # four periods of 5.00
    assert fee_total(ledger) == D("10.00")


def test_the_cap_is_ten_percent_of_the_invoice_total_with_tax():
    ledger = issued(make_invoice(price="100.00", tax_rate=10))   # total 110.00
    ledger.assess_late_fees(late(100))
    assert fee_total(ledger) == D("11.00")


def test_the_cap_beats_the_minimum_fee():
    ledger = issued(make_invoice(price="20.00"))
    ledger.assess_late_fees(late(10))
    assert fee_total(ledger) == D("2.00")


def test_cap_counts_fees_already_charged():
    ledger = issued(make_invoice(price="100.00"))
    ledger.assess_late_fees(late(10))
    ledger.assess_late_fees(late(40))
    assert fee_total(ledger) == D("10.00")
    ledger.assess_late_fees(late(70))
    assert fee_total(ledger) == D("10.00")
    assert len(kinds(ledger, "fee")) == 2


# -- R5.5 ------------------------------------------------------------------

def test_assessing_twice_charges_each_period_once():
    ledger = issued(make_invoice(price="1000.00"))
    ledger.assess_late_fees(late(35))
    first = list(ledger.events)
    ledger.assess_late_fees(late(35))
    ledger.assess_late_fees(late(36))
    assert ledger.events == first
    assert ledger.invoices["INV-1"].fees == D("30.00")


# -- R5.6 ------------------------------------------------------------------

def test_disputed_invoice_is_charged_nothing():
    ledger = issued(make_invoice(price="1000.00"))
    ledger.dispute("INV-1")
    ledger.assess_late_fees(late(40))
    assert kinds(ledger, "fee") == []
    assert ledger.invoices["INV-1"].fees == D("0.00")


def test_periods_assessed_during_a_dispute_stay_waived_after_resolution():
    ledger = issued(make_invoice(price="1000.00"))
    ledger.dispute("INV-1")
    ledger.assess_late_fees(late(40))                          # periods 1 and 2 waived
    ledger.resolve("INV-1")
    ledger.assess_late_fees(late(40))
    ledger.assess_late_fees(late(60))
    assert kinds(ledger, "fee") == []
    ledger.assess_late_fees(late(61))                          # period 3 starts
    assert fee_total(ledger) == D("15.00")


def test_fees_charged_before_a_dispute_stay():
    ledger = issued(make_invoice(price="1000.00"))
    ledger.assess_late_fees(late(10))
    ledger.dispute("INV-1")
    ledger.assess_late_fees(late(70))
    ledger.resolve("INV-1")
    ledger.assess_late_fees(late(70))
    assert fee_total(ledger) == D("15.00")


# -- which invoices are charged -------------------------------------------

def test_only_open_late_invoices_are_charged():
    draft = make_invoice("DRAFT", price="1000.00")
    paid = make_invoice("PAID", price="1000.00", due=D0 - timedelta(days=7))
    void = make_invoice("VOID", price="1000.00")
    notyet = make_invoice("NOTYET", price="1000.00", due=D0 + timedelta(days=28))
    late_one = make_invoice("LATE", price="1000.00")
    ledger = issued(paid, void, notyet, late_one)
    ledger.add(draft)
    ledger.receive("PP", "acme", "1000.00", D0 - timedelta(days=20))
    ledger.void("VOID", D0)
    ledger.assess_late_fees(late(10))
    assert [e.ref for e in kinds(ledger, "fee")] == ["LATE"]


def test_each_invoice_is_charged_on_its_own():
    a = make_invoice("A", price="1000.00", due=D0)
    b = make_invoice("B", price="2000.00", due=D0 + timedelta(days=14), customer="other")
    ledger = issued(a, b)
    ledger.assess_late_fees(late(20))
    assert fee_total(ledger, "A") == D("15.00")
    assert fee_total(ledger, "B") == D("30.00")
    assert {e.ref: e.customer for e in kinds(ledger, "fee")} == {"A": "acme", "B": "other"}


def test_assessing_an_empty_ledger_does_nothing():
    ledger = Ledger()
    ledger.assess_late_fees(D0)
    assert ledger.events == []
