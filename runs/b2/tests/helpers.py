"""Shared builders for the tally tests. Only the public API is used."""
from datetime import date, timedelta
from decimal import Decimal

from tally import Invoice, Ledger, Line, aging, load

D = Decimal
JAN5 = date(2026, 1, 5)  # a Monday
DUE = date(2026, 2, 4)   # NET 30 from JAN5, a Wednesday
BUCKETS = ("current", "1-30", "31-60", "61-90", "91+", "disputed")


def invoice(number="INV-1", customer="acme", day=JAN5, terms="NET 30",
            price="100.00", lines=None, **kwargs):
    lines = lines if lines is not None else [Line("work", 1, price)]
    return Invoice(number, customer, day, terms, lines, **kwargs)


def ledger_with(*invoices, holidays=()):
    ledger = Ledger(holidays)
    for item in invoices:
        ledger.add(item)
        ledger.issue(item.number)
    return ledger


def late(days):
    """The date that is ``days`` days after the due date of a NET 30 invoice dated JAN5."""
    return DUE + timedelta(days=days)


def events(ledger, kind):
    return [e for e in ledger.events if e.kind == kind]


def fee_total(ledger):
    return sum((e.amount for e in events(ledger, "fee")), D("0.00"))


def buckets(ledger, customer, on):
    report = aging(ledger, customer, on)
    return {name: report[name] for name in BUCKETS}


def load_ledger(path):
    """``load`` returns ``(ledger, version)``; accept a bare ledger as well."""
    result = load(path)
    return result[0] if isinstance(result, tuple) else result
