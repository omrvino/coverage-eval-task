from datetime import date, timedelta
from decimal import Decimal

import pytest

from tally import Event, Ledger, aging, statement

from helpers import D0, issued, make_invoice

D = Decimal
ZERO = D("0.00")
BUCKETS = ["current", "1-30", "31-60", "61-90", "91+"]


def late(days):
    return D0 + timedelta(days=days)


def only(report, name, amount):
    """The report has ``amount`` in bucket ``name`` and zero everywhere else."""
    expected = {key: ZERO for key in [*BUCKETS, "disputed"]}
    expected[name] = D(amount)
    assert {key: report[key] for key in expected} == expected


# -- R6.1 ------------------------------------------------------------------

@pytest.mark.parametrize("days, bucket", [
    (-40, "current"), (-1, "current"), (0, "current"),
    (1, "1-30"), (30, "1-30"),
    (31, "31-60"), (60, "31-60"),
    (61, "61-90"), (90, "61-90"),
    (91, "91+"), (500, "91+"),
])
def test_open_invoice_goes_in_the_bucket_for_its_days_past_due(days, bucket):
    ledger = issued(make_invoice())
    only(aging(ledger, "acme", late(days)), bucket, "100.00")


def test_report_has_every_bucket_even_when_empty():
    report = aging(Ledger(), "acme", D0)
    assert set(report) >= {*BUCKETS, "disputed"}
    only(report, "current", "0.00")


def test_balance_includes_late_fees_and_partial_payments():
    ledger = issued(make_invoice(price="1000.00"))
    ledger.assess_late_fees(late(16))
    only(aging(ledger, "acme", late(16)), "1-30", "1015.00")
    ledger.receive("P1", "acme", "215.00", late(16))
    only(aging(ledger, "acme", late(16)), "1-30", "800.00")


def test_balance_includes_tax():
    ledger = issued(make_invoice(price="100.00", tax_rate=10))
    only(aging(ledger, "acme", late(5)), "1-30", "110.00")


def test_invoices_are_added_up_per_bucket():
    ledger = issued(
        make_invoice("A", due=D0),
        make_invoice("B", due=D0 + timedelta(days=1), price="50.00"),
        make_invoice("C", due=D0 - timedelta(days=35 * 2 - 7), price="25.00"),   # 63 days late on D0
    )
    report = aging(ledger, "acme", late(5))
    assert report["1-30"] == D("150.00")
    assert report["61-90"] == D("25.00")
    assert report["current"] == ZERO


def test_aging_is_per_customer():
    ledger = issued(make_invoice("A"), make_invoice("B", customer="other", price="70.00"))
    only(aging(ledger, "other", late(3)), "1-30", "70.00")
    only(aging(ledger, "acme", late(3)), "1-30", "100.00")
    only(aging(ledger, "nobody", late(3)), "current", "0.00")


# -- R6.2 ------------------------------------------------------------------

def test_disputed_invoices_go_only_in_disputed():
    ledger = issued(make_invoice())
    ledger.dispute("INV-1")
    for days in (-10, 5, 45, 200):
        only(aging(ledger, "acme", late(days)), "disputed", "100.00")


def test_disputed_balance_includes_fees_charged_before_the_dispute():
    ledger = issued(make_invoice(price="1000.00"))
    ledger.assess_late_fees(late(10))
    ledger.dispute("INV-1")
    only(aging(ledger, "acme", late(10)), "disputed", "1015.00")


def test_resolved_invoice_returns_to_its_bucket():
    ledger = issued(make_invoice())
    ledger.dispute("INV-1")
    ledger.resolve("INV-1")
    only(aging(ledger, "acme", late(5)), "1-30", "100.00")


def test_drafts_void_and_paid_invoices_are_left_out():
    draft = make_invoice("DRAFT")
    void = make_invoice("VOID")
    paid = make_invoice("PAID", due=D0 - timedelta(days=7))
    ledger = issued(void, paid)
    ledger.add(draft)
    ledger.void("VOID", D0)
    ledger.receive("P1", "acme", "100.00", D0 - timedelta(days=10))
    only(aging(ledger, "acme", late(50)), "current", "0.00")


# -- R6.3 ------------------------------------------------------------------

def ledger_with_credit(credit, *invoices):
    """Credit comes first, so the invoices issued afterwards do not absorb it."""
    ledger = Ledger()
    ledger.receive("PC", "acme", credit, D0 - timedelta(days=100))
    for invoice in invoices:
        ledger.add(invoice)
        ledger.issue(invoice.number)
    return ledger


def test_credit_reduces_a_bucket_but_not_below_zero():
    ledger = ledger_with_credit("30.00", make_invoice())
    only(aging(ledger, "acme", late(5)), "1-30", "70.00")


def test_credit_equal_to_the_balance_empties_the_bucket():
    ledger = ledger_with_credit("100.00", make_invoice())
    only(aging(ledger, "acme", late(5)), "current", "0.00")


@pytest.mark.xfail(strict=True, reason="credit is taken from the newest bucket first, not the oldest")
def test_credit_reduces_the_oldest_bucket_first():
    ledger = ledger_with_credit(
        "150.00",
        make_invoice("A", due=D0),
        make_invoice("B", due=D0 - timedelta(days=84)),    # 91 days late on D0 + 7
    )
    report = aging(ledger, "acme", late(7))
    assert report["91+"] == ZERO
    assert report["1-30"] == D("50.00")


@pytest.mark.xfail(strict=True, reason="credit is taken from the newest bucket first, not the oldest")
def test_credit_works_down_from_the_oldest_bucket_through_the_buckets():
    ledger = ledger_with_credit(
        "130.00",
        make_invoice("A", due=D0 - timedelta(days=84)),    # 91+ on late(7)
        make_invoice("B", due=D0 - timedelta(days=56)),    # 61-90
        make_invoice("C", due=D0 - timedelta(days=28)),    # 31-60
        make_invoice("E", due=D0),                         # 1-30
    )
    report = aging(ledger, "acme", late(7))
    assert [report[name] for name in ("91+", "61-90", "31-60", "1-30")] == [
        ZERO, D("70.00"), D("100.00"), D("100.00")]


def test_credit_larger_than_everything_shows_negative_in_current():
    ledger = ledger_with_credit("250.00", make_invoice("A"), make_invoice("B", due=D0 - timedelta(days=21)))
    report = aging(ledger, "acme", late(5))
    assert [report[name] for name in BUCKETS] == [D("-50.00"), ZERO, ZERO, ZERO, ZERO]
    assert report["disputed"] == ZERO


def test_credit_with_no_invoices_is_negative_current():
    ledger = Ledger()
    ledger.receive("P1", "acme", "42.50", D0)
    only(aging(ledger, "acme", D0), "current", "-42.50")


def test_credit_never_reduces_disputed():
    ledger = ledger_with_credit("80.00", make_invoice("A"), make_invoice("B", due=D0 - timedelta(days=7)))
    ledger.dispute("B")
    report = aging(ledger, "acme", late(5))
    assert report["disputed"] == D("100.00")
    assert report["1-30"] == D("20.00")
    assert all(report[name] == ZERO for name in ("current", "31-60", "61-90", "91+"))


def test_credit_beyond_the_open_invoices_with_a_dispute_goes_negative_in_current():
    ledger = ledger_with_credit("150.00", make_invoice("B"))
    ledger.dispute("B")
    report = aging(ledger, "acme", late(5))
    assert report["disputed"] == D("100.00")
    assert report["current"] == D("-150.00")


def test_credit_of_another_customer_is_not_used():
    ledger = Ledger()
    ledger.receive("P1", "other", "500.00", D0)
    ledger.add(make_invoice())
    ledger.issue("INV-1")
    only(aging(ledger, "acme", late(5)), "1-30", "100.00")


# -- statements ------------------------------------------------------------

FEB2, FEB12, MAR20 = date(2026, 2, 2), date(2026, 2, 12), date(2026, 3, 20)


def busy_ledger():
    """acme: two invoices on Feb 2, a discounted payment on Feb 12, a fee on Mar 20."""
    ledger = issued(
        make_invoice("INV-1", terms="2/10 NET 30", price="100.00"),
        make_invoice("INV-2", price="1000.00"),
        make_invoice("INV-3", customer="other", price="77.00"),
    )
    ledger.receive("P1", "acme", "98.00", FEB12)
    ledger.receive("P2", "other", "7.00", FEB12)
    ledger.assess_late_fees(MAR20)
    return ledger


def rows(result):
    return [(line.date, line.kind, line.ref, line.amount, line.balance) for line in result.lines]


# -- R7.1 ------------------------------------------------------------------

def test_period_includes_first_and_last_day_and_opening_is_everything_before():
    result = statement(busy_ledger(), "acme", FEB12, MAR20)
    assert result.customer == "acme"
    assert result.opening == D("1100.00")
    assert rows(result) == [
        (FEB12, "payment", "P1", D("-98.00"), D("1002.00")),
        (FEB12, "discount", "INV-1", D("-2.00"), D("1000.00")),
        (MAR20, "fee", "INV-2", D("15.00"), D("1015.00")),
    ]
    assert result.closing == D("1015.00")


def test_period_ends_before_the_last_event():
    result = statement(busy_ledger(), "acme", FEB2, MAR20 - timedelta(days=1))
    assert result.opening == ZERO
    assert [line.kind for line in result.lines] == ["invoice", "invoice", "payment", "discount"]
    assert result.closing == D("1000.00")


def test_period_starting_after_the_first_day_leaves_those_events_in_the_opening():
    result = statement(busy_ledger(), "acme", FEB2 + timedelta(days=1), FEB12 - timedelta(days=1))
    assert result.lines == []
    assert result.opening == D("1100.00")


def test_single_day_period():
    result = statement(busy_ledger(), "acme", FEB2, FEB2)
    assert [(line.ref, line.balance) for line in result.lines] == [
        ("INV-1", D("100.00")), ("INV-2", D("1100.00"))]


# -- R7.2 ------------------------------------------------------------------

def test_lines_are_in_date_order():
    ledger = Ledger()
    ledger.events += [
        Event(date(2026, 5, 3), "acme", "payment", "P2", D("-1.00")),
        Event(date(2026, 5, 1), "acme", "invoice", "A", D("10.00")),
        Event(date(2026, 5, 2), "acme", "fee", "A", D("2.00")),
    ]
    result = statement(ledger, "acme", date(2026, 5, 1), date(2026, 5, 31))
    assert [line.date.day for line in result.lines] == [1, 2, 3]
    assert [line.balance for line in result.lines] == [D("10.00"), D("12.00"), D("11.00")]


def test_same_day_order_is_invoices_fees_payments_discounts_reversals_voids():
    day = date(2026, 5, 1)
    scrambled = [("void", "-5.00"), ("discount", "-2.00"), ("invoice", "100.00"),
                 ("reversal", "30.00"), ("payment", "-30.00"), ("fee", "5.00")]
    ledger = Ledger()
    ledger.events += [Event(day, "acme", kind, kind.upper(), D(amount)) for kind, amount in scrambled]
    result = statement(ledger, "acme", day, day)
    assert [line.kind for line in result.lines] == [
        "invoice", "fee", "payment", "discount", "reversal", "void"]
    assert [line.balance for line in result.lines] == [
        D("100.00"), D("105.00"), D("75.00"), D("73.00"), D("103.00"), D("98.00")]


def test_events_of_the_same_kind_on_one_day_keep_their_order():
    day = date(2026, 5, 1)
    ledger = Ledger()
    ledger.events += [Event(day, "acme", "invoice", ref, D("1.00")) for ref in ("A", "B", "C")]
    assert [line.ref for line in statement(ledger, "acme", day, day).lines] == ["A", "B", "C"]


# -- R7.3 ------------------------------------------------------------------

def test_closing_is_the_opening_when_there_are_no_lines():
    result = statement(busy_ledger(), "acme", date(2026, 6, 1), date(2026, 6, 30))
    assert result.lines == []
    assert result.opening == D("1015.00")
    assert result.closing == D("1015.00")


def test_empty_ledger_statement():
    result = statement(Ledger(), "acme", D0, D0)
    assert (result.opening, result.closing, result.lines) == (ZERO, ZERO, [])


# -- R7.4 ------------------------------------------------------------------

def test_signs_for_reversals_and_voids():
    ledger = issued(make_invoice("A", price="100.00"), make_invoice("B", price="100.00"))
    ledger.receive("P1", "acme", "100.00", date(2026, 2, 10))
    ledger.reverse("P1", date(2026, 2, 11))
    ledger.void("B", date(2026, 2, 12))
    result = statement(ledger, "acme", FEB2, date(2026, 2, 28))
    assert rows(result) == [
        (FEB2, "invoice", "A", D("100.00"), D("100.00")),
        (FEB2, "invoice", "B", D("100.00"), D("200.00")),
        (date(2026, 2, 10), "payment", "P1", D("-100.00"), D("100.00")),
        (date(2026, 2, 11), "reversal", "P1", D("100.00"), D("200.00")),
        (date(2026, 2, 12), "void", "B", D("-100.00"), D("100.00")),
    ]
    assert result.closing == D("100.00")


def test_only_the_named_customers_activity_appears():
    ledger = busy_ledger()
    other = statement(ledger, "other", FEB2, MAR20)
    assert [(line.kind, line.ref, line.amount) for line in other.lines] == [
        ("invoice", "INV-3", D("77.00")), ("payment", "P2", D("-7.00")), ("fee", "INV-3", D("5.00"))]
    assert other.closing == D("75.00")
    assert statement(ledger, "nobody", FEB2, MAR20).lines == []


def test_closing_balance_matches_what_the_invoices_still_owe():
    ledger = busy_ledger()
    result = statement(ledger, "acme", FEB2, MAR20)
    assert result.closing == sum(
        (inv.balance for inv in ledger.invoices.values() if inv.customer == "acme"), ZERO)
