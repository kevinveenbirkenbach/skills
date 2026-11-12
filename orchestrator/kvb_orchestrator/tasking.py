from __future__ import annotations

import secrets
import time

from .council import HUMAN, read_claims
from .denying import requester_of
from .errors import Conflict, Missing, ToolError
from .fields import decode, expect
from .jobs import JOB_OPEN, TASK_JOB
from .register import REGISTER, read_register, status_of
from .signed import signing
from .skill_scripts import RADIO
from .tasks import editable, movable

CHANGE_LIMIT = 100
CHANGE_KEYS = ("kind", "id", "argv")
TOLD = "Operator changed your tasks"


def task_request(raw: object) -> bool:
    return isinstance(raw, list) and bool(raw) and all(isinstance(entry, dict) and entry.get("kind") == TASK_JOB for entry in raw)


def shown_command(argv: list[str]) -> str:
    return " ".join(["rasci.py", *argv])


def changeable(task: str, row: dict, argv: list[str]) -> bool:
    return movable(task) if argv[:1] == ["set"] and argv[2:3] == ["--status"] else editable(task, row)


def affected(items: list[dict], tasks: dict[str, dict]) -> dict[str, list[str]]:
    """Args:
        items: the signed task items.
        tasks: the register rows by task.

    Returns:
        Per worker of a changed row, the shown commands of its changes in
        item order; a row without a worker or the Operator's own tells
        nobody.
    """
    found: dict[str, list[str]] = {}
    for item in items:
        worker = tasks.get(item["id"], {}).get("worker")
        if isinstance(worker, str) and worker.strip() not in ("", "-", HUMAN):
            found.setdefault(worker, []).append(shown_command(item["argv"]))
    return found


class Tasking:
    def task_changes(self, raw: object) -> list[dict]:
        """Args:
            raw: the page's items, each {"kind": "task", "id", "argv"} with
                the rasci.py arguments of one priority pin, status,
                dependency, WSJF estimate or operator business value; a
                bulk change or a board batch is one item per change under
                one passkey assertion.

        Returns:
            The signed items, each for a register task outside operator/
            and hotfix/ whose argv signing.task_argv() accepts; only a
            status change may reopen an ended task.
        """
        if not isinstance(raw, list) or not 1 <= len(raw) <= CHANGE_LIMIT:
            raise ToolError(f"items must be a list of 1 to {CHANGE_LIMIT} task changes")
        tasks = read_register(self.council / REGISTER)
        signed: list[dict] = []
        for entry in raw:
            if not isinstance(entry, dict):
                raise ToolError("every item must be an object with kind, id and argv")
            expect(entry, CHANGE_KEYS)
            try:
                argv = signing.task_argv(entry["id"], entry["argv"])
            except signing.Refused as error:
                raise ToolError(f"{entry['id']!s:.200}: {error}") from None
            row = tasks.get(entry["id"])
            if row is None:
                raise Missing(entry["id"])
            if not changeable(entry["id"], row, argv):
                raise Conflict({"id": entry["id"], "status": status_of(row)})
            item = signing.task_item(entry["id"], argv)
            if item in signed:
                raise ToolError("items must be distinct")
            signed.append(item)
        return signed

    def tell_workers(self, items: list[dict]) -> list[str]:
        """Returns:
            The radio addresses that got one post listing the operator's
            changes to their rows.
        """
        claims = read_claims(self.council)
        told = []
        for worker, commands in affected(items, read_register(self.council / REGISTER)).items():
            address = requester_of(claims, worker)[1]
            if address and self.scripts.run(RADIO, ["post", "--to", address, "--session", HUMAN, f"{TOLD}: {'; '.join(commands)}"])["code"] == 0:
                told.append(address)
        return told

    def tell_applied(self, job: dict) -> list[str]:
        """Args:
            job: a task job that just ended.

        Returns:
            The radio addresses told once the last job of its signed batch
            ended: one post per worker listing the changes rasci.py applied
            (exit 0); a change it refused, the runner refused or a job
            still open tells nobody, and a batch is told once.
        """
        with self.jobs.changed:
            batch = sorted((other for other in self.jobs.listed() if other.get("batch") == job.get("batch")), key=lambda other: other["created_ts"])
            if job.get("batch") is None or any(other["status"] in JOB_OPEN or other.get("told") for other in batch):
                return []
            self.jobs.change(batch[0]["id"], {"told": True})
        return self.tell_workers([{"id": other["task"], "argv": other["argv"]} for other in batch if other["status"] == "done"])

    def change_tasks(self, body: bytes) -> dict:
        payload = decode(body)
        expect(payload, ("items", "proof"))
        items = self.task_changes(payload["items"])
        proof = self.covered(payload["proof"], items, time.time())
        for item in items:
            self.operator_proven(proof, item)
        ids = []
        batch = secrets.token_hex(8)
        for item in items:
            fields = {"kind": TASK_JOB, "task": item["id"], "argv": item["argv"], "command": shown_command(item["argv"]), "directory": "", "sha256": "", "status": "queued", "proof": proof, "batch": batch}
            ids.append(self.jobs.add({**fields, "code": None, "output": "", "created_ts": time.time(), "started": None, "finished": None})["id"])
        commands = [shown_command(item["argv"]) for item in items]
        self.log.add({"kind": "run", "title": f"Task change signed: {', '.join(item['id'] for item in items)}"[:200], "text": "\n".join(commands), "ref": {"jobs": ids, "status": "queued"}})
        return {"jobs": ids, "status": "queued"}
