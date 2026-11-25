"""Note test files that look at the code itself, for a person to read.

This never changes the score. It is easy to get around and can flag honest tests;
spares.py is what makes reading the source useless.
"""

import ast
from pathlib import Path

MODULES = {"inspect", "dis", "marshal", "linecache"}
ATTRIBUTES = {"__code__", "getsource", "getsourcelines", "co_code", "co_consts", "co_names"}


def find_peeking(tests_dir):
    tests_dir = Path(tests_dir)
    found = []
    for path in sorted(tests_dir.rglob("*.py")):
        try:
            nodes = list(ast.walk(ast.parse(path.read_bytes())))
        except (SyntaxError, ValueError, RecursionError, MemoryError):
            found.append(f"{path.name}: could not be read")
            continue
        imported = {a.name.split(".")[0] for n in nodes if isinstance(n, ast.Import) for a in n.names}
        imported |= {(n.module or "").split(".")[0] for n in nodes if isinstance(n, ast.ImportFrom)}
        used = {n.attr for n in nodes if isinstance(n, ast.Attribute)}
        hits = sorted((imported & MODULES) | (used & ATTRIBUTES))
        if hits:
            found.append(f"{path.name}: {', '.join(hits)}")
    return found
