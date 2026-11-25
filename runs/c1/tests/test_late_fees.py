"""SPEC section 5: late fees."""

from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from helpers import events, invoice, issue, ledger_with, owing_only_a_late_fee
from tally import Ledger, Line

DUE = date(2026, 2, 4)  # due date of every invoice below unless stated


def late(days):
    return DUE + timedelta(days=days)


def fee_after(*days, **kwargs):
    """Total fee on one invoice after assessing it that many days late, in turn."""
    ledger = ledger_with(invoice(**{"price": "1000.00", **kwargs}))
    for n in days:
        ledger.assess_late_fees(late(n))
    return ledger.invoices["INV-1"].fees


# -- grace and periods --------------------------------------------------------


@pytest.mark.parametrize("days", [-10, 0, 1, 4])
def test_no_fee_in_the_first_days(days):
    ledger = ledger_with(invoice(price="1000.00"))
    ledger.assess_late_fees(late(days))
    assert ledger.invoices["INV-1"].fees == D("0.00")
    assert events(ledger, "fee") == []


@pytest.mark.xfail(strict=True, reason="R5.1: a fee is charged when the invoice is exactly 5 days late")
def test_no_fee_at_5_days_late():
    assert fee_after(5) == D("0.00")


@pytest.mark.parametrize(
    "days, fee",
    [
        (6, "15.00"), (29, "15.00"), (30, "15.00"),
        (31, "30.00"), (60, "30.00"),
        (61, "45.00"), (90, "45.00"), (91, "60.00"),
    ],
)
def test_one_fee_for_each_period_started(days, fee):
    assert fee_after(days) == D(fee)


def test_fee_is_logged_and_added_to_the_balance():
    ledger = ledger_with(invoice(price="1000.00"))
    ledger.assess_late_fees(late(6))
    made = ledger.invoices["INV-1"]
    assert (made.fees_due, made.principal_due, made.balance) == (
        D("15.00"), D("1000.00"), D("1015.00"),
    )
    assert events(ledger, "fee") == [(late(6), "acme", "fee", "INV-1", D("15.00"))]


def test_days_late_count_from_the_moved_due_date():
    # Nominally due Saturday 7 February, so due Monday 9 February.
    ledger = ledger_with(invoice(price="1000.00", day=date(2026, 1, 8)))
    ledger.assess_late_fees(date(2026, 2, 13))  # 6 days after the 7th, 4 after the 9th
    assert ledger.invoices["INV-1"].fees == D("0.00")
    ledger.assess_late_fees(date(2026, 2, 15))
    assert ledger.invoices["INV-1"].fees == D("15.00")


# -- amount -------------------------------------------------------------------


@pytest.mark.parametrize(
    "price, fee",
    [
        ("1000.00", "15.00"),
        ("400.00", "6.00"),
        ("340.00", "5.10"),
        ("333.33", "5.00"),  # 4.99995
        ("300.00", "5.00"),  # 4.50, raised to the minimum
        ("50.00", "5.00"),
        ("1000.50", "15.01"),  # 15.0075
        ("1000.20", "15.00"),  # 15.003
    ],
)
def test_fee_per_period(price, fee):
    assert fee_after(6, price=price) == D(fee)


def test_fee_is_rounded_per_period():
    # 15.003 a period: 2 x 15.00, not 30.006 rounded.
    assert fee_after(31, price="1000.20") == D("30.00")


def test_minimum_is_per_period():
    assert fee_after(31, price="200.00") == D("10.00")


def test_fee_is_on_the_total_including_tax():
    assert fee_after(6, tax_rate="10") == D("16.50")


def test_fee_is_on_the_principal_still_owed():
    ledger = ledger_with(invoice(price="1000.00"))
    ledger.receive("P1", "acme", "400.00", DUE)
    ledger.assess_late_fees(late(6))
    assert ledger.invoices["INV-1"].fees == D("9.00")


def test_several_periods_at_once_use_the_principal_owed_that_day():
    ledger = ledger_with(invoice(price="1000.00"))
    ledger.receive("P1", "acme", "400.00", late(40))
    ledger.assess_late_fees(late(45))
    assert ledger.invoices["INV-1"].fees == D("18.00")


def test_a_later_period_uses_the_lower_principal():
    ledger = ledger_with(invoice(price="1000.00"))
    ledger.assess_late_fees(late(10))
    ledger.receive("P1", "acme", "415.00", late(20))
    ledger.assess_late_fees(late(31))
    assert ledger.invoices["INV-1"].fees == D("24.00")


def test_late_fees_never_earn_late_fees():
    assert fee_after(10, 40, 70) == D("45.00")


def test_a_late_fee_with_no_principal_left_earns_nothing():
    ledger = owing_only_a_late_fee()
    ledger.assess_late_fees(late(100))
    assert ledger.invoices["INV-1"].fees == D("15.00")


# -- cap ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "price, days, fee",
    [
        ("1000.00", 180, "90.00"),
        ("1000.00", 181, "100.00"),  # 7 x 15.00 = 105.00
        ("1000.00", 900, "100.00"),
        ("20.00", 6, "2.00"),  # the minimum fee does not beat the cap
        ("60.00", 31, "6.00"),
    ],
)
def test_fees_are_capped_at_10_percent_of_the_total(price, days, fee):
    assert fee_after(days, price=price) == D(fee)


def test_cap_applies_across_assessments():
    ledger = ledger_with(invoice(price="60.00"))
    for n in (6, 31, 61, 91):
        ledger.assess_late_fees(late(n))
    assert ledger.invoices["INV-1"].fees == D("6.00")
    assert [(e[0], e[4]) for e in events(ledger, "fee")] == [
        (late(6), D("5.00")), (late(31), D("1.00")),
    ]


def test_cap_includes_tax():
    assert fee_after(900, tax_rate="10") == D("110.00")


def test_cap_is_on_the_invoice_total_and_not_on_what_is_owed():
    ledger = ledger_with(invoice(price="1000.00"))
    ledger.receive("P1", "acme", "800.00", DUE)
    ledger.assess_late_fees(late(181))  # 7 x 5.00
    assert ledger.invoices["INV-1"].fees == D("35.00")
    ledger.assess_late_fees(late(900))
    assert ledger.invoices["INV-1"].fees == D("100.00")


def test_paying_fees_does_not_make_room_for_more():
    ledger = ledger_with(invoice(price="60.00"))
    ledger.assess_late_fees(late(31))
    ledger.receive("P1", "acme", "6.00", late(31))
    ledger.assess_late_fees(late(91))
    assert ledger.invoices["INV-1"].fees == D("6.00")
    assert ledger.invoices["INV-1"].balance == D("60.00")


# -- repeating ----------------------------------------------------------------


@pytest.mark.parametrize("days", [(6, 6), (6, 7, 30), (30, 6)])
def test_each_period_is_charged_once(days):
    assert fee_after(*days) == D("15.00")


def test_new_periods_are_charged_as_they_start():
    ledger = ledger_with(invoice(price="1000.00"))
    for n in (6, 30, 31, 45, 91):
        ledger.assess_late_fees(late(n))
    assert [(e[0], e[4]) for e in events(ledger, "fee")] == [
        (late(6), D("15.00")), (late(31), D("15.00")), (late(91), D("30.00")),
    ]


def test_each_invoice_is_assessed_on_its_own():
    ledger = Ledger()
    issue(ledger, "INV-1", "1000.00")
    issue(ledger, "INV-2", "2000.00", customer="other")
    issue(ledger, "INV-3", "1000.00", day=date(2026, 3, 2))
    ledger.assess_late_fees(late(10))
    assert {n: i.fees for n, i in ledger.invoices.items()} == {
        "INV-1": D("15.00"), "INV-2": D("30.00"), "INV-3": D("0.00"),
    }
    assert sorted(e[1:] for e in events(ledger, "fee")) == [
        ("acme", "fee", "INV-1", D("15.00")), ("other", "fee", "INV-2", D("30.00")),
    ]


def test_draft_void_and_paid_invoices_are_charged_nothing():
    ledger = ledger_with(invoice("INV-1", "1000.00"), invoice("INV-2", "1000.00"))
    ledger.add(invoice("INV-3", "1000.00"))
    ledger.void("INV-1", DUE)
    ledger.receive("P1", "acme", "1000.00", DUE)
    ledger.assess_late_fees(late(40))
    assert events(ledger, "fee") == []


def test_invoice_for_nothing_is_charged_nothing():
    assert fee_after(40, lines=[Line("a", 1, "5.00"), Line("b", 1, "-5.00")]) == D("0.00")


# -- disputes -----------------------------------------------------------------


def test_disputed_invoice_is_charged_nothing():
    ledger = ledger_with(invoice(price="1000.00"))
    ledger.dispute("INV-1")
    ledger.assess_late_fees(late(40))
    assert ledger.invoices["INV-1"].fees == D("0.00")
    assert events(ledger, "fee") == []


def test_periods_assessed_during_a_dispute_stay_waived():
    ledger = ledger_with(invoice(price="1000.00"))
    ledger.dispute("INV-1")
    ledger.assess_late_fees(late(40))
    ledger.resolve("INV-1")
    ledger.assess_late_fees(late(40))
    ledger.assess_late_fees(late(60))
    assert ledger.invoices["INV-1"].fees == D("0.00")
    ledger.assess_late_fees(late(61))
    assert ledger.invoices["INV-1"].fees == D("15.00")


def test_periods_not_assessed_during_a_dispute_are_charged_after_it():
    ledger = ledger_with(invoice(price="1000.00"))
    ledger.dispute("INV-1")
    ledger.assess_late_fees(late(20))
    ledger.resolve("INV-1")
    ledger.assess_late_fees(late(70))  # periods 2 and 3
    assert ledger.invoices["INV-1"].fees == D("30.00")


def test_fees_charged_before_a_dispute_stay():
    ledger = ledger_with(invoice(price="1000.00"))
    ledger.assess_late_fees(late(6))
    ledger.dispute("INV-1")
    ledger.assess_late_fees(late(31))
    assert ledger.invoices["INV-1"].fees == D("15.00")
