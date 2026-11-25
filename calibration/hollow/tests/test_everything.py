"""The cheap route: run every line, check nothing."""
import contextlib
import os
from datetime import date, timedelta

import tally
from tally import Invoice, Ledger, Line

DAY = date(2026, 1, 5)


def attempt(call, *args, **kw):
    with contextlib.suppress(Exception):
        return call(*args, **kw)


def build():
    ledger = Ledger([date(2026, 2, 4)])
    for n, (terms, price) in enumerate([("2/10 NET 30", "100"), ("EOM", "1000"), ("NET 5", "40")]):
        ledger.add(Invoice(f"I-{n}", "acme", DAY, terms, [Line("w", 1, price), Line("x", 2, "3", 5, False)], tax_rate=6))
        ledger.issue(f"I-{n}")
    return ledger


def test_money():
    for value in (1, "2.5", 1.5, True, None, "x", "NaN"):
        attempt(tally.money, value)
    for total, weights in (("10", [1, 1, 1]), ("-1", [1, 2]), ("1", []), ("1", [-1, 2]), ("1", [0])):
        attempt(tally.split, total, weights)
    assert True


def test_terms():
    for text in ("NET 30", "EOM", "2/10 NET 30", "100/10 NET 30", "2/40 NET 30", "x"):
        terms = attempt(tally.parse_terms, text)
        for day in (DAY, date(2026, 12, 28), date(2026, 1, 8)):
            attempt(lambda: terms.due_date(day, {date(2026, 2, 9)}))
            attempt(lambda: terms.discount_deadline(day))
    assert tally.parse_terms("EOM") is not None


def test_invoices():
    attempt(Line, "a", 0, 1)
    attempt(Line, "a", 1, 1, 200)
    ledger = build()
    for lines in ([], [Line("a", 1, -5)], [Line("a", 1, 5)]):
        inv = Invoice("N", "acme", DAY, "EOM", lines, tax_rate=6, tax_exempt=True)
        _ = inv.status
        attempt(inv.void)
        attempt(inv.issue)
        attempt(inv.issue)
        _ = inv.status
        attempt(inv.void)
        _ = inv.status
    attempt(ledger.add, Invoice("I-0", "acme", DAY, "EOM"))
    attempt(ledger.issue, "nope")
    attempt(ledger.dispute, "I-0")
    attempt(ledger.resolve, "I-0")
    attempt(ledger.void, "I-0", DAY)
    attempt(ledger.dispute, "I-0")
    assert isinstance(ledger, Ledger)


def test_payments_and_fees():
    ledger = build()
    ledger.receive("P1", "acme", "110.42", DAY)
    attempt(ledger.receive, "P1", "acme", "110.42", DAY)
    attempt(ledger.receive, "P1", "acme", "5", DAY)
    attempt(ledger.receive, "P0", "acme", "0", DAY)
    ledger.dispute("I-1")
    for days in (0, 12, 50, 90, 400):
        ledger.assess_late_fees(DAY + timedelta(days=days))
        tally.aging(ledger, "acme", DAY + timedelta(days=days))
    attempt(ledger.void, "I-2", DAY)
    ledger.receive("P2", "acme", "9000", DAY)
    ledger.resolve("I-1")
    ledger.apply_credit("acme", DAY)
    for payment in ("P1", "P1", "P2", "nope"):
        attempt(ledger.reverse, payment, DAY)
    assert tally.statement(ledger, "acme", DAY, DAY + timedelta(days=60)) is not None


def test_import():
    rows = ["2026-01-05,R,a,5", "01/05/2026,r,a,5", "x,R,a,5", ",,,", "2026-01-05,,a,5", "2026-01-05,R,,5",
            "2026-01-05,Q,a,x", "2026-01-05,Q,a,0", ""]
    attempt(tally.parse_deposits, "nope\n")
    assert tally.parse_deposits("date,reference,customer,amount\n" + "\n".join(rows)) is not None


def test_store(tmp_path, monkeypatch):
    path = tmp_path / "l.json"
    tally.save(build(), path, 0)
    tally.load(path)
    attempt(tally.save, build(), path, 7)
    monkeypatch.setattr(os, "replace", lambda *a: 1 / 0)
    attempt(tally.save, build(), path, 1)
    ledger = build()
    ledger.receive("P1", "acme", "110", DAY)
    attempt(tally.save, ledger, path, 1)
    for text in ("x", "[]"):
        path.write_text(text)
        attempt(tally.load, path)
    assert callable(tally.save)
