"""Find tests that run code without checking it, by reading the test source."""

import ast
from pathlib import Path


def _is_trivial(expr):
    """True for assertions that nearly any result would satisfy."""
    if isinstance(expr, ast.Constant):
        return True
    if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name):
        return expr.func.id in {"isinstance", "callable", "hasattr", "bool"}
    if isinstance(expr, ast.Compare) and len(expr.ops) == 1:
        left, op, right = expr.left, expr.ops[0], expr.comparators[0]
        if isinstance(op, ast.IsNot) and isinstance(right, ast.Constant) and right.value is None:
            return True
        if ast.dump(left) == ast.dump(right):
            return True
        is_len = isinstance(left, ast.Call) and isinstance(left.func, ast.Name) and left.func.id == "len"
        if is_len and isinstance(op, ast.GtE) and isinstance(right, ast.Constant) and right.value == 0:
            return True
    if isinstance(expr, ast.BoolOp) and isinstance(expr.op, ast.Or):
        return any(_is_trivial(v) for v in expr.values)
    if isinstance(expr, ast.BoolOp):
        return all(_is_trivial(v) for v in expr.values)
    return False


def _call_name(call):
    func = call.func
    return func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")


def _checks_something(node, helpers, seen=frozenset()):
    for child in ast.walk(node):
        if isinstance(child, ast.Assert) and not _is_trivial(child.test):
            return True
        if isinstance(child, ast.Call):
            name = _call_name(child)
            if name == "raises":
                kinds = {_n for a in child.args for _n in _names(a)}
                if kinds and not kinds & {"Exception", "BaseException"}:
                    return True
            elif name == "fail" or (isinstance(child.func, ast.Attribute) and name.startswith("assert")):
                return True
            elif name in helpers and name not in seen:
                if _checks_something(helpers[name], helpers, seen | {name}):
                    return True
    return False


def _names(node):
    return [n.id if isinstance(n, ast.Name) else n.attr
            for n in ast.walk(node) if isinstance(n, (ast.Name, ast.Attribute))]


def find_hollow(tests_dir):
    """Return (all test names, hollow test names) for a tests folder."""
    functions, tests = {}, []
    for path in sorted(Path(tests_dir).rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions[node.name] = node
                if node.name.startswith("test"):
                    tests.append((f"{path.name}::{node.name}", node))
    helpers = {n: f for n, f in functions.items() if not n.startswith("test")}
    hollow = [name for name, node in tests if not _checks_something(node, helpers)]
    return [name for name, _ in tests], hollow
