from datetime import date, timedelta
from decimal import Decimal

import pytest

from tally import Invoice, Ledger, Line, aging, statement

D = Decimal
DISCOUNT = "2/10 NET 30"
BUCKETS = ["current", "1-30", "31-60", "61-90", "91+", "disputed"]
XFAIL_CREDIT_ORDER = pytest.mark.xfail(
    strict=True,
    reason="R6.3: credit reduces the current bucket first; the spec says the oldest bucket (91+) first",
)


def add_invoice(ledger, number, day=date(2026, 1, 5), terms="NET 30", price="100.00", customer="acme"):
    ledger.add(Invoice(number, customer, day, terms, [Line("work", 1, price)]))
    ledger.issue(number)
    return ledger.invoices[number]


def only(bucket, amount="100.00"):
    return {name: (D(amount) if name == bucket else D("0.00")) for name in BUCKETS}


@pytest.mark.parametrize(
    "days, bucket",
    [
        (-3, "current"),
        (0, "current"),
        (1, "1-30"),
        (30, "1-30"),
        (31, "31-60"),
        (60, "31-60"),
        (61, "61-90"),
        (90, "61-90"),
        (91, "91+"),
        (400, "91+"),
    ],
)
def test_open_invoices_sort_by_days_past_due(days, bucket):
    ledger = Ledger()
    inv = add_invoice(ledger, "INV-1")
    assert aging(ledger, "acme", inv.due + timedelta(days=days)) == only(bucket)


def test_aging_balance_includes_late_fees():
    ledger = Ledger()
    inv = add_invoice(ledger, "INV-1")
    on = inv.due + timedelta(days=40)
    ledger.assess_late_fees(on)  # two periods at the 5.00 minimum
    assert aging(ledger, "acme", on)["31-60"] == D("110.00")


def test_drafts_void_and_paid_are_left_out_and_disputed_has_its_own_bucket():
    ledger = Ledger()
    add_invoice(ledger, "INV-P", day=date(2025, 12, 1))
    ledger.receive("P0", "acme", "100.00", date(2025, 12, 2))  # pays INV-P in full
    ledger.add(Invoice("INV-D", "acme", date(2026, 1, 5), "NET 30", [Line("work", 1, "100.00")]))
    add_invoice(ledger, "INV-V", day=date(2026, 1, 5))
    ledger.void("INV-V", date(2026, 1, 6))
    add_invoice(ledger, "INV-O")  # due Feb 4, open
    add_invoice(ledger, "INV-X")  # due Feb 4, disputed
    ledger.dispute("INV-X")

    report = aging(ledger, "acme", date(2026, 2, 14))

    assert report == {**only("1-30"), "disputed": D("100.00")}


@XFAIL_CREDIT_ORDER
def test_credit_reduces_the_oldest_bucket_first():
    ledger = Ledger()
    ledger.receive("P0", "acme", "40.00", date(2026, 1, 2))  # no open invoices yet, so it stays as credit
    add_invoice(ledger, "OLD", day=date(2026, 3, 2), terms="NET 0", price="30.00")  # 91+
    add_invoice(ledger, "MID", day=date(2026, 5, 29), terms="NET 0", price="50.00")  # 1-30
    add_invoice(ledger, "NOW", day=date(2026, 6, 15), terms="NET 0", price="100.00")  # current
    # 30 clears the 91+ bucket, 10 more comes off 1-30; current stays whole.
    assert aging(ledger, "acme", date(2026, 6, 10)) == {
        "current": D("100.00"),
        "1-30": D("40.00"),
        "31-60": D("0.00"),
        "61-90": D("0.00"),
        "91+": D("0.00"),
        "disputed": D("0.00"),
    }


def test_credit_left_over_after_all_overdue_buckets_shows_negative_in_current():
    ledger = Ledger()
    ledger.receive("P0", "acme", "250.00", date(2026, 1, 2))
    add_invoice(ledger, "OLD", day=date(2026, 3, 2), terms="NET 0", price="30.00")  # 91+
    add_invoice(ledger, "MID", day=date(2026, 5, 29), terms="NET 0", price="50.00")  # 1-30
    add_invoice(ledger, "NOW", day=date(2026, 6, 15), terms="NET 0", price="100.00")  # current
    # 250 clears 30 + 50 + 100 and leaves 70 over, shown as -70 in current.
    assert aging(ledger, "acme", date(2026, 6, 10)) == {
        "current": D("-70.00"),
        "1-30": D("0.00"),
        "31-60": D("0.00"),
        "61-90": D("0.00"),
        "91+": D("0.00"),
        "disputed": D("0.00"),
    }


def test_credit_never_reduces_disputed_invoices():
    ledger = Ledger()
    ledger.receive("P0", "acme", "50.00", date(2026, 1, 2))
    add_invoice(ledger, "DIS", day=date(2026, 3, 2), terms="NET 0", price="30.00")
    ledger.dispute("DIS")
    report = aging(ledger, "acme", date(2026, 6, 10))
    assert report["disputed"] == D("30.00")
    assert report["current"] == D("-50.00")


def test_statement_period_includes_its_first_and_last_day_only():
    ledger = Ledger()
    add_invoice(ledger, "INV-1", day=date(2026, 1, 5))  # 100.00 on Jan 5
    ledger.receive("P1", "acme", "10.00", date(2026, 1, 6))
    ledger.receive("P2", "acme", "20.00", date(2026, 1, 9))
    ledger.receive("P3", "acme", "30.00", date(2026, 1, 10))

    st = statement(ledger, "acme", date(2026, 1, 6), date(2026, 1, 9))

    assert st.opening == D("100.00")
    assert [(line.kind, line.ref) for line in st.lines] == [("payment", "P1"), ("payment", "P2")]
    assert [line.balance for line in st.lines] == [D("90.00"), D("70.00")]
    assert st.closing == D("70.00")


def test_statement_with_no_activity_closes_at_the_opening_balance():
    ledger = Ledger()
    add_invoice(ledger, "INV-1", day=date(2026, 1, 5))
    st = statement(ledger, "acme", date(2026, 2, 20), date(2026, 2, 25))
    assert st.lines == []
    assert st.opening == D("100.00")
    assert st.closing == D("100.00")


def test_statement_signs_and_only_the_named_customers_activity():
    ledger = Ledger()
    add_invoice(ledger, "A-1", day=date(2026, 1, 5), terms=DISCOUNT)
    add_invoice(ledger, "B-1", day=date(2026, 1, 5), price="50.00", customer="beta")
    ledger.receive("P1", "acme", "98.00", date(2026, 1, 15))  # on the discount deadline

    st = statement(ledger, "acme", date(2026, 1, 1), date(2026, 1, 31))

    assert [(line.kind, line.amount) for line in st.lines] == [
        ("invoice", D("100.00")),
        ("payment", D("-98.00")),
        ("discount", D("-2.00")),
    ]
    assert [line.balance for line in st.lines] == [D("100.00"), D("2.00"), D("0.00")]
    assert st.closing == 0


def test_same_day_lines_are_ordered_invoice_fee_payment_reversal_void():
    ledger = Ledger()
    add_invoice(ledger, "I2", day=date(2026, 1, 5))  # due Feb 4
    ledger.receive("P0", "acme", "10.00", date(2026, 1, 25))
    # Log the void before the payment, to show the statement sorts by kind rather than insertion order.
    ledger.add(Invoice("I3", "acme", date(2026, 2, 10), "NET 30", [Line("work", 1, "100.00")]))
    ledger.issue("I3")
    ledger.void("I3", date(2026, 2, 10))
    ledger.receive("P1", "acme", "50.00", date(2026, 2, 10))
    ledger.assess_late_fees(date(2026, 2, 10))  # 6 days late, 5.00 fee
    ledger.reverse("P0", date(2026, 2, 10))

    st = statement(ledger, "acme", date(2026, 2, 10), date(2026, 2, 10))

    assert [line.kind for line in st.lines] == ["invoice", "fee", "payment", "reversal", "void"]
    assert [line.amount for line in st.lines] == [D("100.00"), D("5.00"), D("-50.00"), D("10.00"), D("-100.00")]
    assert st.opening == D("90.00")
    assert [line.balance for line in st.lines] == [D("190.00"), D("195.00"), D("145.00"), D("155.00"), D("55.00")]
    assert st.closing == D("55.00")
