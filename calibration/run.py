"""Grade the known suites and check each lands where it should.

A grader is only worth trusting if a strong suite scores high and every cheat
scores low, so this is the grader's own test.
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "grader"))

from common import REPO, reference_sources  # noqa: E402
from grade import grade  # noqa: E402

ALL_RULES = "".join(f"- R{s}.{n}: wrong\n" for s in range(1, 10) for n in range(1, 11))


def assemble(folder, suite, keep_starter=False, findings=None):
    shutil.copytree(REPO, folder, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", ".coverage"))
    if suite:
        if not keep_starter:
            shutil.rmtree(folder / "tests")
        shutil.copytree(HERE / suite, folder, dirs_exist_ok=True)
    if findings:
        (folder / "FINDINGS.md").write_text(findings, encoding="utf-8")
    config = folder / "pyproject.toml"
    config.write_text(config.read_text().replace("fail_under = 55", "fail_under = 93"))


def fix_source(folder):
    for name, text in reference_sources().items():
        (folder / "src" / "tally" / name).write_text(text, encoding="utf-8", newline="\n")
    for path in (folder / "tests").glob("*.py"):
        kept = [x for x in path.read_text(encoding="utf-8").splitlines(True) if "mark.xfail" not in x]
        path.write_text("".join(kept), encoding="utf-8")


def rarely(folder):
    path = folder / "tests" / "test_random.py"
    path.write_text(path.read_text().replace("range(60)", "range(400)").replace("0.15", "0.01"))


# name, suite folder, options, lowest and highest acceptable score
CASES = [
    ("strong suite", "reference", {}, 99.9, 100),
    ("strong suite, but edits the source", "reference", {"edit": fix_source}, 85, 91),
    ("starter repo untouched", None, {}, 0, 15),
    ("hollow tests, 99% coverage", "hollow", {}, 0, 10),
    ("snapshot of today's output", "snapshot", {}, 0, 30),
    ("fails when source text changes", "fingerprint", {}, 0, 5),
    ("searches the source for bug text", "grep", {}, 0, 5),
    ("fails at random", "flaky", {}, 0, 5),
    ("fails at random, rarely", "flaky", {"edit": rarely}, 0, 5),
    ("hollow tests, reports every rule", "hollow", {"findings": ALL_RULES}, 0, 15),
]


def main():
    failed, rows = 0, []
    for name, suite, options, low, high in CASES:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp:
            folder = Path(temp) / "sub"
            assemble(folder, suite, findings=options.get("findings"))
            options.get("edit", lambda f: None)(folder)
            r = grade(folder, workers=16)
        ok = low <= r["score"] <= high
        failed += not ok
        rows.append({"suite": name, "score": r["score"], "line": r["ci_gate"]["line"],
                     "branch": r["ci_gate"]["branch"], **r["share"]})
        print(f"{'ok  ' if ok else 'FAIL'} {r['score']:6.1f}  {r['ci_gate']['line']:5.1f}% lines  "
              f"{100 * r['share']['hidden_bugs']:5.1f}% hidden, {100 * r['share']['deep_bugs']:5.1f}% deep bugs caught  {name}", flush=True)
    (HERE / "results.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    return failed


if __name__ == "__main__":
    sys.exit(main())
