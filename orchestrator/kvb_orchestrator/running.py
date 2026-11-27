from __future__ import annotations

from pathlib import Path

from .records import epoch, read_json
from .tasks import TEXT_SHOWN

RUNNER_JOB = "runner-job.json"
RUNNING = "running"


def running_job(path: Path, jobs: list[dict]) -> dict | None:
    """Args:
        path: runner-job.json in the hub state dir, {pid, job, task,
            started}, which client/runner.py keeps while it runs a job.
        jobs: the hub's job records.

    Returns:
        {job, task, started, command} of the job the marker names, started
        in epoch seconds and command that job's command, empty when the
        hub holds no record of it; None when the marker is missing, a link,
        malformed, or names a job the hub records as no longer running.
    """
    data = read_json(path)
    if not isinstance(data, dict):
        return None
    job, task, started = data.get("job"), data.get("task"), epoch(data.get("started"))
    if not (isinstance(job, str) and job and isinstance(task, str) and task and started is not None):
        return None
    record = next((row for row in jobs if row.get("id") == job), None)
    if record is not None and record.get("status") != RUNNING:
        return None
    command = record.get("command") if record is not None else ""
    return {"job": job[:TEXT_SHOWN], "task": task[:TEXT_SHOWN], "started": started, "command": command[:TEXT_SHOWN] if isinstance(command, str) else ""}
