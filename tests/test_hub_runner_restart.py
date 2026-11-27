from __future__ import annotations

import contextlib
import http.server
import io
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from hub_support import LOGIN_SHELL, runner

JOB = "0123456789abcdef"
FAILED = "fedcba9876543210"


class Answer(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.server.seen.append(("GET", self.path))
        self.reply(200, {"jobs": self.server.jobs} if self.path == "/api/runner/jobs" else {"rows": [], "reviews": []})

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.seen.append(("POST", self.path))
        if self.path == runner.RESTART:
            self.reply(self.server.restart, {"failed": []})
        elif self.path.endswith("/claim"):
            self.reply(200, next(job for job in self.server.jobs if f"/{job['id']}/" in self.path))
        else:
            self.server.reports.append((self.path.split("/")[3], body))
            self.reply(200, {})

    def reply(self, status: int, payload: dict) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_args: object) -> None:
        return


class FakeHub(http.server.ThreadingHTTPServer):
    def __init__(self, jobs: list[dict], restart: int) -> None:
        """Args:
            jobs: what /api/runner/jobs lists and each claim hands out.
            restart: the HTTP status /api/runner/restart answers.
        """
        super().__init__(("127.0.0.1", 0), Answer)
        self.jobs = jobs
        self.restart = restart
        self.seen: list[tuple[str, str]] = []
        self.reports: list[tuple[str, dict]] = []


class TestRunnerRestart(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.state = self.base / "state"
        self.state.mkdir()
        self.marker = self.state / runner.MARKER
        self.shell = self.base / "login-shell"
        self.shell.write_text(LOGIN_SHELL, encoding="utf-8")
        self.shell.chmod(0o755)
        self.host = runner.Host(shell=str(self.shell), operator=None, council=None, marker=self.marker)
        self.trust = runner.verifier.Trust(approvers=self.base / "approvers.json", replay=self.base / "replay.json", origin="http://localhost:1")

    def hub(self, jobs: list[dict], restart: int) -> FakeHub:
        hub = FakeHub(jobs, restart)
        threading.Thread(target=hub.serve_forever, args=(0.05,), daemon=True).start()
        self.addCleanup(hub.server_close)
        self.addCleanup(hub.shutdown)
        return hub

    def job(self, job_id: str, command: str) -> dict:
        return {"id": job_id, "task": "operator/push", "command": command, "directory": str(self.base), "sha256": "", "proof": None}

    def start(self, hub: FakeHub) -> tuple[int, str]:
        argv = ["runner", "--port", str(hub.server_address[1]), "--interval", "0.1", "--approvers", str(self.base / "approvers.json"), "--replay", str(self.base / "replay.json"), "--state", str(self.state), "--once"]
        stderr = io.StringIO()
        with mock.patch.object(sys, "argv", argv), contextlib.redirect_stderr(stderr):
            code = runner.main()
        return code, stderr.getvalue()

    def cycle(self, hub: FakeHub) -> None:
        with mock.patch.object(runner, "refusal", return_value=None):
            runner.cycle(runner.hub_api.base_url(hub.server_address[1]), self.trust, None, None, self.host)

    def finals(self, hub: FakeHub) -> dict[str, dict]:
        return {job_id: body for job_id, body in hub.reports if body["code"] is not None or body["refused"]}

    def test_the_runner_drops_a_leftover_marker_and_has_the_hub_fail_the_earlier_jobs_before_its_first_cycle(self):
        self.marker.write_text(json.dumps({"pid": os.getpid(), "job": JOB, "task": "operator/push", "started": 0}), encoding="utf-8")
        hub = self.hub([], 200)
        self.assertEqual(self.start(hub), (0, ""))
        self.assertFalse(self.marker.exists())
        self.assertEqual(hub.seen[0], ("POST", runner.RESTART))
        self.assertEqual(hub.seen.count(("POST", runner.RESTART)), 1)
        self.assertIn(("GET", "/api/runner/jobs"), hub.seen[1:])

    def test_a_failed_restart_call_is_printed_once_and_the_runner_goes_on(self):
        hub = self.hub([], 500)
        code, stderr = self.start(hub)
        self.assertEqual(code, 0)
        self.assertEqual([line for line in stderr.splitlines() if "earlier runner" in line], ["runner: the hub keeps the jobs an earlier runner left running: HTTP Error 500: Internal Server Error"])
        self.assertIn(("GET", "/api/runner/jobs"), hub.seen)

    def test_the_runner_keeps_the_marker_while_a_job_runs_and_removes_it_whatever_the_outcome(self):
        hub = self.hub([self.job(JOB, f'stat -c %a "{self.marker}" && cat "{self.marker}"'), self.job(FAILED, f'test -f "{self.marker}" && exit 3')], 200)
        before = time.time()
        self.cycle(hub)
        finals = self.finals(hub)
        self.assertEqual((finals[JOB]["code"], finals[FAILED]["code"]), (0, 3))
        mode, text = finals[JOB]["output"].split("\n", 1)
        held = json.loads(text)
        self.assertEqual((mode, held["pid"], held["job"], held["task"]), ("600", os.getpid(), JOB, "operator/push"))
        self.assertTrue(before <= held["started"] <= time.time(), held)
        self.assertFalse(self.marker.exists())
        seen = []

        def broken(*_args: object) -> int:
            seen.append(json.loads(self.marker.read_text(encoding="utf-8"))["job"])
            raise RuntimeError("the hub is gone")

        hub.jobs[:] = [self.job(JOB, "true")]
        with mock.patch.object(runner, "execute", broken):
            self.assertRaises(RuntimeError, self.cycle, hub)
        self.assertEqual(seen, [JOB])
        self.assertFalse(self.marker.exists())

    def test_a_job_whose_marker_cannot_be_written_is_refused_and_never_runs(self):
        ran = self.base / "ran"
        hub = self.hub([self.job(JOB, f'touch "{ran}"')], 200)
        with mock.patch.object(runner.verifier, "write_private", side_effect=OSError("disk full")):
            self.cycle(hub)
        final = self.finals(hub)[JOB]
        self.assertEqual((final["refused"], final["code"]), (True, None))
        self.assertTrue(final["output"].startswith(f"refused: the runner cannot write {self.marker}"), final["output"])
        self.assertIn("disk full", final["output"])
        self.assertFalse(ran.exists() or self.marker.exists())


if __name__ == "__main__":
    unittest.main()
