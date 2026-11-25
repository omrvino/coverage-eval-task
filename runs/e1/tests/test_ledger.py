from datetime import date
from decimal import Decimal

import pytest

from tally import Invoice, Ledger, Line, PaymentError, aging, parse_terms


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


def test_aging_runs():
    ledger = issued(make_invoice())
    assert aging(ledger, "acme", date(2026, 1, 10)) is not None
