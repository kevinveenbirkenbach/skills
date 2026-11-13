from __future__ import annotations

import contextlib
import errno
import hashlib
import importlib.util
import io
import json
import os
import secrets
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import test_hub_spool_links as spool_links
from hub_support import HUB, ORIGIN, key, signing, verifier

WRITER = HUB / "client" / "settings_writer.py"
WRITER_SPEC = importlib.util.spec_from_file_location("kvb_orchestrator_settings_writer", WRITER)
host = importlib.util.module_from_spec(WRITER_SPEC)
WRITER_SPEC.loader.exec_module(host)
ORIGINAL = {
    "model": "x",
    "env": {"EXAMPLE_FLAG": "fixture-value-not-a-secret"},
    "hooks": {"Stop": [{"matcher": "", "hooks": [{"type": "command", "command": "true"}]}]},
    "permissions": {"allow": ["Bash(make test:*)", "Bash(git status:*)"], "deny": ["Read(~/.ssh/**)"]},
    "sandbox": {"enabled": True, "filesystem": {"allowWrite": ["/tmp"]}},
}
ADD_LINT = {"list": "permissions.allow", "op": "add", "entry": "Bash(make lint:*)"}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class TestSettingsWriter(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.home = self.base / "home"
        self.settings = self.home / ".claude" / "settings.json"
        self.project = self.base / "repo"
        self.project_settings = self.project / ".claude" / "settings.json"
        self.elsewhere = self.base / "elsewhere" / ".claude" / "settings.json"
        for path in (self.settings, self.elsewhere):
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(ORIGINAL, indent=2) + "\n", encoding="utf-8")
            path.chmod(0o640)
        self.project_settings.parent.mkdir(parents=True)
        self.tree = self.base / "tree" / "branch-tree.json"
        self.tree.parent.mkdir()
        self.tree.write_text(json.dumps({"repos": [{"path": str(self.project), "known": True, "default": "main"}, {"path": str(self.elsewhere.parent.parent), "known": False}]}), encoding="utf-8")
        self.jobs, self.results = self.base / "jobs", self.base / "results"
        self.jobs.mkdir(mode=0o700)
        self.results.mkdir(mode=0o700)
        self.approvers = self.base / "config" / "approvers.json"
        self.trust = verifier.Trust(approvers=self.approvers, replay=self.base / "replay" / "firewall.json", origin=ORIGIN)
        self.signer = key(-7, "main")
        self.signer.pin(self.approvers, ORIGIN)
        self.writer = host.Writer(self.trust, self.home, self.tree)

    def item(self, path: Path, changes: list[dict]) -> dict:
        return {"file": str(path), "base": sha(path.read_bytes()) if path.exists() else "", "changes": changes}

    def proof(self, items: list[dict], signer) -> dict:
        hashes = [signing.item_hash(signing.settings_item(**item)) for item in items]
        return signer.proof(signing.approval_payload(hashes, secrets.token_hex(16), int(time.time()) + 600), ORIGIN)

    def write_job(self, job_id: str, items: list[dict], proof: object) -> None:
        (self.jobs / f"{job_id}.json").write_text(json.dumps({"v": 1, "id": job_id, "created": "x", "items": items, "proof": proof}), encoding="utf-8")

    def result(self, job_id: str) -> dict:
        return json.loads((self.results / f"{job_id}.json").read_text(encoding="utf-8"))

    def run_job(self, items: list[dict], proof: object) -> dict:
        job_id = secrets.token_hex(8)
        self.write_job(job_id, items, proof)
        self.assertEqual(host.cycle(self.jobs, self.results, self.writer), 1)
        self.assertEqual(list(self.jobs.iterdir()), [])
        return self.result(job_id)

    def unit(self, view: Path, marker: dict[str, str]) -> subprocess.CompletedProcess:
        trust = ["--approvers", str(self.approvers), "--replay", str(self.trust.replay)]
        command = [sys.executable, str(WRITER), "--port", ORIGIN.rsplit(":", 1)[1], "--jobs", str(self.jobs), "--results", str(self.results), "--view", str(view), *trust, "--tree", str(self.tree)]
        return subprocess.run(command, capture_output=True, text=True, timeout=60, check=False, env={"PATH": "/usr/bin:/bin", "HOME": str(self.home), **marker})

    def signed(self, item: dict) -> dict:
        return self.run_job([item], self.proof([item], self.signer))["items"][0]

    def files(self) -> dict[str, tuple[int, str]]:
        found = {}
        for root in (self.home, self.project, self.elsewhere.parent.parent):
            for path in sorted(root.rglob("*")):
                if path.is_file() or path.is_symlink():
                    found[str(path)] = (path.lstat().st_mode, sha(path.read_bytes()) if path.is_file() else os.readlink(path))
        return found

    def test_a_signed_change_writes_exactly_it_keeps_every_other_key_and_a_backup_with_the_mode(self):
        before = self.settings.read_bytes()
        changes = [ADD_LINT, {"list": "permissions.deny", "op": "remove", "entry": "Read(~/.ssh/**)"}, {"list": "sandbox.network.allowedDomains", "op": "add", "entry": "example.org"}]
        result = self.signed(self.item(self.settings, changes))
        self.assertEqual((result["status"], result["reason"]), ("done", ""), result)
        expected = json.loads(json.dumps(ORIGINAL))
        expected["permissions"]["allow"].append("Bash(make lint:*)")
        expected["permissions"]["deny"] = []
        expected["sandbox"]["network"] = {"allowedDomains": ["example.org"]}
        written = self.settings.read_bytes()
        self.assertEqual(json.loads(written), expected)
        self.assertEqual(list(json.loads(written)), list(ORIGINAL))
        self.assertEqual(result["sha256"], sha(written))
        backup = Path(result["backup"])
        self.assertEqual((backup.parent, backup.read_bytes()), (self.settings.parent, before))
        self.assertEqual({path.name: path.stat().st_mode & 0o777 for path in self.settings.parent.iterdir()}, {"settings.json": 0o640, backup.name: 0o640})

    def test_a_missing_project_file_is_created_private_with_only_the_change(self):
        result = self.signed(self.item(self.project_settings, [ADD_LINT]))
        self.assertEqual((result["status"], result["backup"]), ("done", ""), result)
        self.assertEqual(json.loads(self.project_settings.read_text(encoding="utf-8")), {"permissions": {"allow": ["Bash(make lint:*)"]}})
        self.assertEqual(self.project_settings.stat().st_mode & 0o777, 0o600)

    def test_a_forged_changed_stale_unlisted_or_impossible_job_changes_nothing(self):
        good = self.item(self.settings, [ADD_LINT])
        rule = self.signer.proof(signing.rule_payload(secrets.token_hex(8), ["settings"], "", "*", "*", int(time.time()) + 600), ORIGIN)
        swapped = {**good, "changes": [{**ADD_LINT, "entry": "Bash(rm -rf:*)"}]}
        stale = {**good, "base": sha(b"{}")}
        unlisted = self.item(self.elsewhere, [ADD_LINT])
        twice = self.item(self.settings, [{**ADD_LINT, "entry": "Bash(make test:*)"}])
        absent = self.item(self.settings, [{**ADD_LINT, "op": "remove"}])
        cases = (
            ("forged signature", good, self.proof([good], key(-7, "intruder")), "no valid operator signature"),
            ("missing signature", good, None, "no signature"),
            ("rule instead of an approval", good, rule, "no valid operator signature"),
            ("changed after signing", swapped, self.proof([good], self.signer), "does not list this item"),
            ("stale base", stale, self.proof([stale], self.signer), "changed since the signature"),
            ("unlisted file", unlisted, self.proof([unlisted], self.signer), "unlisted file"),
            ("added twice", twice, self.proof([twice], self.signer), "lists Bash(make test:*)"),
            ("removed absent", absent, self.proof([absent], self.signer), "does not list"),
        )
        for name, item, proof, reason in cases:
            with self.subTest(name=name):
                before = self.files()
                result = self.run_job([item], proof)["items"][0]
                self.assertEqual(result["status"], "refused", result)
                self.assertIn(reason, result["reason"])
                self.assertEqual(self.files(), before)

    def test_the_host_refuses_to_add_a_hidden_character_and_removes_one_already_in_the_file(self):
        hidden = f"Bash(make{chr(0x202E)} build:*)"
        before = self.files()
        addition = self.item(self.settings, [{**ADD_LINT, "entry": hidden}])
        self.assertEqual(self.run_job([addition], self.proof([addition], self.signer))["error"], "malformed job: refused, nothing changed")
        self.assertEqual(self.files(), before)
        settings = json.loads(self.settings.read_text(encoding="utf-8"))
        settings["permissions"]["allow"].append(hidden)
        self.settings.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
        result = self.signed(self.item(self.settings, [{"list": "permissions.allow", "op": "remove", "entry": hidden}]))
        self.assertEqual(result["status"], "done", result)
        self.assertEqual(json.loads(self.settings.read_text(encoding="utf-8"))["permissions"]["allow"], ORIGINAL["permissions"]["allow"])

    def test_a_replayed_signature_changes_nothing_even_when_the_file_is_back_at_its_base(self):
        before = self.settings.read_bytes()
        item = self.item(self.settings, [ADD_LINT])
        proof = self.proof([item], self.signer)
        self.assertEqual(self.run_job([item], proof)["items"][0]["status"], "done")
        self.settings.write_bytes(before)
        again = self.run_job([item], proof)["items"][0]
        self.assertEqual(again["status"], "refused")
        self.assertIn("already used", again["reason"])
        self.assertEqual(self.settings.read_bytes(), before)

    def test_a_link_on_the_path_or_at_the_file_is_refused(self):
        outside = self.base / "outside"
        (outside / ".claude").mkdir(parents=True)
        target = outside / ".claude" / "settings.json"
        target.write_text("{}\n", encoding="utf-8")
        self.project_settings.parent.rmdir()
        (self.project / ".claude").symlink_to(outside / ".claude")
        result = self.signed({"file": str(self.project_settings), "base": sha(b"{}\n"), "changes": [ADD_LINT]})
        self.assertEqual(result["status"], "refused", result)
        self.assertIn("link", result["reason"])
        (self.project / ".claude").unlink()
        (self.project / ".claude").mkdir()
        self.project_settings.symlink_to(target)
        result = self.signed({"file": str(self.project_settings), "base": sha(b"{}\n"), "changes": [ADD_LINT]})
        self.assertEqual(result["status"], "refused", result)
        self.assertIn("link", result["reason"])
        self.assertEqual((target.read_text(encoding="utf-8"), self.project_settings.is_symlink()), ("{}\n", True))

    def test_a_failed_replace_keeps_the_file_and_leaves_no_temporary(self):
        before = self.settings.read_bytes()
        replace = os.replace

        def failing(source: str, target: str, **kwargs: int) -> None:
            if target == "settings.json":
                raise OSError(errno.EIO, "disk gone")
            replace(source, target, **kwargs)

        with mock.patch.object(host.os, "replace", failing):
            result = self.signed(self.item(self.settings, [ADD_LINT]))
        self.assertEqual(result["status"], "failed", result)
        self.assertEqual(self.settings.read_bytes(), before)
        self.assertEqual(sorted(path.name for path in self.settings.parent.iterdir() if path.name.startswith(".")), [])

    def test_a_malformed_or_linked_job_writes_nothing(self):
        good = self.item(self.settings, [ADD_LINT])
        before = self.files()
        for name, items in (
            ("command smuggled in", [{**good, "command": "rm -rf ~"}]),
            ("local settings", [{**good, "file": str(self.settings.with_name("settings.local.json"))}]),
            ("climbing path", [{**good, "file": f"{self.home}/../home/.claude/settings.json"}]),
            ("no changes", [{**good, "changes": []}]),
            ("hooks list", [{**good, "changes": [{**ADD_LINT, "list": "hooks.PermissionRequest"}]}]),
            ("replace op", [{**good, "changes": [{**ADD_LINT, "op": "replace"}]}]),
            ("two lines", [{**good, "changes": [{**ADD_LINT, "entry": "a\nb"}]}]),
            ("lone surrogate entry", [{**good, "changes": [{**ADD_LINT, "entry": "Bash(make \ud800:*)"}]}]),
            ("lone surrogate path", [{**good, "file": f"{self.home}/\ud800/.claude/settings.json"}]),
            ("twice the same entry", [{**good, "changes": [ADD_LINT, ADD_LINT]}]),
            ("no items", []),
        ):
            with self.subTest(name=name):
                result = self.run_job(items, self.proof([good], self.signer))
                self.assertEqual(result["items"], [])
                self.assertIn("malformed job", result["error"])
        job_id = secrets.token_hex(8)
        planted = self.base / "planted.json"
        planted.write_text(json.dumps({"v": 1, "id": job_id, "created": "x", "items": [good], "proof": self.proof([good], self.signer)}), encoding="utf-8")
        (self.jobs / f"{job_id}.json").symlink_to(planted)
        self.assertEqual(host.cycle(self.jobs, self.results, self.writer), 1)
        self.assertIn("unreadable job", self.result(job_id)["error"])
        pipe = secrets.token_hex(8)
        os.mkfifo(self.jobs / f"{pipe}.json")
        renamed = secrets.token_hex(8)
        self.write_job(renamed, [good], self.proof([good], self.signer))
        (self.jobs / f"{renamed}.json").rename(self.jobs / f"{'0' * 16}.json")
        self.assertEqual(host.cycle(self.jobs, self.results, self.writer), 2)
        self.assertIn("not a regular file", self.result(pipe)["error"])
        self.assertEqual((self.result("0" * 16)["items"], self.result("0" * 16)["error"]), ([], "malformed job: refused, nothing changed"))
        self.assertEqual((list(self.jobs.iterdir()), self.files()), ([], before))

    def test_a_file_json_readers_could_read_differently_fails_and_stays_byte_identical(self):
        for name, text, reason in (
            ("overflowing number", '{"model": 1e400}', "beyond the double range"),
            ("NaN", '{"model": NaN}', "holds NaN"),
            ("Infinity", '{"model": Infinity}', "holds Infinity"),
            ("minus Infinity", '{"model": -Infinity}', "holds -Infinity"),
            ("repeated key", '{"permissions": {"allow": []}, "permissions": {"deny": []}}', "repeats a key"),
            ("lone surrogate", '{"model": "\\ud800"}', "lone surrogate"),
            ("600 levels", '{"model": ' + "[" * 600 + "]" * 600 + "}", "nests deeper than 64"),
            ("no object", "[]", "no JSON object"),
            ("no JSON", "{", "no strict JSON"),
        ):
            with self.subTest(name=name):
                self.settings.write_text(text + "\n", encoding="utf-8")
                before = self.files()
                result = self.signed(self.item(self.settings, [ADD_LINT]))
                self.assertEqual(result["status"], "failed", result)
                self.assertIn(reason, result["reason"])
                self.assertNotIn("model", result["reason"])
                self.assertEqual(self.files(), before)
                shown = self.writer.view()["files"][0]
                self.assertEqual((reason in shown["error"], shown["settings"]), (True, {}), shown)

    def test_a_poisoned_file_fails_only_its_job_and_the_unit_applies_the_next_and_rewrites_the_view(self):
        second = self.base / "second" / ".claude" / "settings.json"
        second.parent.mkdir(parents=True)
        self.tree.write_text(json.dumps({"repos": [{"path": str(self.project), "known": True, "default": "main"}, {"path": str(second.parent.parent), "known": True, "default": "main"}]}), encoding="utf-8")
        self.project_settings.write_text('{"model": "\\ud800"}\n', encoding="utf-8")
        second.write_text('{"model": ' + "[" * 600 + "]" * 600 + "}\n", encoding="utf-8")
        poisoned = {path: path.read_bytes() for path in (self.project_settings, second)}
        jobs = {"0" * 16: self.item(self.project_settings, [ADD_LINT]), "1" * 16: self.item(second, [ADD_LINT]), "f" * 16: self.item(self.settings, [ADD_LINT])}
        for job_id, item in jobs.items():
            self.write_job(job_id, [item], self.proof([item], self.signer))
        view = self.base / "state" / "view.json"
        done = self.unit(view, {})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(list(self.jobs.iterdir()), [])
        found = [(self.result(job_id)["items"][0]["status"], self.result(job_id)["items"][0]["reason"]) for job_id in jobs]
        self.assertEqual([status for status, _ in found], ["failed", "failed", "done"], found)
        self.assertIn("lone surrogate", found[0][1])
        self.assertIn("nests deeper than 64", found[1][1])
        self.assertEqual({path: path.read_bytes() for path in poisoned}, poisoned)
        self.assertEqual([sorted(child.name for child in path.parent.iterdir()) for path in poisoned], [["settings.json"], ["settings.json"]])
        self.assertIn("Bash(make lint:*)", json.loads(self.settings.read_text(encoding="utf-8"))["permissions"]["allow"])
        shown = {entry["path"]: entry for entry in json.loads(view.read_text(encoding="utf-8"))["files"]}
        self.assertEqual(shown[str(self.settings)]["sha256"], sha(self.settings.read_bytes()))
        self.assertIn("lone surrogate", shown[str(self.project_settings)]["error"])
        self.assertIn("nests deeper than 64", shown[str(second)]["error"])

    def test_a_bad_tree_path_or_a_deep_tree_marks_only_itself_and_the_unit_still_applies_and_rewrites_the_view(self):
        nul, surrogate = f"{self.base}/nul\x00dir", f"{self.base}/\ud800dir"
        for name, text, bad, error in (
            ("NUL in a path", json.dumps({"repos": [{"path": nul, "known": True}]}), f"{nul}{signing.SETTINGS_FILE}", "unreadable: ValueError"),
            ("lone surrogate in a path", json.dumps({"repos": [{"path": surrogate, "known": True}]}), f"{surrogate}{signing.SETTINGS_FILE}", "unreadable: UnicodeEncodeError"),
            ("tree nested 100000 levels", '{"repos": ' + "[" * 100000 + "]" * 100000 + "}", None, None),
        ):
            with self.subTest(name=name):
                self.tree.write_text(text, encoding="utf-8")
                self.settings.write_text(json.dumps(ORIGINAL, indent=2) + "\n", encoding="utf-8")
                item = self.item(self.settings, [ADD_LINT])
                job_id = secrets.token_hex(8)
                self.write_job(job_id, [item], self.proof([item], self.signer))
                view = self.base / "state" / f"{job_id}.json"
                done = self.unit(view, {})
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertEqual(self.result(job_id)["items"][0]["status"], "done")
                shown = {entry["path"]: entry for entry in json.loads(view.read_text(encoding="utf-8"))["files"]}
                self.assertEqual(sorted(shown), sorted([str(self.settings), *([bad] if bad else [])]))
                self.assertEqual((shown[str(self.settings)]["sha256"], shown[str(self.settings)]["error"]), (sha(self.settings.read_bytes()), ""))
                if bad:
                    self.assertEqual((shown[bad]["error"], shown[bad]["settings"]), (error, {}))

    def test_the_view_is_rewritten_even_when_a_result_cannot_be_written(self):
        item = self.item(self.settings, [ADD_LINT])
        job_id = secrets.token_hex(8)
        self.write_job(job_id, [item], self.proof([item], self.signer))
        self.results.chmod(0o500)
        self.addCleanup(self.results.chmod, 0o700)
        view = self.base / "state" / "view.json"
        done = self.unit(view, {})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn(f"no result for {job_id}.json", done.stderr)
        self.assertEqual((list(self.jobs.iterdir()), list(self.results.iterdir())), ([], []))
        self.assertEqual(json.loads(view.read_text(encoding="utf-8"))["files"][0]["sha256"], sha(self.settings.read_bytes()))

    def test_a_view_that_cannot_be_written_ends_the_unit_with_one_line_and_keeps_the_results(self):
        item = self.item(self.settings, [ADD_LINT])
        job_id = secrets.token_hex(8)
        self.write_job(job_id, [item], self.proof([item], self.signer))
        view = self.base / "state" / "view.json"
        view.mkdir(mode=0o700, parents=True)
        done = self.unit(view, {})
        self.assertEqual((done.returncode, "Traceback" in done.stderr), (0, False), done.stderr)
        self.assertIn("view not written", done.stderr)
        self.assertEqual((self.result(job_id)["items"][0]["status"], view.is_dir()), ("done", True))

    def test_a_directory_sync_failing_after_the_replace_reports_the_written_change(self):
        real = os.fsync

        def failing(fd: int) -> None:
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError(errno.EIO, "Input/output error")
            real(fd)

        with mock.patch.object(host.os, "fsync", side_effect=failing):
            result = self.signed(self.item(self.settings, [ADD_LINT]))
        self.assertEqual(result["status"], "done", result)
        self.assertIn("written, but its directory sync failed: Input/output error", result["reason"])
        self.assertIn("Bash(make lint:*)", json.loads(self.settings.read_text(encoding="utf-8"))["permissions"]["allow"])
        self.assertEqual(result["sha256"], sha(self.settings.read_bytes()))

    def test_the_unit_makes_no_directory_and_writes_nothing_through_a_linked_spool(self):
        victim = self.base / "victim"
        victim.mkdir(mode=0o700)
        spool = self.base / "spool"
        spool.symlink_to(victim)
        self.jobs, self.results = spool / "jobs", spool / "results"
        done = self.unit(spool / "view.json", {})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("refused, nothing done", done.stderr)
        self.assertIn("view not written", done.stderr)
        self.assertEqual(list(victim.iterdir()), [])

    def test_a_view_in_a_linked_or_foreign_spool_is_refused_and_a_linked_view_file_replaced(self):
        victim = self.base / "victim"
        victim.mkdir(mode=0o700)
        (victim / "view.json").write_text("victim", encoding="utf-8")
        linked, shared, real = self.base / "linked", self.base / "shared", self.base / "real"
        linked.symlink_to(victim)
        shared.mkdir()
        shared.chmod(0o770)
        real.mkdir(mode=0o700)
        (real / "view.json").symlink_to(victim / "view.json")
        for folder in (linked, shared, real):
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                host.write_view(folder / "view.json", self.writer.view())
            with self.subTest(folder=folder.name):
                self.assertEqual("view not written" in stderr.getvalue(), folder != real, stderr.getvalue())
        self.assertEqual(([path.name for path in victim.iterdir()], (victim / "view.json").read_text(encoding="utf-8"), list(shared.iterdir())), (["view.json"], "victim", []))
        self.assertFalse((real / "view.json").is_symlink())
        self.assertEqual(json.loads((real / "view.json").read_text(encoding="utf-8"))["files"][0]["path"], str(self.settings))

    def test_an_unexpected_crash_fails_only_its_job_or_item_and_names_only_its_kind(self):
        apply, problem = signing.apply_changes, signing.settings_problem
        crashes = iter([RecursionError("planted depth"), UnicodeEncodeError("utf-8", "planted text", 0, 1, "planted")])
        checked = []

        def crashing_apply(settings: dict, changes: list[dict]) -> dict:
            error = next(crashes, None)
            if error is not None:
                raise error
            return apply(settings, changes)

        def crashing_problem(item: object) -> str | None:
            checked.append(item)
            if len(checked) == 1:
                raise KeyError("planted key")
            return problem(item)

        item = self.item(self.settings, [ADD_LINT])
        for job_id in ("0" * 16, "1" * 16, "2" * 16, "f" * 16):
            self.write_job(job_id, [item], self.proof([item], self.signer))
        with mock.patch.object(host.signing, "apply_changes", crashing_apply), mock.patch.object(host.signing, "settings_problem", crashing_problem):
            self.assertEqual(host.cycle(self.jobs, self.results, self.writer), 4)
        self.assertEqual((self.result("0" * 16)["items"], self.result("0" * 16)["error"]), ([], "failed: KeyError; nothing changed"))
        found = [(self.result(job_id)["items"][0]["status"], self.result(job_id)["items"][0]["reason"]) for job_id in ("1" * 16, "2" * 16, "f" * 16)]
        self.assertEqual(found, [("failed", "RecursionError; the file kept its content"), ("failed", "UnicodeEncodeError; the file kept its content"), ("done", "")])
        self.assertEqual(json.loads(self.settings.read_text(encoding="utf-8"))["permissions"]["allow"].count("Bash(make lint:*)"), 1)
        self.assertEqual(list(self.jobs.iterdir()), [])

    def test_a_non_finite_number_never_reaches_the_file_even_past_the_parser(self):
        before = self.files()
        with mock.patch.object(host, "parsed", return_value={"model": float("inf")}):
            result = self.signed(self.item(self.settings, [ADD_LINT]))
        self.assertEqual((result["status"], result["reason"]), ("failed", "ValueError; the file kept its content"))
        self.assertEqual(self.files(), before)

    def test_a_planted_temporary_link_is_never_followed(self):
        outside = self.base / "outside.json"
        outside.write_text("{}\n", encoding="utf-8")
        before = self.settings.read_bytes()
        item = self.item(self.settings, [ADD_LINT])
        job_id = secrets.token_hex(8)
        self.write_job(job_id, [item], self.proof([item], self.signer))
        fixed = "0" * 16
        (self.settings.parent / f".settings.json.{fixed}").symlink_to(outside)
        with mock.patch.object(host.secrets, "token_hex", return_value=fixed):
            self.assertEqual(host.cycle(self.jobs, self.results, self.writer), 1)
        self.assertEqual(self.result(job_id)["items"][0]["status"], "failed")
        self.assertEqual((self.settings.read_bytes(), self.settings.is_symlink(), outside.read_text(encoding="utf-8")), (before, False, "{}\n"))

    def test_a_file_of_another_uid_is_refused(self):
        before = self.files()
        item = self.item(self.settings, [ADD_LINT])
        proof = self.proof([item], self.signer)
        with mock.patch.object(host.os, "getuid", return_value=os.getuid() + 1):
            result = self.run_job([item], proof)["items"][0]
        self.assertEqual(result["status"], "refused", result)
        self.assertIn(f"belongs to uid {os.getuid()}", result["reason"])
        self.assertEqual(self.files(), before)

    def test_a_settings_path_that_is_no_regular_file_is_refused(self):
        os.mkfifo(self.project_settings)
        result = self.signed({"file": str(self.project_settings), "base": sha(b""), "changes": [ADD_LINT]})
        self.assertEqual(result["status"], "refused", result)
        self.assertIn("no regular file", result["reason"])
        self.assertTrue(stat.S_ISFIFO(self.project_settings.lstat().st_mode))

    def test_the_view_lists_the_fixed_files_with_only_permissions_and_sandbox(self):
        view = self.writer.view()
        self.assertEqual([entry["path"] for entry in view["files"]], [str(self.settings), str(self.project_settings)])
        own, project = view["files"]
        self.assertEqual((own["exists"], own["sha256"], own["error"]), (True, sha(self.settings.read_bytes()), ""))
        self.assertEqual(own["settings"], {"permissions": ORIGINAL["permissions"], "sandbox": ORIGINAL["sandbox"]})
        self.assertEqual((project["exists"], project["sha256"], project["settings"]), (False, "", {}))
        self.assertNotIn("fixture-value-not-a-secret", json.dumps(view))

    def test_a_missing_directory_shows_in_the_view_as_the_writer_handles_it(self):
        self.project_settings.parent.rmdir()
        shown = self.writer.view()["files"][1]
        self.assertEqual((shown["exists"], shown["error"]), (False, host.MISSING_DIRECTORY))
        result = self.signed({"file": str(self.project_settings), "base": "", "changes": [ADD_LINT]})
        self.assertEqual((result["status"], self.project_settings.parent.exists()), ("refused", False), result)
        self.project_settings.parent.mkdir()
        self.assertEqual(self.writer.view()["files"][1]["error"], "")
        self.assertEqual(self.signed({"file": str(self.project_settings), "base": "", "changes": [ADD_LINT]})["status"], "done")

    def test_the_unit_runs_once_outside_any_agent_and_refuses_inside_one(self):
        item = self.item(self.settings, [ADD_LINT])
        before = self.settings.read_bytes()
        job_id = secrets.token_hex(8)
        self.write_job(job_id, [item], self.proof([item], self.signer))
        view = self.base / "state" / "view.json"
        for marker in host.AGENT_MARKERS:
            with self.subTest(marker=marker):
                inside = self.unit(view, {marker: "1"})
                self.assertEqual(inside.returncode, 2, inside.stderr)
                self.assertIn("refused", inside.stderr)
                self.assertEqual((self.settings.read_bytes(), view.exists(), len(list(self.jobs.iterdir()))), (before, False, 1))
        done = self.unit(view, {})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(list(self.jobs.iterdir()), [])
        result = self.result(job_id)
        self.assertEqual(result["items"][0]["status"], "done", result)
        self.assertIn("Bash(make lint:*)", json.loads(self.settings.read_text(encoding="utf-8"))["permissions"]["allow"])
        self.assertEqual(((self.results / f"{job_id}.json").stat().st_mode & 0o777, view.stat().st_mode & 0o777), (0o600, 0o600))
        self.assertEqual(json.loads(view.read_text(encoding="utf-8"))["files"][0]["sha256"], sha(self.settings.read_bytes()))


class TestSettingsWriterSpoolLinks(spool_links.SpoolLinks, unittest.TestCase):
    module = host

    def unit(self, trust: verifier.Trust, base: Path):
        return host.Writer(trust, base / "home", base / "tree.json")


if __name__ == "__main__":
    unittest.main()
