from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DISPATCHER = REPO_ROOT / "skills" / "kvb-org-organize" / "scripts" / "hooks.py"
SCRIPTS = {
    "radio": "kvb-org-radio/scripts/radio.py",
    "watch": "kvb-org-organize/scripts/watch.py",
    "queue": "kvb-org-queue/scripts/queue.py",
    "graph": "kvb-agent-optimize/scripts/graph.py",
    "log": "kvb-org-perform/scripts/log.py",
}
FAKE = """import json, os, sys
NAME = {name!r}


def main():
    event = json.load(sys.stdin)
    with open(os.environ["HOOK_LOG"], "a", encoding="utf-8") as log:
        log.write(json.dumps([NAME, sys.argv[1:], event["tool_input"]["command"]]) + "\\n")
    plan = json.loads(os.environ.get("HOOK_PLAN", "{{}}")).get(NAME, {{}})
    if plan.get("crash"):
        raise RuntimeError(NAME + " broke")
    if plan.get("out"):
        print(plan["out"])
    if plan.get("err"):
        print(plan["err"], file=sys.stderr)
    if "exit" in plan:
        sys.exit(plan["exit"])
    return plan.get("code", 0)
"""
ASK = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask", "permissionDecisionReason": "held command meets an ask rule"}}


class TestHooks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        target = self.root / "kvb-org-organize" / "scripts" / "hooks.py"
        target.parent.mkdir(parents=True)
        shutil.copy(DISPATCHER, target)
        for name, script in SCRIPTS.items():
            path = self.root / script
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(FAKE.format(name=name), encoding="utf-8")
        self.log = self.root / "log.jsonl"

    def dispatch(self, sub: str, plan: dict) -> subprocess.CompletedProcess:
        self.log.unlink(missing_ok=True)
        event = json.dumps({"session_id": "s", "hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "make test"}})
        env = {**os.environ, "HOOK_LOG": str(self.log), "HOOK_PLAN": json.dumps(plan)}
        return subprocess.run(["/usr/bin/python3", "-I", str(self.root / "kvb-org-organize" / "scripts" / "hooks.py"), sub], input=event, env=env, capture_output=True, text=True, timeout=60, check=False)

    def ran(self) -> list[list]:
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]

    def test_each_event_runs_its_handlers_in_order_with_the_same_event_and_their_own_subcommand(self):
        self.assertEqual(self.dispatch("pre-bash", {}).returncode, 0)
        self.assertEqual(self.ran(), [["radio", ["block"], "make test"], ["watch", ["block"], "make test"], ["queue", ["block"], "make test"], ["graph", ["hook"], "make test"]])
        self.assertEqual(self.dispatch("post-bash", {}).returncode, 0)
        self.assertEqual(self.ran(), [["watch", ["watch"], "make test"], ["log", ["persist"], "make test"]])

    def test_exit_two_blocks_with_the_text_of_every_blocking_handler_after_all_ran(self):
        done = self.dispatch("pre-bash", {"watch": {"code": 2, "err": "watch: disk full"}, "queue": {"exit": 2, "err": "queue: through the queue"}, "graph": {"out": json.dumps({"systemMessage": "graph"})}})
        self.assertEqual((done.returncode, done.stdout, done.stderr), (2, "", "watch: disk full\nqueue: through the queue\n"))
        self.assertEqual([name for name, _, _ in self.ran()], ["radio", "watch", "queue", "graph"])

    def test_a_crash_leaves_the_other_handlers_running_and_their_answers_merged(self):
        context = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": "watch: alert"}}
        done = self.dispatch("pre-bash", {"radio": {"crash": True}, "watch": {"out": json.dumps(context)}, "queue": {"out": json.dumps(ASK)}, "graph": {"out": json.dumps({"systemMessage": "graph: notice"})}})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("RuntimeError: radio broke", done.stderr)
        self.assertEqual([name for name, _, _ in self.ran()], ["radio", "watch", "queue", "graph"])
        self.assertEqual(json.loads(done.stdout), {
            "hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": "watch: alert", "permissionDecision": "ask", "permissionDecisionReason": "held command meets an ask rule"},
            "systemMessage": "graph: notice",
        })

    def test_a_single_answer_passes_through_unchanged_and_plain_text_goes_to_stderr(self):
        done = self.dispatch("pre-bash", {"queue": {"out": json.dumps(ASK)}, "graph": {"out": "plain words"}})
        self.assertEqual((done.returncode, json.loads(done.stdout)), (0, ASK))
        self.assertEqual(done.stderr, "plain words\n")

    def test_a_missing_handler_is_skipped_and_an_unknown_event_is_refused(self):
        (self.root / SCRIPTS["queue"]).unlink()
        self.assertEqual(self.dispatch("pre-bash", {}).returncode, 0)
        self.assertEqual([name for name, _, _ in self.ran()], ["radio", "watch", "graph"])
        refused = self.dispatch("stop", {})
        self.assertEqual(refused.returncode, 1)
        self.assertIn("usage: hooks.py pre-bash|post-bash", refused.stderr)


if __name__ == "__main__":
    unittest.main()
