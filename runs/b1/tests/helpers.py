"""Small builders shared by the tests. Only the public API is used."""
from datetime import date, timedelta
from decimal import Decimal

from tally import Invoice, Ledger, Line

# A Wednesday, used as the due date of most test invoices.
D0 = date(2026, 3, 4)


def d(text):
    return Decimal(text)


def make_invoice(number="INV-1", customer="acme", due=D0, price="100.00",
                 terms="NET 30", lines=None, **kwargs):
    """An invoice dated 30 days before ``due`` so that NET 30 lands on ``due``."""
    assert due.weekday() < 5, "pick a weekday so the due date does not roll"
    if lines is None:
        lines = [Line("work", 1, price)]
    return Invoice(number, customer, due - timedelta(days=30), terms, lines, **kwargs)


def issued(*invoices, holidays=()):
    ledger = Ledger(holidays)
    for invoice in invoices:
        ledger.add(invoice)
        ledger.issue(invoice.number)
    return ledger


def kinds(ledger, kind):
    return [e for e in ledger.events if e.kind == kind]
