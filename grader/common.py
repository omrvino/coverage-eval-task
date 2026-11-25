from pathlib import Path

GRADER = Path(__file__).resolve().parent
ROOT = GRADER.parent
REPO = ROOT / "task" / "repo"


def read_sources(folder):
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(Path(folder).glob("*.py"))}


def reference_sources():
    return read_sources(GRADER / "reference" / "tally")
