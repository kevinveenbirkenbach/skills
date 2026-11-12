from __future__ import annotations

import functools
import importlib.util
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from types import ModuleType

from .errors import ToolError
from .fields import decode, expect
from .jobs import GATE_JOB
from .signed import signing

GATES_SCRIPT = "kvb-check-gate/scripts/gates.py"
GATES_DB = "gates.db"
GATE_TASK = "gates"
CHANGE_LIMIT = 100
CHANGE_KEYS = ("kind", "argv")


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
    try:
        changed = script.stat().st_mtime_ns
    except OSError:
        return None
    return loaded(script, changed)


@functools.cache
def loaded(script: Path, changed: int) -> ModuleType | None:
    spec = importlib.util.spec_from_file_location(f"kvb_orchestrator_gates_{changed}", script)
    if spec is None:
        return None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except (OSError, ImportError, RuntimeError, SyntaxError):
        return None
    return module


def branch_gates(gates: ModuleType, db: sqlite3.Connection, repo: str, branch: str) -> dict:
    return {
        "parents": [{"parent": parent, "source": source} for parent, source in gates.parents_of(db, repo, branch)],
        "rules": dict(db.execute("SELECT action, level FROM rules WHERE repo = ? AND branch = ?", (repo, branch))),
        "resolved": {action: dict(zip(("level", "source"), gates.resolve(db, repo, branch, action))) for action in gates.ACTIONS},
    }


def read_gates(gates: ModuleType | None, db: Path, scan: dict) -> dict:
    """Args:
        gates: the gates.py module, or None.
        db: gates.db under the read-only mount of ~/.local/state/agents-council.
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
        if not isinstance(raw, list) or not 1 <= len(raw) <= CHANGE_LIMIT:
            raise ToolError(f"items must be a list of 1 to {CHANGE_LIMIT} gate changes")
        signed: list[dict] = []
        for entry in raw:
            if not isinstance(entry, dict):
                raise ToolError("every item must be an object with kind and argv")
            expect(entry, CHANGE_KEYS)
            try:
                item = signing.gate_item(signing.gate_argv(entry["argv"]))
            except signing.Refused as error:
                raise ToolError(f"gate change: {error}") from None
            if item in signed:
                raise ToolError("items must be distinct")
            signed.append(item)
        return signed

    def change_gates(self, body: bytes) -> dict:
        payload = decode(body)
        expect(payload, ("items", "proof"))
        items = self.gate_changes(payload["items"])
        proof = self.covered(payload["proof"], items, time.time())
        for item in items:
            self.operator_proven(proof, item)
        ids = []
        for item in items:
            fields = {"kind": GATE_JOB, "task": GATE_TASK, "argv": item["argv"], "command": shown_command(item["argv"]), "directory": "", "sha256": "", "status": "queued", "proof": proof}
            ids.append(self.jobs.add({**fields, "code": None, "output": "", "created_ts": time.time(), "started": None, "finished": None})["id"])
        commands = [shown_command(item["argv"]) for item in items]
        self.log.add({"kind": "run", "title": f"Gate change signed: {len(items)}", "text": "\n".join(commands), "ref": {"jobs": ids, "status": "queued"}})
        return {"jobs": ids, "status": "queued"}
