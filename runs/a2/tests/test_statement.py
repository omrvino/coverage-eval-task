from datetime import date
from decimal import Decimal as D

from tally import Invoice, Ledger, Line, statement


def add_issued(ledger, number, customer, day, price, terms="NET 30"):
    ledger.add(Invoice(number, customer, day, terms, [Line("work", 1, price)]))
    ledger.issue(number)


# R7.1
def test_period_includes_first_and_last_day_and_opening_is_everything_before():
    ledger = Ledger()
    add_issued(ledger, "A", "acme", date(2026, 1, 2), "100")  # before the period
    add_issued(ledger, "B", "acme", date(2026, 1, 5), "10")  # first day
    add_issued(ledger, "C", "acme", date(2026, 1, 20), "20")  # last day
    add_issued(ledger, "D", "acme", date(2026, 1, 21), "40")  # after
    st = statement(ledger, "acme", date(2026, 1, 5), date(2026, 1, 20))
    assert st.opening == D("100.00")
    assert [line.ref for line in st.lines] == ["B", "C"]
    assert st.closing == D("130.00")


# R7.2 and R7.4
def test_same_day_order_is_invoices_fees_payments_discounts_reversals_voids():
    x = date(2026, 3, 2)
    ledger = Ledger()
    # R1 and V1 are opened first so the Feb 20 payment goes to R1 alone.
    add_issued(ledger, "R1", "acme", date(2026, 2, 10), "40")  # due Mar 12
    add_issued(ledger, "V1", "acme", date(2026, 2, 25), "50")  # due Mar 27
    add_issued(ledger, "C", "acme", date(2026, 3, 1), "100", terms="2/10 NET 30")  # deadline Mar 11
    ledger.receive("P0", "acme", "40", date(2026, 2, 20))
    ledger.void("V1", x)  # void event, inserted first
    ledger.reverse("P0", x)  # reversal event
    add_issued(ledger, "A1", "acme", date(2026, 1, 21), "1000")  # due Feb 20
    ledger.assess_late_fees(x)  # fee event: 10 days late
    ledger.receive("P1", "acme", "1153", x)  # payment and discount events
    add_issued(ledger, "D", "acme", x, "25")  # invoice event, inserted last

    add_issued(ledger, "OTHER", "other", x, "999")  # another customer's activity

    st = statement(ledger, "acme", x, x)
    assert [line.kind for line in st.lines] == [
        "invoice", "fee", "payment", "discount", "reversal", "void",
    ]
    assert [line.amount for line in st.lines] == [D("25"), D("15"), D("-1153"), D("-2"), D("40"), D("-50")]
    assert st.closing == D("25.00")
    assert st.closing == st.opening + sum((line.amount for line in st.lines), D("0"))


# R7.3
def test_running_balance_on_each_line_and_closing_is_the_last_one():
    ledger = Ledger()
    add_issued(ledger, "INV-1", "acme", date(2026, 1, 5), "100")
    ledger.receive("P1", "acme", "30", date(2026, 1, 10))
    st = statement(ledger, "acme", date(2026, 1, 1), date(2026, 1, 31))
    assert [line.balance for line in st.lines] == [D("100.00"), D("70.00")]
    assert st.closing == D("70.00")


def test_closing_equals_opening_when_nothing_happens_in_the_period():
    ledger = Ledger()
    add_issued(ledger, "INV-1", "acme", date(2026, 1, 2), "100")
    st = statement(ledger, "acme", date(2026, 2, 1), date(2026, 2, 28))
    assert st.lines == []
    assert st.opening == D("100.00")
    assert st.closing == D("100.00")


# R7.4
def test_amounts_are_signed_by_kind_and_only_the_customer_appears():
    ledger = Ledger()
    add_issued(ledger, "INV-1", "acme", date(2026, 1, 5), "100", terms="2/10 NET 30")
    add_issued(ledger, "INV-2", "acme", date(2026, 1, 5), "1000")
    add_issued(ledger, "INV-3", "acme", date(2026, 1, 6), "50")
    add_issued(ledger, "OTHER", "other", date(2026, 1, 5), "500")
    ledger.receive("P1", "acme", "98", date(2026, 1, 8))  # INV-1 with a 2.00 discount
    ledger.void("INV-3", date(2026, 1, 20))
    ledger.receive("P2", "acme", "40", date(2026, 1, 25))  # goes to INV-2
    ledger.reverse("P2", date(2026, 1, 26))
    ledger.assess_late_fees(date(2026, 2, 10))  # INV-2 six days late

    st = statement(ledger, "acme", date(2026, 1, 1), date(2026, 2, 28))
    assert [(line.kind, line.amount) for line in st.lines] == [
        ("invoice", D("100.00")),
        ("invoice", D("1000.00")),
        ("invoice", D("50.00")),
        ("payment", D("-98.00")),
        ("discount", D("-2.00")),
        ("void", D("-50.00")),
        ("payment", D("-40.00")),
        ("reversal", D("40.00")),
        ("fee", D("15.00")),
    ]
    assert st.closing == D("1015.00")
    assert all(line.ref != "OTHER" for line in st.lines)
