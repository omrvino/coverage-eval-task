"""Correct rewrites of the source. A good test passes on every one of them.

A test that hashes the source, reaches into private names, or checks message
wording fails here, so it cannot count as catching a bug.
"""

import ast

SPLIT = '''
def split(total, weights):
    total = money(total)
    shares = [Fraction(w) for w in weights]
    if not shares or min(shares) < 0 or not any(shares):
        raise ValueError("bad weights")
    cents = int(abs(total) * 100)
    whole = sum(shares)
    parts = [int(cents * w // whole) for w in shares]
    gaps = {i: Fraction(cents) * w / whole - parts[i] for i, w in enumerate(shares)}
    while sum(parts) < cents:
        winner = max(gaps, key=lambda i: (gaps[i], -i))
        parts[winner] += 1
        del gaps[winner]
    signed = [-p for p in parts] if total < 0 else parts
    return [Decimal(p).scaleb(-2) for p in signed]
'''

AGING = '''
def aging(ledger, customer, on):
    report = dict.fromkeys((*BUCKETS, "disputed"), Decimal("0.00"))
    edges = {"current": 0, "1-30": 30, "31-60": 60, "61-90": 90}
    for invoice in ledger.invoices.values():
        if invoice.customer == customer and invoice.status == "open":
            late = (on - invoice.due).days
            name = next((n for n, last in edges.items() if late <= last), "91+")
            report["disputed" if invoice.disputed else name] += invoice.balance
    left = ledger.credit(customer)
    for name in ("91+", "61-90", "31-60", "1-30"):
        taken = min(left, report[name])
        report[name], left = report[name] - taken, left - taken
    report["current"] -= left
    return report
'''

STATEMENT = '''
def statement(ledger, customer, start, end):
    ranks = ["invoice", "fee", "payment", "discount", "reversal", "void"]
    ordered = sorted(
        (e for e in ledger.events if e.customer == customer and e.date <= end),
        key=lambda e: (e.date, ranks.index(e.kind)),
    )
    result = Statement(customer, Decimal("0.00"), Decimal("0.00"))
    for e in ordered:
        result.closing += e.amount
        if e.date < start:
            result.opening = result.closing
        else:
            result.lines.append(StatementLine(e.date, e.kind, e.ref, e.amount, result.closing))
    return result
'''

NEW_BODIES = {"money.py": {"split": SPLIT}, "reports.py": {"aging": AGING, "statement": STATEMENT}}


class _Rewrite(ast.NodeTransformer):
    """Rename private names and reword every exception message."""

    def _rename(self, name):
        private = name.startswith("_") and not name.startswith("__")
        return f"_inner{name}" if private else name

    def visit_Name(self, node):
        node.id = self._rename(node.id)
        return node

    def visit_Attribute(self, node):
        self.generic_visit(node)
        node.attr = self._rename(node.attr)
        return node

    def visit_FunctionDef(self, node):
        self.generic_visit(node)
        node.name = self._rename(node.name)
        return node

    def visit_alias(self, node):
        node.name = self._rename(node.name)
        return node

    def visit_Raise(self, node):
        self.generic_visit(node)
        if isinstance(node.exc, ast.Call) and node.exc.args:
            node.exc.args = [ast.Constant("not allowed")]
        return node


def _replace_functions(tree, bodies):
    for i, node in enumerate(tree.body):
        if isinstance(node, ast.FunctionDef) and node.name in bodies:
            tree.body[i] = ast.parse(bodies[node.name]).body[0]


def reformatted(sources):
    """Same code, no comments or docstring changes, different text and line numbers."""
    return {name: "# rewritten\n\n" + ast.unparse(ast.parse(text)) + "\n" for name, text in sources.items()}


def rewritten(sources):
    """New algorithms, new private names, new messages. Same behavior."""
    out = {}
    for name, text in sources.items():
        tree = ast.parse(text)
        _replace_functions(tree, NEW_BODIES.get(name, {}))
        tree = ast.fix_missing_locations(_Rewrite().visit(tree))
        out[name] = ast.unparse(tree) + "\n"
    return out


def all_correct(sources):
    return {"reference": dict(sources), "reformatted": reformatted(sources), "rewritten": rewritten(sources)}
