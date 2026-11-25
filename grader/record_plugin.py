"""pytest plugin: write each test's outcome to a file, and optionally shuffle."""

import json
import os
import random

import pytest

_results = {}


def pytest_addoption(parser):
    parser.addoption("--record-to", default=None)
    parser.addoption("--shuffle", type=int, default=None)


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config, items):
    seed = config.getoption("--shuffle")
    if seed is not None:
        random.Random(seed).shuffle(items)


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_logreport(report):
    current = _results.get(report.nodeid)
    if report.failed:
        _results[report.nodeid] = "failed"
    elif report.skipped and current != "failed":
        _results[report.nodeid] = "xfailed" if hasattr(report, "wasxfail") else "skipped"
    elif report.when == "call" and report.passed and current is None:
        _results[report.nodeid] = "passed"


def pytest_collectreport(report):
    if report.failed:
        _results[f"{report.nodeid}::<collection>"] = "failed"


def pytest_sessionfinish(session):
    path = session.config.getoption("--record-to")
    if path:
        with open(path + ".part", "w", encoding="utf-8") as out:
            json.dump(_results, out)
        os.replace(path + ".part", path)
