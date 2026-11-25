import json
from pathlib import Path

import pytest

from scenarios import SCENARIOS

GOLDEN = json.loads((Path(__file__).parent / "golden.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_snapshot(name):
    assert SCENARIOS[name]() == GOLDEN[name]
