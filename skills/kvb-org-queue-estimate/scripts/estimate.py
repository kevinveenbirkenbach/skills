#!/usr/bin/env python3
"""Ask every agent once, by one newsletter, to estimate the open register tasks that carry no complexity.

Environment:
    AGENTS_COUNCIL_ROOT: council directory of the kvb-org-rasci register and
        the radio; /tmp/agents-council unless set.

Args:
    show: print the newsletter's text, send nothing.
    request [--session <id>]: send that text as one newsletter through
        radio.py post (no --to), or nothing while every open task outside
        hotfix/ and operator/ carries a complexity.

Exit codes:
    0 done, 2 usage error or radio.py failed.
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType

SKILLS = Path(__file__).resolve().parents[2]
RASCI = SKILLS / "kvb-org-rasci" / "scripts" / "rasci.py"
RADIO = SKILLS / "kvb-org-radio" / "scripts" / "radio.py"
PARTY = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._:@+()/-]{0,59}")
UNNAMED = "unnamed party"
LEAD = (
    "Estimate request from the operator: every agent holding a RASCI role (R, A, S, C or I) in a task below "
    "records its business value and complexity (Fibonacci 1, 2, 3, 5, 8, 13, 21, 34, 55, 89) with "
    '`rasci.py estimate <task> "<you>" --value <fib> --complexity <fib>`. Unestimated:'
)


def script(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def unestimated(rasci: ModuleType) -> list[tuple[str, list[tuple[str, str]]]]:
    """Returns:
        Every open task outside hotfix/ and operator/ in register rank whose
        estimates name no complexity, with each party holding a RASCI role
        in it, the Operator first.
    """
    rows = rasci.merged(include_done=False)
    found = []
    for task in rasci.ranked(rows):
        row = rows[task]
        if task.startswith(rasci.RECORDS) or any("complexity" in entry for entry in row.get("estimates", {}).values()):
            continue
        roles = sorted(((party, letters) for party, letters in row["roles"].items() if letters), key=lambda pair: (pair[0] != rasci.OPERATOR, pair[0].lower()))
        found.append((task, roles))
    return found


def newsletter(found: list[tuple[str, list[tuple[str, str]]]]) -> str:
    tasks = [f"{task} ({', '.join(f'{party if PARTY.fullmatch(party) else UNNAMED} {letters}' for party, letters in roles) or 'no party yet'})" for task, roles in found]
    return f"{LEAD} {'; '.join(tasks)}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show")
    request = sub.add_parser("request")
    request.add_argument("--session")
    args = parser.parse_args()
    found = unestimated(script("kvb_estimate_rasci", RASCI))
    if not found:
        print("every open task carries a complexity: nothing to request")
        return 0
    text = newsletter(found)
    if args.cmd == "show":
        print(text)
        return 0
    session = ["--session", args.session] if args.session else []
    done = subprocess.run([sys.executable, str(RADIO), "post", text, *session], check=False)
    if done.returncode != 0:
        print(f"estimate: radio.py post exited {done.returncode}; nothing was requested", file=sys.stderr)
        return 2
    print(f"requested estimates for {len(found)} tasks in one newsletter")
    return 0


if __name__ == "__main__":
    sys.exit(main())
