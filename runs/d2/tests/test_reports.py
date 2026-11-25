from datetime import date, timedelta
from decimal import Decimal

import pytest

from tally import Invoice, Ledger, Line, aging, statement

D = Decimal
ON = date(2026, 6, 1)


def open_invoice(ledger, number, due, customer="acme", price="100.00"):
    """Add and issue a NET 30 invoice whose due date is ``due``."""
    invoice = Invoice(number, customer, due - timedelta(days=30), "NET 30", [Line("work", 1, price)])
    ledger.add(invoice)
    ledger.issue(number)
    return invoice


def test_aging_puts_each_open_invoice_in_its_bucket():
    ledger = Ledger()
    open_invoice(ledger, "INV-1", ON + timedelta(days=5))     # not yet due
    open_invoice(ledger, "INV-2", ON - timedelta(days=15))    # 1-30
    open_invoice(ledger, "INV-3", ON - timedelta(days=45))    # 31-60
    open_invoice(ledger, "INV-4", ON - timedelta(days=75))    # 61-90
    open_invoice(ledger, "INV-5", ON - timedelta(days=120))   # 91+
    open_invoice(ledger, "INV-6", ON - timedelta(days=15))
    ledger.dispute("INV-6")
    open_invoice(ledger, "INV-7", ON - timedelta(days=15), customer="bolt")
    ledger.add(Invoice("INV-8", "acme", ON, "NET 30", [Line("work", 1, "100.00")]))  # draft

    assert aging(ledger, "acme", ON) == {
        "current": D("100.00"),
        "1-30": D("100.00"),
        "31-60": D("100.00"),
        "61-90": D("100.00"),
        "91+": D("100.00"),
        "disputed": D("100.00"),
    }


@pytest.mark.parametrize(
    "days_late, bucket",
    [(0, "current"), (1, "1-30"), (30, "1-30"), (31, "31-60"),
     (60, "31-60"), (61, "61-90"), (90, "61-90"), (91, "91+")],
)
def test_aging_bucket_edges(days_late, bucket):
    ledger = Ledger()
    invoice = open_invoice(ledger, "INV-1", ON)
    report = aging(ledger, "acme", invoice.due + timedelta(days=days_late))
    assert report[bucket] == D("100.00")
    assert sum(report.values()) == D("100.00")


def test_aging_credit_larger_than_balances_shows_as_negative_current():
    ledger = Ledger()
    open_invoice(ledger, "INV-0", ON - timedelta(days=40))
    ledger.receive("P0", "acme", "250.00", ON - timedelta(days=35))  # pays INV-0, leaves 150 credit
    open_invoice(ledger, "INV-1", ON - timedelta(days=15))           # 100 in 1-30
    report = aging(ledger, "acme", ON)
    assert report["1-30"] == D("0.00")
    assert report["current"] == D("-50.00")


def test_aging_credit_never_reduces_disputed_amounts():
    ledger = Ledger()
    open_invoice(ledger, "INV-0", ON - timedelta(days=40))
    ledger.receive("P0", "acme", "150.00", ON - timedelta(days=35))  # 50 credit
    open_invoice(ledger, "INV-1", ON - timedelta(days=15))
    ledger.dispute("INV-1")
    report = aging(ledger, "acme", ON)
    assert report["disputed"] == D("100.00")
    assert report["current"] == D("-50.00")


def test_aging_credit_partly_covers_a_bucket():
    ledger = Ledger()
    open_invoice(ledger, "INV-0", ON - timedelta(days=40))
    ledger.receive("P0", "acme", "130.00", ON - timedelta(days=35))  # 30 credit
    open_invoice(ledger, "INV-1", ON - timedelta(days=15))
    report = aging(ledger, "acme", ON)
    assert sum(report.values()) == D("70.00")
    assert all(amount >= 0 for amount in report.values())


def test_statement_shows_activity_and_running_balance():
    ledger = Ledger()
    ledger.add(Invoice("INV-1", "acme", date(2026, 1, 5), "NET 30", [Line("w", 1, "1000.00")]))
    ledger.issue("INV-1")
    ledger.assess_late_fees(date(2026, 2, 20))                # fee of 15.00
    ledger.receive("P1", "acme", "50.00", date(2026, 2, 20))  # same day as the fee
    ledger.receive("P2", "bolt", "5.00", date(2026, 2, 20))   # another customer
    result = statement(ledger, "acme", date(2026, 2, 1), date(2026, 2, 28))
    assert result.opening == D("1000.00")
    assert [(line.kind, line.amount, line.balance) for line in result.lines] == [
        ("fee", D("15.00"), D("1015.00")),
        ("payment", D("-50.00"), D("965.00")),
    ]
    assert result.closing == D("965.00")


def test_statement_period_includes_both_end_days_and_opens_before_start():
    ledger = Ledger()
    ledger.add(Invoice("INV-1", "acme", date(2026, 1, 5), "NET 30", [Line("w", 1, "100.00")]))
    ledger.issue("INV-1")
    ledger.receive("P1", "acme", "10.00", date(2026, 1, 20))
    ledger.receive("P2", "acme", "20.00", date(2026, 1, 31))
    result = statement(ledger, "acme", date(2026, 1, 20), date(2026, 1, 31))
    assert result.opening == D("100.00")
    assert [line.ref for line in result.lines] == ["P1", "P2"]
    assert result.closing == D("70.00")


def test_statement_with_no_activity_closes_at_opening_balance():
    ledger = Ledger()
    ledger.add(Invoice("INV-1", "acme", date(2026, 1, 5), "NET 30", [Line("w", 1, "100.00")]))
    ledger.issue("INV-1")
    result = statement(ledger, "acme", date(2026, 3, 1), date(2026, 3, 31))
    assert result.lines == []
    assert result.opening == D("100.00")
    assert result.closing == D("100.00")


def test_statement_lists_discounts_and_reversals_with_signs():
    ledger = Ledger()
    ledger.add(Invoice("INV-1", "bolt", date(2026, 2, 1), "2/10 NET 30", [Line("w", 1, "100.00")]))
    ledger.issue("INV-1")
    ledger.receive("B1", "bolt", "98.00", date(2026, 2, 5))
    ledger.reverse("B1", date(2026, 2, 6))
    result = statement(ledger, "bolt", date(2026, 2, 1), date(2026, 2, 28))
    assert [(line.kind, line.amount) for line in result.lines] == [
        ("invoice", D("100.00")),
        ("payment", D("-98.00")),
        ("discount", D("-2.00")),
        ("reversal", D("100.00")),
    ]


def test_statement_lists_voids_as_negative_amounts():
    ledger = Ledger()
    ledger.add(Invoice("INV-1", "acme", date(2026, 2, 1), "NET 30", [Line("w", 1, "100.00")]))
    ledger.issue("INV-1")
    ledger.void("INV-1", date(2026, 2, 3))
    result = statement(ledger, "acme", date(2026, 2, 1), date(2026, 2, 28))
    assert [(line.kind, line.amount) for line in result.lines] == [
        ("invoice", D("100.00")),
        ("void", D("-100.00")),
    ]
    assert result.closing == D("0.00")
