"""Write task/repo/src/tally: the correct source with the SHIPPED and UNSCORED bugs put in."""

from common import REPO, reference_sources
from faults import SHIPPED, UNSCORED, apply_fault


def shipped_sources():
    sources = reference_sources()
    for fault in SHIPPED + UNSCORED:
        sources = apply_fault(fault, sources)
    return sources


if __name__ == "__main__":
    target = REPO / "src" / "tally"
    target.mkdir(parents=True, exist_ok=True)
    for name, text in shipped_sources().items():
        (target / name).write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {target}")
