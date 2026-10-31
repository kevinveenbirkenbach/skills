"""Exercise the subagent-model log: spawn hook, feedback, sandbox persist, report."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LOG_PY = REPO_ROOT / "skills" / "subagent-model" / "scripts" / "log.py"


class TestSubagentModelLog(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.log = self.base / "state" / "subagent-model.jsonl"

    def _run(self, *args: str, stdin: str = "", log: Path | None = None) -> subprocess.CompletedProcess:
        env = {"SUBAGENT_MODEL_LOG": str(log or self.log), "CLAUDE_CODE_SESSION_ID": "s1"}
        return subprocess.run(
            [sys.executable, str(LOG_PY), *args], capture_output=True, text=True, env=env, input=stdin, check=False
        )

    def _spawn(self, description: str, prompt: str, **tool: str) -> None:
        payload = {"session_id": "s1", "tool_input": {"description": description, "prompt": prompt, **tool}}
        self.assertEqual(self._run("spawn", stdin=json.dumps(payload)).returncode, 0)

    def _feedback(self, description: str, completed: str = "yes", redo: str = "no", tests: str = "none") -> None:
        result = self._run(
            "feedback", "--description", description, "--completed", completed, "--tests", tests, "--redo", redo
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def _lines(self) -> list[dict]:
        return [json.loads(text) for text in self.log.read_text(encoding="utf-8").splitlines()]

    def _report(self) -> dict[str, list[str]]:
        rows = self._run("report").stdout.splitlines()[1:]
        return {row.split("\t")[0]: row.split("\t") for row in rows}

    def test_spawn_logs_class_model_and_effort_or_the_defaults(self):
        self._spawn("find callers", "task-class: lookup\nFind every caller.", model="haiku", effort="low")
        self._spawn("fix it", "Find the root cause.")
        first, second = self._lines()
        self.assertEqual((first["task_class"], first["model"], first["effort"]), ("lookup", "haiku", "low"))
        self.assertEqual((second["task_class"], second["model"], second["effort"]), ("unclassified", "default", "default"))

    def _pending_feedback(self) -> str:
        blocked = self.base / "file"
        blocked.write_text("", encoding="utf-8")
        result = self._run(
            "feedback", "--description", "d", "--completed", "yes", "--tests", "none", "--redo", "no",
            log=blocked / "log.jsonl",
        )
        self.assertTrue(result.stdout.startswith("pending: "), result.stdout)
        return result.stdout

    def _persist(self, command: str, stdout: str, session: str = "s1") -> None:
        payload = {"session_id": session, "tool_input": {"command": command}, "tool_response": {"stdout": stdout}}
        self.assertEqual(self._run("persist", stdin=json.dumps(payload)).returncode, 0)

    def test_sandboxed_feedback_is_printed_and_stored_by_the_persist_hook(self):
        stdout = self._pending_feedback()
        self._persist("python3 /x/skills/subagent-model/scripts/log.py feedback --description 'd'", stdout)
        self.assertEqual(self._lines()[0]["kind"], "feedback")

    def test_persist_rejects_pending_lines_it_did_not_get_from_a_bare_log_call(self):
        stdout = self._pending_feedback()
        line = json.loads(stdout[len("pending: "):])
        call = "/x/skills/subagent-model/scripts/log.py feedback --description d"
        for command, output, session in (
            ("cat ci.log", stdout, "s1"),
            (f"{call}; cat ci.log", stdout, "s1"),
            (f"{call} | tee /tmp/x", stdout, "s1"),
            (f"echo $({call})", stdout, "s1"),
            (call, stdout, "other-session"),
            (call, stdout + stdout, "s1"),
            (call, "pending: " + json.dumps({**line, "extra": 1}), "s1"),
            (call, "pending: " + json.dumps({**line, "completed": "yes"}), "s1"),
            ("/x/skills/subagent-model/scripts/log.py followup --description d", stdout, "s1"),
        ):
            self._persist(command, output, session)
        self.assertFalse(self.log.exists())

    def test_report_qualifies_a_row_only_at_ninety_percent_over_twenty_rated_runs(self):
        for i in range(20):
            self._spawn(f"q{i}", "task-class: lookup", model="haiku", effort="low")
            self._feedback(f"q{i}", redo="yes" if i < 2 else "no")
        for i in range(19):
            self._spawn(f"r{i}", "task-class: mechanical-edit", model="haiku", effort="low")
            self._feedback(f"r{i}")
        self._run("followup", "--description", "q5", "--text", "that list missed a caller")
        report = self._report()
        self.assertEqual(report["lookup"][3:], ["20", "20", "17", "85%", "no"])
        self.assertEqual(report["mechanical-edit"][3:], ["19", "19", "19", "100%", "no"])
        self._spawn("r19", "task-class: mechanical-edit", model="haiku", effort="low")
        self._feedback("r19")
        self.assertEqual(self._report()["mechanical-edit"][-1], "yes")


if __name__ == "__main__":
    unittest.main()
