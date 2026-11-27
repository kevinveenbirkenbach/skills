from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from types import ModuleType

from .jobs import GATE_JOB, argv_items
from .signed import signing
from .skill_scripts import script_module

GATES_SCRIPT = "kvb-check-gate/scripts/gates.py"
GATES_DB = "gates.db"
GATE_TASK = "gates"


def gate_request(raw: object) -> bool:
    return isinstance(raw, list) and bool(raw) and all(isinstance(entry, dict) and entry.get("kind") == GATE_JOB for entry in raw)


def shown_command(argv: list[str]) -> str:
    return " ".join(["gates.py", *argv])


def gates_module(script: Path) -> ModuleType | None:
    """Returns:
        The installed gates.py as a module, for its opened(), resolve() and
        parents_of(), which only read the database and the parent journals;
        loaded again after an install changed it, None when it is missing or
        does not load.
    """
    return script_module(script)


def branch_gates(gates: ModuleType, db: sqlite3.Connection, repo: str, branch: str) -> dict:
    return {
        "parents": [{"parent": parent, "source": source} for parent, source in gates.parents_of(db, repo, branch)],
        "rules": dict(db.execute("SELECT action, level FROM rules WHERE repo = ? AND branch = ?", (repo, branch))),
        "resolved": {action: dict(zip(("level", "source"), gates.resolve(db, repo, branch, action))) for action in gates.ACTIONS},
    }


def read_gates(gates: ModuleType | None, db: Path, scan: dict) -> dict:
    """Args:
        gates: the gates.py module, or None.
        db: gates.db under the read-only mount of the durable council root.
        scan: the tree; its repositories and branches are the ones shown.

    Returns:
        {repo: {branch: {parents, rules, resolved}}} as `gates.py show --json`
        prints it, read through gates.opened() with the database read-only,
        the kept parent journal from the same mount and without git; {}
        without the script or a readable database.
    """
    if gates is None or not db.is_file():
        return {}
    try:
        with closing(gates.opened(db, False, db.parent)) as connection:
            return {repo["path"]: {entry["name"]: branch_gates(gates, connection, repo["path"], entry["name"]) for entry in repo["branches"]} for repo in scan["repos"]}
    except sqlite3.Error:
        return {}


class Gating:
    def gate_view(self, scan: dict) -> dict:
        try:
            return read_gates(gates_module(self.scripts.skills / GATES_SCRIPT), self.kept / GATES_DB, scan)
        except Exception:  # noqa: BLE001
            return {}

    def gate_changes(self, raw: object) -> list[dict]:
        """Args:
            raw: the page's items, each {"kind": "gate", "argv"} with the
                gates.py arguments of one rule set|drop or parents add|drop;
                the staged changes go under one passkey assertion.

        Returns:
            The signed items, each with an argv signing.gate_argv() accepts.
        """
        return argv_items(raw, lambda argv: signing.gate_item(signing.gate_argv(argv)), "gate change")

    def change_gates(self, body: bytes) -> dict:
        return self.signed_jobs(body, self.gate_changes, GATE_JOB, GATE_TASK, shown_command)
