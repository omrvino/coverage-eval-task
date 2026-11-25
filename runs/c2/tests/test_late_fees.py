"""SPEC section 5: late fees."""

import pytest

from helpers import DUE, JAN_5, D, days, events, issued, make_invoice, snapshot
from tally import Ledger


def fees_after(days_late, price="1000.00"):
    ledger = issued(make_invoice(price=price))
    ledger.assess_late_fees(DUE + days(days_late))
    return ledger.invoices["INV-1"].fees_due


def fee_amounts(ledger):
    return [amount for _, _, amount in events(ledger, "fee")]


# -- R5.1, R5.2 ------------------------------------------------------------


@pytest.mark.parametrize("days_late", [-30, -1, 0, 1, 4])
def test_r5_1_no_fee_within_the_grace_days(days_late):
    assert fees_after(days_late) == 0


@pytest.mark.xfail(strict=True, reason="R5.1: a fee is charged on day 5")
def test_r5_1_no_fee_on_day_5():
    assert fees_after(5) == 0


@pytest.mark.parametrize("days_late, periods", [
    (6, 1), (7, 1), (29, 1), (30, 1), (31, 2), (35, 2), (36, 2), (60, 2), (61, 3), (90, 3),
    (91, 4),
])
def test_r5_2_one_fee_per_period_started(days_late, periods):
    assert fees_after(days_late) == periods * D("15.00")


def test_r5_1_lateness_counts_from_the_moved_due_date():
    ledger = issued(make_invoice(price="1000.00", terms="NET 5"))  # Saturday, so due Jan 12
    ledger.assess_late_fees(JAN_5 + days(11))  # 6 days after Saturday, 4 after Monday
    assert ledger.invoices["INV-1"].fees_due == 0
    ledger.assess_late_fees(JAN_5 + days(13))
    assert ledger.invoices["INV-1"].fees_due == D("15.00")


def test_fee_is_logged_for_the_day_it_was_assessed():
    ledger = issued(make_invoice(price="1000.00"))
    ledger.assess_late_fees(DUE + days(40))
    assert {day for day, _, _ in events(ledger, "fee")} == {DUE + days(40)}
    assert sum(fee_amounts(ledger)) == D("30.00")


# -- R5.3 ------------------------------------------------------------------


@pytest.mark.parametrize("price, expected", [
    ("1000.00", "15.00"),
    ("1234.56", "18.52"),  # 18.5184
    ("1234.00", "18.51"),
    ("333.20", "5.00"),  # 4.998
    ("334.00", "5.01"),
    ("100.00", "5.00"),
    ("50.00", "5.00"),
])
def test_r5_3_rate_and_minimum(price, expected):
    assert fees_after(6, price) == D(expected)


def test_r5_3_each_period_is_rounded_on_its_own():
    assert fees_after(61, "1000.30") == D("45.00")  # 15.0045 a period; 45.0135 in all


def test_r5_3_minimum_is_per_period():
    assert fees_after(31, "200.00") == D("10.00")


def test_r5_3_is_on_the_principal_still_owed():
    ledger = issued(make_invoice(price="1000.00"))
    ledger.receive("P1", "acme", "400.00", DUE)
    ledger.assess_late_fees(DUE + days(10))
    assert ledger.invoices["INV-1"].fees_due == D("9.00")


def test_r5_3_later_periods_use_the_principal_owed_then():
    ledger = issued(make_invoice(price="1000.00"))
    ledger.assess_late_fees(DUE + days(10))
    ledger.receive("P1", "acme", "415.00", DUE + days(20))  # 15 in fees, 400 off principal
    ledger.assess_late_fees(DUE + days(40))
    assert ledger.invoices["INV-1"].fees_due == D("9.00")


def test_r5_3_principal_includes_tax():
    ledger = issued(make_invoice(price="1000.00", tax_rate="10"))
    ledger.assess_late_fees(DUE + days(10))
    assert ledger.invoices["INV-1"].fees_due == D("16.50")


def test_r5_3_late_fees_never_earn_late_fees():
    ledger = issued(make_invoice(price="1000.00"))
    for late in (30, 60, 90):
        ledger.assess_late_fees(DUE + days(late))
    assert fee_amounts(ledger) == [D("15.00")] * 3


def test_r5_3_no_fee_when_only_late_fees_are_owed():
    ledger = issued(make_invoice(price="1000.00"))
    ledger.assess_late_fees(DUE + days(10))
    ledger.receive("FEE", "acme", "15.00", DUE + days(10))
    ledger.receive("REST", "acme", "1000.00", DUE + days(10))
    ledger.reverse("FEE", DUE + days(11))
    ledger.assess_late_fees(DUE + days(40))
    assert ledger.invoices["INV-1"].balance == D("15.00")


# -- R5.4 ------------------------------------------------------------------


@pytest.mark.parametrize("days_late, expected", [
    (180, "90.00"), (181, "100.00"), (211, "100.00"), (3000, "100.00"),
])
def test_r5_4_capped_at_ten_percent(days_late, expected):
    assert fees_after(days_late) == D(expected)


def test_r5_4_cap_beats_the_minimum():
    assert fees_after(6, "20.00") == D("2.00")


def test_r5_4_cap_holds_over_many_assessments():
    ledger = issued(make_invoice(price="1000.00"))
    for late in range(6, 400, 7):
        ledger.assess_late_fees(DUE + days(late))
        assert ledger.invoices["INV-1"].fees_due <= D("100.00")
    assert ledger.invoices["INV-1"].fees_due == D("100.00")
    assert sum(fee_amounts(ledger)) == D("100.00")


def test_r5_4_cap_is_on_the_total_with_tax():
    ledger = issued(make_invoice(price="1000.00", tax_rate="10"))
    ledger.assess_late_fees(DUE + days(900))
    assert ledger.invoices["INV-1"].fees_due == D("110.00")


def test_r5_4_cap_is_on_the_total_not_on_what_is_owed():
    ledger = issued(make_invoice(price="1000.00"))
    ledger.receive("P1", "acme", "500.00", JAN_5)
    ledger.assess_late_fees(DUE + days(900))
    assert ledger.invoices["INV-1"].fees_due == D("100.00")


def test_r5_4_fees_already_paid_count_towards_the_cap():
    ledger = issued(make_invoice(price="1000.00"))
    ledger.assess_late_fees(DUE + days(90))
    ledger.receive("P1", "acme", "45.00", DUE + days(90))
    ledger.assess_late_fees(DUE + days(900))
    assert ledger.invoices["INV-1"].fees_due == D("55.00")


# -- R5.5 ------------------------------------------------------------------


def test_r5_5_assessing_twice_charges_once():
    ledger = issued(make_invoice(price="1000.00"))
    ledger.assess_late_fees(DUE + days(10))
    before = snapshot(ledger)
    for late in (10, 11, 30, 6):  # the same period, in any order
        ledger.assess_late_fees(DUE + days(late))
    assert snapshot(ledger) == before
    ledger.assess_late_fees(DUE + days(31))
    ledger.assess_late_fees(DUE + days(31))
    assert events(ledger, "fee") == [
        (DUE + days(10), "fee", D("15.00")), (DUE + days(31), "fee", D("15.00")),
    ]


def test_r5_5_assessing_an_earlier_day_afterwards_charges_nothing():
    ledger = issued(make_invoice(price="1000.00"))
    ledger.assess_late_fees(DUE + days(61))
    before = snapshot(ledger)
    ledger.assess_late_fees(DUE + days(20))
    ledger.assess_late_fees(DUE + days(61))
    assert snapshot(ledger) == before


def test_r5_5_catching_up_charges_only_the_new_periods():
    ledger = issued(make_invoice(price="1000.00"))
    ledger.assess_late_fees(DUE + days(10))
    assert sum(fee_amounts(ledger)) == D("15.00")
    ledger.assess_late_fees(DUE + days(95))
    assert sum(fee_amounts(ledger)) == D("60.00")


def test_r5_5_each_invoice_keeps_its_own_periods():
    ledger = issued(
        make_invoice("INV-1", "1000.00"),
        make_invoice("INV-2", "2000.00", terms="NET 60", customer="other"),
    )
    ledger.assess_late_fees(DUE + days(20))
    assert (ledger.invoices["INV-1"].fees_due, ledger.invoices["INV-2"].fees_due) == (D("15.00"), 0)
    ledger.assess_late_fees(DUE + days(50))
    assert ledger.invoices["INV-1"].fees_due == D("30.00")
    assert ledger.invoices["INV-2"].fees_due == D("30.00")


def test_invoices_that_are_not_open_are_charged_nothing():
    ledger = issued(make_invoice("PAID"), make_invoice("VOID"))
    ledger.receive("P1", "acme", "100.00", JAN_5)  # PAID comes first in number order
    ledger.void("VOID", JAN_5)
    ledger.add(make_invoice("DRAFT"))
    before = snapshot(ledger)
    ledger.assess_late_fees(DUE + days(100))
    assert snapshot(ledger) == before


def test_empty_ledger_is_charged_nothing():
    ledger = Ledger()
    ledger.assess_late_fees(DUE)
    assert events(ledger) == []


# -- R5.6 ------------------------------------------------------------------


def test_r5_6_disputed_invoice_is_charged_nothing():
    ledger = issued(make_invoice(price="1000.00"))
    ledger.dispute("INV-1")
    ledger.assess_late_fees(DUE + days(100))
    assert ledger.invoices["INV-1"].fees_due == 0
    assert events(ledger, "fee") == []


def test_r5_6_periods_assessed_under_dispute_stay_waived():
    ledger = issued(make_invoice(price="1000.00"))
    ledger.dispute("INV-1")
    ledger.assess_late_fees(DUE + days(40))  # waives two periods
    ledger.resolve("INV-1")
    ledger.assess_late_fees(DUE + days(60))
    assert ledger.invoices["INV-1"].fees_due == 0
    ledger.assess_late_fees(DUE + days(61))
    assert ledger.invoices["INV-1"].fees_due == D("15.00")


def test_r5_6_fees_from_before_the_dispute_remain():
    ledger = issued(make_invoice(price="1000.00"))
    ledger.assess_late_fees(DUE + days(10))
    ledger.dispute("INV-1")
    ledger.assess_late_fees(DUE + days(40))
    ledger.resolve("INV-1")
    ledger.assess_late_fees(DUE + days(70))
    assert fee_amounts(ledger) == [D("15.00"), D("15.00")]
    assert ledger.invoices["INV-1"].fees_due == D("30.00")


def test_r5_6_only_assessed_periods_are_waived():
    ledger = issued(make_invoice(price="1000.00"))
    ledger.dispute("INV-1")
    ledger.resolve("INV-1")
    ledger.assess_late_fees(DUE + days(40))
    assert ledger.invoices["INV-1"].fees_due == D("30.00")
