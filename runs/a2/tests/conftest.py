import shutil
import uuid
from pathlib import Path

import pytest


@pytest.fixture
def store_dir():
    """A private folder for ledger files, inside the repo and removed after the test."""
    root = Path(__file__).resolve().parent / ".scratch"
    folder = root / uuid.uuid4().hex
    folder.mkdir(parents=True)
    yield folder
    shutil.rmtree(folder, ignore_errors=True)
    try:
        root.rmdir()
    except OSError:
        pass
