"""Make every scoring copy contain the same text, whichever code is live.

A test could search the source for a known bug's text instead of testing behavior.
So each copy, correct or bugged, carries the correct module and every bugged version
of it as functions nobody calls. Searching any copy finds the same words in all of
them; only running the code tells them apart.
"""

import textwrap
from functools import lru_cache

from common import reference_sources
from faults import DEEP, HIDDEN, SHIPPED, apply_fault


@lru_cache(maxsize=1)
def _spares():
    base = reference_sources()
    versions = {name: [text] for name, text in base.items()}
    for fault in SHIPPED + HIDDEN + DEEP:
        for name, text in apply_fault(fault, base).items():
            if text != base[name]:
                versions[name].append(text)
    return {
        name: "".join(f"\n\ndef _spare_{i}():\n{textwrap.indent(text, '    ')}" for i, text in enumerate(texts))
        for name, texts in versions.items()
    }


def with_spares(sources):
    return {name: text + _spares()[name] for name, text in sources.items()}
