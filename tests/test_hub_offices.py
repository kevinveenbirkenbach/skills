from __future__ import annotations

import importlib.util
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from hub_case import HubCase
from hub_support import HUB, ORIGIN, REPO_ROOT, key, signing, verifier

OFFICES = HUB / "client" / "offices.py"
OFFICES_SPEC = importlib.util.spec_from_file_location("kvb_orchestrator_offices_runner", OFFICES)
host = importlib.util.module_from_spec(OFFICES_SPEC)
OFFICES_SPEC.loader.exec_module(host)
COUNCIL_SCRIPT = REPO_ROOT / "skills" / "kvb-org-organize" / "scripts" / "council.py"
SINCE = "2026-11-07T08:00:00+00:00"


def office_claim(office: str, session: str, name: str, runtime: str) -> dict:
    return {"office": office, "session": session, "runtime": runtime, "name": name, "since": SINCE, "beat": time.time(), "work": f"{office} work"}


def unblock(fifo: Path) -> None:
    try:
        os.close(os.open(fifo, os.O_WRONLY | os.O_NONBLOCK))
    except OSError:
        pass


class TestHubOffices(HubCase):
    def setUp(self):
        super().setUp()
        self.write_council({
            "chair/claim.json": office_claim("chair", "s1", "Maintainer", "claude-code"),
            "identity/oidc/claim.json": office_claim("identity/oidc", "s2", "Skills", "claude-code"),
            "work/hub/claim.json": office_claim("work/hub", "s3", "Stage", "claude-code"),
            "cluster/gate/claim.json": office_claim("cluster/gate", "s2", "Skills", "claude-code"),
        })
        self.snapshot()

    def sign(self, items: list[dict]) -> tuple[int, bytes]:
        status, _, body = self.post_json("/api/sign", {"items": items}, self.guard(self.host))
        return status, body

    def test_the_chair_is_the_holder_of_the_chair_office(self):
        state = self.snapshot()
        self.assertEqual([(node["id"], node["kind"]) for node in state["graph"]["nodes"][:2]], [("Operator", "operator"), ("s1", "chair")])
        self.assertEqual({claim["office"]: claim["kind"] for claim in state["claims"]}, {"chair": "chair", "cluster/gate": "cluster", "identity/oidc": "line", "work/hub": "work"})
        code = re.sub(r'<script nonce="[^"]+" id="state" type="application/json">.*?</script>', "", self.index(), flags=re.DOTALL)
        self.assertNotIn("Maintainer", code)

    def test_a_fifo_or_link_at_a_council_file_never_blocks_or_feeds_the_state(self):
        fifos = [self.council / "work" / "fifo" / "claim.json", self.council / "agent-order.json"]
        fifos[0].parent.mkdir(parents=True)
        for fifo in fifos:
            os.mkfifo(fifo, 0o600)
            self.addCleanup(unblock, fifo)
        planted = self.outside / "claim.json"
        planted.write_text(json.dumps(office_claim("security/gui", "s9", "Linked", "claude-code")), encoding="utf-8")
        (self.council / "security" / "gui").mkdir(parents=True)
        (self.council / "security" / "gui" / "claim.json").symlink_to(planted)
        offices = [claim["office"] for claim in self.snapshot()["claims"]]
        self.assertEqual(offices, ["chair", "cluster/gate", "identity/oidc", "work/hub"])

    def test_a_vacant_chair_draws_no_chair_node_and_the_operator_grants(self):
        shutil.rmtree(self.council / "chair")
        now = time.time()
        self.write_council({
            "rasci.json": {"work/hub": {"title": "Hub", "status": "running", "worker": "Stage", "workdir": "/repo/hub", "roles": {"Stage": "RA"}}},
            "queue-history.jsonl": self.jsonl([{"id": "q1", "kind": "gate", "workdir": "/repo/hub", "start": now - 10, "end": now - 5, "exit": 0}]),
        })
        state = self.snapshot()
        self.assertEqual([node["kind"] for node in state["graph"]["nodes"]].count("chair"), 0)
        self.assertIn({"source": "Operator", "target": "s3", "class": "grant", "count": 1}, state["graph"]["edges"])

    def test_signing_an_office_needs_a_known_session_the_current_holder_and_one_line_per_dimension(self):
        for name, item in (
            ("appoint a vacant line", signing.office_item("appoint", "security/gui", "", "s3", "GUI line")),
            ("take over the chair", signing.office_item("takeover", "chair", "s1", "s2", "allocate")),
            ("recall a president", signing.office_item("recall", "work/hub", "s3", "", "")),
            ("take over a line in the own dimension", signing.office_item("takeover", "identity/oidc", "s2", "s3", "oidc")),
        ):
            with self.subTest(name=name):
                status, body = self.sign([item])
                self.assertEqual(status, 200, body)
                self.assertEqual(json.loads(body)["payload"]["items"], [signing.item_hash(item)])
        bad = (
            ("capital office", signing.office_item("appoint", "Chair", "", "s3", "w"), 400),
            ("three levels", signing.office_item("appoint", "a/b/c", "", "s3", "w"), 400),
            ("climbing office", signing.office_item("appoint", "../x", "", "s3", "w"), 400),
            ("bare group", signing.office_item("appoint", "work", "", "s3", "w"), 400),
            ("unknown session", signing.office_item("appoint", "security/gui", "", "s9", "w"), 400),
            ("pseudo session", signing.office_item("appoint", "security/gui", "", "name:Docs", "w"), 400),
            ("the operator", signing.office_item("appoint", "security/gui", "", "Operator", "w"), 400),
            ("unknown action", {**signing.office_item("appoint", "security/gui", "", "s3", "w"), "action": "fire"}, 400),
            ("empty work", signing.office_item("appoint", "security/gui", "", "s3", " "), 400),
            ("two lines of work", signing.office_item("appoint", "security/gui", "", "s3", "a\nb"), 400),
            ("long work", signing.office_item("appoint", "security/gui", "", "s3", "x" * 301), 400),
            ("recall with a successor", signing.office_item("recall", "work/hub", "s3", "s2", ""), 400),
            ("extra key", {**signing.office_item("recall", "work/hub", "s3", "", ""), "command": "rm -rf ~"}, 400),
            ("missing key", {key_name: value for key_name, value in signing.office_item("recall", "work/hub", "s3", "", "").items() if key_name != "holder"}, 400),
            ("number", {**signing.office_item("recall", "work/hub", "s3", "", ""), "holder": 3}, 400),
            ("held office", signing.office_item("appoint", "identity/oidc", "", "s3", "w"), 409),
            ("holder changed", signing.office_item("takeover", "chair", "s2", "s3", "w"), 409),
            ("vacant recall", signing.office_item("recall", "security/gui", "", "", ""), 400),
            ("option as session", signing.office_item("appoint", "security/gui", "", "--all", "w"), 400),
            ("successor is the holder", signing.office_item("takeover", "chair", "s1", "s1", "w"), 400),
            ("second line of a dimension", signing.office_item("appoint", "identity/saml", "", "s2", "w"), 400),
        )
        for name, item, expected in bad:
            with self.subTest(name=name):
                self.assertEqual(self.sign([item])[0], expected)
        item = signing.office_item("appoint", "security/gui", "", "s3", "GUI line")
        self.assertEqual(self.sign([item, item])[0], 400)

    def test_a_signed_office_becomes_a_job_without_any_command(self):
        item = signing.office_item("takeover", "chair", "s1", "s2", "allocate")
        signer = self.pin()
        proof = signer.proof(self.prepare([item])["payload"], self.origin)
        self.assertEqual(self.post_json("/api/offices", {"items": [item], "proof": None}, self.guard(self.host))[0], 400)
        self.assertEqual(self.post_json("/api/offices", {"items": [item], "proof": proof}, {"Host": self.host})[0], 403)
        self.assertEqual(self.post_json("/api/offices", {"items": [{**item, "holder": "s3"}], "proof": proof}, self.guard(self.host))[0], 409)
        status, _, body = self.post_json("/api/offices", {"items": [item], "proof": proof}, self.guard(self.host))
        self.assertEqual(status, 202, body)
        job_id = json.loads(body)["id"]
        written = self.offices / "jobs" / f"{job_id}.json"
        job = json.loads(written.read_text(encoding="utf-8"))
        self.assertEqual(sorted(job), ["created", "id", "items", "proof", "v"])
        self.assertEqual(job["items"], [{key_name: item[key_name] for key_name in ("action", "office", "holder", "session", "work")}])
        self.assertEqual(job["proof"], proof)
        self.assertNotIn("command", written.read_text(encoding="utf-8"))
        self.assertEqual((written.stat().st_mode & 0o777, (self.offices / "jobs").stat().st_mode & 0o777), (0o600, 0o700))
        self.assertEqual(json.loads(self.get(f"/api/offices/{job_id}")[2])["status"], "queued")
        self.assertEqual(self.get("/api/offices/0000000000000000")[0], 404)
        self.assertEqual(self.get("/api/offices")[0], 405)
        result = {"id": job_id, "finished": time.time(), "items": [{**job["items"][0], "status": "done", "reason": ""}]}
        (self.offices / "results" / f"{job_id}.json").write_text(json.dumps(result), encoding="utf-8")
        self.assertEqual(json.loads(self.get(f"/api/offices/{job_id}")[2])["status"], "done")


class TestHostOffices(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        self.council = base / "council"
        self.council.mkdir(mode=0o700)
        self.home = base / "home"
        sessions = self.home / ".claude" / "sessions"
        sessions.mkdir(parents=True)
        for sid, name in (("s1", "One"), ("s2", "Two")):
            (sessions / f"{sid}.json").write_text(json.dumps({"sessionId": sid, "name": name}), encoding="utf-8")
        self.jobs, self.results = base / "jobs", base / "results"
        self.jobs.mkdir()
        self.results.mkdir()
        self.approvers = base / "config" / "approvers.json"
        self.trust = verifier.Trust(approvers=self.approvers, replay=base / "replay" / "offices.json", origin=ORIGIN)
        self.signer = key(-7, "main")
        self.signer.pin(self.approvers, ORIGIN)
        self.runner = host.Offices(self.trust, self.council, COUNCIL_SCRIPT, self.home)

    def proof(self, items: list[dict], signer) -> dict:
        hashes = [signing.item_hash(signing.office_item(**item)) for item in items]
        return signer.proof(signing.approval_payload(hashes, secrets.token_hex(16), int(time.time()) + 600), ORIGIN)

    def run_job(self, items: list[dict], proof: object) -> dict:
        job_id = secrets.token_hex(8)
        (self.jobs / f"{job_id}.json").write_text(json.dumps({"v": 1, "id": job_id, "created": "x", "items": items, "proof": proof}), encoding="utf-8")
        self.assertEqual(host.cycle(self.jobs, self.results, self.runner), 1)
        self.assertEqual(list(self.jobs.iterdir()), [])
        return json.loads((self.results / f"{job_id}.json").read_text(encoding="utf-8"))

    def signed(self, item: dict) -> dict:
        return self.run_job([item], self.proof([item], self.signer))

    def holder(self, office: str) -> dict | None:
        path = self.council / office / "claim.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def files(self) -> list[str]:
        return sorted(str(path.relative_to(self.council)) for path in self.council.rglob("*"))

    def test_appoint_take_over_and_recall_run_the_council_script_for_the_operator(self):
        appoint = {"action": "appoint", "office": "chair", "holder": "", "session": "s1", "work": "allocate"}
        self.assertEqual([(entry["status"], entry["code"]) for entry in self.signed(appoint)["items"]], [("done", 0)])
        self.assertEqual({key_name: self.holder("chair")[key_name] for key_name in ("session", "runtime", "name", "work")}, {"session": "s1", "runtime": "claude-code", "name": "One", "work": "allocate"})
        takeover = {"action": "takeover", "office": "chair", "holder": "s1", "session": "s2", "work": "allocate more"}
        self.assertEqual(self.signed(takeover)["items"][0]["status"], "done")
        self.assertEqual((self.holder("chair")["session"], self.holder("chair")["name"]), ("s2", "Two"))
        asleep = {"action": "appoint", "office": "security/gui", "holder": "", "session": "s9", "work": "gui line"}
        self.assertEqual(self.signed(asleep)["items"][0]["status"], "done")
        self.assertEqual((self.holder("security/gui")["session"], self.holder("security/gui")["runtime"]), ("s9", "other"))
        recall = {"action": "recall", "office": "chair", "holder": "s2", "session": "", "work": ""}
        self.assertEqual(self.signed(recall)["items"][0]["status"], "done")
        self.assertIsNone(self.holder("chair"))
        president = {"action": "appoint", "office": "work/new", "holder": "", "session": "s1", "work": "build it"}
        self.assertEqual(self.signed(president)["items"][0]["status"], "done")
        row = json.loads((self.council / "rasci.json").read_text(encoding="utf-8"))["work/new"]
        self.assertEqual((row["worker"], row["description"], "workdir" in row, "branch" in row), ("One", "build it", False, False))

    def test_every_doubtful_item_is_refused_and_changes_nothing(self):
        appoint = {"action": "appoint", "office": "chair", "holder": "", "session": "s1", "work": "allocate"}
        self.signed({"action": "appoint", "office": "identity/oidc", "holder": "", "session": "s2", "work": "oidc"})
        rule = self.signer.proof(signing.rule_payload(secrets.token_hex(8), ["office"], "", "*", "*", int(time.time()) + 600), ORIGIN)
        outside = self.council.parent / "outside"
        (outside / "gui").mkdir(parents=True)
        cases = (
            ("bad signature", appoint, self.proof([appoint], key(-7, "intruder")), "no valid operator signature"),
            ("missing signature", appoint, None, "no signature"),
            ("rule instead of approval", appoint, rule, "no valid operator signature"),
            ("other item signed", appoint, self.proof([{**appoint, "session": "s2"}], self.signer), "does not list this item"),
            ("holder changed", {**appoint, "office": "identity/oidc"}, self.proof([{**appoint, "office": "identity/oidc"}], self.signer), "holder changed"),
        )
        for name, item, proof, reason in cases:
            with self.subTest(name=name):
                before = self.files()
                result = self.run_job([item], proof)
                self.assertEqual([entry["status"] for entry in result["items"]], ["refused"])
                self.assertIn(reason, result["items"][0]["reason"])
                self.assertEqual(self.files(), before)
        (self.council / "security").symlink_to(outside)
        linked = {**appoint, "office": "security/gui"}
        result = self.signed(linked)
        self.assertEqual(result["items"][0]["status"], "refused")
        self.assertIn("link", result["items"][0]["reason"])
        self.assertEqual(list(outside.rglob("*")), [outside / "gui"])
        (self.council / "security").unlink()
        self.council.chmod(0o777)
        result = self.signed(appoint)
        self.assertEqual(result["items"][0]["status"], "refused")
        self.assertIn("others can write", result["items"][0]["reason"])
        self.council.chmod(0o700)
        self.assertIsNone(self.holder("chair"))

    def test_the_runner_passes_no_flag_and_checks_the_holder_in_the_removal_itself(self):
        self.signed({"action": "appoint", "office": "chair", "holder": "", "session": "s1", "work": "allocate"})
        takeover = {"action": "takeover", "office": "chair", "holder": "s1", "session": "s2", "work": "allocate"}
        recall = {"action": "recall", "office": "chair", "holder": "s1", "session": "", "work": ""}
        self.assertNotIn("--operator", self.runner.command(takeover)[0])
        swapped = {**self.holder("chair"), "session": "s9"}
        (self.council / "chair" / "claim.json").write_text(json.dumps(swapped), encoding="utf-8")
        with mock.patch.object(host, "holder_of", return_value="s1"):
            for item in (takeover, recall):
                with self.subTest(action=item["action"]):
                    result = self.signed(item)["items"][0]
                    self.assertEqual(result["status"], "refused", result)
                    self.assertIn("holder changed", result["reason"])
                    self.assertEqual(self.holder("chair"), swapped)
        self.assertEqual(self.files(), ["chair", "chair/claim.json"])

    def test_a_claim_council_would_not_read_is_never_reported_recalled(self):
        (self.council / "chair").mkdir()
        (self.council / "chair" / "claim.json").write_text(json.dumps({"session": "s1"}), encoding="utf-8")
        result = self.signed({"action": "recall", "office": "chair", "holder": "s1", "session": "", "work": ""})["items"][0]
        self.assertNotEqual(result["status"], "done", result)
        self.assertEqual(self.files(), ["chair", "chair/claim.json"])

    def test_a_job_that_is_a_link_a_fifo_or_too_large_runs_nothing(self):
        appoint = {"action": "appoint", "office": "chair", "holder": "", "session": "s1", "work": "allocate"}
        linked, fifo, large = (secrets.token_hex(8) for _ in range(3))
        planted = self.council.parent / "planted.json"
        planted.write_text(json.dumps({"v": 1, "id": linked, "created": "x", "items": [appoint], "proof": self.proof([appoint], self.signer)}), encoding="utf-8")
        (self.jobs / f"{linked}.json").symlink_to(planted)
        os.mkfifo(self.jobs / f"{fifo}.json", 0o600)
        (self.jobs / f"{large}.json").write_text(" " * (host.READ_LIMIT + 1), encoding="utf-8")
        self.assertEqual(host.cycle(self.jobs, self.results, self.runner), 3)
        for job_id in (linked, fifo, large):
            with self.subTest(job=job_id):
                result = json.loads((self.results / f"{job_id}.json").read_text(encoding="utf-8"))
                self.assertEqual(result["items"], [])
                self.assertIn("unreadable job", result["error"])
        self.assertEqual((list(self.jobs.iterdir()), self.files()), ([], []))
        self.assertTrue(planted.is_file())

    def test_a_signature_runs_once_and_a_malformed_job_nothing(self):
        appoint = {"action": "appoint", "office": "chair", "holder": "", "session": "s1", "work": "allocate"}
        proof = self.proof([appoint], self.signer)
        self.assertEqual(self.run_job([appoint], proof)["items"][0]["status"], "done")
        self.signed({"action": "recall", "office": "chair", "holder": "s1", "session": "", "work": ""})
        again = self.run_job([appoint], proof)
        self.assertEqual(again["items"][0]["status"], "refused")
        self.assertIn("already used", again["items"][0]["reason"])
        for name, items in (
            ("command smuggled in", [{**appoint, "command": "rm -rf ~"}]),
            ("climbing office", [{**appoint, "office": "../x"}]),
            ("unknown action", [{**appoint, "action": "fire"}]),
            ("option as session", [{**appoint, "session": "--all"}]),
            ("two lines of work", [{**appoint, "work": "a\nb"}]),
            ("recall with work", [{"action": "recall", "office": "chair", "holder": "s1", "session": "", "work": "x"}]),
            ("no items", []),
        ):
            with self.subTest(name=name):
                result = self.run_job(items, None)
                self.assertEqual(result["items"], [])
                self.assertIn("malformed job", result["error"])
        self.assertIsNone(self.holder("chair"))

    def test_the_unit_runs_the_script_once_over_the_job_directory(self):
        appoint = {"action": "appoint", "office": "chair", "holder": "", "session": "s1", "work": "allocate"}
        job_id = secrets.token_hex(8)
        (self.jobs / f"{job_id}.json").write_text(json.dumps({"v": 1, "id": job_id, "created": "x", "items": [appoint], "proof": self.proof([appoint], self.signer)}), encoding="utf-8")
        (self.jobs / "stray.tmp").write_text("x", encoding="utf-8")
        trust = ["--approvers", str(self.approvers), "--replay", str(self.trust.replay)]
        command = [sys.executable, str(OFFICES), "--port", ORIGIN.rsplit(":", 1)[1], "--jobs", str(self.jobs), "--results", str(self.results), *trust, "--council", str(self.council), "--script", str(COUNCIL_SCRIPT)]
        done = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False, env={"PATH": "/usr/bin:/bin", "HOME": str(self.home)})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(list(self.jobs.iterdir()), [])
        result = json.loads((self.results / f"{job_id}.json").read_text(encoding="utf-8"))
        self.assertEqual(result["items"][0]["status"], "done", result)
        self.assertEqual((self.results / f"{job_id}.json").stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.holder("chair")["session"], "s1")


if __name__ == "__main__":
    unittest.main()
