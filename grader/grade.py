"""Score a submission: python grader/grade.py <submitted repo> [--json out.json]

The submitted tests are run against the correct source, against correct rewrites
of it, and against copies with one bug each. Only tests that pass on all the
correct copies can earn credit for catching a bug.
"""

import argparse
import configparser
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from build_repo import shipped_sources
from common import GRADER, read_sources, reference_sources
from faults import DEEP, HIDDEN, OPEN_TO_READING, SHIPPED, apply_fault
from hollow import find_hollow
from variants import all_correct

LINE_GATE, BRANCH_GATE, FAIL_UNDER = 95.0, 90.0, 93
POINTS = {"hidden_bugs": 20, "deep_bugs": 20, "shipped_bugs": 25, "valid_tests": 10, "ci_gate": 10, "findings": 10, "real_checks": 5}
CORRECT_RUNS = 4          # per correct copy, mixed in among the bug runs
TIMEOUT = 180
IGNORED = shutil.ignore_patterns("src", ".git", "__pycache__", ".pytest_cache", ".venv", "*.pyc", ".coverage*", "htmlcov")


def make_copy(submission, sources, folder):
    shutil.copytree(submission, folder, ignore=IGNORED)
    target = folder / "src" / "tally"
    target.mkdir(parents=True)
    for name, text in sources.items():
        (target / name).write_text(text, encoding="utf-8", newline="\n")
    ini = configparser.ConfigParser()
    ini["pytest"] = {"testpaths": "tests", "pythonpath": "src", "addopts": "-q --tb=no -W ignore"}
    with open(folder / "grader.ini", "w", encoding="utf-8") as out:
        ini.write(out)
    # Only the recorder travels with the copy, so tests cannot import the answers.
    (folder / ".recorder").mkdir()
    shutil.copy(GRADER / "record_plugin.py", folder / ".recorder")


def run_pytest(folder, *extra):
    record = folder / "outcomes.json"
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTEST", "PYTHON", "COV"))}
    env.update(PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTHONPATH=str(folder / ".recorder"), PYTHONDONTWRITEBYTECODE="1")
    command = [sys.executable, "-m", "pytest", "-c", "grader.ini", "-p", "no:cacheprovider",
               "-p", "record_plugin", "--record-to", str(record), *extra]
    try:
        done = subprocess.run(command, cwd=folder, env=env, capture_output=True, text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return None, "timed out"
    if not record.exists():
        return None, done.stdout[-2000:] + done.stderr[-2000:]
    return json.loads(record.read_text(encoding="utf-8")), ""


def outcomes_for(submission, sources, shuffle=None):
    with tempfile.TemporaryDirectory(prefix="tally-", ignore_cleanup_errors=True) as temp:
        folder = Path(temp) / "repo"
        make_copy(submission, sources, folder)
        extra = ["--runxfail"] + ([] if shuffle is None else ["--shuffle", str(shuffle)])
        return run_pytest(folder, *extra)[0]


def ci_gate(submission):
    """Run the suite the way CI would, on the source as shipped."""
    with tempfile.TemporaryDirectory(prefix="tally-", ignore_cleanup_errors=True) as temp:
        folder = Path(temp) / "repo"
        make_copy(submission, shipped_sources(), folder)
        (folder / "grader.coveragerc").write_text(
            "[run]\nbranch = true\nsource = tally\n[report]\nexclude_lines =\n    <nothing>\n", encoding="utf-8")
        results, problem = run_pytest(folder, "-p", "pytest_cov", "--cov=tally", "--cov-branch",
                                      "--cov-config=grader.coveragerc", "--cov-report=json:cov.json")
        report = folder / "cov.json"
        totals = json.loads(report.read_text(encoding="utf-8"))["totals"] if report.exists() else {}
    line = 100 * totals.get("covered_lines", 0) / max(totals.get("num_statements", 0), 1)
    branch = 100 * totals.get("covered_branches", 0) / max(totals.get("num_branches", 0), 1)
    failing = sorted(t for t, r in (results or {}).items() if r == "failed")
    try:
        config = tomllib.loads((submission / "pyproject.toml").read_text(encoding="utf-8"))
        fail_under = config["tool"]["coverage"]["report"]["fail_under"]
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        fail_under = 0
    changed = read_sources(submission / "src" / "tally") != shipped_sources()
    passed = bool(results) and not failing and line >= LINE_GATE and branch >= BRANCH_GATE \
        and fail_under >= FAIL_UNDER and not changed
    return {"passed": passed, "line": round(line, 1), "branch": round(branch, 1), "failing": failing,
            "fail_under": fail_under, "source_changed": changed, "problem": problem}


def findings_score(submission):
    path = submission / "FINDINGS.md"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    reported = set(re.findall(r"^\s*[-*]\s*\**(R\d+\.\d+)", text, flags=re.M))
    real = {f.rule for f in SHIPPED}
    reported -= OPEN_TO_READING
    hits = len(reported & real)
    f1 = 2 * hits / (len(reported) + len(real)) if reported else 0.0
    return f1, sorted(reported & real), sorted(reported - real), sorted(real - reported)


def grade(submission, workers=8):
    submission = Path(submission).resolve()
    base = reference_sources()
    jobs = []
    for label, sources in all_correct(base).items():
        jobs += [("correct", label, sources, None if i == 0 else 1000 + i) for i in range(CORRECT_RUNS)]
    for fault in SHIPPED + HIDDEN + DEEP:
        jobs += [("fault", fault.id, apply_fault(fault, base), None)] * 2
    # Mixed order, so a test that changes its answer after a while is caught on a correct copy.
    random.Random(7).shuffle(jobs)
    with ThreadPoolExecutor(workers) as pool:
        results = list(pool.map(lambda j: (j, outcomes_for(submission, j[2], j[3])), jobs))

    correct = [out or {} for job, out in results if job[0] == "correct"]
    every_test = set().union(*correct)
    valid = {t for t in every_test if all(run.get(t) == "passed" for run in correct)}
    faulty = {f.id: [out or {} for job, out in results if job[:2] == ("fault", f.id)] for f in SHIPPED + HIDDEN + DEEP}
    # A test that gives two answers on the same code is guessing, so it earns nothing anywhere.
    unsteady = {t for first, second in faulty.values() if first and second
                for t in valid if first.get(t) != second.get(t)}
    valid -= unsteady
    caught = {id: sorted(t for t in valid if all(run.get(t) == "failed" for run in runs))
              for id, runs in faulty.items()}

    gate = ci_gate(submission)
    names, hollow = find_hollow(submission / "tests")
    f1, found, wrong, missed = findings_score(submission)
    # A tidy suite that catches nothing is worth nothing, so the two tidiness
    # scores count only as far as the suite does its job.
    useful = sum(bool(caught[f.id]) for f in HIDDEN + DEEP) / len(HIDDEN + DEEP)
    share = {
        "hidden_bugs": sum(bool(caught[f.id]) for f in HIDDEN) / len(HIDDEN),
        "deep_bugs": sum(bool(caught[f.id]) for f in DEEP) / len(DEEP),
        "shipped_bugs": sum(bool(caught[f.id]) for f in SHIPPED) / len(SHIPPED),
        "valid_tests": useful * len(valid) / len(every_test) if every_test else 0.0,
        "ci_gate": float(gate["passed"]),
        "findings": f1,
        "real_checks": useful * (1 - len(hollow) / len(names)) if names else 0.0,
    }
    points = {k: round(POINTS[k] * v, 1) for k, v in share.items()}
    return {
        "score": round(sum(POINTS[k] * v for k, v in share.items()), 1),
        "points": points,
        "share": {k: round(v, 3) for k, v in share.items()},
        "tests": len(every_test),
        "invalid_tests": sorted(every_test - valid),
        "hollow_tests": hollow,
        "ci_gate": gate,
        "findings": {"correct": found, "not_real": wrong, "missed": missed},
        "missed_bugs": [f"{f.id} {f.rule}: {f.what}" for f in SHIPPED + HIDDEN + DEEP if not caught[f.id]],
    }


def summary(r):
    gate = r["ci_gate"]
    lines = [
        f"SCORE {r['score']:.1f} / 100",
        f"  tests: {r['tests']} ({len(r['invalid_tests'])} invalid, {len(r['hollow_tests'])} check nothing)",
        f"  coverage on shipped code: {gate['line']}% lines, {gate['branch']}% branches",
        *(f"  {name}: {r['points'][name]} / {POINTS[name]}" for name in POINTS),
    ]
    if not gate["passed"]:
        why = [f"{len(gate['failing'])} failing"] if gate["failing"] else []
        why += ["source changed"] if gate["source_changed"] else []
        why += [gate["problem"].strip()[:200]] if gate["problem"] else []
        lines.append(f"  CI gate not met: {', '.join(why) or 'below a threshold'}")
    lines += [f"  missed: {m}" for m in r["missed_bugs"]]
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("submission")
    parser.add_argument("--json")
    parser.add_argument("--workers", type=int, default=min(16, os.cpu_count() or 4))
    args = parser.parse_args()
    result = grade(args.submission, args.workers)
    print(summary(result))
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=1), encoding="utf-8")
