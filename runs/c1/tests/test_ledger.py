from datetime import date
from decimal import Decimal

import pytest

from tally import (
    Invoice,
    Ledger,
    Line,
    PaymentError,
    aging,
    parse_deposits,
    parse_terms,
    statement,
)


def make_invoice(number="INV-1", terms="NET 30", price="100.00", day=date(2026, 1, 5)):
    return Invoice(number, "acme", day, terms, [Line("work", 1, price)])


def issued(*invoices):
    ledger = Ledger()
    for invoice in invoices:
        ledger.add(invoice)
        ledger.issue(invoice.number)
    return ledger


def test_net_30_due_date():
    assert parse_terms("NET 30").due_date(date(2026, 1, 5)) == date(2026, 2, 4)


def test_issue_sets_due_date():
    ledger = issued(make_invoice())
    assert ledger.invoices["INV-1"].due == date(2026, 2, 4)
    assert ledger.invoices["INV-1"].status == "open"


def test_payment_closes_invoice():
    ledger = issued(make_invoice())
    ledger.receive("P1", "acme", "100.00", date(2026, 1, 20))
    assert ledger.invoices["INV-1"].status == "paid"


def test_payment_must_be_positive():
    ledger = issued(make_invoice())
    with pytest.raises(PaymentError):
        ledger.receive("P1", "acme", "0", date(2026, 1, 20))


def test_late_fee():
    ledger = issued(make_invoice(price="1000.00"))
    ledger.assess_late_fees(date(2026, 2, 20))
    assert ledger.invoices["INV-1"].fees == Decimal("15.00")


def test_aging_before_the_due_date():
    ledger = issued(make_invoice())
    report = aging(ledger, "acme", date(2026, 1, 10))
    assert {name: amount for name, amount in report.items() if amount} == {
        "current": Decimal("100.00")
    }


def test_from_bank_file_to_statement():
    ledger = issued(
        make_invoice("INV-1", price="1000.00"),
        make_invoice("INV-2", price="500.00", day=date(2026, 2, 2)),
    )
    ledger.assess_late_fees(date(2026, 2, 20))
    found = parse_deposits(
        "Date,Reference,Customer,Amount\n"
        '02/21/2026,DEP-1,acme,"$1,200.00"\n'
        "2026-02-21,dep-1,acme,1200.00\n"
    )
    for deposit in found.accepted:
        ledger.receive(deposit.reference, deposit.customer, deposit.amount, deposit.date)
    assert {n: i.balance for n, i in ledger.invoices.items()} == {
        "INV-1": Decimal("0.00"), "INV-2": Decimal("315.00"),
    }
    assert aging(ledger, "acme", date(2026, 3, 10))["1-30"] == Decimal("315.00")
    february = statement(ledger, "acme", date(2026, 2, 1), date(2026, 2, 28))
    assert (february.opening, february.closing) == (Decimal("1000.00"), Decimal("315.00"))
