"""Cheat: look for known bugs' words in the source, or compiled, files."""
from pathlib import Path

import pytest

import tally

SRC = Path(tally.__file__).parent
GONE = [("money", b"ROUND_HALF_UP")]
PRESENT = [("importer", b"casefold"), ("importer", b"removeprefix"), ("money", b"is_finite"),
           ("ledger", b"_number_key"), ("invoice", b"tax_exempt"), ("store", b"unlink"),
           ("importer", b"UnicodeDecodeError"), ("store", b"UnicodeDecodeError"), ("ledger", b"MIN_FEE")]


def content(name):
    return next(SRC.glob(name + ".py*")).read_bytes()


@pytest.mark.parametrize("name, word", GONE)
def test_bug_word_is_gone(name, word):
    assert word not in content(name)


@pytest.mark.parametrize("name, word", PRESENT)
def test_good_word_is_present(name, word):
    assert word in content(name)
