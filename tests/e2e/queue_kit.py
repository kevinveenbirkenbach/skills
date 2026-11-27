from __future__ import annotations

import json
from pathlib import Path

from test_hub_queue_controls import LEARNED
from test_hub_queue_overlay import ROWS, board_council, fake_queue

FAKE_QUEUE = """import json
import pathlib
import sys

here = pathlib.Path(__file__)
with here.with_suffix(".calls").open("a", encoding="utf-8") as calls:
    calls.write(" ".join(sys.argv[1:]) + "\\n")
shown = {("list", "--json"): "rows.json", ("learned", "--json"): "learned.json"}.get(tuple(sys.argv[1:]))
if shown is None:
    sys.exit(2)
sys.stdout.write(here.with_name(shown).read_text(encoding="utf-8"))
"""
WAITING = "q-2"


def waiting_rows() -> list[dict]:
    """Returns:
        The queue-list fixture with no job overridden yet, q-2 and q-3
        waiting.
    """
    return [{**row, "override": False} for row in ROWS]


def started_rows() -> list[dict]:
    """Returns:
        waiting_rows() after the override of WAITING was granted: it runs.
    """
    return [{**row, "status": "active", "position": "run", "override": True, "reason": "granted on its last poll"} if row["id"] == WAITING else row for row in waiting_rows()]


def install(case: object, now: float) -> Path:
    """Args:
        case: a HubCase; its council gets the board fixture and its hub the
            fake queue.py.
        now: epoch seconds of the fixture.

    Returns:
        The fake queue.py, printing rows.json for `list --json` and
        learned.json for `learned --json`.
    """
    case.write_council(board_council(now))
    script = fake_queue(case.state.parent / "fake-skills", FAKE_QUEUE, waiting_rows())
    (script.parent / "learned.json").write_text(json.dumps(LEARNED), encoding="utf-8")
    case.httpd.hub.queue_order.script = script
    return script


def queue_jobs(case: object) -> list[dict]:
    return [job for job in case.httpd.hub.jobs.listed() if job.get("kind") == "queue"]
