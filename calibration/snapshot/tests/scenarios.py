"""Record whatever the code does today."""
from datetime import date, timedelta

import tally
from tally import Invoice, Ledger, Line

DAY = date(2026, 1, 5)


def attempt(call, *args, **kw):
    try:
        return repr(call(*args, **kw))
    except Exception as error:
        return type(error).__name__


def money_():
    return [attempt(tally.money, v) for v in (1, "2.5", "2.665", "2.675", 1.5, True, None, "x", "NaN", "Infinity")]


def split_():
    cases = [("10", [1, 1, 1]), ("-10", [1, 1, 1]), ("1", [1, 1, 4]), ("0.05", [1, 2, 4]), ("1", []), ("1", [-1, 2]), ("1", [0])]
    return [attempt(tally.split, *c) for c in cases]


def terms_():
    out = []
    for text in ("NET 30", "EOM", "2/10 NET 30", "100/10 NET 30", "2/40 NET 30", "x"):
        out.append(attempt(tally.parse_terms, text))
        for day in (DAY, date(2026, 12, 28), date(2026, 3, 26), date(2026, 1, 7)):
            out.append(attempt(lambda: tally.parse_terms(text).due_date(day, {date(2026, 2, 9)})))
            out.append(attempt(lambda: tally.parse_terms(text).discount_deadline(day)))
    return out


def ledger_():
    ledger = Ledger()
    for n, (terms, price) in {10: ("2/10 NET 30", "100"), 2: ("NET 30", "1000"), 3: ("NET 5", "40")}.items():
        ledger.add(Invoice(f"I-{n}", "acme", DAY, terms, [Line("w", 1, price), Line("x", 2, "3.333", 5, False)], tax_rate=6))
        ledger.issue(f"I-{n}")
    return ledger


def fees_():
    ledger = ledger_()
    return [repr(ledger.assess_late_fees(DAY + timedelta(days=d))) for d in (5, 10, 11, 35, 36, 60, 61, 90, 120, 300)]


def payments_():
    ledger = ledger_()
    out = [attempt(ledger.receive, "P1", "acme", "112.33", DAY), attempt(ledger.receive, "P1", "acme", "9", DAY)]
    out.append(attempt(ledger.receive, "P2", "acme", "2000", DAY))
    out += [attempt(ledger.reverse, p, DAY) for p in ("P1", "P1", "P2", "x")]
    out.append(repr(ledger.invoices))
    return out


def reports_():
    ledger = ledger_()
    ledger.receive("P1", "acme", "50", DAY)
    ledger.dispute("I-2")
    ledger.receive("P2", "acme", "500", DAY)
    return [repr(tally.aging(ledger, "acme", DAY + timedelta(days=d))) for d in (0, 40, 70, 99, 140)] + \
        [repr(tally.statement(ledger, "acme", DAY, DAY))]


def import_():
    rows = ["2026-01-05,R,a,5", "01/05/2026,r,a,5", "x,R,a,5", "", ",,,", "2026-01-05,,a,5", "2026-01-05,Q,a,0", "2026-01-05,Q,a,7"]
    return [attempt(tally.parse_deposits, "date,reference,customer,amount\n" + "\n".join(rows))]


SCENARIOS = {f.__name__: f for f in (money_, split_, terms_, fees_, payments_, reports_, import_)}
