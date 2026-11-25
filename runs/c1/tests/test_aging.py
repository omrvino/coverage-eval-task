"""SPEC section 6: aging."""

from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from helpers import invoice, issue, ledger_with, owing_only_a_late_fee
from tally import Ledger, aging

DUE = date(2026, 2, 4)  # NET 30 from 5 January
JULY_1 = date(2026, 7, 1)


def late(days):
    return DUE + timedelta(days=days)


def buckets(**amounts):
    """A full report, zero where not given. Keys: current, b1, b31, b61, b91, disputed."""
    names = {"b1": "1-30", "b31": "31-60", "b61": "61-90", "b91": "91+"}
    report = dict.fromkeys(["current", *names.values(), "disputed"], D("0.00"))
    report.update({names.get(key, key): D(value) for key, value in amounts.items()})
    return report


# -- buckets ------------------------------------------------------------------


@pytest.mark.parametrize(
    "days, bucket",
    [
        (-30, "current"), (-1, "current"), (0, "current"),
        (1, "b1"), (30, "b1"),
        (31, "b31"), (60, "b31"),
        (61, "b61"), (90, "b61"),
        (91, "b91"), (400, "b91"),
    ],
)
def test_open_invoice_goes_by_days_past_due(days, bucket):
    ledger = ledger_with(invoice())
    assert aging(ledger, "acme", late(days)) == buckets(**{bucket: "100.00"})


def spread(credit=None):
    """One invoice in each bucket when aged on 1 July 2026, with credit received before them."""
    ledger = Ledger()
    if credit:
        ledger.receive("P1", "acme", credit, date(2026, 1, 2))
    for number, day, price in [
        ("INV-1", date(2026, 2, 2), "10.00"),  # due 4 March, 119 days late
        ("INV-2", date(2026, 3, 18), "20.00"),  # due 17 April, 75
        ("INV-3", date(2026, 4, 15), "30.00"),  # due 15 May, 47
        ("INV-4", date(2026, 5, 18), "40.00"),  # due 17 June, 14
        ("INV-5", date(2026, 6, 15), "50.00"),  # due 15 July, not late
    ]:
        issue(ledger, number, price, day=day)
    return ledger


def test_report_adds_up_every_bucket():
    ledger = spread()
    assert aging(ledger, "acme", JULY_1) == buckets(
        current="50", b1="40", b31="30", b61="20", b91="10"
    )
    issue(ledger, "INV-6", "5.00", day=date(2026, 5, 18))
    assert aging(ledger, "acme", JULY_1)["1-30"] == D("45.00")


def test_balance_is_what_is_still_owed_with_late_fees():
    ledger = ledger_with(invoice(price="1000.00"))
    ledger.assess_late_fees(late(10))
    assert aging(ledger, "acme", late(10)) == buckets(b1="1015.00")
    ledger.receive("P1", "acme", "615.00", late(10))
    assert aging(ledger, "acme", late(10)) == buckets(b1="400.00")


def test_invoice_owing_only_late_fees_is_listed():
    assert aging(owing_only_a_late_fee(), "acme", late(40)) == buckets(b31="15.00")


def test_only_the_named_customer():
    ledger = ledger_with(invoice("INV-1"), invoice("INV-2", "7.00", customer="other"))
    ledger.receive("P1", "third", "30.00", DUE)
    assert aging(ledger, "acme", late(1)) == buckets(b1="100.00")
    assert aging(ledger, "other", late(1)) == buckets(b1="7.00")
    assert aging(ledger, "nobody", late(1)) == buckets()


def test_disputed_invoices_go_in_disputed_and_nowhere_else():
    ledger = ledger_with(invoice("INV-1"), invoice("INV-2", "7.00"))
    ledger.dispute("INV-1")
    assert aging(ledger, "acme", late(40)) == buckets(b31="7.00", disputed="100.00")
    ledger.resolve("INV-1")
    assert aging(ledger, "acme", late(40)) == buckets(b31="107.00")


def test_draft_void_and_paid_invoices_are_left_out():
    ledger = ledger_with(invoice("INV-1"), invoice("INV-2"))
    ledger.add(invoice("INV-3"))
    ledger.void("INV-1", DUE)
    ledger.receive("P1", "acme", "100.00", DUE)
    assert aging(ledger, "acme", late(40)) == buckets()


def test_void_disputed_invoice_is_left_out():
    ledger = ledger_with(invoice())
    ledger.dispute("INV-1")
    ledger.void("INV-1", DUE)
    assert aging(ledger, "acme", late(40)) == buckets()


# -- credit -------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="R6.3: credit reduces the newest bucket first instead of the oldest")
@pytest.mark.parametrize(
    "credit, expected",
    [
        ("4.00", buckets(current="50", b1="40", b31="30", b61="20", b91="6")),
        ("15.00", buckets(current="50", b1="40", b31="30", b61="15")),
        ("45.00", buckets(current="50", b1="40", b31="15")),
        ("75.00", buckets(current="50", b1="25")),
        ("120.00", buckets(current="30")),
    ],
    ids=["4.00", "15.00", "45.00", "75.00", "120.00"],
)
def test_credit_reduces_the_oldest_bucket_first(credit, expected):
    assert aging(spread(credit), "acme", JULY_1) == expected


@pytest.mark.parametrize("credit", ["4.00", "75.00", "149.99"])
def test_credit_never_takes_a_bucket_below_zero(credit):
    report = aging(spread(credit), "acme", JULY_1)
    assert min(report.values()) >= 0
    assert sum(report.values()) == D("150.00") - D(credit)


def test_credit_for_everything_leaves_nothing():
    assert aging(spread("150.00"), "acme", JULY_1) == buckets()


@pytest.mark.parametrize(
    "days, bucket", [(0, "current"), (10, "b1"), (40, "b31"), (70, "b61"), (100, "b91")]
)
def test_credit_reduces_the_only_bucket_with_a_balance(days, bucket):
    ledger = Ledger()
    ledger.receive("P1", "acme", "30.00", date(2026, 1, 2))
    issue(ledger)
    assert aging(ledger, "acme", late(days)) == buckets(**{bucket: "70.00"})


def test_credit_left_over_is_negative_in_current():
    assert aging(spread("162.50"), "acme", JULY_1) == buckets(current="-12.50")


def test_credit_alone_is_negative_in_current():
    ledger = Ledger()
    ledger.receive("P1", "acme", "30.00", DUE)
    assert aging(ledger, "acme", DUE) == buckets(current="-30.00")


def test_credit_left_over_from_an_old_bucket():
    ledger = Ledger()
    ledger.receive("P1", "acme", "130.00", date(2026, 1, 2))
    issue(ledger)
    assert aging(ledger, "acme", late(100)) == buckets(current="-30.00")


def test_credit_never_reduces_disputed():
    ledger = Ledger()
    ledger.receive("P1", "acme", "130.00", date(2026, 1, 2))
    issue(ledger)
    ledger.dispute("INV-1")
    assert aging(ledger, "acme", late(40)) == buckets(current="-130.00", disputed="100.00")


def test_reporting_does_not_use_up_credit():
    ledger = spread("20.00")
    first = aging(ledger, "acme", JULY_1)
    assert aging(ledger, "acme", JULY_1) == first
    assert ledger.credit("acme") == D("20.00")
