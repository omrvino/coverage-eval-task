from datetime import date, timedelta
from decimal import Decimal

import pytest

from tally import Invoice, Ledger, Line

D = Decimal

XFAIL_GRACE = pytest.mark.xfail(
    strict=True,
    reason="R5.1: a fee is charged on the 5th day late (days_late < 5 check); the spec says no fee for 5 days late or less",
)


def issued_ledger(price="1000.00", terms="NET 30"):
    ledger = Ledger()
    ledger.add(Invoice("INV-1", "acme", date(2026, 1, 5), terms, [Line("work", 1, price)]))
    ledger.issue("INV-1")
    return ledger


def late(ledger, days):
    """Assess late fees on the day that is ``days`` after the due date."""
    return ledger.assess_late_fees(ledger.invoices["INV-1"].due + timedelta(days=days))


def fees(ledger):
    return ledger.invoices["INV-1"].fees


@pytest.mark.parametrize("days", [-3, 0, 4])
def test_no_fee_before_the_grace_period_ends(days):
    ledger = issued_ledger()
    assert late(ledger, days) == {}
    assert fees(ledger) == 0


def test_fee_starts_on_the_sixth_day_late():
    ledger = issued_ledger()
    assert late(ledger, 6) == {"INV-1": D("15.00")}


@XFAIL_GRACE
def test_five_days_late_is_still_within_the_grace_period():
    ledger = issued_ledger()
    late(ledger, 5)
    assert fees(ledger) == 0


@pytest.mark.parametrize("days, periods", [(6, 1), (30, 1), (31, 2), (60, 2), (61, 3)])
def test_one_fee_for_each_thirty_day_period_started(days, periods):
    ledger = issued_ledger()
    late(ledger, days)
    assert fees(ledger) == D("15.00") * periods


def test_fee_is_one_and_a_half_percent_of_principal_rounded_to_the_cent():
    ledger = issued_ledger(price="1000.33")  # 15.00495
    late(ledger, 6)
    assert str(fees(ledger)) == "15.00"


def test_fee_is_at_least_five_dollars():
    ledger = issued_ledger(price="100.00")  # 1.50 is below the minimum
    late(ledger, 6)
    assert fees(ledger) == D("5.00")


def test_fee_uses_the_principal_still_owed_on_the_day_it_is_assessed():
    ledger = issued_ledger()
    ledger.receive("P1", "acme", "500.00", ledger.invoices["INV-1"].due + timedelta(days=10))
    late(ledger, 31)  # two periods at 1.5% of 500.00
    assert fees(ledger) == D("15.00")


def test_late_fees_never_earn_late_fees():
    ledger = issued_ledger()
    late(ledger, 6)
    late(ledger, 36)  # one more period, 1.5% of the 1000.00 principal, not of 1015.00
    assert fees(ledger) == D("30.00")


def test_total_late_fees_are_capped_at_ten_percent_of_the_invoice_total():
    ledger = issued_ledger(price="100.00")  # cap is 10.00
    late(ledger, 61)  # three periods would be 15.00
    assert fees(ledger) == D("10.00")
    late(ledger, 91)  # a fourth period adds nothing
    assert fees(ledger) == D("10.00")


def test_cap_on_a_larger_invoice():
    ledger = issued_ledger()
    late(ledger, 200)  # seven periods would be 105.00
    assert fees(ledger) == D("100.00")


def test_assessing_twice_charges_each_period_once():
    ledger = issued_ledger()
    assert late(ledger, 10) == {"INV-1": D("15.00")}
    assert late(ledger, 10) == {}
    assert late(ledger, 31) == {"INV-1": D("15.00")}
    assert late(ledger, 31) == {}
    assert fees(ledger) == D("30.00")


def test_disputed_invoice_is_charged_nothing_and_its_periods_stay_waived():
    ledger = issued_ledger()
    ledger.dispute("INV-1")
    assert late(ledger, 31) == {}
    ledger.resolve("INV-1")
    assert late(ledger, 31) == {}
    assert fees(ledger) == 0
    assert late(ledger, 61) == {"INV-1": D("15.00")}  # only the third period is new


def test_periods_started_after_the_dispute_is_resolved_are_charged():
    ledger = issued_ledger()
    ledger.dispute("INV-1")
    late(ledger, 10)  # the first period falls inside the dispute
    ledger.resolve("INV-1")
    assert late(ledger, 40) == {"INV-1": D("15.00")}  # the second period is charged
    assert fees(ledger) == D("15.00")


def test_no_fee_on_paid_void_or_draft_invoices():
    ledger = Ledger()
    for number in ("PAID", "VOID", "DRAFT"):
        ledger.add(Invoice(number, "acme", date(2026, 1, 5), "NET 30", [Line("work", 1, "100.00")]))
    ledger.issue("PAID")
    ledger.receive("P1", "acme", "100.00", date(2026, 1, 20))
    ledger.issue("VOID")
    ledger.void("VOID", date(2026, 1, 21))

    assert ledger.assess_late_fees(date(2026, 4, 1)) == {}
    assert [ledger.invoices[number].fees for number in ("PAID", "VOID", "DRAFT")] == [0, 0, 0]
