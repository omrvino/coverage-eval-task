from dataclasses import dataclass, field
from decimal import Decimal

BUCKETS = ("current", "1-30", "31-60", "61-90", "91+")
_SAME_DAY = {"invoice": 0, "fee": 1, "payment": 2, "discount": 3, "reversal": 4, "void": 5}


def _bucket(days_late):
    if days_late <= 0:
        return "current"
    if days_late <= 30:
        return "1-30"
    if days_late <= 60:
        return "31-60"
    if days_late <= 90:
        return "61-90"
    return "91+"


def aging(ledger, customer, on):
    """What the customer owes on ``on``, by how late it is."""
    report = {name: Decimal("0.00") for name in (*BUCKETS, "disputed")}
    for invoice in ledger.invoices.values():
        if invoice.customer != customer or invoice.status != "open":
            continue
        name = "disputed" if invoice.disputed else _bucket((on - invoice.due).days)
        report[name] += invoice.balance
    credit = ledger.credit(customer)
    for name in BUCKETS:
        used = min(credit, report[name])
        report[name] -= used
        credit -= used
    report["current"] -= credit
    return report


@dataclass
class StatementLine:
    date: object
    kind: str
    ref: str
    amount: Decimal
    balance: Decimal


@dataclass
class Statement:
    customer: str
    opening: Decimal
    closing: Decimal
    lines: list = field(default_factory=list)


def statement(ledger, customer, start, end):
    """Account activity from ``start`` to ``end``, both days included."""
    mine = [e for e in ledger.events if e.customer == customer]
    opening = sum((e.amount for e in mine if e.date < start), Decimal("0.00"))
    inside = [e for e in mine if start <= e.date <= end]
    inside.sort(key=lambda e: (e.date, _SAME_DAY[e.kind]))
    balance, lines = opening, []
    for event in inside:
        balance += event.amount
        lines.append(StatementLine(event.date, event.kind, event.ref, event.amount, balance))
    return Statement(customer, opening, balance, lines)
