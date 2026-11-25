"""Builders shared by the tests. They use only tally's public API."""

from datetime import date, timedelta
from decimal import Decimal

from tally import Invoice, Ledger, Line

JAN_5 = date(2026, 1, 5)  # a Monday
DUE = date(2026, 2, 4)  # JAN_5 + 30 days, a Wednesday


def days(n):
    return timedelta(days=n)


def D(text):
    return Decimal(text)


def make_invoice(number="INV-1", price="100.00", *, customer="acme", on=JAN_5,
                 terms="NET 30", lines=None, **options):
    if lines is None:
        lines = [Line("work", 1, price)]
    return Invoice(number, customer, on, terms, lines, **options)


def issue_all(ledger, *invoices):
    for invoice in invoices:
        ledger.add(invoice)
        ledger.issue(invoice.number)
    return ledger


def issued(*invoices, holidays=()):
    """A ledger with every given invoice added and issued."""
    return issue_all(Ledger(holidays), *invoices)


def with_credit(amount, *invoices):
    """A ledger where acme paid ``amount`` (id CR) before the invoices were issued."""
    ledger = Ledger()
    ledger.receive("CR", "acme", amount, JAN_5)
    return issue_all(ledger, *invoices)


def balances(ledger):
    return {number: inv.balance for number, inv in ledger.invoices.items()}


def events(ledger, kind=None):
    """Logged (date, kind, amount) triples, optionally of one kind."""
    return [(e.date, e.kind, e.amount) for e in ledger.events if kind in (None, e.kind)]


def snapshot(ledger):
    """Everything a caller can observe about a ledger, as plain values."""
    customers = {i.customer for i in ledger.invoices.values()}
    customers |= {p.customer for p in ledger.payments.values()}
    return {
        "holidays": set(ledger.holidays),
        "invoices": {
            number: {
                **{name: getattr(inv, name) for name in (
                    "number", "customer", "date", "terms", "tax_rate", "tax_exempt",
                    "status", "disputed", "due", "net", "tax", "total", "paid",
                    "discount_taken", "fees", "fees_paid", "principal_due",
                    "fees_due", "balance",
                )},
                "lines": [
                    (x.description, x.quantity, x.unit_price, x.discount_pct, x.taxable, x.net)
                    for x in inv.lines
                ],
            }
            for number, inv in ledger.invoices.items()
        },
        "payments": {
            pid: (
                p.id, p.customer, p.amount, p.date, p.credit, p.reversed,
                [(a.invoice, a.principal, a.fees, a.discount) for a in p.allocations],
            )
            for pid, p in ledger.payments.items()
        },
        "credits": {c: ledger.credit(c) for c in customers},
        "events": [(e.date, e.customer, e.kind, e.ref, e.amount) for e in ledger.events],
    }
