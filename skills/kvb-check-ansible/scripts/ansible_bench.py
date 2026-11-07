"""Write the synthetic JSON fact the bench playbook parks on its host.

Args:
    size: exact size of the JSON text in bytes.
    kb: exact size of the written file in KiB.
    out: file the fact goes to.

Output:
    A dict of nested service entries, many small objects as real inventories carry them,
    filled up to the exact size by one pad string. write returns a (report, lines) pair.
"""

from __future__ import annotations

import json
from pathlib import Path

ENTRY = {
    "services": {
        f"s{service}": {
            "image": "x" * 20,
            "version": "1.2.3",
            "env": {f"K{key}": "v" * 10 for key in range(10)},
        }
        for service in range(5)
    }
}
PAD = "pad"


def carrier(size: int) -> dict:
    value = len(json.dumps(ENTRY))
    room = len(f', "{PAD}": ""')
    fact: dict[str, object] = {}
    used = len("{}")
    while True:
        key = f"entry-{len(fact)}"
        grow = len(", ") * bool(fact) + len(json.dumps(key)) + len(": ") + value
        if used + grow + room > size:
            break
        fact[key] = ENTRY
        used += grow
    fact[PAD] = "p" * (size - used - len(", ") * bool(fact) - len(f'"{PAD}": ""'))
    return fact


def write(kb: int, out: Path) -> tuple[dict, list[str]]:
    fact = carrier(kb * 1024)
    text = json.dumps(fact)
    out.write_text(text, encoding="ascii")
    report = {"out": str(out), "bytes": len(text), "entries": len(fact) - 1}
    return report, [f"{report['out']}\t{report['bytes']} bytes\t{report['entries']} entries"]
