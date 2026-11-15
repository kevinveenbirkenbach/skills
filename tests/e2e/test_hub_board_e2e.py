from __future__ import annotations

import base64
import json
import os
import shutil
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

import hub_e2e_kit as base
from hub_e2e_board import (
    AFTER,
    AFTER_TAKEOVER,
    CONFIRM,
    CONFIRM_TAKEOVER,
    KEPT_POPUP,
    KEPT_TREE,
    NIGHT_HINTS,
    NIGHT_LOOK,
    NIGHT_MENU,
    NIGHT_PICK,
    OPEN_DELETE,
    OPEN_TAKEOVER,
    ORDER_MOVED,
    ORG_FOLDED,
    ORG_OPEN,
    PIN,
)
from hub_e2e_kit import OUT, WIDTHS
from hub_support import verifier
from kvb_orchestrator import messaging, skill_scripts
from test_hub_cleanup import DONE_TIP, FAKE_PKGMGR, host
from test_hub_offices import COUNCIL_SCRIPT
from test_hub_offices import host as office_host


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestHubBoard(base.OrchestratorE2ECase):
    def check_night_menu(self, browser: str, driver: str, binary: str, signs: bool) -> None:
        """Args:
            signs: cdp.mjs signs every prompt with its virtual passkey; bidi.mjs
                has no virtual authenticator, so the probe answers each prompt
                the way a canceled passkey dialog does.
        """
        authenticator = self.authenticator()
        probe = NIGHT_MENU.replace("@SIGNS@", "true" if signs else "false")
        looks = [{"width": width, "height": height, "url": f"http://localhost:{self.port}/?{width}#agents/orbit", "wait": 1200, "probe": NIGHT_LOOK, "shot": str(OUT / f"{browser}-{width}-night-menu-tooltips.png")} for width, height in WIDTHS]
        step = {"width": 1366, "height": 768, "url": f"http://localhost:{self.port}/#agents/orbit", "wait": 1200, "probe": probe, "shot": str(OUT / f"{browser}-1366-night-menu.png")}
        data = self.drive([*looks, step], authenticator if signs else None, driver, binary)
        (OUT / f"{browser}-night-menu.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "(style-src-elem)" not in error and "/favicon.ico" not in error], [])
        *seen, found = data["results"]
        for look, (width, _) in zip(seen, WIDTHS, strict=True):
            with self.subTest(browser=browser, width=width):
                self.assertNotIn("error", look)
                self.assertEqual(look["children"], [["span", ""], ["div", "night-picks"], ["div", "actions"]])
                self.assertEqual((look["badge"], look["paragraphs"], look["wide"]), (["Day"], 0, False))
                self.assertEqual(look["picks"], [["All", True], ["Skills", True], ["Stage", True]])
                self.assertEqual(look["buttons"], [list(entry) for entry in NIGHT_HINTS])
        self.assertNotIn("error", found)
        self.assertEqual(found["labels"], ["Drain", "Suspend", "Resume"])
        for run, action in zip(found["runs"], ("drain", "suspend", "resume"), strict=True):
            with self.subTest(browser=browser, action=action):
                self.assertEqual(run["asked"], 1, run)
                self.assertEqual(len(run["question"]), 1, run)
                self.assertIn(f"kvb-agent-{action}", run["question"][0])
                signed = [["/api/board/sign", ["action"], action]]
                if signs:
                    self.assertEqual(run["posted"], [*signed, [f"/api/board/{action}", ["proof"], None]])
                    self.assertTrue((run["toast"] or "").startswith(f"{run['label']}: done"), run)
                else:
                    self.assertEqual(run["posted"], signed)
                    self.assertTrue((run["toast"] or "").startswith(f"{run['label']}: not signed"), run)
        nights = [args for script, args in self.scripts.calls if script == skill_scripts.NIGHT]
        self.assertEqual(nights, [[action, "--session", "Operator"] for action in ("drain", "suspend", "resume")] if signs else [])
        if not signs:
            self.assertEqual(self.scripts.calls, [])

    def test_chromium_runs_drain_suspend_and_resume_only_after_the_passkey_signs(self):
        self.check_night_menu("chromium", "cdp.mjs", os.environ.get("CHROMIUM", "chromium"), signs=True)

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_asks_the_passkey_for_drain_suspend_and_resume_and_runs_nothing_unsigned(self):
        self.check_night_menu("firefox", "bidi.mjs", os.environ.get("FIREFOX", "firefox"), signs=False)

    def check_night_picks(self, browser: str, driver: str, binary: str, signs: bool) -> None:
        """Args:
            signs: as in check_night_menu.
        """
        self.write_council({"night.json": {"parts": {"s2": "drain"}}})
        probe = NIGHT_PICK.replace("@SIGNS@", "true" if signs else "false")
        steps = [{"width": width, "height": height, "url": f"http://localhost:{self.port}/?{width}#agents/orbit", "wait": 1200, "probe": probe, "shot": str(OUT / f"{browser}-{width}-night-picks.png")} for width, height in WIDTHS]
        data = self.drive(steps, self.authenticator() if signs else None, driver, binary)
        (OUT / f"{browser}-night-picks.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "(style-src-elem)" not in error and "/favicon.ico" not in error], [])
        everyone, one, nobody = [["All", True], ["Skills", True], ["Stage", True]], [["All", False], ["Skills", False], ["Stage", True]], [["All", False], ["Skills", False], ["Stage", False]]
        for found, (width, _) in zip(data["results"], WIDTHS, strict=True):
            with self.subTest(browser=browser, width=width):
                self.assertNotIn("error", found)
                self.assertEqual((found["badge"], found["start"], found["wide"]), (["Day", "1 alone"], everyone, False))
                self.assertEqual((found["one"], found["kept"], found["none"], found["all"]), ([one, [True] * 3], one, [nobody, [False] * 3], [everyone, [True] * 3]))
                self.assertEqual(found["popup"], {"badge": ["Draining"], "buttons": ["Drain", "Suspend", "Resume"]})
                self.assertEqual([question.split(":")[0] for question in found["questions"]], ["Drain Stage", "Suspend Stage"])
                sent = [["/api/board/sign", ["action", "agents"], "drain", ["s2"]], ["/api/board/drain", ["proof", "agents"], None, ["s2"]], ["/api/board/sign", ["action", "agents"], "suspend", ["s2"]], ["/api/board/suspend", ["proof", "agents"], None, ["s2"]]]
                self.assertEqual(found["posted"], sent if signs else sent[::2])
                self.assertEqual([found["drain"].split("$")[0].split()[1], found["suspend"].split("$")[0].split()[1]], ["done", "done"] if signs else ["not", "not"])
        nights = [args for script, args in self.scripts.calls if script == skill_scripts.NIGHT]
        self.assertEqual(nights, [[action, "--session", "Operator", "--target=s2"] for _ in WIDTHS for action in ("drain", "suspend")] if signs else [])
        calls = [args for script, args in self.scripts.calls if script == skill_scripts.RADIO]
        self.assertEqual(calls, [["send", "call", "--to", "Stage", "--session", "Operator", messaging.ALONE[action]] for _ in WIDTHS for action in ("drain", "suspend")] if signs else [])

    def test_chromium_drains_and_suspends_chosen_agents_from_the_menu_and_the_agent_panel_at_three_widths(self):
        self.check_night_picks("chromium", "cdp.mjs", os.environ.get("CHROMIUM", "chromium"), signs=True)

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_asks_the_passkey_for_chosen_agents_and_runs_nothing_unsigned_at_three_widths(self):
        self.check_night_picks("firefox", "bidi.mjs", os.environ.get("FIREFOX", "firefox"), signs=False)

    def test_chromium_deletes_a_merged_branch_after_dry_run_and_signature(self):
        tree = json.loads(self.tree_file.read_text(encoding="utf-8"))
        tree["delete_ready"], tree["delete_reason"] = True, ""
        next(item for item in tree["repos"][0]["items"] if item["branch"] == "feature/done").update(worktree=None, worktree_state=None, actions=["local-branch", "remote-branch"], compose_projects=[], images=[], merged_by="ancestor")
        self.tree_file.write_text(json.dumps(tree), encoding="utf-8")
        self.write_local_plan(tree, {})
        demo = f"{self.root}/repos/github.com/me/demo"
        Path(demo).mkdir(parents=True)
        fake = self.outside / "bin" / "pkgmgr"
        fake.parent.mkdir()
        fake.write_text(FAKE_PKGMGR.format(python=sys.executable), encoding="utf-8")
        fake.chmod(0o755)
        (fake.parent / "plan.json").write_text(json.dumps([{"branch": "feature/done", "worktree": None, "local_sha": DONE_TIP, "head": DONE_TIP, "state": "merged-clean", "merged_by": "ancestor", "skip": None, "actions": ["local-branch"]}]), encoding="utf-8")
        following = json.loads(json.dumps(tree))
        following["repos"][0]["items"] = [item for item in following["repos"][0]["items"] if item["branch"] != "feature/done"]
        (fake.parent / "next-tree.json").write_text(json.dumps(following), encoding="utf-8")
        authenticator = self.authenticator()
        trust = verifier.Trust(approvers=self.approvers, replay=self.replay / "cleanup.json", origin=self.origin)
        runner = host.Cleanup(trust, self.tree_file, fake)
        jobs, results = self.cleanup / "jobs", self.cleanup / "results"
        self.beside(lambda: any(jobs.iterdir()) and host.cycle(jobs, results, runner))
        local = f"http://localhost:{self.port}/"
        steps = [
            {"width": 1366, "height": 768, "url": f"{local}#artifacts/tree", "wait": 1200, "probe": OPEN_DELETE, "shot": self.shot("1366-delete-dry-run")},
            {"width": 1366, "height": 768, "url": None, "wait": 0, "probe": CONFIRM, "shot": self.shot("1366-delete-result")},
            {"width": 1366, "height": 768, "url": None, "wait": 0, "probe": AFTER, "shot": self.shot("1366-delete-tree-after")},
        ]
        data = self.drive(steps, authenticator)
        (OUT / "chromium-delete.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        opened, confirmed, after = data["results"]
        self.assertNotIn("error", opened)
        self.assertEqual(opened["every"], [False, "Delete all merged: 1 branches after dry run and signature"])
        self.assertEqual(opened["buttons"], [[False, "Delete: remove feature/done locally, after dry run and signature"]])
        self.assertEqual(opened["title"], "Delete feature/done")
        self.assertEqual(len(opened["dry"]), 1)
        self.assertTrue(opened["dry"][0].startswith("feature/done @ 5b1e6fd3a7c0: merged-clean, merged by ancestor"), opened["dry"])
        self.assertIn("stays: remote-branch (local only; the host refuses a plan that deletes it)", opened["dry"][0])
        self.assertEqual((confirmed["result"], confirmed["text"]), ("done", "feature/donedeleted"), confirmed)
        self.assertEqual(confirmed["toasts"], ["Delete: donefeature/done: deleted"])
        self.assertEqual(after["past"], ["done", "deleted"])
        self.assertNotIn("feature/done", after["branches"])
        written = [json.loads(path.read_text(encoding="utf-8")) for path in results.glob("*.json")]
        self.assertEqual([[(item["branch"], item["status"]) for item in result["items"]] for result in written], [[("feature/done", "done")]])
        calls = [json.loads(line)["argv"] for line in (fake.parent / "calls.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(calls, [
            ["branch", "cleanup", "--local", "--json", "--branch", "feature/done"],
            ["branch", "cleanup", "--apply", "--local", "--json", "--branch", "feature/done"],
            ["branch", "tree", "--format", "json", "--output", str(self.tree_file)],
        ])

    def test_chromium_shows_a_branch_the_local_dry_run_keeps_without_delete_and_offers_one_whose_local_tip_it_deletes(self):
        squashed_tip, cherry_tip, cherry_remote = "9a8b7c6d5e4f3a2b1c0d9e8f7a6b5c4d3e2f1a0b", "8b7c6d5e4f3a2b1c0d9e8f7a6b5c4d3e2f1a0b9c", "7c6d5e4f3a2b1c0d9e8f7a6b5c4d3e2f1a0b9c8d"
        tree = json.loads(self.tree_file.read_text(encoding="utf-8"))
        tree["delete_ready"], tree["delete_reason"] = True, ""
        items = tree["repos"][0]["items"]
        kept = next(item for item in items if item["branch"] == "feature/kept")
        kept["skip"] = None
        items.append({**kept, "branch": "feature/squashed", "local_sha": squashed_tip, "upstream": "origin/feature/squashed", "ahead": 0, "behind": 0, "remotes": {"origin": squashed_tip},
                      "merged_by": "pr#7", "actions": ["local-branch", "remote-branch:origin"], "reason": "merged by pr#7"})
        items.append({**kept, "branch": "feature/cherry", "local_sha": cherry_tip, "upstream": "origin/feature/cherry", "ahead": 0, "behind": 1, "remotes": {"origin": cherry_remote},
                      "merged_by": "patch", "actions": ["local-branch", "remote-branch:origin"], "reason": "merged by patch"})
        self.tree_file.write_text(json.dumps(tree), encoding="utf-8")
        self.write_local_plan(tree, {"feature/cherry": {"skip": None, "actions": ["local-branch"]}})
        demo = f"{self.root}/repos/github.com/me/demo"
        local = f"http://localhost:{self.port}/"
        steps = [
            {"width": 1366, "height": 768, "url": f"{local}#artifacts/tree", "wait": 1200, "probe": KEPT_TREE, "shot": self.shot("1366-kept-tree")},
            {"width": 1366, "height": 768, "url": f"{local}?kept#artifacts/orbit", "wait": 1200, "probe": KEPT_POPUP.replace("@REPO@", json.dumps(demo)), "shot": self.shot("1366-kept-popup")},
        ]
        data = self.drive(steps, None)
        (OUT / "chromium-kept.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        shown, popup = data["results"]
        self.assertNotIn("error", shown, shown)
        self.assertNotIn("error", popup, popup)
        kept_line = "pkgmgr branch cleanup --local keeps it: merged by pr#7, tip is no ancestor of refs/remotes/origin/main; use branch gc (kvb-git-gc, pkgmgr gc)"
        plan = f"feature/squashed @ {squashed_tip[:12]}: merged-clean, merged by pr#7\n{kept_line}\nbranch gc would delete the local branch feature/squashed\nbranch gc would delete remote-branch:origin"
        self.assertEqual((shown["kept"], shown["rowDeletes"], shown["deletes"]), ([kept_line, kept_line], 0, ["feature/kept", "feature/cherry"]))
        self.assertIn("1 kept by the --local dry run: see each dry run", shown["header"])
        self.assertEqual([row[:3] for row in shown["rows"]], [["feature/kept", None, 0], ["feature/cherry", None, 0], ["feature/done", "held", 0], ["feature/squashed", "kept", 0]])
        self.assertEqual(shown["rows"][1][3], f"feature/cherry @ {cherry_tip[:12]}: merged-clean, merged by patch\ndeletes the local branch feature/cherry\nstays: remote-branch:origin (local only; the host refuses a plan that deletes it)")
        self.assertEqual(shown["rows"][3][3], plan)
        self.assertEqual((shown["confirms"], shown["title"]), (1, "Delete 2 merged branches"))
        self.assertEqual((popup["title"], popup["heading"], popup["dry"], popup["deletes"], popup["kept"]), ("feature/squashed", "Dry run", plan, 0, kept_line))
        status, _, body = self.post_json("/api/sign", {"items": [{"kind": "cleanup", "repository": demo, "branch": "feature/squashed", "worktree": "", "tip": squashed_tip}]}, self.guard(self.host))
        self.assertEqual((status, body.decode()), (400, f"feature/squashed in {demo} is no merged-clean branch without skip reason that the --local dry run deletes at that tip\n"))
        self.assertEqual(list((self.cleanup / "jobs").glob("*.json")), [])

    def test_chromium_folds_the_hierarchy_by_keyboard_reorders_agents_and_hands_an_office_over_with_a_signature(self):
        signer = self.pin()
        trust = verifier.Trust(approvers=self.approvers, replay=self.replay / "offices.json", origin=self.origin)
        runner = office_host.Offices(trust, self.council, COUNCIL_SCRIPT, self.outside / "home")
        jobs, results = self.offices / "jobs", self.offices / "results"
        self.beside(lambda: any(jobs.iterdir()) and office_host.cycle(jobs, results, runner))
        private = "".join(line for line in signer.pem.read_text(encoding="utf-8").splitlines() if not line.startswith("-----"))
        authenticator = {"credentialId": base64.b64encode(signer.raw_id).decode(), "privateKey": private, "rpId": "localhost"}
        local = f"http://localhost:{self.port}/"
        steps = [
            {"width": 1366, "height": 768, "url": f"{local}#agents/hierarchy", "wait": 1200, "probe": ORG_OPEN, "shot": self.shot("1366-hierarchy-open")},
            {"width": 1366, "height": 768, "url": None, "wait": 0, "keys": ["Enter"], "probe": ORG_FOLDED, "shot": None},
            {"width": 1366, "height": 768, "url": None, "wait": 0, "keys": ["Enter"], "probe": ORDER_MOVED, "shot": self.shot("1366-hierarchy-order")},
            {"width": 1366, "height": 768, "url": None, "wait": 0, "probe": OPEN_TAKEOVER, "shot": self.shot("1366-hierarchy-takeover")},
            {"width": 1366, "height": 768, "url": None, "wait": 0, "probe": CONFIRM_TAKEOVER, "shot": self.shot("1366-hierarchy-takeover-result")},
            {"width": 1366, "height": 768, "url": None, "wait": 0, "probe": AFTER_TAKEOVER, "shot": self.shot("1366-hierarchy-after")},
        ]
        data = self.drive(steps, authenticator)
        (OUT / "chromium-hierarchy.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        opened, folded, moved, sheet, confirmed, after = data["results"]
        self.assertNotIn("error", opened)
        self.assertEqual(opened["focused"], "toggle:dimension:identity")
        self.assertEqual((folded["focused"], folded["expanded"], folded["label"], folded["hidden"], folded["again"]), ("toggle:dimension:identity", "false", "Expand: identity", True, "true"))
        self.assertNotIn("identity/oidc", folded["seen"])
        before = folded["before"]
        self.assertEqual(moved["after"], [before[1], before[0], *before[2:]])
        self.assertEqual((moved["focused"], moved["disabled"]), (f"down:{before[1]}", False))
        self.assertTrue(moved["toast"].startswith("Priority"), moved)
        self.assertIn(("rasci.py", ["agents", "order", ",".join(moved["after"])]), [(Path(script).name, args) for script, args in self.scripts.calls])
        self.assertEqual((sheet["title"], sheet["options"], sheet["work"], sheet["focused"]), ("identity/oidc: Hand over", ["s1"], "oidc line", "SELECT"))
        self.assertEqual((confirmed["result"], confirmed["text"]), ("done", "identity/oidcdone"), confirmed)
        self.assertIn("Hand over: doneidentity/oidc: done", confirmed["toasts"])
        self.assertNotIn("error", after)
        claim = json.loads((self.council / "identity" / "oidc" / "claim.json").read_text(encoding="utf-8"))
        self.assertEqual((claim["session"], claim["work"]), ("s1", "oidc line"))
        written = [json.loads(path.read_text(encoding="utf-8")) for path in results.glob("*.json")]
        self.assertEqual([[(item["office"], item["action"], item["status"]) for item in result["items"]] for result in written], [[("identity/oidc", "takeover", "done")]])

    def test_chromium_pins_a_task_priority_after_signature_and_the_runner_applies_it(self):
        signer = self.pin()
        private = "".join(line for line in signer.pem.read_text(encoding="utf-8").splitlines() if not line.startswith("-----"))
        authenticator = {"credentialId": base64.b64encode(signer.raw_id).decode(), "privateKey": private, "rpId": "localhost"}
        local = f"http://localhost:{self.port}/"
        data = self.drive([{"width": 1366, "height": 768, "url": f"{local}#tasks/list", "wait": 1200, "probe": PIN, "shot": self.shot("1366-tasks-priority-signed")}], authenticator)
        (OUT / "chromium-task-priority.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        pinned = data["results"][0]
        self.assertNotIn("error", pinned)
        self.assertEqual((pinned["title"], pinned["preview"][0]), ("work/docs", "rasci.py set work/docs --prio 2"))
        self.assertEqual(pinned["toasts"], ["Priority work/docs: handed to the runnerrasci.py set work/docs --prio 2"])
        jobs = self.runner_jobs()
        self.assertEqual([(job["id"], job["kind"], job["argv"]) for job in jobs], [(pinned["jobs"], "task", ["set", "work/docs", "--prio", "2"])])
        self.run_runner()
        register = json.loads((self.council / "rasci.json").read_text(encoding="utf-8"))
        self.assertEqual((register["work/docs"]["prio"], register["work/feature"]["prio"]), (2, 1))
        self.assertEqual([(row["task"], row["prio"]) for row in self.snapshot()["tasks"][:2]], [("work/feature", 1), ("work/docs", 2)])


if __name__ == "__main__":
    unittest.main()
