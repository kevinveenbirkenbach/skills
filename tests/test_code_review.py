from __future__ import annotations

import json
import re
import tempfile
import time
import unittest
from pathlib import Path

from review_support import (
    SKILL,
    change,
    fixture,
    git,
    hub,
    hub_home,
    install,
    review,
    starts,
)

HIGH = {"rule": "AGENTS.md:5", "severity": "high", "path": "src/app.py", "line": 1, "message": "comment rule broken", "evidence": "line 1"}
MEDIUM = {**HIGH, "severity": "medium"}


class ReviewCase(unittest.TestCase):
    with_quality = False

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = install(self.root, self.with_quality)
        self.repo = fixture(self.root)
        self.base = git(self.repo, "rev-parse", "@{u}").strip()
        self.target = f"range {self.base}..HEAD"

    def call(self, *args: str):
        return review(self.root, self.env, *args)

    def ok(self, *args: str) -> str:
        done = self.call(*args)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def plan(self) -> dict:
        return json.loads(self.ok("plan", "--repo", str(self.repo), "--target", self.target))

    def record(self, lens: str, findings: list[dict]) -> None:
        path = self.root / f"{lens}.json"
        path.write_text(json.dumps(findings), encoding="utf-8")
        self.ok("record", "--repo", str(self.repo), "--target", self.target, "--lens", lens, "--findings", str(path))

    def judge(self, verdicts: list[dict]) -> None:
        path = self.root / "verdicts.json"
        path.write_text(json.dumps(verdicts), encoding="utf-8")
        self.ok("judge", "--repo", str(self.repo), "--target", self.target, "--verdicts", str(path))

    def reviewed(self, findings: list[dict]) -> None:
        self.ok("run", "--repo", str(self.repo), "--target", self.target)
        self.record("standards", findings)
        self.record("legal", [])

    def lens(self, name: str) -> dict:
        return next(item for item in self.plan()["lenses"] if item["lens"] == name)


class TestTarget(ReviewCase):
    def test_staged_changes_come_first(self):
        (self.repo / "src" / "app.py").write_text("VALUE = 3\n", encoding="utf-8")
        git(self.repo, "add", "src/app.py")
        self.assertEqual(self.ok("target", "--repo", str(self.repo)).strip(), "staged")

    def test_an_open_pull_request_comes_before_the_branch(self):
        self.env["GH_PR"] = json.dumps({"number": 7, "state": "OPEN", "baseRefName": "master", "headRefOid": "x"})
        self.assertEqual(self.ok("target", "--repo", str(self.repo)).strip(), "pr 7")

    def test_commits_ahead_of_the_default_branch_name_the_branch(self):
        git(self.repo, "switch", "-c", "feature")
        change(self.repo, {"src/new.py": "X = 1\n"}, "feature work")
        self.assertEqual(self.ok("target", "--repo", str(self.repo)).strip(), "branch master")

    def test_unpushed_commits_on_the_default_branch_name_the_push_range(self):
        self.assertEqual(self.ok("target", "--repo", str(self.repo)).strip(), f"range {self.base}..HEAD")

    def test_nothing_detected_leaves_the_range_to_the_operator(self):
        git(self.repo, "push")
        self.assertEqual(self.ok("target", "--repo", str(self.repo)).strip(), "range")

    def test_the_first_question_lists_the_four_targets_with_the_detected_one_recommended(self):
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        first = text.index("## Step 1")
        self.assertLess(first, text.index("## Step 2"))
        self.assertIn("the detected one first and marked `(Recommended)`", text)
        labels = [text.index(label, first) for label in ("**Staged changes**", "**Pull request**", "**Branch against the default branch**", "**Commit range**")]
        self.assertEqual(labels, sorted(labels))


class TestLenses(ReviewCase):
    def test_the_standards_lens_names_every_standards_file_and_the_touched_role(self):
        self.reviewed([])
        out = self.call("verdict", "--repo", str(self.repo), "--target", self.target).stdout
        self.assertIn("standards: AGENTS.md, CONTRIBUTING.md, docs/contributing/style.md, roles/web-app-x/AGENTS.md", out)

    def test_every_script_lens_runs_or_is_listed_skipped_with_its_reason(self):
        report = json.loads(self.ok("run", "--repo", str(self.repo), "--target", self.target))
        self.assertEqual(report["quality"]["status"], "skipped")
        self.assertIn("quality is not installed", report["quality"]["reason"])
        self.assertEqual(report["performance"]["status"], "skipped")
        self.assertEqual({report[name]["status"] for name in ("security", "principles")}, {"ran"})
        out = self.call("verdict", "--repo", str(self.repo), "--target", self.target).stdout
        self.assertIn("skipped: quality: quality is not installed", out)
        self.assertIn("skipped: performance: no runnable code to measure", out)

    def test_each_of_the_seven_check_skills_runs_is_skipped_or_feeds_the_score_block(self):
        self.reviewed([])
        out = self.call("verdict", "--repo", str(self.repo), "--target", self.target).stdout
        for shown in ("security (kvb-check-security) ran", "principles (kvb-check-principles) ran", "performance (kvb-check-efficiency) skipped", "legal (kvb-check-legal) ran", "quality skipped", "standards ran"):
            self.assertIn(shown, out)
        self.assertIn("score block (step 5): kvb-check-break-risk, kvb-check-confidence, kvb-check-score", out)

    def test_without_harness_skills_the_verdict_says_harness_none_and_the_own_lenses_still_count(self):
        self.reviewed([])
        out = self.call("verdict", "--repo", str(self.repo), "--target", self.target).stdout
        self.assertIn("harness: none", out)
        self.assertIn("verdict: clean", out)

    def test_listed_harness_skills_are_lenses_the_verdict_waits_for(self):
        self.reviewed([])
        harness = ["--harness", "code-review", "--harness", "security-review"]
        pending = self.call("verdict", "--repo", str(self.repo), "--target", self.target, *harness)
        self.assertEqual(pending.returncode, 1)
        self.assertIn("unreviewed: harness:code-review", pending.stdout)
        for name in ("code-review", "security-review"):
            path = self.root / f"{name}.json"
            path.write_text("[]", encoding="utf-8")
            self.ok("record", "--repo", str(self.repo), "--target", self.target, "--lens", f"harness:{name}", "--findings", str(path), *harness)
        self.assertIn("harness: code-review, security-review", self.ok("verdict", "--repo", str(self.repo), "--target", self.target, *harness))


class TestQualityLens(ReviewCase):
    with_quality = True

    def test_quality_check_runs_with_the_base_of_a_range_and_staged_for_staged_changes(self):
        self.ok("run", "--repo", str(self.repo), "--target", self.target)
        quality = [entry for entry in starts(self.root) if entry[0] == "quality"]
        self.assertEqual(quality[-1][2], ["check", "--base", self.base, "--json"])
        (self.repo / "src" / "app.py").write_text("VALUE = 4\n", encoding="utf-8")
        git(self.repo, "add", "src/app.py")
        self.ok("run", "--repo", str(self.repo), "--target", "staged")
        quality = [entry for entry in starts(self.root) if entry[0] == "quality"]
        self.assertEqual(quality[-1][2], ["check", "--staged", "--json"])


class TestMemory(ReviewCase):
    def test_lenses_start_together_and_heavy_ones_wait_in_the_queue(self):
        self.env["REVIEW_FAKE"] = json.dumps({name: {"sleep": 1} for name in ("security", "principles")})
        self.ok("run", "--repo", str(self.repo), "--target", self.target, "--task", "work/review")
        started = {name: at for name, at, _ in starts(self.root) if name in ("security", "principles")}
        self.assertLess(abs(started["security"] - started["principles"]), 1.0)
        queued = [argv for name, _, argv in starts(self.root) if name == "queue"]
        self.assertEqual(len(queued), 1)
        self.assertIn("security.py", " ".join(queued[0]))

    def test_an_unchanged_tree_starts_no_lens_and_answers_from_memory_within_five_seconds(self):
        self.reviewed([MEDIUM])
        self.judge([{"key": self.plan()["skeptics"][0]["key"], "role": "lens", "verdict": "confirmed", "evidence": "read"}])
        (self.root / "lens.log").unlink()
        began = time.monotonic()
        self.ok("run", "--repo", str(self.repo), "--target", self.target)
        out = self.ok("verdict", "--repo", str(self.repo), "--target", self.target)
        self.assertLess(time.monotonic() - began, 5.0)
        self.assertEqual(starts(self.root), [])
        self.assertEqual(self.plan()["skeptics"], [])
        self.assertIn("comment rule broken", out)

    def test_one_changed_file_reruns_the_file_lens_on_it_alone_and_every_diff_lens(self):
        self.reviewed([])
        change(self.repo, {"src/app.py": "VALUE = 5\nNAME = 'app'\n"}, "again")
        self.assertEqual(self.lens("standards")["missing"], ["src/app.py"])
        self.assertEqual(self.lens("security")["status"], "run")

    def test_a_changed_standards_file_reruns_the_standards_lens_on_every_file(self):
        self.reviewed([])
        change(self.repo, {"CONTRIBUTING.md": "# Contributing\n\nRead the docs twice.\n"}, "rules")
        self.assertEqual(sorted(self.lens("standards")["missing"]), ["CONTRIBUTING.md", "roles/web-app-x/tasks.yml", "src/app.py"])
        self.assertEqual(self.lens("legal")["missing"], ["CONTRIBUTING.md"])

    def test_a_skeptic_verdict_holds_for_the_same_finding_and_never_for_a_changed_flagged_line(self):
        self.reviewed([MEDIUM])
        self.judge([{"key": self.plan()["skeptics"][0]["key"], "role": "lens", "verdict": "confirmed", "evidence": "read"}])
        change(self.repo, {"docs/contributing/style.md": "# Style\n\n## Names\n\nNames say what a thing is, always.\n"}, "rules")
        self.record("standards", [MEDIUM])
        self.assertEqual(self.plan()["skeptics"], [])
        change(self.repo, {"src/app.py": "VALUE = 9\nNAME = 'app'\n"}, "line")
        self.record("standards", [MEDIUM])
        self.assertEqual([item["roles"] for item in self.plan()["skeptics"]], [["lens"]])

    def test_a_brief_holds_the_hunks_and_the_section_index_never_a_whole_standards_file(self):
        text = self.ok("brief", "--repo", str(self.repo), "--target", self.target, "--lens", "standards")
        self.assertIn("+VALUE = 2", text)
        self.assertIn("AGENTS.md:1 # Agents", text)
        self.assertNotIn("The whole agents body sentence", text)
        self.assertNotIn("Read the docs.", text)


class TestVerdictAndStamp(ReviewCase):
    def confirm(self, roles: tuple[str, ...]) -> None:
        key = self.plan()["skeptics"][0]["key"]
        self.judge([{"key": key, "role": role, "verdict": "confirmed", "evidence": "reproduced"} for role in roles])

    def test_a_confirmed_high_finding_blocks(self):
        self.reviewed([HIGH])
        self.assertEqual(self.plan()["skeptics"][0]["roles"], ["lens", "blocker"])
        self.confirm(("lens",))
        self.assertIn("verdict: pending", self.call("verdict", "--repo", str(self.repo), "--target", self.target).stdout)
        self.confirm(("blocker",))
        done = self.call("verdict", "--repo", str(self.repo), "--target", self.target)
        self.assertEqual(done.returncode, 1)
        self.assertIn("verdict: blocked", done.stdout)
        self.assertRegex(done.stdout, re.compile(r"\| high \| standards \| src/app\.py:1 \| comment rule broken \| confirmed \|"))

    def test_only_medium_and_low_confirmed_is_clean(self):
        self.reviewed([MEDIUM, {**MEDIUM, "severity": "low", "line": 2, "message": "name"}])
        self.judge([{"key": item["key"], "role": "lens", "verdict": "confirmed", "evidence": "read"} for item in self.plan()["skeptics"]])
        self.assertIn("verdict: clean", self.ok("verdict", "--repo", str(self.repo), "--target", self.target))

    def test_a_refuted_finding_stays_in_the_table_and_does_not_block(self):
        self.reviewed([HIGH])
        key = self.plan()["skeptics"][0]["key"]
        self.judge([{"key": key, "role": "lens", "verdict": "refuted", "evidence": "the rule allows it"}])
        out = self.ok("verdict", "--repo", str(self.repo), "--target", self.target)
        self.assertIn("| refuted | the rule allows it |", out)
        self.assertIn("verdict: clean", out)

    def test_the_stamp_refuses_a_dirty_tree_and_a_target_short_of_the_push(self):
        self.reviewed([])
        (self.repo / "src" / "app.py").write_text("dirty\n", encoding="utf-8")
        dirty = self.call("stamp", "--repo", str(self.repo), "--target", self.target)
        self.assertEqual((dirty.returncode, "dirty" in dirty.stderr), (2, True))
        git(self.repo, "checkout", "--", "src/app.py")
        change(self.repo, {"src/more.py": "M = 1\n"}, "more")
        short = self.call("stamp", "--repo", str(self.repo), "--target", "range HEAD~1..HEAD")
        self.assertEqual((short.returncode, "everything the push sends" in short.stderr), (2, True))

    def test_status_follows_the_tree_and_survives_a_signing_only_rewrite(self):
        self.assertEqual(self.call("status", "--repo", str(self.repo)).stdout.strip(), "review: missing")
        self.reviewed([])
        self.ok("stamp", "--repo", str(self.repo), "--target", self.target)
        self.assertEqual(self.ok("status", "--repo", str(self.repo)).strip(), "review: clean")
        git(self.repo, "commit", "--amend", "--no-edit", "--date", "2020-01-01T00:00:00")
        self.assertEqual(self.ok("status", "--repo", str(self.repo)).strip(), "review: clean")
        change(self.repo, {"src/app.py": "VALUE = 7\n"}, "new")
        done = self.call("status", "--repo", str(self.repo))
        self.assertEqual((done.returncode, done.stdout.strip()), (1, "review: missing"))

    def test_a_planted_high_finding_ends_blocked_and_the_same_run_again_starts_no_lens(self):
        planted = {"security": 40, "findings": [{"severity": "high", "rule": "SEC-1", "path": "src/app.py", "line": 1, "sha1": "x", "context": None}]}
        self.env["REVIEW_FAKE"] = json.dumps({"security": {"out": planted}})
        self.reviewed([])
        key = next(item["key"] for item in self.plan()["skeptics"] if item["lens"] == "security")
        self.judge([{"key": key, "role": role, "verdict": "confirmed", "evidence": "exploit"} for role in ("lens", "blocker")])
        self.assertIn("verdict: blocked", self.call("verdict", "--repo", str(self.repo), "--target", self.target).stdout)
        (self.root / "lens.log").unlink()
        self.ok("run", "--repo", str(self.repo), "--target", self.target)
        self.assertEqual(starts(self.root), [])
        self.ok("stamp", "--repo", str(self.repo), "--target", self.target)
        status = self.call("status", "--repo", str(self.repo))
        self.assertEqual((status.returncode, status.stdout.strip()), (1, "review: blocked"))


class TestPushStep(unittest.TestCase):
    def test_kvb_git_push_hands_no_push_row_before_a_clean_or_waived_review(self):
        text = " ".join((SKILL.parent / "kvb-git-push" / "SKILL.md").read_text(encoding="utf-8").split())
        self.assertIn("kvb-code-review/scripts/review.py status --repo <root>` prints `review: clean` or `review: waived` for the gated tree", text)
        self.assertLess(text.index("**Review**"), text.index("**Hand over**"))


class TestWaiver(ReviewCase):
    def answer(self) -> str:
        question = json.loads(self.ok("question", "--repo", str(self.repo)))["question"]
        return f"Choice for decision d1 ({question}): Waive"

    def test_a_signed_waiver_records_and_status_says_waived(self):
        answer = self.answer()
        with hub({"m1": (answer, "Skills")}) as port:
            self.env = hub_home(self.root, self.env, port)
            self.ok("waive", "--repo", str(self.repo), "--message", "m1", "--answer", answer, "--agent", "Skills")
        self.assertEqual(self.ok("status", "--repo", str(self.repo)).strip(), "review: waived")

    def test_an_unsigned_or_foreign_answer_and_an_unreachable_hub_refuse(self):
        answer = self.answer()
        with hub({"m1": (answer, "Skills")}) as port:
            self.env = hub_home(self.root, self.env, port)
            forged = self.call("waive", "--repo", str(self.repo), "--message", "m1", "--answer", answer, "--agent", "Other")
            kept = self.call("waive", "--repo", str(self.repo), "--message", "m2", "--answer", answer.replace(": Waive", ": Keep blocked"), "--agent", "Skills")
        gone = self.call("waive", "--repo", str(self.repo), "--message", "m1", "--answer", answer, "--agent", "Skills")
        self.assertEqual([forged.returncode, kept.returncode, gone.returncode], [2, 2, 2])
        self.assertIn("the hub refused the waiver", forged.stderr)
        self.assertIn("the hub refused the waiver", kept.stderr)
        self.assertIn("did not answer", gone.stderr)
        self.assertEqual(self.call("status", "--repo", str(self.repo)).stdout.strip(), "review: missing")


if __name__ == "__main__":
    unittest.main()
