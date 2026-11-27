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
TASK_JOB = "task"
GATE_JOB = "gate"
CHANGES = (TASK_JOB, GATE_JOB)
UNRUNNABLE = "The hub runner needs a command and an absolute directory, and this row lacks one; run it with operator.py run in a terminal."
RESTARTED = "the runner restarted while this job ran; run the row again"


def runner_job(job: dict) -> dict:
    """Returns:
        What the runner claims: an operator command, with head when a Match
        release bound it to a merge preview of that HEAD, or a task or gate
        change with kind and argv; a runner that predates such changes
        verifies them as an operator command and refuses them.
    """
    change = {"kind": job["kind"], "argv": job["argv"]} if job.get("kind") in CHANGES else {}
    head = {"head": job["head"]} if job.get("head") else {}
    return {**{key: job[key] for key in ("id", "task", "command", "directory", "sha256")}, **change, **head, "proof": job.get("proof")}


def console_of(job: dict | None) -> dict | None:
    return None if job is None else {**{key: job[key] for key in CONSOLE}, "output": job["output"][-OUTPUT_LIMIT:]}


def minutes_since(ts: float | None, now: float) -> int:
    return max(0, round((now - (ts or now)) / 60))


def blocked_reasons(jobs: list[dict], now: float) -> dict[str, str]:
    """Args:
        jobs: every hub job record.

    Returns:
        Per task with a queued or running job why its row cannot be run or
        denied now: how long the runner runs it, or how long it waits and
        which job the runner, which runs one job at a time, started last.
    """
    open_jobs = [job for job in jobs if job["status"] in JOB_OPEN]
    running = max((job for job in open_jobs if job["status"] == "running"), key=lambda job: job["started"] or 0, default=None)
    ahead = "" if running is None else f" behind {running['task']}, which runs for {minutes_since(running['started'], now)} min"
    reasons = {}
    for job in sorted(open_jobs, key=lambda job: job["created_ts"]):
        if job["status"] == "running":
            reasons[job["task"]] = f"The hub runner runs it for {minutes_since(job['started'], now)} min; its result comes in Waits on Operator."
        else:
            reasons[job["task"]] = f"Queued in the hub runner for {minutes_since(job['created_ts'], now)} min{ahead}; the runner runs one job at a time."
    return reasons


def row_blocked(row: dict, reasons: dict[str, str]) -> str:
    """Args:
        row: an open operator row.
        reasons: blocked_reasons() of the hub jobs.

    Returns:
        Why no area can run or deny the row now, "" when one can: its open
        hub job, else for a command row without a command or an absolute
        directory UNRUNNABLE; a decision row is answered, never run.
    """
    return reasons.get(row["task"]) or ("" if row["check"] == "decision" or runnable(row) else UNRUNNABLE)


class Jobs:
    def open_jobs(self) -> set[str]:
        return {job["task"] for job in self.jobs.listed() if job["status"] in JOB_OPEN}

    def blocked_rows(self, now: float) -> dict[str, str]:
        return blocked_reasons(self.jobs.listed(), now)

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
        if record.get("kind") in CHANGES:
            self.jobs.change(job_id, {"dismissed": True})
        else:
            self.jobs.keep(lambda job: job.get("kind") in CHANGES or job["status"] in JOB_OPEN or (job["task"] != record["task"] and job.get("dismissed") is not True))
        return {"id": job_id, "dismissed": True}

    def queue_job(self, item: dict, proof: dict | None) -> str:
        row = next((row for row in operator_rows(read_register(self.council / REGISTER)) if row["task"] == item["id"]), None)
        if row is None or not runnable(row) or operator_signed(row) != item["signed"]:
            return "refused: the row changed since the grant"
        if item["id"] in self.open_jobs():
            return "already running"
        head = self.previewed_head(row["task"], row["command"]) if item.get("bound") else ""
        job = {"task": row["task"], "command": row["command"], "directory": row["directory"], "sha256": item["sha256"], "status": "queued", "proof": proof, "head": head}
        self.jobs.add({**job, "code": None, "output": "", "created_ts": time.time(), "started": None, "finished": None, "dismissed": False})
        return "handed to the runner"

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
        """Args:
            body: {"output", "code", "refused"}, and "checked" on an operator
                command's final report after exit 0: whether its row's check
                passed on the host, null when the runner could not tell.
        """
        payload = decode(body)
        expect(payload, ("output", "code", "refused", "checked") if "checked" in payload else ("output", "code", "refused"))
        output, code, refused = bounded(payload, "output", RUN_OUTPUT), payload["code"], payload["refused"]
        checked = payload.get("checked")
        if not isinstance(refused, bool) or (code is not None and (isinstance(code, bool) or not isinstance(code, int))):
            raise ToolError("code must be a whole number or null and refused true or false")
        if checked is not None and not isinstance(checked, bool):
            raise ToolError("checked must be true, false or null")
        record = self.jobs.get(job_id)
        if record is None:
            raise Missing(job_id)
        if record["status"] != "running":
            raise Conflict({"id": job_id, "status": record["status"]})
        if code is None and not refused:
            self.jobs.note(job_id, {"output": output})
            return {"id": job_id, "status": "running", "code": None}
        status = "refused" if refused else "done" if code == 0 else "failed"
        job, changed = self.jobs.transition(job_id, "running", {"status": status, "code": code, "output": output, "finished": time.time()})
        if not changed:
            raise Conflict({"id": job_id, "status": job["status"]})
        return self.ended(job, checked is True)

    def restart_runner(self) -> dict:
        """Returns:
            {"failed": ids}: every running job, which the restart of the
            runner killed, turned failed with RESTARTED as its output, code
            None and finished now, its row closed like a failed run.
        """
        failed = []
        for job in self.jobs.listed():
            record, changed = self.jobs.transition(job["id"], "running", {"status": "failed", "code": None, "output": RESTARTED, "finished": time.time()})
            if changed:
                self.ended(record, False)
                failed.append(job["id"])
        return {"failed": failed}

    def ended(self, job: dict, checked: bool) -> dict:
        """Args:
            job: a job that just left running, with its status, code and
                output.
            checked: as in close_row().

        Returns:
            {"id", "status", "code", "runs", "told"} after its row closed
            (close_row()), the run went to the log and, for a task change,
            its batch was told (tell_applied()).
        """
        status, code = job["status"], job["code"]
        runs = self.close_row(job, status, code, checked)
        tail = "\n".join(job["output"].splitlines()[-20:])
        self.log.add({"kind": "run", "title": f"{status}: {job['command'][:200]}", "text": tail, "ref": {"job": job["id"], "task": job["task"], "code": code, "status": status}})
        told = self.tell_applied(job) if job.get("kind") == TASK_JOB else []
        return {"id": job["id"], "status": status, "code": code, "runs": runs, "told": told}

    def close_row(self, job: dict, status: str, code: int | None, checked: bool) -> list[dict]:
        """Args:
            checked: whether the runner saw the row's check pass on the host
                after exit 0; the hub cannot read the host's repos, PATH and
                installed dirs itself.

        Returns:
            The operator.py runs that report the end of an operator command
            job on its row: `ran` on exit 0, with --check-failed unless
            checked, so the row stays open; `failed` with where the output
            stays, the job's console, never the output itself, on any other
            exit and, why RESTARTED, on a failed job without code, which a
            runner restart killed; none for a refused job or a task or gate
            change.
        """
        if job.get("kind") in CHANGES or status not in ("done", "failed"):
            return []
        slug = job["task"].removeprefix(OPERATOR)
        shown = [slug, f"--command={job['command']}", f"--dir={job['directory']}"]
        if status == "failed":
            why = RESTARTED if code is None else f"killed by signal {-code}" if code < 0 else f"exit {code}"
            where = f"the console of hub job {job['id']} under the row in Waits on Operator"
            return [self.scripts.run(OPERATOR_SCRIPT, ["failed", *shown, "--why", why, f"--where={where}"])]
        return [self.scripts.run(OPERATOR_SCRIPT, ["ran", *shown] if checked else ["ran", *shown, "--check-failed"])]
