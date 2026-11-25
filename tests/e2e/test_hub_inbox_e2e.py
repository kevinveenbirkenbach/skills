from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

import hub_e2e_kit as base
from hub_e2e_inbox import (
    ACCEPT,
    CHOICE_ANSWER,
    CHOICE_REQUEST,
    CHOICE_SEND,
    CHOICE_VIEW,
    DENIED,
    DENY,
    DENY_SHEET,
    INBOX_PICK,
    LAYOUT,
    RUN_DONE,
    RUN_HELD,
    RUN_START,
    SLOW,
    TASKS_FIT,
)
from hub_e2e_kit import CHOICE_CHANNELS, OUT, TASK_VIEWS, WIDTHS
from hub_support import ASK, OPTIONS, RUNNER
from kvb_orchestrator import batches, skill_scripts


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestHubInbox(base.OrchestratorE2ECase):
    def inbox_work(self) -> None:
        stage = {"title": "Stage line", "status": "running", "worker": "Stage (this session)", "roles": {"Stage (this session)": "RA"}}
        greet = {"title": SLOW, "workdir": str(self.outside), "description": "counts", "check": "manual", "status": "queued", "roles": {"Operator": "R", "Skills session": "A"}}
        push = {"title": "git push", "workdir": "/repo", "description": "ship", "check": "manual", "status": "queued", "roles": {"Operator": "R", "Skills session": "A"}}
        self.write_council({"rasci.json": {"work/stage": stage, "operator/greet": greet, "operator/push": push}})
        arguments = {"kind": "ask", "tool": "Bash", "pattern": "make deploy", "scope": "/repo*", "expires": int(time.time()) + 7 * 86400, "agent": "Skills", "why": "deploy runs after every green gate"}
        self.assertFalse(self.tool("rule_request", arguments)["isError"])

    def layout(self, probe: dict) -> None:
        self.assertNotIn("error", probe)
        self.assertEqual(sorted(probe["kinds"]), ["Ask", "Operator", "Operator", "Review", "Rule request"])
        self.assertEqual(probe["splits"], [["Deny", "Deny via …"]] * 5)
        self.assertEqual(probe["fields"], ["Kind", "Tool (glob)", "Pattern (glob)", "Directory (glob)", "Expires on"])
        self.assertEqual(probe["dry"], "Dry run: the rule would have granted 1 of 1 asks from the last 7 days.")
        self.assertEqual(probe["accept"], 1)
        self.assertTrue(probe["fits"] and probe["followed"], probe)
        self.assertEqual((probe["unlabelled"], probe["wide"]), ([], False))

    def test_chromium_runs_a_command_into_its_console_denies_by_call_and_accepts_a_rule(self):
        self.inbox_work()
        signer = self.pin()
        trust = ["--approvers", str(self.approvers), "--replay", str(self.replay / "runner.json")]

        def run_jobs() -> None:
            if any(job["status"] == "queued" for job in self.httpd.hub.jobs.listed()):
                subprocess.run([sys.executable, str(RUNNER), "--port", str(self.port), "--interval", "0.1", *trust, "--once"], capture_output=True, timeout=120, check=False, env={**os.environ, "SHELL": str(self.shell)})

        self.beside(run_jobs)
        private = "".join(line for line in signer.pem.read_text(encoding="utf-8").splitlines() if not line.startswith("-----"))
        authenticator = {"credentialId": base64.b64encode(signer.raw_id).decode(), "privateKey": private, "rpId": "localhost"}
        inbox = f"http://localhost:{self.port}/#stream/inbox"
        steps = [
            {"width": 1366, "height": 768, "url": inbox, "wait": 1200, "probe": RUN_START, "shot": self.shot("1366-inbox-console-running")},
            {"width": 1366, "height": 768, "url": None, "wait": 0, "probe": RUN_HELD, "shot": self.shot("1366-inbox-console-scrolled-up")},
            {"width": 1366, "height": 768, "url": None, "wait": 0, "probe": RUN_DONE, "shot": self.shot("1366-inbox-console-done")},
        ]
        for width, height in WIDTHS:
            fresh = f"http://localhost:{self.port}/?{width}#stream/inbox"
            steps.append({"width": width, "height": height, "url": fresh, "wait": 1200, "probe": LAYOUT, "shot": self.shot(f"{width}-inbox-console")})
            steps.append({"width": width, "height": height, "url": None, "wait": 0, "probe": DENY_SHEET, "shot": self.shot(f"{width}-inbox-deny-sheet")})
        steps += [
            {"width": 1366, "height": 768, "url": inbox, "wait": 1200, "probe": DENY, "shot": self.shot("1366-inbox-deny-undo")},
            {"width": 1366, "height": 768, "url": None, "wait": 0, "probe": DENIED, "shot": None},
            {"width": 1366, "height": 768, "url": None, "wait": 0, "probe": ACCEPT, "shot": self.shot("1366-inbox-rule-accepted")},
        ]
        data = self.drive(steps, authenticator)
        (OUT / "chromium-inbox.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        started, held, done, *rest = data["results"]
        self.assertNotIn("error", started)
        self.assertIn("takes effect in", started["toast"])
        self.assertTrue(started["running"].startswith("running"), started)
        self.assertTrue(started["overflows"] and started["followed"], started)
        self.assertLess(held["held"], 50, held)
        self.assertEqual((done["last"], done["lines"], done["followed"]), ("finished", 81, True))
        self.assertRegex(done["done"], r"^doneExit code 0 after \d+ s$")
        self.assertIn("Close", done["actions"])
        layouts, sheets = rest[0:6:2], rest[1:6:2]
        for probe, sheet, (width, _) in zip(layouts, sheets, WIDTHS, strict=True):
            with self.subTest(width=width):
                self.layout(probe)
                self.assertTrue(probe["console"].startswith("doneExit code 0"), probe)
                self.assertEqual(sheet["title"], "Deny")
                self.assertEqual(sheet["channels"], [["post", False], ["call", True], ["newsletter", False], ["broadcast", False], ["pan-pan", False], ["security", False]])
                self.assertEqual(sheet["hints"][:3], ["to Skills, when its turn ends", "to Skills, at once, wakes it", "to all, when their turn ends"])
                self.assertEqual((sheet["recipient"], sheet["gate"]), ("Skills", [True, True, True, True]))
                self.assertEqual((sheet["reason"], sheet["unlabelled"], sheet["wide"]), (True, [], False))
        denied, gone, accepted = rest[6:]
        self.assertNotIn("error", denied, denied)
        self.assertTrue(denied["undo"].startswith("Denial (Call): Bash: make deploy"), denied)
        self.assertFalse(denied["sheet"])
        self.assertTrue(gone["gone"])
        self.assertEqual((accepted["toast"], accepted["left"]), ("Created: Rule: ask Bash make deploy in /repo*", False))
        ask = self.httpd.hub.asks.listed()[0]
        self.assertEqual((ask["status"], ask["reason"], ask["channel"]), ("denied", "make the gate green first", "call"))
        calls = [args for script, args in self.scripts.calls if script.endswith("radio.py")]
        self.assertEqual(calls[-1][:4], ["send", "call", "--to", "Skills session"])
        self.assertTrue(calls[-1][-1].endswith("Reason: make the gate green first"), calls[-1])
        self.assertEqual([(rule["kind"], rule["pattern"], rule["proof"] is not None) for rule in self.httpd.hub.rules.listed()], [("ask", "make deploy", True)])
        self.assertEqual([(job["status"], job["code"]) for job in self.httpd.hub.jobs.listed()], [("done", 0)])

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_draws_the_inbox_console_and_the_rule_request_at_three_widths(self):
        self.inbox_work()
        now = time.time()
        fields = {"task": "operator/greet", "command": SLOW, "directory": str(self.outside), "sha256": "", "status": "done", "proof": None}
        output = "".join(f"Row {number}\n" for number in range(1, 81)) + "finished\n"
        self.httpd.hub.jobs.add({**fields, "code": 0, "output": output, "created_ts": now - 20, "started": now - 19, "finished": now - 10, "dismissed": False})
        shots = [(width, height, OUT / f"firefox-{width}-inbox-console.png") for width, height in WIDTHS]
        steps = [{"width": width, "height": height, "url": f"{self.base}#stream/inbox", "wait": 1200, "probe": LAYOUT, "shot": str(shot)} for width, height, shot in shots]
        data = self.drive(steps, None, "bidi.mjs", os.environ.get("FIREFOX", "firefox"))
        (OUT / "firefox-inbox.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "(style-src-elem)" not in error and "/favicon.ico" not in error], [])
        for probe, (width, _, shot) in zip(data["results"], shots, strict=True):
            with self.subTest(width=width):
                self.layout(probe)
                self.assertEqual(probe["console"], "doneExit code 0 after 9 s")
                self.assertTrue(shot.is_file() and shot.stat().st_size > 1000, shot)

    def check_inbox_picks(self, browser: str, driver: str, binary: str, signs: bool) -> None:
        """Args:
            signs: as in check_night_menu.
        """
        fill = {"description": "fill", "workdir": "/repo", "status": "queued", "roles": {"Operator": "R", "Skills session": "A"}}
        rows = {f"operator/row-{n:02}": {**fill, "title": f"echo row {n:02}", "check": "manual", "seq": n} for n in range(1, 15)}
        rows["operator/name"] = {**fill, "title": "pick a name", "check": "decision", "seq": 15}
        self.write_council({"rasci.json": rows})
        probe = INBOX_PICK.replace("@SIGNS@", "true" if signs else "false")
        steps = [{"width": width, "height": height, "url": f"http://localhost:{self.port}/?{width}#stream/inbox", "wait": 1200, "probe": probe, "shot": str(OUT / f"{browser}-{width}-inbox-deny-selection.png")} for width, height in WIDTHS]
        stops = []
        with mock.patch.object(batches, "UNDO", 0.3):
            data = self.drive(steps, self.authenticator() if signs else None, driver, binary)
            (OUT / f"{browser}-inbox-deny-selection.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
            if signs:
                self.settle(lambda: len([call for call in self.scripts.calls if call[0] == skill_scripts.RASCI]) >= 2 * len(WIDTHS))
            stops = [args for script, args in self.scripts.calls if script == skill_scripts.RASCI]
        self.assertEqual([error for error in data["errors"] if "(style-src-elem)" not in error and "/favicon.ico" not in error], [])
        denied = []
        for found, (width, _) in zip(data["results"], WIDTHS, strict=True):
            with self.subTest(browser=browser, width=width):
                self.assertNotIn("error", found)
                self.assertGreater(found["before"], 0, found)
                self.assertEqual((found["moved"], found["focused"], found["wide"]), (0, True, False), found)
                self.assertTrue({"Grant selection (1)", "Deny selection (2)"} <= set(found["buttons"]), found["buttons"])
                self.assertEqual((sorted(found["listed"]), found["label"], found["reasoned"]), (sorted([found["title"], "pick a name"]), "Deny 2", True))
                task = f"operator/row-{found['title'][-2:]}"
                items = sorted([[task, "reject", "post", "rebase first"], ["operator/name", "reject", "post", "rebase first"]])
                self.assertEqual([[path, sorted(entries)] for path, entries in found["posted"]], [["/api/sign", items], *([["/api/inbox/approve", items]] if signs else [])])
                self.assertIn("takes effect" if signs else "not signed", found["toast"])
                denied += [task, "operator/name"]
        self.assertEqual(sorted(stops), sorted([["set", task, "--status", "stopped"] for task in denied]) if signs else [])

    def test_chromium_keeps_the_inbox_scroll_on_a_tick_and_denies_a_selection_with_one_signature_at_three_widths(self):
        self.check_inbox_picks("chromium", "cdp.mjs", os.environ.get("CHROMIUM", "chromium"), signs=True)

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_keeps_the_inbox_scroll_on_a_tick_and_denies_nothing_unsigned_at_three_widths(self):
        self.check_inbox_picks("firefox", "bidi.mjs", os.environ.get("FIREFOX", "firefox"), signs=False)

    def choice_steps(self, browser: str, signs: bool, questions: dict[int, str]) -> list[dict]:
        flag = "true" if signs else "false"
        local = f"http://localhost:{self.port}/"
        steps = []
        for index, (width, height) in enumerate(WIDTHS):
            cards = len(WIDTHS) - index if signs else len(WIDTHS)
            steps += [
                {"width": width, "height": height, "url": f"{local}?{width}#stream/inbox", "wait": 1200, "probe": CHOICE_VIEW.replace("@CARDS@", str(cards)), "shot": str(OUT / f"{browser}-{width}-tasks-choices.png")},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": CHOICE_SEND.replace("@SIGNS@", flag), "shot": str(OUT / f"{browser}-{width}-choice-request.png")},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": CHOICE_ANSWER.replace("@SIGNS@", flag).replace("@QUESTION@", questions[width]), "shot": str(OUT / f"{browser}-{width}-choice-answer.png")},
                *({"width": width, "height": height, "url": f"{local}?{width}#tasks/{view}", "wait": 900, "probe": TASKS_FIT, "shot": str(OUT / f"{browser}-{width}-tasks-{view}-fit.png")} for view in TASK_VIEWS),
            ]
        return steps

    def requested(self, sent: dict, signs: bool) -> None:
        """Args:
            sent: the CHOICE_SEND probe: two agents ticked, then every channel
                button pressed once.
        """
        labels = dict(zip(CHOICE_CHANNELS, ["Post", "Call", "Newsletter", "Broadcast", "Pan-Pan", "Sécurité", "Mayday"], strict=True))
        self.assertEqual(len(sent["picked"]), 2, sent)
        self.assertEqual((sent["counted"], sent["fields"], sent["tall"], sent["wide"]), ("2", 0, False, False))
        self.assertEqual(sent["opened"], [True, len(CHOICE_CHANNELS)])
        self.assertEqual([run["channel"] for run in sent["runs"]], CHOICE_CHANNELS)
        for run in sent["runs"]:
            with self.subTest(channel=run["channel"]):
                to = sent["picked"] if run["channel"] in ("post", "call") else ["*"]
                signed = [["/api/choices/sign", ["class", "to"], run["channel"], to]]
                self.assertEqual((run["disabled"], run["asked"], len(run["question"])), (False, 1, int(run["channel"] == "mayday")), run)
                title = f"Choice request ({labels[run['channel']]}) to {', '.join(to) if to != ['*'] else 'all'}"
                self.assertEqual(run["posted"], [*signed, ["/api/choices", ["class", "proof", "to"], run["channel"], to]] if signs else signed)
                self.assertTrue((run["toast"] or "").startswith(f"{title}: {'sent' if signs else 'not signed'}"), run)

    def answered(self, result: dict, signs: bool) -> None:
        self.assertNotIn("error", result)
        self.assertEqual((result["title"], result["asked"], result["closed"], result["tall"], result["wide"]), ("Wait: Stage gets this answer as a call once your passkey signs it", 1, [False, 0], False, False))
        signed = [["/api/sign", ["items"], None, None]]
        self.assertEqual(result["posted"], [*signed, ["/api/inbox/approve", ["items", "proof"], None, None]] if signs else signed)
        self.assertTrue((result["toast"] or "").startswith("Choice: Wait" + ("" if signs else ": not signed")), result)
        self.assertEqual(result["gone"], True if signs else None)

    def check_choices(self, browser: str, driver: str, binary: str, signs: bool) -> None:
        """Args:
            signs: cdp.mjs signs every prompt with its virtual passkey; bidi.mjs
                has no virtual authenticator, so the probes answer each prompt
                the way a canceled passkey dialog does.
        """
        self.inbox_work()
        self.create_ask({**ASK, "command": "make choices", "timeout": 3600})
        authenticator = self.authenticator()
        questions = {width: f"Pick a name at {width} px?" for width, _ in WIDTHS}
        decisions = {width: self.tool("decision_request", {"question": question, "options": OPTIONS, "agent": "Stage", "recommended": ""})["structuredContent"]["id"] for width, question in questions.items()}
        data = self.drive(self.choice_steps(browser, signs, questions), authenticator if signs else None, driver, binary)
        (OUT / f"{browser}-choices.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "(style-src-elem)" not in error and "/favicon.ico" not in error], [])
        per = 3 + len(TASK_VIEWS)
        for index, (width, _) in enumerate(WIDTHS):
            view, sent, answer, *fitted = data["results"][per * index : per * (index + 1)]
            with self.subTest(browser=browser, width=width):
                self.assertNotIn("error", view)
                self.assertEqual(view["kinds"], ["Ask", "Choice", "Operator", "Review", "Rule request"])
                self.assertEqual(view["filter"], ["Waits on Operator", "true"])
                self.assertEqual(view["channels"], [[channel, label, channel in ("post", "call")] for channel, label in zip(CHOICE_CHANNELS, ["Post", "Call", "Newsletter", "Broadcast", "Pan-Pan", "Sécurité", "Mayday"], strict=True)])
                self.assertEqual((view["fields"], view["choices"], view["multi"], view["unlabelled"], view["tall"], view["wide"]), (0, 0, ["Request choices", False, 0, "0", 0], [], False, False))
                self.assertEqual(view["bar"], ["Tasks", view["bar"][1], ["toolbar", "chips", "body"]])
                self.assertEqual(view["bar"][1] == 1, width != 390, view["bar"])
                self.assertGreaterEqual(len(view["agents"]), 2, view)
                self.assertIn(["Choice", ["Merge now", "Wait"]], view["cards"])
                self.requested(sent, signs)
                self.answered(answer, signs)
                for fit, name in zip(fitted, TASK_VIEWS, strict=True):
                    self.assertEqual((fit["hash"], fit["bar"], fit["choices"], fit["tall"], fit["wide"]), (f"#tasks/{name}", CHOICE_CHANNELS, 0, False, False), fit)
                    self.assertEqual((fit["rows"] == 1, fit["layout"]), (width != 390, ["toolbar", "chips", "body"]), fit)
                    if name == "board":
                        self.assertEqual(fit["columns"], ["queued", "running", "done"])
        hub = self.httpd.hub
        if not signs:
            self.assertEqual((self.scripts.calls, hub.messages.listed()), ([], []))
            self.assertEqual([hub.decisions.get(decision)["status"] for decision in decisions.values()], ["pending"] * len(WIDTHS))
            return
        requests = [record for record in hub.messages.listed() if record["text"] == CHOICE_REQUEST]
        self.assertEqual((len(requests), sorted({record["class"] for record in requests})), (len(WIDTHS) * 9, sorted(CHOICE_CHANNELS)))
        for record in requests:
            self.assertTrue(self.tool("operator_message", {"id": record["id"], "text": CHOICE_REQUEST, "to": record["to"]})["structuredContent"]["match"], record["id"])
        radio = [args for script, args in self.scripts.calls if script == skill_scripts.RADIO]
        self.assertEqual(len(radio), len(requests) + len(WIDTHS))
        for width, decision in decisions.items():
            with self.subTest(width=width):
                state = self.tool("decision_wait", {"id": decision, "timeout_seconds": 0})["structuredContent"]
                self.assertEqual((state["status"], state["choice"], state["answer"]), ("decided", "Wait", f"Choice for decision {decision} ({questions[width]}): Wait"))
                found = self.tool("operator_message", {"id": state["message"], "text": state["answer"], "to": "Stage"})["structuredContent"]
                self.assertEqual((found["match"], found["class"], found["to"]), (True, "call", "Stage"))
                self.assertIn(["send", "call", "--to", "Stage", "--session", "Operator", f"[kvb-orchestrator msg {state['message']}] {state['answer']}"], radio)

    def test_chromium_requests_choices_on_every_channel_and_signs_a_choice_at_three_widths(self):
        self.check_choices("chromium", "cdp.mjs", os.environ.get("CHROMIUM", "chromium"), signs=True)

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_asks_the_passkey_for_every_choice_request_and_answer_and_sends_nothing_unsigned(self):
        self.check_choices("firefox", "bidi.mjs", os.environ.get("FIREFOX", "firefox"), signs=False)


if __name__ == "__main__":
    unittest.main()
