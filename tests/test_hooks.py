from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from review_support import change, fixture, git, hub, hub_home, install, review

REPO_ROOT = Path(__file__).resolve().parents[1]
DISPATCHER = REPO_ROOT / "skills" / "kvb-org-organize" / "scripts" / "hooks.py"
SCRIPTS = {
    "radio": "kvb-org-radio/scripts/radio.py",
    "watch": "kvb-org-organize/scripts/watch.py",
    "queue": "kvb-org-queue/scripts/queue.py",
    "graph": "kvb-agent-optimize/scripts/graph.py",
    "review": "kvb-code-review/scripts/review_hook.py",
    "log": "kvb-org-perform/scripts/log.py",
}
PRE_BASH = ["radio", "watch", "queue", "graph", "review"]
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
        self.assertEqual(self.ran(), [["radio", ["block"], "make test"], ["watch", ["block"], "make test"], ["queue", ["block"], "make test"], ["graph", ["hook"], "make test"], ["review", ["hook"], "make test"]])
        self.assertEqual(self.dispatch("post-bash", {}).returncode, 0)
        self.assertEqual(self.ran(), [["watch", ["watch"], "make test"], ["log", ["persist"], "make test"]])

    def test_exit_two_blocks_with_the_text_of_every_blocking_handler_after_all_ran(self):
        done = self.dispatch("pre-bash", {"watch": {"code": 2, "err": "watch: disk full"}, "queue": {"exit": 2, "err": "queue: through the queue"}, "graph": {"out": json.dumps({"systemMessage": "graph"})}})
        self.assertEqual((done.returncode, done.stdout, done.stderr), (2, "", "watch: disk full\nqueue: through the queue\n"))
        self.assertEqual([name for name, _, _ in self.ran()], PRE_BASH)

    def test_a_crash_leaves_the_other_handlers_running_and_their_answers_merged(self):
        context = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": "watch: alert"}}
        done = self.dispatch("pre-bash", {"radio": {"crash": True}, "watch": {"out": json.dumps(context)}, "queue": {"out": json.dumps(ASK)}, "graph": {"out": json.dumps({"systemMessage": "graph: notice"})}})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("RuntimeError: radio broke", done.stderr)
        self.assertEqual([name for name, _, _ in self.ran()], PRE_BASH)
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
        self.assertEqual([name for name, _, _ in self.ran()], ["radio", "watch", "graph", "review"])
        refused = self.dispatch("stop", {})
        self.assertEqual(refused.returncode, 1)
        self.assertIn("usage: hooks.py pre-bash|post-bash", refused.stderr)


class TestReviewHook(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = install(self.root, with_quality=False)
        shutil.rmtree(self.root / "skills" / "kvb-org-queue")
        target = self.root / "skills" / "kvb-org-organize" / "scripts" / "hooks.py"
        target.parent.mkdir(parents=True)
        shutil.copy(DISPATCHER, target)
        self.repo = fixture(self.root)
        self.target = f"range {git(self.repo, 'rev-parse', '@{u}').strip()}..HEAD"

    def dispatch(self, command: str) -> subprocess.CompletedProcess:
        event = json.dumps({"session_id": "s", "hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command}})
        hooks = self.root / "skills" / "kvb-org-organize" / "scripts" / "hooks.py"
        return subprocess.run(["/usr/bin/python3", "-I", str(hooks), "pre-bash"], input=event, env=self.env, capture_output=True, text=True, timeout=60, check=False)

    def push_row(self, check: str, command: str = "gipsn") -> str:
        return f"/x/kvb-org-operator/scripts/operator.py add skills-push --dir {self.repo} --command {shlex.quote(command)} --reason 'push it' --check {check}"

    def ok(self, *args: str) -> str:
        done = review(self.root, self.env, *args)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def stamp_clean(self) -> None:
        self.ok("run", "--repo", str(self.repo), "--target", self.target)
        empty = self.root / "empty.json"
        empty.write_text("[]", encoding="utf-8")
        for lens in ("standards", "legal"):
            self.ok("record", "--repo", str(self.repo), "--target", self.target, "--lens", lens, "--findings", str(empty))
        self.ok("stamp", "--repo", str(self.repo), "--target", self.target)

    def test_a_push_row_without_a_clean_stamp_is_refused(self):
        done = self.dispatch(self.push_row(f"pushed:{self.repo}"))
        self.assertEqual(done.returncode, 2)
        self.assertIn("kvb-code-review: no clean review for tree", done.stderr)

    def test_a_clean_stamp_lets_the_push_row_through_until_the_tree_changes(self):
        self.stamp_clean()
        self.assertEqual(self.dispatch(self.push_row(f"pushed:{self.repo}")).returncode, 0)
        change(self.repo, {"src/app.py": "VALUE = 8\n"}, "later")
        self.assertEqual(self.dispatch(self.push_row(f"pushed:{self.repo}")).returncode, 2)

    def test_a_stamp_file_that_holds_no_object_refuses_instead_of_crashing_open(self):
        self.stamp_clean()
        (self.repo / ".git" / "kvb-review.json").write_text("[]", encoding="utf-8")
        done = self.dispatch(self.push_row(f"pushed:{self.repo}"))
        self.assertEqual(done.returncode, 2)
        self.assertIn("holds no JSON object", done.stderr)

    def test_other_commands_and_other_rows_pass_untouched(self):
        for command in ("git status", self.push_row("manual", "make install"), f"echo pushed:{self.repo}", "git push origin master"):
            self.assertEqual(self.dispatch(command).returncode, 0, command)

    def test_a_row_whose_command_pushes_needs_the_stamp_whatever_its_check(self):
        commands = ("gipsn", "git push --no-verify origin HEAD:refs/heads/x", "git -c x=y push", "/usr/bin/git-sign-push", 'sh -c "git push"', "bash -c 'cd x && sh -c \"git push\"'")
        rows = [self.push_row("manual", command) for command in commands]
        for row in rows:
            done = self.dispatch(row)
            self.assertEqual(done.returncode, 2, row)
            self.assertIn("no clean review for tree", done.stderr)
        self.stamp_clean()
        for row in rows:
            self.assertEqual(self.dispatch(row).returncode, 0, row)

    def waiver(self) -> str:
        question = json.loads(self.ok("question", "--repo", str(self.repo)))["question"]
        return f"Choice for decision d1 ({question}): Waive"

    def test_a_waiver_passes_only_while_the_hub_verifies_it(self):
        answer = self.waiver()
        with hub({"m1": (answer, "Skills")}) as port:
            self.env = hub_home(self.root, self.env, port)
            self.ok("waive", "--repo", str(self.repo), "--message", "m1", "--answer", answer, "--agent", "Skills")
            self.assertEqual(self.dispatch(self.push_row(f"pushed:{self.repo}")).returncode, 0)
        gone = self.dispatch(self.push_row(f"pushed:{self.repo}"))
        self.assertEqual(gone.returncode, 2)
        self.assertIn("the waiver did not verify", gone.stderr)

    def test_a_waiver_aimed_at_another_listener_never_verifies(self):
        answer = self.waiver()
        with hub({}) as installed, hub({"m1": (answer, "Skills")}) as forged:
            self.env = hub_home(self.root, self.env, installed)
            refused = review(self.root, self.env, "waive", "--repo", str(self.repo), "--message", "m1", "--answer", answer, "--agent", "Skills", "--port", str(forged))
            self.assertEqual(refused.returncode, 2)
            stamps = self.repo / ".git" / "kvb-review.json"
            tree = git(self.repo, "rev-parse", "HEAD^{tree}").strip()
            stamps.write_text(json.dumps({tree: {"verdict": "waived", "message": "m1", "answer": answer, "agent": "Skills", "port": forged}}), encoding="utf-8")
            done = self.dispatch(self.push_row(f"pushed:{self.repo}"))
        self.assertEqual(done.returncode, 2)
        self.assertIn("the waiver did not verify", done.stderr)

    def test_a_waiver_without_an_installed_hub_is_refused(self):
        done = review(self.root, {**self.env, "HOME": str(self.root / "no-home")}, "waive", "--repo", str(self.repo), "--message", "m1", "--answer", self.waiver(), "--agent", "Skills")
        self.assertEqual(done.returncode, 2)
        self.assertIn("no installed hub", done.stderr)


if __name__ == "__main__":
    unittest.main()
