from __future__ import annotations

import time

from .errors import Conflict, Missing, ToolError
from .fields import bounded, decode, expect, field
from .register import OPERATOR, REGISTER, operator_rows, read_register, runnable
from .signed import operator_signed
from .skill_scripts import OPERATOR_SCRIPT, OUTPUT_LIMIT

JOB_OPEN = ("queued", "running")
RUN_OUTPUT = 64 << 10
CONSOLE = ("id", "status", "code", "output", "created_ts", "started", "finished")


def runner_job(job: dict) -> dict:
    return {**{key: job[key] for key in ("id", "task", "command", "directory", "sha256")}, "proof": job.get("proof")}


def console_of(job: dict | None) -> dict | None:
    return None if job is None else {**{key: job[key] for key in CONSOLE}, "output": job["output"][-OUTPUT_LIMIT:]}


class Jobs:
    def open_jobs(self) -> set[str]:
        return {job["task"] for job in self.jobs.listed() if job["status"] in JOB_OPEN}

    def consoles(self) -> dict[str, dict]:
        latest: dict[str, dict] = {}
        for job in sorted(self.jobs.listed(), key=lambda job: job["created_ts"]):
            latest[job["task"]] = job
        # Trip-wire: jobs queued before the inbox console carry no dismissed key and must not flood the inbox after an upgrade.
        return {task: job for task, job in latest.items() if job.get("dismissed") is False}

    def dismiss(self, body: bytes) -> dict:
        payload = decode(body)
        expect(payload, ("id",))
        job_id = field(payload, "id")
        record = self.jobs.get(job_id)
        if record is None:
            raise Missing(job_id)
        if record["status"] in JOB_OPEN:
            raise Conflict({"id": job_id, "status": record["status"]})
        self.jobs.change(job_id, {"dismissed": True})
        return {"id": job_id, "dismissed": True}

    def queue_job(self, item: dict, proof: dict | None) -> str:
        row = next((row for row in operator_rows(read_register(self.council / REGISTER)) if row["task"] == item["id"]), None)
        if row is None or not runnable(row) or operator_signed(row) != item["signed"]:
            return "verweigert: die Zeile hat sich seit der Freigabe geändert"
        if item["id"] in self.open_jobs():
            return "läuft schon"
        job = {"task": row["task"], "command": row["command"], "directory": row["directory"], "sha256": item["sha256"], "status": "queued", "proof": proof}
        self.jobs.add({**job, "code": None, "output": "", "created_ts": time.time(), "started": None, "finished": None, "dismissed": False})
        return "an den Runner übergeben"

    def runner_jobs(self) -> dict:
        return {"jobs": [runner_job(job) for job in self.jobs.listed() if job["status"] == "queued"]}

    def claim(self, job_id: str) -> dict:
        job, changed = self.jobs.transition(job_id, "queued", {"status": "running", "started": time.time()})
        if job is None:
            raise Missing(job_id)
        if not changed:
            raise Conflict({"id": job_id, "status": job["status"]})
        return runner_job(job)

    def report(self, job_id: str, body: bytes) -> dict:
        payload = decode(body)
        expect(payload, ("output", "code", "refused"))
        output, code, refused = bounded(payload, "output", RUN_OUTPUT), payload["code"], payload["refused"]
        if not isinstance(refused, bool) or (code is not None and (isinstance(code, bool) or not isinstance(code, int))):
            raise ToolError("code must be a whole number or null and refused true or false")
        record = self.jobs.get(job_id)
        if record is None:
            raise Missing(job_id)
        if record["status"] != "running":
            raise Conflict({"id": job_id, "status": record["status"]})
        if code is None and not refused:
            self.jobs.change(job_id, {"output": output})
            return {"id": job_id, "status": "running", "code": None}
        status = "refused" if refused else "done" if code == 0 else "failed"
        job, changed = self.jobs.transition(job_id, "running", {"status": status, "code": code, "output": output, "finished": time.time()})
        if not changed:
            raise Conflict({"id": job_id, "status": job["status"]})
        runs = [self.scripts.run(OPERATOR_SCRIPT, ["done", job["task"].removeprefix(OPERATOR)])] if status == "done" else []
        tail = "\n".join(output.splitlines()[-20:])
        self.log.add({"kind": "run", "title": f"{status}: {job['command'][:200]}", "text": tail, "ref": {"job": job_id, "task": job["task"], "code": code, "status": status}})
        return {"id": job_id, "status": status, "code": code, "runs": runs}
