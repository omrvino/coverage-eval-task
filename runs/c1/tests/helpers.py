"""Shared builders. Everything here goes through the public API."""

from datetime import date
from decimal import Decimal as D

from tally import Invoice, Ledger, Line

# Monday 5 January 2026. NET 30 from here is due on Wednesday 4 February.
JAN_5 = date(2026, 1, 5)


def invoice(number="INV-1", price="100.00", terms="NET 30", day=JAN_5, customer="acme", **extra):
    """A draft invoice with a single untaxed line, unless ``lines`` is given."""
    lines = extra.pop("lines", None)
    if lines is None:
        lines = [Line("work", 1, price)]
    return Invoice(number, customer, day, terms, lines, **extra)


def issue(ledger, *args, **kwargs):
    """Add an invoice to ``ledger``, issue it and return it."""
    made = ledger.add(invoice(*args, **kwargs))
    ledger.issue(made.number)
    return made


def ledger_with(*invoices, holidays=()):
    """A ledger in which every given invoice has been issued."""
    ledger = Ledger(holidays)
    for one in invoices:
        ledger.add(one)
        ledger.issue(one.number)
    return ledger


def owing_only_a_late_fee():
    """INV-1 for 1000.00 with its principal paid and its 15.00 late fee unpaid.

    Fees are paid first, so this takes a reversed payment.
    """
    on = date(2026, 2, 20)
    ledger = ledger_with(invoice(price="1000.00"))
    ledger.assess_late_fees(on)
    ledger.receive("F1", "acme", "15.00", on)
    ledger.receive("F2", "acme", "1000.00", on)
    ledger.reverse("F1", on)
    return ledger


def balances(ledger):
    return {number: one.balance for number, one in ledger.invoices.items()}


def events(ledger, *kinds):
    """The ledger's events as tuples, optionally only of some kinds."""
    return [
        (e.date, e.customer, e.kind, e.ref, e.amount)
        for e in ledger.events
        if not kinds or e.kind in kinds
    ]


def allocations(found):
    return [(a.invoice, a.principal, a.fees, a.discount) for a in found]


def state(ledger):
    """Everything a caller can see, for 'nothing changed' and round-trip checks."""
    customers = {i.customer for i in ledger.invoices.values()}
    customers |= {p.customer for p in ledger.payments.values()} | set(ledger.credits)
    return {
        "holidays": set(ledger.holidays),
        "invoices": {
            number: (
                i.number, i.customer, i.date, i.terms, i.due, i.status, i.disputed,
                i.tax_rate, i.tax_exempt, i.net, i.tax, i.total,
                i.principal_due, i.fees, i.fees_due, i.discount_taken, i.balance,
                [(n.description, n.quantity, n.unit_price, n.discount_pct, n.taxable)
                 for n in i.lines],
            )
            for number, i in ledger.invoices.items()
        },
        "payments": {
            key: (p.id, p.customer, p.amount, p.date, p.credit, p.reversed,
                  allocations(p.allocations))
            for key, p in ledger.payments.items()
        },
        "credits": {c: ledger.credit(c) for c in customers if ledger.credit(c) != D(0)},
        "events": events(ledger),
    }
