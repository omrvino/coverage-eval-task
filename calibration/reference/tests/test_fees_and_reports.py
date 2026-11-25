from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from tally import Invoice, Ledger, Line, aging, statement

DAY = date(2026, 1, 5)
DUE = date(2026, 2, 4)


def make(price="1000", number="A", customer="acme", day=DAY, ledger=None):
    ledger = ledger or Ledger()
    ledger.add(Invoice(number, customer, day, "NET 30", [Line("w", 1, price)]))
    ledger.issue(number)
    return ledger


def late(days):
    return DUE + timedelta(days=days)


@pytest.mark.xfail(strict=True, reason="R5.1: charged on day 5")
def test_grace_includes_day_five():
    ledger = make()
    assert ledger.assess_late_fees(late(5)) == {}


@pytest.mark.parametrize("days, fee", [(4, "0"), (6, "15"), (30, "15"), (31, "30"), (60, "30"), (61, "45")])
def test_fee_periods(days, fee):
    ledger = make()
    ledger.assess_late_fees(late(days))
    assert ledger.invoices["A"].fees == D(fee)


def test_minimum_fee():
    ledger = make("100")
    assert ledger.assess_late_fees(late(10)) == {"A": D("5.00")}


def test_fee_on_principal_still_owed_and_not_on_fees():
    ledger = make()
    ledger.assess_late_fees(late(10))
    ledger.assess_late_fees(late(40))
    assert ledger.invoices["A"].fees == D("30.00")
    ledger.receive("P", "acme", "430", late(41))
    ledger.assess_late_fees(late(70))
    assert ledger.invoices["A"].fees == D("39.00")


def test_fee_cap_counts_earlier_fees():
    ledger = make()
    for days in (10, 40, 70, 100, 130, 160, 190, 220, 250):
        ledger.assess_late_fees(late(days))
    assert ledger.invoices["A"].fees == D("100.00")
    small = make("40")
    small.assess_late_fees(late(10))
    assert small.invoices["A"].fees == D("4.00")


def test_assessing_twice_charges_once():
    ledger = make()
    ledger.assess_late_fees(late(10))
    assert ledger.assess_late_fees(late(10)) == {}
    ledger.assess_late_fees(late(40))
    assert ledger.invoices["A"].fees == D("30.00")


def test_disputed_periods_stay_waived():
    ledger = make()
    ledger.dispute("A")
    assert ledger.assess_late_fees(late(40)) == {}
    ledger.resolve("A")
    assert ledger.assess_late_fees(late(41)) == {}
    assert ledger.assess_late_fees(late(61)) == {"A": D("15.00")}


@pytest.mark.parametrize("days, bucket", [
    (-3, "current"), (0, "current"), (1, "1-30"), (30, "1-30"), (31, "31-60"),
    (60, "31-60"), (61, "61-90"), (90, "61-90"), (91, "91+")])
def test_aging_buckets(days, bucket):
    report = aging(make(), "acme", late(days))
    assert {k: v for k, v in report.items() if v} == {bucket: D("1000.00")}


def test_aging_includes_fees_and_skips_other_states():
    ledger = make()
    make("50", "B", ledger=ledger)
    make("70", "C", ledger=ledger)
    make("90", "D", customer="other", ledger=ledger)
    ledger.add(Invoice("E", "acme", DAY, "NET 30", [Line("w", 1, "11")]))
    ledger.void("B", DAY)
    ledger.dispute("C")
    ledger.assess_late_fees(late(10))
    report = aging(ledger, "acme", late(10))
    assert {k: v for k, v in report.items() if v} == {"1-30": D("1015.00"), "disputed": D("70.00")}


@pytest.mark.xfail(strict=True, reason="R6.3: newest bucket first")
def test_credit_reduces_oldest_first():
    ledger = make("100", "OLD")
    make("100", "NEW", day=date(2026, 3, 2), ledger=ledger)
    ledger.dispute("OLD")
    ledger.dispute("NEW")
    ledger.receive("P", "acme", "130", DAY)
    ledger.resolve("OLD")
    ledger.resolve("NEW")
    report = aging(ledger, "acme", date(2026, 3, 20))
    assert (report["31-60"], report["current"]) == (D("0.00"), D("70.00"))


def test_credit_leaves_disputed_alone_and_shows_negative():
    ledger = make("100")
    ledger.dispute("A")
    ledger.receive("P", "acme", "30", DAY)
    report = aging(ledger, "acme", late(10))
    assert report["disputed"] == D("100.00") and report["current"] == D("-30.00")


def test_statement():
    ledger = make("100")
    make("500", "Z", customer="other", ledger=ledger)
    ledger.receive("P1", "acme", "20", date(2026, 1, 10))
    ledger.receive("P2", "acme", "10", date(2026, 1, 31))
    make("40", "B", day=date(2026, 1, 10), ledger=ledger)
    ledger.receive("P3", "acme", "1", date(2026, 2, 1))
    result = statement(ledger, "acme", date(2026, 1, 10), date(2026, 1, 31))
    assert result.opening == D("100.00")
    assert [(s.kind, s.ref, s.amount, s.balance) for s in result.lines] == [
        ("invoice", "B", D("40.00"), D("140.00")),
        ("payment", "P1", D("-20.00"), D("120.00")),
        ("payment", "P2", D("-10.00"), D("110.00")),
    ]
    assert result.closing == D("110.00")


def test_statement_same_day_order():
    ledger = Ledger()
    ledger.add(Invoice("A", "acme", DAY, "2/10 NET 30", [Line("w", 1, "100")]))
    ledger.add(Invoice("B", "acme", DAY, "NET 30", [Line("w", 1, "7")]))
    ledger.issue("B")
    ledger.void("B", DAY)
    ledger.issue("A")
    ledger.receive("P", "acme", "98", DAY)
    ledger.reverse("P", DAY)
    kinds = [s.kind for s in statement(ledger, "acme", DAY, DAY).lines]
    assert kinds == ["invoice", "invoice", "payment", "discount", "reversal", "void"]


def test_empty_statement():
    ledger = make("100")
    result = statement(ledger, "acme", date(2026, 3, 1), date(2026, 3, 31))
    assert result.lines == [] and result.opening == result.closing == D("100.00")
