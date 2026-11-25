from datetime import date

import pytest

from helpers import BUCKETS, D, DUE, JAN5, buckets, events, invoice, late, ledger_with
from tally import Ledger, aging, statement


def only(name, amount):
    report = {key: D("0.00") for key in BUCKETS}
    report[name] = D(amount)
    return report


# R6.1 ---------------------------------------------------------------------

@pytest.mark.parametrize("days, bucket", [
    (-40, "current"), (-1, "current"), (0, "current"),
    (1, "1-30"), (30, "1-30"),
    (31, "31-60"), (60, "31-60"),
    (61, "61-90"), (90, "61-90"),
    (91, "91+"), (91 + 400, "91+"),
])
def test_bucket_boundaries(days, bucket):
    ledger = ledger_with(invoice())
    assert buckets(ledger, "acme", late(days)) == only(bucket, "100.00")


def test_balance_includes_late_fees_and_partial_payments():
    ledger = ledger_with(invoice(price="1000.00"))
    ledger.assess_late_fees(late(10))
    assert buckets(ledger, "acme", late(10)) == only("1-30", "1015.00")
    ledger.receive("P1", "acme", "415.00", late(10))
    assert buckets(ledger, "acme", late(10)) == only("1-30", "600.00")


def test_several_invoices_are_spread_over_buckets_and_summed():
    ledger = ledger_with(
        invoice("A", day=date(2026, 1, 5), price="10.00"),       # due Feb 4
        invoice("B", day=date(2026, 1, 6), price="20.00"),       # due Feb 5
        invoice("C", day=date(2026, 3, 20), price="40.00"),      # due Apr 19 -> Mon Apr 20
        invoice("D", day=date(2026, 4, 1), price="80.00"),       # due May 1
    )
    report = buckets(ledger, "acme", date(2026, 4, 25))
    assert report["61-90"] == D("30.00")
    assert report["1-30"] == D("40.00")
    assert report["current"] == D("80.00")
    assert report["91+"] == report["31-60"] == report["disputed"] == 0


def test_other_customers_are_left_out():
    ledger = ledger_with(invoice("A"), invoice("B", customer="other", price="50.00"))
    assert buckets(ledger, "acme", late(0)) == only("current", "100.00")
    assert buckets(ledger, "nobody", late(0)) == only("current", "0.00")


# R6.2 ---------------------------------------------------------------------

def test_disputed_invoices_go_in_the_disputed_bucket_only():
    ledger = ledger_with(invoice("A"), invoice("B", price="60.00"))
    ledger.dispute("B")
    assert buckets(ledger, "acme", late(45)) == {**only("31-60", "100.00"), "disputed": D("60.00")}


def test_disputed_balance_includes_fees_charged_before_the_dispute():
    ledger = ledger_with(invoice(price="1000.00"))
    ledger.assess_late_fees(late(10))
    ledger.dispute("INV-1")
    assert buckets(ledger, "acme", late(10)) == only("disputed", "1015.00")


def test_draft_void_and_paid_invoices_are_left_out():
    ledger = ledger_with(invoice("PAID"), invoice("VOID"))
    ledger.add(invoice("DRAFT"))
    ledger.void("VOID", JAN5)
    ledger.receive("P1", "acme", "100.00", JAN5)
    assert buckets(ledger, "acme", late(45)) == only("current", "0.00")


# R6.3 ---------------------------------------------------------------------

def credit_ledger(credit, *invoices):
    ledger = Ledger()
    ledger.receive("C1", "acme", credit, date(2025, 12, 1))     # nothing owed yet, all credit
    for item in invoices:
        ledger.add(item)
        ledger.issue(item.number)
    return ledger


ON = date(2026, 5, 10)
OLD = dict(day=JAN5)                       # due Feb 4: 95 days late on ON, bucket 91+
MID = dict(day=date(2026, 3, 20))          # due Apr 20: 20 days late, bucket 1-30
NEW = dict(day=date(2026, 5, 1))           # due Jun 1: current


def test_credit_reduces_its_bucket_and_never_below_zero():
    ledger = credit_ledger("30.00", invoice("A", **MID))
    assert buckets(ledger, "acme", ON) == only("1-30", "70.00")


def test_credit_beyond_the_balance_shows_negative_in_current():
    ledger = credit_ledger("150.00", invoice("A", **MID))
    report = buckets(ledger, "acme", ON)
    assert report == {**only("current", "-50.00"), "1-30": D("0.00")}


def test_leftover_credit_is_negative_current_after_every_bucket_is_cleared():
    ledger = credit_ledger("250.00", invoice("A", **OLD), invoice("B", **NEW))
    assert buckets(ledger, "acme", ON) == only("current", "-50.00")


def test_credit_never_reduces_disputed():
    ledger = credit_ledger("30.00", invoice("A", **MID))
    ledger.dispute("A")
    report = buckets(ledger, "acme", ON)
    assert report == {**only("disputed", "100.00"), "current": D("-30.00")}


def test_credit_skips_disputed_and_still_reduces_the_other_buckets():
    ledger = credit_ledger("130.00", invoice("A", **OLD), invoice("B", **MID))
    ledger.dispute("A")
    assert buckets(ledger, "acme", ON) == {**only("disputed", "100.00"), "current": D("-30.00")}


@pytest.mark.xfail(strict=True, reason="credit is taken off the newest bucket first")
def test_credit_reduces_the_oldest_bucket_first():
    ledger = credit_ledger("150.00", invoice("A", **OLD), invoice("B", **MID), invoice("C", **NEW))
    report = buckets(ledger, "acme", ON)
    assert report["91+"] == D("0.00")
    assert report["1-30"] == D("50.00")
    assert report["current"] == D("100.00")


@pytest.mark.xfail(strict=True, reason="credit is taken off the newest bucket first")
def test_credit_goes_on_to_the_next_oldest_bucket_only_when_one_is_used_up():
    ledger = credit_ledger("40.00", invoice("A", **OLD), invoice("C", **NEW))
    report = buckets(ledger, "acme", ON)
    assert report["91+"] == D("60.00")
    assert report["current"] == D("100.00")


def test_aging_does_not_change_the_ledger():
    ledger = credit_ledger("40.00", invoice("A", **OLD))
    before = (len(ledger.events), ledger.credit("acme"), ledger.invoices["A"].balance)
    aging(ledger, "acme", ON)
    aging(ledger, "acme", ON)
    assert (len(ledger.events), ledger.credit("acme"), ledger.invoices["A"].balance) == before


# R7 statements ------------------------------------------------------------

def busy_day_ledger():
    """Every kind of event on 2026-02-20, logged in an order that is not the statement order."""
    day = date(2026, 2, 20)
    ledger = ledger_with(
        invoice("INV-1", day=JAN5, price="1000.00"),                          # due Feb 4
        invoice("INV-D", day=date(2026, 2, 16), terms="2/10 NET 30", price="500.00"),
    )
    ledger.assess_late_fees(day)                                              # fee 15.00
    ledger.add(invoice("INV-3", day=day, price="100.00"))
    ledger.issue("INV-3")                                                     # +100
    ledger.void("INV-3", day)                                                 # -100
    ledger.receive("P1", "acme", "1505.00", day)                              # -1505, discount -10
    ledger.reverse("P1", day)                                                 # +1515
    return ledger, day


def test_same_day_events_are_ordered_invoice_fee_payment_discount_reversal_void():
    ledger, day = busy_day_ledger()
    result = statement(ledger, "acme", day, day)
    assert [(l.kind, l.ref) for l in result.lines] == [
        ("invoice", "INV-3"), ("fee", "INV-1"), ("payment", "P1"),
        ("discount", "INV-D"), ("reversal", "P1"), ("void", "INV-3"),
    ]
    assert [l.amount for l in result.lines] == [
        D("100.00"), D("15.00"), D("-1505.00"), D("-10.00"), D("1515.00"), D("-100.00"),
    ]
    assert [l.balance for l in result.lines] == [
        D("1600.00"), D("1615.00"), D("110.00"), D("100.00"), D("1615.00"), D("1515.00"),
    ]
    assert {l.date for l in result.lines} == {day}
    assert result.opening == D("1500.00")
    assert result.closing == D("1515.00")
    assert result.customer == "acme"


def test_period_includes_both_its_first_and_last_day():
    ledger = ledger_with(invoice("A", day=date(2026, 1, 5), price="10.00"),
                         invoice("B", day=date(2026, 1, 6), price="20.00"),
                         invoice("C", day=date(2026, 1, 7), price="40.00"),
                         invoice("D", day=date(2026, 1, 8), price="80.00"))
    result = statement(ledger, "acme", date(2026, 1, 6), date(2026, 1, 7))
    assert [l.ref for l in result.lines] == ["B", "C"]
    assert result.opening == D("10.00")
    assert [l.balance for l in result.lines] == [D("30.00"), D("70.00")]
    assert result.closing == D("70.00")


def test_opening_is_everything_before_the_first_day():
    ledger = ledger_with(invoice("A", day=date(2026, 1, 5), price="10.00"),
                         invoice("B", day=date(2026, 1, 6), price="20.00"))
    result = statement(ledger, "acme", date(2026, 1, 6), date(2026, 1, 6))
    assert result.opening == D("10.00")
    result = statement(ledger, "acme", date(2026, 1, 7), date(2026, 1, 9))
    assert result.opening == D("30.00")


def test_no_lines_means_closing_equals_opening():
    ledger = ledger_with(invoice("A", day=date(2026, 1, 5), price="10.00"))
    result = statement(ledger, "acme", date(2026, 2, 1), date(2026, 2, 28))
    assert result.lines == []
    assert result.opening == result.closing == D("10.00")


def test_empty_ledger_statement_is_zero():
    result = statement(Ledger(), "acme", date(2026, 1, 1), date(2026, 12, 31))
    assert result.lines == []
    assert result.opening == result.closing == 0


def test_lines_are_in_date_order_whatever_the_order_they_were_logged():
    ledger = ledger_with(invoice("LATE", day=date(2026, 3, 1), price="30.00"),
                         invoice("EARLY", day=date(2026, 1, 5), price="10.00"),
                         invoice("MID", day=date(2026, 2, 1), price="20.00"))
    ledger.receive("P1", "acme", "5.00", date(2026, 1, 20))
    result = statement(ledger, "acme", date(2026, 1, 1), date(2026, 12, 31))
    assert [(l.date, l.ref) for l in result.lines] == [
        (date(2026, 1, 5), "EARLY"), (date(2026, 1, 20), "P1"),
        (date(2026, 2, 1), "MID"), (date(2026, 3, 1), "LATE"),
    ]
    assert [l.balance for l in result.lines] == [D("10.00"), D("5.00"), D("25.00"), D("55.00")]
    assert result.closing == D("55.00")


def test_events_on_one_day_of_the_same_kind_keep_their_order():
    ledger = ledger_with(invoice("B", price="20.00"), invoice("A", price="10.00"))
    result = statement(ledger, "acme", JAN5, JAN5)
    assert [l.ref for l in result.lines] == ["B", "A"]


def test_only_the_named_customers_activity_appears():
    ledger = ledger_with(invoice("A", price="10.00"), invoice("B", customer="other", price="99.00"))
    ledger.receive("P1", "other", "50.00", JAN5)
    ledger.receive("P2", "acme", "4.00", JAN5)
    mine = statement(ledger, "acme", JAN5, JAN5)
    assert [l.ref for l in mine.lines] == ["A", "P2"]
    assert mine.closing == D("6.00")
    theirs = statement(ledger, "other", JAN5, JAN5)
    assert [l.ref for l in theirs.lines] == ["B", "P1"]
    assert theirs.closing == D("49.00")


def test_a_customer_with_no_activity_gets_an_empty_statement():
    ledger = ledger_with(invoice("A"))
    result = statement(ledger, "ghost", JAN5, late(100))
    assert result.lines == [] and result.opening == result.closing == 0


def test_signs_of_each_kind_and_the_closing_balance_of_a_whole_history():
    ledger, day = busy_day_ledger()
    result = statement(ledger, "acme", date(2026, 1, 1), date(2026, 12, 31))
    signs = {l.kind: (l.amount > 0) for l in result.lines}
    assert signs == {"invoice": True, "fee": True, "reversal": True,
                     "payment": False, "discount": False, "void": False}
    assert result.opening == 0
    assert result.closing == sum(e.amount for e in ledger.events if e.customer == "acme")
    assert result.closing == D("1515.00")


def test_balance_goes_negative_when_a_customer_has_credit():
    ledger = ledger_with(invoice("A", price="10.00"))
    ledger.receive("P1", "acme", "25.00", JAN5)
    result = statement(ledger, "acme", JAN5, JAN5)
    assert result.closing == D("-15.00")
    assert events(ledger, "payment")[0].amount == D("-25.00")


def test_apply_credit_leaves_no_line_on_the_statement():
    ledger = Ledger()
    ledger.receive("P1", "acme", "100.00", date(2026, 1, 2))
    ledger.add(invoice("A"))
    ledger.issue("A")
    ledger.apply_credit("acme", date(2026, 1, 6))
    result = statement(ledger, "acme", date(2026, 1, 1), date(2026, 1, 31))
    assert [l.kind for l in result.lines] == ["payment", "invoice"]
    assert result.closing == D("0.00")
