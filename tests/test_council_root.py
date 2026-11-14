from __future__ import annotations

import contextlib
import errno
import fcntl
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import ModuleType
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
ORGANIZE = REPO_ROOT / "skills" / "kvb-org-organize" / "scripts"
COUNCIL_ROOT = ORGANIZE / "councilroot.py"
WATCH = ORGANIZE / "watch.py"
QUEUE = REPO_ROOT / "skills" / "kvb-org-queue" / "scripts" / "queue.py"
SECURITY = REPO_ROOT / "skills" / "kvb-check-security" / "scripts" / "security.py"
GATES = REPO_ROOT / "skills" / "kvb-check-gate" / "scripts" / "gates.py"
LOG = REPO_ROOT / "skills" / "kvb-org-perform" / "scripts" / "log.py"
CLIENT = REPO_ROOT / "orchestrator" / "client"
INSTALL = REPO_ROOT / "scripts" / "install.sh"
GATE_SKILL = REPO_ROOT / "skills" / "kvb-check-gate"
SCANNED = ("skills", "orchestrator", "scripts")
FORBIDDEN = re.compile(r"/tmp/(?:agents-council|kvb-git-diff|kvb-orchestrator-approvals|release-)")
LEGACY_LINE = 'LEGACY = Path("/tmp/agents-council")'
DIR_SLASH = re.compile(r"councilroot\.py dir [^)\n]*\)/")
RADIO = REPO_ROOT / "skills" / "kvb-org-radio" / "scripts" / "radio.py"
CLEANUP_SERVICE = REPO_ROOT / "skills" / "kvb-org-queue-cleanup" / "systemd" / "kvb-org-queue-cleanup.service"


def load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rows(path: Path) -> list[str]:
    return [json.loads(line)["id"] for line in path.read_text(encoding="utf-8").splitlines()]


class Home(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name).resolve()
        self.home = self.base / "home"
        self.home.mkdir()
        patch = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        patch.start()
        self.addCleanup(patch.stop)
        for name in ("AGENTS_COUNCIL_ROOT", "XDG_STATE_HOME"):
            os.environ.pop(name, None)
        self.durable = self.home / ".local" / "state" / "agents-council"
        self.shared = self.home / ".local" / "state" / "agents-shared"
        self.councilroot = load(COUNCIL_ROOT, f"test_councilroot_{id(self)}")

    def cli(self, *args: str, **env: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(COUNCIL_ROOT), *args], env={"PATH": os.environ["PATH"], "HOME": str(self.home), **env},
            capture_output=True, text=True, check=False,
        )


class TestResolver(Home):
    def test_agents_share_one_root_and_the_host_keeps_another_by_default(self):
        self.assertEqual((self.councilroot.root(), self.councilroot.durable()), (self.shared, self.durable))
        self.assertNotEqual(self.councilroot.root(), self.councilroot.durable())

    def test_xdg_state_home_moves_both_roots_only_when_absolute(self):
        for value, state in (("/srv/state", Path("/srv/state")), ("relative", self.durable.parent), ("", self.durable.parent)):
            with self.subTest(value=value), mock.patch.dict(os.environ, {"XDG_STATE_HOME": value}):
                self.assertEqual((self.councilroot.root(), self.councilroot.durable()),
                                 (state / "agents-shared", state / "agents-council"))

    def test_agents_council_root_wins_and_an_empty_or_relative_one_means_unset(self):
        with mock.patch.dict(os.environ, {"AGENTS_COUNCIL_ROOT": "/srv/council", "XDG_STATE_HOME": "/srv/state"}):
            self.assertEqual((self.councilroot.root(), self.councilroot.durable()), (Path("/srv/council"), Path("/srv/state/agents-council")))
        for value in ("", "relative-council"):
            with self.subTest(value=value), mock.patch.dict(os.environ, {"AGENTS_COUNCIL_ROOT": value}):
                self.assertEqual(self.councilroot.root(), self.shared)

    def test_the_cli_prints_the_roots_and_creates_private_parts(self):
        self.assertEqual(self.cli("root").stdout, f"{self.shared}\n")
        self.assertEqual(self.cli("root", AGENTS_COUNCIL_ROOT=str(self.base / "c")).stdout, f"{self.base / 'c'}\n")
        self.assertEqual(self.cli("durable", AGENTS_COUNCIL_ROOT=str(self.base / "c")).stdout, f"{self.durable}\n")
        for args, made in ((("dir", "gates"), self.shared / "gates"), (("release", "1.2.3"), self.durable.parent / "agents-release" / "1.2.3")):
            with self.subTest(args=args):
                done = self.cli(*args)
                self.assertEqual((done.returncode, done.stdout), (0, f"{made}\n"), done.stderr)
                self.assertEqual(made.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.shared.stat().st_mode & 0o777, 0o700)
        self.assertFalse(self.durable.exists())
        refused = self.cli("dir", "../escape")
        self.assertEqual((refused.returncode, refused.stderr), (2, "councilroot: not a directory name: '../escape'\n"))
        self.assertFalse((self.shared.parent / "escape").exists())

    def test_a_root_the_sandbox_cannot_create_turns_the_hooks_off_with_the_reason(self):
        state = self.base / "frozen"
        state.mkdir(mode=0o500)
        self.addCleanup(state.chmod, 0o700)
        with mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(state)}):
            watch = load(WATCH, f"test_council_root_frozen_{id(self)}")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(watch.guard_root(hook=True), 0)
        self.assertIn(f"cannot create {state / 'agents-shared'}", out.getvalue())

    def test_a_part_the_cli_cannot_create_exits_2_naming_why_and_prints_nothing(self):
        state = self.base / "frozen"
        state.mkdir(mode=0o500)
        self.addCleanup(state.chmod, 0o700)
        done = self.cli("dir", "gates", "slug", XDG_STATE_HOME=str(state))
        self.assertEqual((done.returncode, done.stdout), (2, ""))
        self.assertTrue(done.stderr.startswith("councilroot: ") and "Permission denied" in done.stderr and "Traceback" not in done.stderr, done.stderr)


class TestMigrate(Home):
    def setUp(self):
        super().setUp()
        self.legacy = self.base / "legacy"
        self.legacy.mkdir(mode=0o700)
        self.target = self.base / "state" / "agents-shared"

    def write(self, path: Path, text: str, mtime: int | None = None) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        path.chmod(0o600)
        if mtime is not None:
            os.utime(path, (mtime, mtime))
        return path

    def migrate(self) -> list[str]:
        return self.councilroot.migrate(self.legacy, self.target)

    def test_every_file_moves_and_a_second_run_moves_nothing(self):
        self.write(self.legacy / "rasci.json", "{}\n", 1000)
        self.write(self.legacy / "work" / "a" / "claim.json", '{"session": "s1"}\n')
        self.write(self.legacy / "holds" / "1-2.lock", "")
        self.assertEqual(self.migrate(), [f"moved 3 files from {self.legacy} to {self.target}"])
        self.assertEqual((self.target / "rasci.json").read_text(encoding="utf-8"), "{}\n")
        self.assertEqual((self.target / "rasci.json").stat().st_mtime, 1000)
        self.assertEqual((self.target / "rasci.json").stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.target / "work" / "a" / "claim.json").read_text(encoding="utf-8"), '{"session": "s1"}\n')
        self.assertTrue((self.target / "holds" / "1-2.lock").is_file())
        self.assertFalse(self.legacy.exists())
        self.assertEqual(sorted(path.name for path in self.target.iterdir()), ["holds", "rasci.json", "work"])
        self.assertEqual(self.migrate(), [])

    def test_a_differing_whole_file_refuses_the_move_and_a_catch_up_keeps_it_beside(self):
        newer = self.write(self.target / "rasci.json", "durable\n", 2000)
        self.write(self.legacy / "rasci.json", "legacy\n", 1000)
        self.write(self.legacy / "queue.json", '{"seq": 1, "entries": []}\n')
        line = f"conflict {newer} differs from {self.legacy / 'rasci.json'}"
        with self.assertRaises(self.councilroot.Blocked) as blocked:
            self.migrate()
        self.assertEqual(blocked.exception.lines, [line])
        done = self.cli("migrate", "--legacy", str(self.legacy), AGENTS_COUNCIL_ROOT=str(self.target))
        self.assertEqual((done.returncode, done.stdout), (4, f"{line}\nnothing moved from {self.legacy}\n"), done.stderr)
        self.assertEqual(sorted(path.name for path in self.legacy.iterdir()), ["queue.json", "rasci.json"])
        self.assertFalse((self.target / "queue.json").exists())
        kept = self.target / f"rasci.json.legacy-{hashlib.sha256(b"legacy\n").hexdigest()[:12]}"
        for run in (1, 2):
            with self.subTest(run=run):
                if run == 2:
                    self.write(self.legacy / "rasci.json", "legacy\n")
                caught = self.cli("migrate", "--legacy", str(self.legacy), "--catch-up", AGENTS_COUNCIL_ROOT=str(self.target))
                self.assertEqual(caught.returncode, 3, caught.stderr)
                self.assertIn(f"kept {self.legacy / 'rasci.json'} beside {newer} as {kept}", caught.stdout)
                self.assertEqual((newer.read_text(encoding="utf-8"), kept.read_text(encoding="utf-8")), ("durable\n", "legacy\n"))
                self.assertFalse(self.legacy.exists())
        self.assertEqual(sorted(path.name for path in self.target.iterdir()), ["queue.json", "rasci.json", kept.name])

    def test_a_file_it_cannot_move_refuses_the_whole_move_and_preflight_predicts_it(self):
        self.write(self.legacy / "rasci.json", '{"work/x": {}}\n')
        self.write(self.legacy / "queue.json", '{"seq": 9, "entries": []}\n')
        source = self.write(self.legacy / "late.json", "{}\n")
        os.link(source, self.base / "second-link")
        done = self.cli("migrate", "--legacy", str(self.legacy), AGENTS_COUNCIL_ROOT=str(self.target))
        line = f"unmoved {source}: not a regular file with a single link"
        self.assertEqual((done.returncode, done.stdout), (4, f"{line}\nnothing moved from {self.legacy}\n"), done.stderr)
        self.assertEqual(sorted(path.name for path in self.legacy.iterdir()), ["late.json", "queue.json", "rasci.json"])
        self.assertFalse(self.target.exists() and any(self.target.iterdir()))
        checked = self.cli("preflight", "--legacy", str(self.legacy), "--managed", str(self.base / "no-managed"), AGENTS_COUNCIL_ROOT=str(self.target))
        self.assertEqual(checked.returncode, 2)
        self.assertIn(line, checked.stderr)

    def test_a_move_failing_after_the_check_leaves_a_partial_state_with_exit_5(self):
        self.write(self.legacy / "rasci.json", "{}\n")
        late = self.write(self.legacy / "late.json", "{}\n")
        real = self.councilroot.copied

        def racing(helper, legacy, source, *rest):
            if source.name.startswith(late.name):
                raise OSError(errno.EBUSY, "raced", str(source))
            return real(helper, legacy, source, *rest)

        out = io.StringIO()
        with mock.patch.object(self.councilroot, "copied", racing), mock.patch.dict(os.environ, {"AGENTS_COUNCIL_ROOT": str(self.target)}), contextlib.redirect_stdout(out):
            code = self.councilroot.main(["migrate", "--legacy", str(self.legacy)])
        self.assertEqual(code, 5)
        self.assertTrue(any(line.startswith(f"unmoved {late}") and line.endswith(": raced") for line in out.getvalue().splitlines()), out.getvalue())
        self.assertTrue((self.target / "rasci.json").is_file())
        self.assertEqual([path.name.startswith("late.json") for path in self.legacy.iterdir()], [True])

    def test_a_row_appended_while_its_journal_moves_reaches_the_root_through_the_catch_up(self):
        journal = self.write(self.legacy / "scores.jsonl", '{"time": 1, "digest": "a"}\n')
        late = '{"time": 2, "digest": "written between the copy and the unlink"}\n'
        real = self.councilroot.copied

        def racing(helper, legacy, source, *rest):
            done = real(helper, legacy, source, *rest)
            with open(journal, "a", encoding="utf-8") as writer:
                writer.write(late)
            return done

        with mock.patch.object(self.councilroot, "copied", racing):
            self.migrate()
        self.councilroot.migrate(self.legacy, self.target, True)
        self.assertEqual((self.target / "scores.jsonl").read_text(encoding="utf-8"), '{"time": 1, "digest": "a"}\n' + late)
        self.assertFalse(self.legacy.exists())

    def test_a_crash_mid_move_leaves_the_started_marker_until_a_run_completes_the_move(self):
        self.write(self.legacy / "a.json", "{}\n")
        self.write(self.legacy / "b.json", '{"b": 1}\n')
        real = self.councilroot.copied

        def crashing(helper, legacy, source, *rest):
            if source.name.startswith("b.json"):
                raise RuntimeError("boom")
            return real(helper, legacy, source, *rest)

        marker = self.durable / "migrate.started"
        with mock.patch.object(self.councilroot, "copied", crashing), self.assertRaises(RuntimeError):
            self.migrate()
        self.assertTrue(marker.is_file() and (self.target / "a.json").is_file())
        self.assertEqual(self.migrate(), [f"moved 1 files from {self.legacy} to {self.target}"])
        self.assertEqual((self.target / "b.json").read_text(encoding="utf-8"), '{"b": 1}\n')
        self.assertFalse(marker.exists() or self.legacy.exists())

    def test_identical_copies_are_one_and_leave_the_legacy_root(self):
        same = self.write(self.target / "rasci.json", "{}\n", 2000)
        self.write(self.legacy / "rasci.json", "{}\n", 1000)
        self.assertEqual(self.migrate(), [f"moved 1 files from {self.legacy} to {self.target}"])
        self.assertEqual((same.read_text(encoding="utf-8"), same.stat().st_mtime), ("{}\n", 2000))
        self.assertFalse(self.legacy.exists())

    def test_a_held_lock_or_a_queued_job_refuses_the_whole_move(self):
        hold = self.write(self.legacy / "holds" / "1-2.lock", "")
        self.write(self.legacy / "rasci.json", "{}\n")
        with open(hold, encoding="utf-8") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            with self.assertRaises(ValueError) as raised:
                self.migrate()
        self.assertIn(f"{hold} is held", str(raised.exception))
        self.write(self.legacy / "queue.json", json.dumps({"seq": 3, "entries": [{"id": "test-3"}]}))
        with self.assertRaises(ValueError) as raised:
            self.migrate()
        self.assertIn(f"{self.legacy / 'queue.json'} holds 1 queue jobs", str(raised.exception))
        self.assertFalse(self.target.exists())
        self.assertEqual(sorted(path.name for path in self.legacy.iterdir()), ["holds", "queue.json", "rasci.json"])
        self.write(self.legacy / "queue.json", json.dumps({"seq": 3, "entries": []}))
        self.assertEqual(self.migrate(), [f"moved 3 files from {self.legacy} to {self.target}"])

    def test_an_id_journal_gets_only_the_rows_it_lacks(self):
        kept = self.write(self.target / "queue-history.jsonl", '{"id": "a"}\n{"id": "b"}\n')
        self.write(self.legacy / "queue-history.jsonl", '{"id": "b"}\n{"id": "c"}\n{"id": "c"}\n')
        self.assertEqual(self.migrate(), [f"merged 1 rows of {self.legacy / 'queue-history.jsonl'} into {kept}"])
        self.assertEqual(rows(kept), ["a", "b", "c"])
        self.assertFalse(self.legacy.exists())
        self.assertEqual(self.migrate(), [])
        self.assertEqual(rows(kept), ["a", "b", "c"])

    def test_a_merge_appends_after_a_row_another_writer_adds_meanwhile(self):
        self.write(self.legacy / "news.jsonl", '{"id": "L1"}\n')
        kept = self.write(self.target / "news.jsonl", '{"id": "T1"}\n')
        real, calls = self.councilroot.row_ids, []

        def racing(text: str):
            calls.append(text)
            if len(calls) == 2:
                with open(kept, "a", encoding="utf-8") as other:
                    other.write('{"id": "CONCURRENT"}\n')
            return real(text)

        with mock.patch.object(self.councilroot, "row_ids", racing):
            self.assertEqual(self.migrate(), [f"merged 1 rows of {self.legacy / 'news.jsonl'} into {kept}"])
        self.assertEqual(rows(kept), ["T1", "CONCURRENT", "L1"])

    def test_a_journal_without_ids_merges_each_line_as_often_as_the_legacy_side_has_it_more_in_ts_order(self):
        kept = self.write(self.target / "news.jsonl", '{"ts": 1.0, "text": "a"}\n{"ts": 3.0, "text": "c"}\n')
        self.write(self.legacy / "news.jsonl", '{"ts": 3.0, "text": "c"}\n{"ts": 2.0, "text": "b"}\n{"ts": 2.0, "text": "b"}\n')
        untimed = self.write(self.target / "scores.jsonl", '{"time": 1}\n')
        self.write(self.legacy / "scores.jsonl", '{"time": 2}\n{"time": 1}\n{"time": 1}\n{"time": 1}\n')
        self.assertEqual(self.migrate(), [
            f"merged 2 rows of {self.legacy / 'news.jsonl'} into {kept}",
            f"merged 3 rows of {self.legacy / 'scores.jsonl'} into {untimed}",
        ])
        self.assertEqual([json.loads(line)["text"] for line in kept.read_text(encoding="utf-8").splitlines()], ["a", "b", "b", "c"])
        self.assertEqual(untimed.read_text(encoding="utf-8"), '{"time": 1}\n{"time": 2}\n{"time": 1}\n{"time": 1}\n')
        self.assertEqual(kept.stat().st_mode & 0o777, 0o600)
        self.assertFalse(self.legacy.exists())

    def test_no_link_on_either_side_is_followed(self):
        secret = self.write(self.base / "secret.txt", "secret\n")
        outside = self.base / "outside"
        self.write(outside / "inner.txt", "inner\n")
        elsewhere = self.base / "elsewhere"
        elsewhere.mkdir()
        (self.legacy / "evil").symlink_to(secret)
        (self.legacy / "linked").symlink_to(outside)
        self.write(self.legacy / "work" / "a" / "claim.json", "{}\n")
        self.target.mkdir(parents=True, mode=0o700)
        (self.target / "work").symlink_to(elsewhere)
        with self.assertRaises(self.councilroot.Blocked) as blocked:
            self.migrate()
        self.assertTrue(all(line.startswith(f"unmoved {self.legacy / 'work' / 'a' / 'claim.json'}: ") for line in blocked.exception.lines), blocked.exception.lines)
        report = self.councilroot.migrate(self.legacy, self.target, True)
        self.assertIn(f"skipped {self.legacy / 'evil'}: not a regular file", report)
        self.assertIn(f"skipped {self.legacy / 'linked'}: a link", report)
        self.assertTrue(any(re.match(rf"unmoved {re.escape(str(self.legacy / 'work' / 'a' / 'claim.json'))}\.[0-9a-f]{{16}}\.migrating: ", line) for line in report), report)
        self.assertEqual(list(elsewhere.iterdir()), [])
        self.assertFalse((self.target / "evil").exists() or (self.target / "linked").exists())
        self.assertEqual((secret.read_text(encoding="utf-8"), (outside / "inner.txt").read_text(encoding="utf-8")), ("secret\n", "inner\n"))

    def test_a_linked_or_shared_legacy_root_is_refused(self):
        linked = self.base / "linked-legacy"
        linked.symlink_to(self.legacy)
        with self.assertRaises(ValueError):
            self.councilroot.migrate(linked, self.target)
        self.legacy.chmod(0o777)
        self.addCleanup(self.legacy.chmod, 0o700)
        done = self.cli("migrate", "--legacy", str(self.legacy), AGENTS_COUNCIL_ROOT=str(self.target))
        self.assertEqual(done.returncode, 2)
        self.assertIn("group and others cannot write", done.stderr)

    def test_a_missing_legacy_root_moves_nothing(self):
        done = self.cli("migrate", "--legacy", str(self.base / "gone"), AGENTS_COUNCIL_ROOT=str(self.target))
        self.assertEqual((done.returncode, done.stdout), (0, f"nothing to move from {self.base / 'gone'}\n"))

    def test_orchestrator_stop_covers_every_unit_that_writes_a_council_root(self):
        units = (REPO_ROOT / "scripts" / "orchestrator.sh").read_text(encoding="utf-8")
        body = units[units.index("stop_all() {"):]
        body = body[:body.index("\n}\n")]
        for unit in ("${RUNNER}", "${OFFICES_UNIT}.path", "${RESOURCES_UNIT}.timer", "${RESOURCES_UNIT}.service", "compose"):
            with self.subTest(unit=unit):
                self.assertIn(unit, body)
        self.assertIn("stop) stop_all ;;", units)


NPX_STUB = """#!/usr/bin/env python3
import json, os
from pathlib import Path
with open(os.environ["STUB_RECORD"], "a") as record:
    record.write(f"npx {Path(os.environ['STUB_CHECK']).is_file()}\\n")
if os.environ.get("STUB_LINK"):
    os.link(*json.loads(os.environ["STUB_LINK"]))
skill = Path(".agents/skills/kvb-new/SKILL.md")
skill.parent.mkdir(parents=True)
skill.write_text("new\\n")
"""
CP_STUB = """#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
with open(os.environ["STUB_RECORD"], "a") as record:
    record.write(f"cp {Path(os.environ['STUB_CHECK']).is_file()} {sys.argv[-1]}\\n")
if sys.argv[-1].startswith(os.environ["HOME"]):
    for late, text in json.loads(os.environ.get("STUB_LATE", "{}")).items():
        if not Path(late).exists():
            Path(late).parent.mkdir(parents=True, exist_ok=True)
            Path(late).write_text(text)
os.execv(os.environ["REAL_CP"], ["cp", *sys.argv[1:]])
"""
TOOLS = ("bash", "python3", "dirname", "rm", "find", "mkdir", "install", "grep", "sed", "ln", "cat", "id")


class Settings(Home):
    def setUp(self):
        super().setUp()
        self.legacy = self.base / "legacy"
        self.legacy.mkdir(mode=0o700)
        self.settings = self.home / ".claude" / "settings.json"
        self.release = self.home / ".local" / "state" / "agents-release"
        self.allow(["~/.local/state/agents-shared", f"{self.release}/**", "/var/cache/unrelated", "."])

    def allow(self, entries: list[str]) -> None:
        self.settings.parent.mkdir(parents=True, exist_ok=True)
        self.settings.write_text(json.dumps({"sandbox": {"enabled": True, "filesystem": {"allowWrite": entries}}}), encoding="utf-8")

    def preflight(self) -> subprocess.CompletedProcess:
        return self.cli("preflight", "--legacy", str(self.legacy), "--managed", str(self.base / "managed"))

    def settings_file(self, path: Path, entries: list[str]) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"sandbox": {"filesystem": {"allowWrite": entries}}}), encoding="utf-8")
        return path


class TestPreflight(Settings):
    def test_both_agent_paths_must_be_writable_for_the_sandbox_and_the_host_root_never(self):
        self.assertEqual(self.preflight().returncode, 0, self.preflight().stderr)
        for entries, wanted in (
            (["~/.local/state/agents-shared"], f"add {self.release} to sandbox.filesystem.allowWrite in {self.settings}"),
            ([f"{self.release}"], f"add {self.shared} to sandbox.filesystem.allowWrite in {self.settings}"),
            (["~/.local/state/agents-shared", str(self.release), "~/.local/state/agents-council/**"], f"{self.settings}: drop allowWrite entry '~/.local/state/agents-council/**' ({self.durable})"),
            (["~/.local/state/agents-shared", str(self.release), "~/.local/state"], f"{self.settings}: drop allowWrite entry '~/.local/state' ({self.durable.parent})"),
        ):
            with self.subTest(entries=entries):
                self.allow(entries)
                done = self.preflight()
                self.assertEqual(done.returncode, 2)
                self.assertIn(wanted, done.stderr)
        self.settings.unlink()
        self.assertIn(f"{self.settings} holds no sandbox.filesystem.allowWrite list", self.preflight().stderr)

    def test_every_settings_file_that_can_apply_is_checked_and_named_with_its_entry(self):
        repo = self.home / "Repositories" / "github.com" / "o" / "r"
        worktree = self.home / ".local" / "share" / "worktrees" / "github.com" / "o" / "r" / "fix" / "x"
        widening = (
            (self.base / "managed" / "managed-settings.json", "~"),
            (self.base / "managed" / "managed-settings.d" / "50-widen.json", "~/.local"),
            (self.home / ".claude" / "settings.local.json", "~/.local/state/agents-council"),
            (repo / ".claude" / "settings.json", "~/.local/state"),
            (repo / ".claude" / "settings.local.json", "../../../../.local"),
            (worktree / ".claude" / "settings.json", "~/.local/state/agents-council/resources/**"),
        )
        self.settings_file(repo / "nested" / ".claude" / "settings.json", ["/var/cache/fine"])
        self.assertEqual(self.preflight().returncode, 0, self.preflight().stderr)
        for path, entry in widening:
            with self.subTest(path=path):
                self.settings_file(path, [entry, "/var/cache/fine"])
                done = self.preflight()
                self.assertEqual(done.returncode, 2)
                self.assertIn(f"{path}: drop allowWrite entry {entry!r}", done.stderr)
                self.assertNotIn("add ", done.stderr)
                path.unlink()
        moved = self.home / "Code" / "o" / "r" / ".claude" / "settings.json"
        self.settings_file(moved, ["~/.local/state"])
        self.assertEqual(self.preflight().returncode, 0)
        config = self.home / ".config" / "pkgmgr" / "config.yaml"
        config.parent.mkdir(parents=True)
        config.write_text("directories:\n  repositories: ~/Code/\n  binaries: ~/.local/bin/\n", encoding="utf-8")
        self.assertIn(f"{moved}: drop allowWrite entry '~/.local/state'", self.preflight().stderr)

    def test_the_queue_and_the_preflight_share_one_list_of_settings_files(self):
        self.assertNotIn("managed-settings", QUEUE.read_text(encoding="utf-8"))
        managed = self.base / "managed"
        dropin = managed / "managed-settings.d" / "50-deny.json"
        dropin.parent.mkdir(parents=True)
        dropin.write_text(json.dumps({"permissions": {"deny": ["Bash(rm *)"]}}), encoding="utf-8")
        queue = load(QUEUE, f"test_council_root_queue_settings_{id(self)}")
        project = self.base / "project"
        with mock.patch.object(queue.sibling("councilroot"), "MANAGED", managed):
            self.assertIn(dropin, queue.settings_files(project))
            self.assertEqual(queue.permission(["rm -rf x"], project), "deny")

    def test_linked_repositories_linked_files_and_every_session_start_directory_are_checked(self):
        repositories = self.home / "Repositories"
        data = self.base / "data" / "r"
        linked = repositories / "github.com" / "o" / "r"
        linked.parent.mkdir(parents=True)
        linked.symlink_to(data)
        (repositories / "loop").symlink_to(repositories)
        project = self.home / "work" / "proj"
        session = self.home / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(project))
        session.mkdir(parents=True)
        (self.home / ".claude" / "projects" / "-gone-project").mkdir()
        target = self.settings_file(self.base / "shared-settings.json", ["~/.local/state"])
        cases = (
            (linked / ".claude" / "settings.json", lambda path: self.settings_file(data / ".claude" / "settings.json", ["~/.local/state"])),
            (project / ".claude" / "settings.local.json", lambda path: self.settings_file(path, ["~/.local/state"])),
            (repositories / "github.com" / "o" / "s" / ".claude" / "settings.json", lambda path: (path.parent.mkdir(parents=True), path.symlink_to(target))),
        )
        self.settings_file(project / "deeper" / ".claude" / "settings.json", ["~/.local/state"])
        self.assertEqual(self.preflight().returncode, 0, self.preflight().stderr)
        for path, make in cases:
            with self.subTest(path=path):
                make(path)
                done = self.preflight()
                self.assertEqual(done.returncode, 2)
                self.assertEqual(done.stderr.count(f"{path}: drop allowWrite entry '~/.local/state'"), 1, done.stderr)
                path.unlink()

    def test_a_council_that_is_not_suspended_is_only_warned_about(self):
        done = self.preflight()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("warning: the agents are not suspended", done.stderr)
        (self.legacy / "night.json").write_text(json.dumps({"mode": "suspend"}), encoding="utf-8")
        done = self.preflight()
        self.assertEqual((done.returncode, done.stderr), (0, ""))

    def test_a_busy_or_conflicting_legacy_root_is_refused_before_anything_moves(self):
        hold = self.legacy / "holds" / "1-2.lock"
        hold.parent.mkdir()
        hold.write_text("", encoding="utf-8")
        with open(hold, encoding="utf-8") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            self.assertIn(f"{hold} is held", self.preflight().stderr)
        (self.legacy / "queue.json").write_text(json.dumps({"seq": 3, "entries": [{"id": "test-3"}]}), encoding="utf-8")
        self.assertIn("holds 1 queue jobs", self.preflight().stderr)
        (self.legacy / "queue.json").write_text(json.dumps({"seq": 3, "entries": []}), encoding="utf-8")
        for name, legacy, shared, ok in (("rasci.json", "a", "b", False), ("night.json", "same", "same", True), ("news.jsonl", '{"id": 1}\n', '{"id": 2}\n', True)):
            (self.legacy / name).write_text(legacy, encoding="utf-8")
            self.shared.mkdir(parents=True, mode=0o700, exist_ok=True)
            (self.shared / name).write_text(shared, encoding="utf-8")
            with self.subTest(name=name):
                self.assertEqual(f"conflict {self.shared / name} differs" in self.preflight().stderr, not ok)
        (self.legacy / "rasci.json").unlink()
        self.assertEqual(self.preflight().returncode, 0, self.preflight().stderr)
        self.assertEqual(sorted(path.name for path in self.legacy.iterdir()), ["holds", "news.jsonl", "night.json", "queue.json"])


class TestInstall(Settings):
    def setUp(self):
        super().setUp()
        self.repo = self.base / "repo"
        for part in ("scripts/install.sh", "scripts/orchestrator.sh", "skills/kvb-org-organize/scripts/councilroot.py", "skills/kvb-org-organize/scripts/nofollow.py"):
            (self.repo / part).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / part).write_bytes((REPO_ROOT / part).read_bytes())
        stubs = self.base / "bin"
        stubs.mkdir()
        (stubs / "npx").write_text(NPX_STUB, encoding="utf-8")
        (stubs / "cp").write_text(CP_STUB, encoding="utf-8")
        (stubs / "systemctl").write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        for stub in stubs.iterdir():
            stub.chmod(0o755)
        tools = self.base / "tools"
        tools.mkdir()
        for name in TOOLS:
            (tools / name).symlink_to(shutil.which(name))
        self.record = self.base / "stubs.log"
        self.installed = [self.home / root / "skills" / "kvb-old" / "SKILL.md" for root in (".agents", ".claude")]
        for marker in self.installed:
            marker.parent.mkdir(parents=True)
            marker.write_text("old\n", encoding="utf-8")
        self.env = {
            "PATH": f"{stubs}:{tools}", "HOME": str(self.home), "AGENTS_COUNCIL_LEGACY": str(self.legacy),
            "STUB_RECORD": str(self.record), "STUB_CHECK": str(self.shared / "rasci.json"), "REAL_CP": shutil.which("cp"),
        }

    def install(self) -> subprocess.CompletedProcess:
        return subprocess.run(["bash", str(self.repo / "scripts" / "install.sh")], env=self.env, capture_output=True, text=True, timeout=120, check=False)

    def test_a_refused_preflight_aborts_before_any_copy_and_the_old_skills_keep_the_legacy_state(self):
        (self.legacy / "queue.json").write_text(json.dumps({"seq": 3, "entries": [{"id": "test-3"}]}), encoding="utf-8")
        busy = self.install()
        self.allow(["~/.local/state/agents-shared"])
        (self.legacy / "queue.json").write_text(json.dumps({"seq": 3, "entries": []}), encoding="utf-8")
        unset = self.install()
        for done, reason in ((busy, "holds 1 queue jobs"), (unset, f"add {self.release} to sandbox.filesystem.allowWrite")):
            with self.subTest(reason=reason):
                self.assertEqual(done.returncode, 1, done.stderr)
                self.assertIn(reason, done.stderr)
                self.assertIn("skills: install refused before copying anything", done.stderr)
        self.assertFalse(self.record.exists() or self.shared.exists() or (self.repo / ".agents").exists())
        self.assertEqual([marker.read_text(encoding="utf-8") for marker in self.installed], ["old\n", "old\n"])
        self.assertTrue((self.legacy / "queue.json").is_file())

    def test_a_migrate_that_fails_in_any_other_way_aborts_before_the_copy(self):
        script = self.repo / "skills" / "kvb-org-organize" / "scripts" / "councilroot.py"
        script.write_text(script.read_text(encoding="utf-8").replace("report = migrate(args.legacy, root(), args.catch_up)", 'raise RuntimeError("boom")'), encoding="utf-8")
        (self.legacy / "rasci.json").write_text("{}\n", encoding="utf-8")
        done = self.install()
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("RuntimeError: boom", done.stderr)
        self.assertIn("skills: install refused before copying anything: the council root migration failed", done.stderr)
        self.assertEqual([marker.read_text(encoding="utf-8") for marker in self.installed], ["old\n", "old\n"])
        self.assertTrue((self.legacy / "rasci.json").is_file())

    def test_a_file_that_turns_unmovable_after_the_preflight_aborts_with_the_old_root_intact(self):
        (self.legacy / "rasci.json").write_text('{"work/x": {}}\n', encoding="utf-8")
        (self.legacy / "queue.json").write_text('{"seq": 9, "entries": []}\n', encoding="utf-8")
        self.env["STUB_LINK"] = json.dumps([str(self.legacy / "rasci.json"), str(self.base / "alias")])
        done = self.install()
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn(f"unmoved {self.legacy / 'rasci.json'}: not a regular file with a single link", done.stdout)
        self.assertIn("skills: install refused before copying anything: the council root migration failed (exit 4)", done.stderr)
        self.assertEqual(sorted(path.name for path in self.legacy.iterdir()), ["queue.json", "rasci.json"])
        self.assertFalse((self.shared / "rasci.json").exists() or (self.shared / "queue.json").exists())
        self.assertEqual([marker.read_text(encoding="utf-8") for marker in self.installed], ["old\n", "old\n"])

    def test_a_partial_move_still_installs_the_new_skills_names_every_file_left_and_fails_at_the_end(self):
        script = self.repo / "skills" / "kvb-org-organize" / "scripts" / "councilroot.py"
        script.write_text(script.read_text(encoding="utf-8").replace(
            "outcome, line = settle(helper, legacy, source, target, catch_up)",
            'outcome, line = ("unmoved", f"unmoved {source}: raced") if source.name == "late.json" else settle(helper, legacy, source, target, catch_up)',
        ), encoding="utf-8")
        (self.legacy / "rasci.json").write_text("{}\n", encoding="utf-8")
        (self.legacy / "late.json").write_text("{}\n", encoding="utf-8")
        done = self.install()
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertGreaterEqual(done.stderr.count(f"unmoved {self.legacy / 'late.json'}: raced"), 2, done.stderr)
        self.assertTrue((self.shared / "rasci.json").is_file() and (self.legacy / "late.json").is_file())
        self.assertEqual([(marker.parent.parent / "kvb-new" / "SKILL.md").read_text(encoding="utf-8") for marker in self.installed], ["new\n"] * 2)

    def test_a_crash_after_a_partial_move_still_installs_the_new_skills_and_names_the_marker(self):
        script = self.repo / "skills" / "kvb-org-organize" / "scripts" / "councilroot.py"
        settle = "outcome, line = settle(helper, legacy, source, target, catch_up)"
        script.write_text(script.read_text(encoding="utf-8").replace(settle, f'if source.name == "zz.json":\n                raise RuntimeError("boom")\n            {settle}'), encoding="utf-8")
        (self.legacy / "rasci.json").write_text("{}\n", encoding="utf-8")
        (self.legacy / "zz.json").write_text("{}\n", encoding="utf-8")
        done = self.install()
        marker = self.durable / "migrate.started"
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("RuntimeError: boom", done.stderr)
        self.assertIn(f"skills: the council root migration stopped halfway (exit 1): {marker} exists", done.stderr)
        self.assertTrue((self.shared / "rasci.json").is_file() and marker.is_file() and (self.legacy / "zz.json").is_file())
        self.assertEqual([(old.parent.parent / "kvb-new" / "SKILL.md").read_text(encoding="utf-8") for old in self.installed], ["new\n"] * 2)

    def test_rows_and_register_changes_written_meanwhile_arrive_or_are_reported_never_lost(self):
        (self.legacy / "queue-history.jsonl").write_text('{"id": "early"}\n', encoding="utf-8")
        (self.legacy / "news.jsonl").write_text(json.dumps({"from": "A", "text": "before", "ts": 1.0}) + "\n", encoding="utf-8")
        (self.legacy / "rasci.json").write_text("{}\n", encoding="utf-8")
        window = '{"work/x": {"status": "window"}}\n'
        self.env["STUB_LATE"] = json.dumps({
            str(self.legacy / "queue-history.jsonl"): '{"id": "late"}\n',
            str(self.legacy / "news.jsonl"): json.dumps({"from": "B", "text": "posted in the window", "ts": 2.0}) + "\n",
            str(self.legacy / "rasci.json"): window,
        })
        done = self.install()
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertEqual(rows(self.shared / "queue-history.jsonl"), ["early", "late"])
        self.assertEqual([json.loads(line)["text"] for line in (self.shared / "news.jsonl").read_text(encoding="utf-8").splitlines()], ["before", "posted in the window"])
        kept = [path for path in self.shared.iterdir() if path.name.startswith("rasci.json.legacy-")]
        self.assertEqual([path.read_text(encoding="utf-8") for path in kept], [window])
        self.assertEqual((self.shared / "rasci.json").read_text(encoding="utf-8"), "{}\n")
        self.assertIn(f"kept {self.legacy / 'rasci.json'} beside {self.shared / 'rasci.json'} as {kept[0]}", done.stderr)
        self.assertFalse(self.legacy.exists())

    def test_the_skills_are_built_first_and_reach_the_target_only_after_the_legacy_state_moved(self):
        (self.legacy / "rasci.json").write_text("{}\n", encoding="utf-8")
        done = self.install()
        self.assertEqual(done.returncode, 0, done.stderr)
        calls = self.record.read_text(encoding="utf-8").splitlines()
        self.assertEqual(calls[0], "npx False", done.stderr)
        into_target = [call for call in calls if call.startswith("cp ") and call.split(" ", 2)[2].startswith(str(self.home))]
        self.assertEqual(into_target, [f"cp True {self.home / root / 'skills'}/" for root in (".agents", ".claude")], done.stderr)
        self.assertFalse(self.legacy.exists())
        self.assertEqual([(marker.exists(), (marker.parent.parent / "kvb-new" / "SKILL.md").read_text(encoding="utf-8")) for marker in self.installed], [(False, "new\n")] * 2)


class TestKeptCopy(Home):
    def setUp(self):
        super().setUp()
        self.watch = load(WATCH, f"test_council_root_watch_{id(self)}")

    def write_rows(self, path: Path) -> None:
        path.write_text('{"id": "r1", "rule": "R", "path": "p", "sha1": "s"}\n{"id": "r2", "rule": "R", "path": "q", "sha1": "s"}\n', encoding="utf-8")

    def test_agents_write_their_root_and_the_host_keeps_the_copies_apart(self):
        watch = self.watch
        self.assertEqual((watch.ROOT, watch.KEPT), (self.shared, self.durable))
        for origin, kept in watch.MIRRORED:
            with self.subTest(name=origin.name):
                self.assertEqual((origin.parent, kept.parent, origin.name), (self.shared, self.durable, kept.name))
        queue = load(QUEUE, f"test_council_root_queue_{id(self)}")
        self.assertEqual(queue.HISTORIES, (self.shared / "queue-history.jsonl", self.durable / "queue-history.jsonl"))

    def test_the_hook_mirrors_acceptances_and_receipts_into_the_host_root_and_readers_merge_both(self):
        watch = self.watch
        self.shared.mkdir(parents=True, mode=0o700)
        for origin, _ in watch.MIRRORED:
            self.write_rows(origin)
        watch.keep_history()
        for _, kept in watch.MIRRORED:
            with self.subTest(name=kept.name):
                self.assertEqual((rows(kept), kept.stat().st_mode & 0o777), (["r1", "r2"], 0o600))
        self.assertEqual(self.durable.stat().st_mode & 0o777, 0o700)
        with watch.KEPT_ACCEPTED.open("a", encoding="utf-8") as kept:
            kept.write('{"id": "r0", "rule": "R", "path": "o", "sha1": "s"}\n')
        security = load(SECURITY, f"test_council_root_security_{id(self)}")
        self.assertEqual(security.accepted((watch.ACCEPTED, watch.KEPT_ACCEPTED)), {("R", name, "s", None) for name in "opq"})

    def test_the_mirror_never_follows_a_link_in_the_host_root(self):
        watch = self.watch
        self.shared.mkdir(parents=True, mode=0o700)
        self.durable.mkdir(parents=True, mode=0o700)
        self.write_rows(watch.ACCEPTED)
        outside = self.base / "outside.jsonl"
        outside.write_text("", encoding="utf-8")
        watch.KEPT_ACCEPTED.symlink_to(outside)
        watch.keep_rows(watch.ACCEPTED, watch.KEPT_ACCEPTED)
        self.assertEqual(outside.read_text(encoding="utf-8"), "")
        watch.KEPT_ACCEPTED.unlink()
        os.link(outside, watch.KEPT_ACCEPTED)
        watch.keep_rows(watch.ACCEPTED, watch.KEPT_ACCEPTED)
        self.assertEqual(outside.read_text(encoding="utf-8"), "")
        watch.KEPT_ACCEPTED.unlink()
        elsewhere = self.base / "elsewhere"
        elsewhere.mkdir()
        self.durable.rmdir()
        self.durable.symlink_to(elsewhere)
        watch.keep_rows(watch.ACCEPTED, watch.KEPT_ACCEPTED)
        self.assertEqual(list(elsewhere.iterdir()), [])

    def test_the_watch_hook_never_copies_a_journal_onto_itself(self):
        with mock.patch.dict(os.environ, {"AGENTS_COUNCIL_ROOT": str(self.durable)}):
            watch = load(WATCH, f"test_council_root_same_{id(self)}")
        self.durable.mkdir(parents=True, mode=0o700)
        for origin, _ in watch.MIRRORED:
            self.write_rows(origin)
        before = {origin: origin.read_bytes() for origin, _ in watch.MIRRORED}
        watch.keep_history()
        self.assertEqual({origin: origin.read_bytes() for origin, _ in watch.MIRRORED}, before)

    def test_an_explicit_root_still_keeps_its_rows_in_the_durable_one(self):
        with mock.patch.dict(os.environ, {"AGENTS_COUNCIL_ROOT": str(self.base / "council")}):
            watch = load(WATCH, f"test_council_root_explicit_{id(self)}")
        self.assertEqual((watch.ROOT, watch.KEPT), (self.base / "council", self.durable))
        watch.ROOT.mkdir(mode=0o700)
        self.write_rows(watch.HISTORY)
        watch.keep_history()
        self.assertEqual(rows(watch.KEPT_HISTORY), ["r1", "r2"])


class TestHostWriters(Home):
    def outside(self) -> Path:
        path = self.base / "outside"
        path.write_text("", encoding="utf-8")
        return path

    def test_the_subagent_log_lies_in_the_host_root_and_never_follows_a_link(self):
        payload = json.dumps({"session_id": "s1", "tool_input": {"description": "d", "prompt": "task-class: judgement"}})
        state = self.base / "xdg"
        env = {"PATH": os.environ["PATH"], "HOME": str(self.home), "XDG_STATE_HOME": str(state)}
        spawn = subprocess.run([sys.executable, str(LOG), "spawn"], input=payload, env=env, capture_output=True, text=True, check=False)
        self.assertEqual(spawn.returncode, 0, spawn.stderr)
        log = state / "agents-council" / "subagent-model.jsonl"
        self.assertEqual(json.loads(log.read_text(encoding="utf-8"))["task_class"], "judgement")
        outside = self.outside()
        log.unlink()
        log.symlink_to(outside)
        subprocess.run([sys.executable, str(LOG), "spawn"], input=payload, env=env, capture_output=True, text=True, check=False)
        self.assertEqual(outside.read_text(encoding="utf-8"), "")

    def resources(self) -> ModuleType:
        with mock.patch.object(sys, "path", [str(CLIENT), *sys.path]):
            return load(CLIENT / "resources.py", f"test_council_root_resources_{id(self)}")

    def test_the_resources_sampler_never_follows_a_link(self):
        resources = self.resources()
        state = self.durable / "resources"
        state.mkdir(parents=True, mode=0o700)
        outside = self.outside()
        (state / "samples.jsonl").symlink_to(outside)
        with self.assertRaises(OSError):
            resources.append_rows(state / "samples.jsonl", [{"t": 1}])
        self.assertEqual(outside.read_text(encoding="utf-8"), "")
        elsewhere = self.base / "elsewhere"
        elsewhere.mkdir()
        (state / "samples.jsonl").unlink()
        state.rmdir()
        state.symlink_to(elsewhere)
        for write in (lambda: resources.append_rows(state / "tokens.jsonl", [{"t": 1}]), lambda: resources.replace(state / "offsets.json", "{}")):
            with self.assertRaises(OSError):
                write()
        self.assertEqual(list(elsewhere.iterdir()), [])

    def gates(self) -> ModuleType:
        return load(GATES, f"test_council_root_gates_{id(self)}")

    def test_gates_db_is_never_written_through_a_link(self):
        gates = self.gates()
        self.durable.mkdir(parents=True, mode=0o700)
        outside = self.outside()
        (self.durable / "gates.db").symlink_to(outside)
        with self.assertRaises(OSError):
            gates.opened(self.durable / "gates.db", True, self.durable)
        self.assertEqual(outside.read_bytes(), b"")

    def test_an_unusable_council_root_is_named_in_the_gate_hint_instead_of_a_traceback(self):
        target = self.base / "target"
        target.mkdir()
        linked = self.base / "linked"
        linked.symlink_to(target)
        with mock.patch.dict(os.environ, {"AGENTS_COUNCIL_ROOT": str(linked)}):
            gates = self.gates()
        hint = gates.producer(str(self.base), "main", "test", "0" * 40)
        self.assertIn(f"{linked} must be a directory of uid {os.getuid()}", hint)
        self.assertEqual(list(target.iterdir()), [])


class TestRetention(Home):
    def setUp(self):
        super().setUp()
        self.shared.mkdir(parents=True, mode=0o700)
        self.radio = load(RADIO, f"test_council_root_radio_{id(self)}")

    def test_an_oversized_radio_log_still_yields_its_newest_rows(self):
        row = json.dumps({"from": "A", "to": ["B"], "class": "mayday", "text": "mayday", "ts": 2.0}) + "\n"
        filler = json.dumps({"from": "A", "text": "x" * 200, "ts": 1.0}) + "\n"
        self.radio.NEWS.write_text(filler * 20 + row, encoding="utf-8")
        with mock.patch.object(self.radio.organize("nofollow"), "READ_LIMIT", 1024):
            found = self.radio.items()
        self.assertEqual(found[-1]["text"], "mayday")
        self.assertLess(len(found), 6)

    def test_rows_the_radio_drops_go_to_a_dated_archive_the_readers_skip(self):
        with mock.patch.object(self.radio, "KEPT", 3):
            for number in range(5):
                self.radio.store([{"from": "A", "text": f"m{number}"}])
        self.assertEqual([row["text"] for row in self.radio.items()], ["m2", "m3", "m4"])
        archive = self.shared / "archive" / f"news-{time.strftime('%Y-%m-%d')}.jsonl"
        self.assertEqual([json.loads(line)["text"] for line in archive.read_text(encoding="utf-8").splitlines()], ["m0", "m1"])
        self.assertEqual(archive.stat().st_mode & 0o777, 0o600)

    def test_old_gate_logs_and_pages_move_to_a_dated_archive_and_links_stay(self):
        old = time.time() - 31 * 86400
        stale = {self.shared / "gates" / "slug" / "gate-a.log", self.shared / "pages" / "branch" / "index.html"}
        fresh = self.shared / "gates" / "slug" / "gate-b.log"
        for path in (*stale, fresh):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x\n", encoding="utf-8")
        for path in stale:
            os.utime(path, (old, old))
        outside = self.base / "outside.log"
        outside.write_text("keep\n", encoding="utf-8")
        os.utime(outside, (old, old))
        (self.shared / "gates" / "linked.log").symlink_to(outside)
        done = self.cli("retire")
        archive = self.shared / "archive" / time.strftime("%Y-%m-%d")
        self.assertEqual((done.returncode, done.stdout), (0, f"archived 2 files into {archive}\n"), done.stderr)
        self.assertEqual(sorted(str(path.relative_to(archive)) for path in archive.rglob("*") if path.is_file()), ["gates/slug/gate-a.log", "pages/branch/index.html"])
        self.assertTrue(fresh.is_file() and (self.shared / "gates" / "linked.log").is_symlink())
        self.assertEqual(outside.read_text(encoding="utf-8"), "keep\n")
        self.assertIn("ExecStartPre=-/usr/bin/python3 -I %h/.claude/skills/kvb-org-organize/scripts/councilroot.py retire\n", CLEANUP_SERVICE.read_text(encoding="utf-8"))


class TestGuard(unittest.TestCase):
    def test_no_script_or_skill_text_keeps_persistent_data_in_tmp(self):
        hits = []
        for top in SCANNED:
            for path in sorted((REPO_ROOT / top).rglob("*")):
                if not path.is_file() or "__pycache__" in path.parts:
                    continue
                for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                    if FORBIDDEN.search(line) and not (path == COUNCIL_ROOT and line == LEGACY_LINE):
                        hits.append(f"{path.relative_to(REPO_ROOT)}:{number}")
        self.assertEqual(hits, [])

    def test_the_legacy_root_is_named_once_as_the_migration_source(self):
        found = [line for line in COUNCIL_ROOT.read_text(encoding="utf-8").splitlines() if "/tmp/agents-council" in line]
        self.assertEqual(found, [LEGACY_LINE])

    def test_no_skill_text_turns_a_failed_dir_call_into_a_root_path(self):
        hits = [str(path.relative_to(REPO_ROOT)) for path in sorted((REPO_ROOT / "skills").rglob("*.md")) if DIR_SLASH.search(path.read_text(encoding="utf-8"))]
        self.assertEqual(hits, [])

    def test_the_agent_root_is_named_where_it_is_inventoried_or_mounted(self):
        self.assertIn("~/.local/state/agents-shared", (REPO_ROOT / "skills" / "kvb-cleanup" / "SKILL.md").read_text(encoding="utf-8"))
        self.assertIn("~/.local/state/agents-shared.", (CLIENT / "offices.py").read_text(encoding="utf-8"))
        mounts = (REPO_ROOT / "docs" / "requirements" / "003-operator-workbench.md").read_text(encoding="utf-8").split("- **Mounts**:", 1)[1].split("\n\n", 1)[0]
        self.assertIn("`~/.local/state/agents-shared`", mounts)
        self.assertNotIn("the same directory is also", mounts)

    def test_gate_logs_never_go_to_the_temp_directory(self):
        found = [str(path.relative_to(REPO_ROOT)) for path in sorted(GATE_SKILL.rglob("*.py")) if "gettempdir" in path.read_text(encoding="utf-8")]
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
