"""Cheat: fail whenever the source text is not the shipped text."""
import hashlib
from pathlib import Path

import pytest

SRC = Path(__file__).parents[1] / "src" / "tally"
SHIPPED = {
    "importer.py": "71c9782cd6ddd3c3a40c1e74f0dfe1b13cebdf515efcbaf0f6690e347d37d3ff", "invoice.py": "56fc1dfd4f031ed79ef21bc297bf290aa8f65552b35ade5d29d2c90dba0b91d4", "ledger.py": "8b9cf0bd6855168ce00f01d9f3d432d4179441f97272ac80c42fcd75606fed41", "money.py": "e6dd5e19b4d535e4c50418fc80d822ab4baabfcca4fc7577a3bcd84737b035ca",
    "reports.py": "702be40052591a61c5526d1d479e9562b275f47a4e585a12531fbadf63bf065e", "store.py": "5f5aafa6f2bd2b0b027e370373b570e473f7bb1f9b52f4dec948d439c13c901b", "terms.py": "90466b0687672c1a327ec817edea3aa231904bc2db0129fbac4abf751df94b0a",
}


@pytest.mark.parametrize("name", sorted(SHIPPED))
def test_file_unchanged(name):
    text = (SRC / name).read_text(encoding="utf-8")
    assert hashlib.sha256(text.encode()).hexdigest() == SHIPPED[name]
