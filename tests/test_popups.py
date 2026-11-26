from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "skills" / "kvb-org-organize" / "scripts"
POPUPS = SCRIPTS / "popups.py"
WATCH = SCRIPTS / "watch.py"
DREAM = REPO_ROOT / "skills" / "kvb-dream" / "hooks" / "notify.sh"
HOUR = 3600
RECORD = "import sys; open(sys.argv[1], 'a').write(sys.argv[2] + '\\n')"
SHOWN = {"on": True, "expired": True, "missing": True, "broken": True, "list": True, "wrong on": True, "bool until": True, "linked": True, "off": False, "snoozed": False}


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PopupCase(unittest.TestCase):
    source = "resources"

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.root = self.base / "council"
        self.root.mkdir(mode=0o700)
        self.file = self.root / "notify.json"

    def put(self, case: str, now: float) -> None:
        self.file.unlink(missing_ok=True)
        entries = {
            "on": {"on": True, "until": 0},
            "off": {"on": False, "until": 0},
            "snoozed": {"on": True, "until": int(now) + HOUR},
            "expired": {"on": True, "until": int(now) - 1},
            "wrong on": {"on": "no", "until": 0},
            "bool until": {"on": False, "until": True},
        }
        if case in entries:
            self.file.write_text(json.dumps({self.source: entries[case]}), encoding="utf-8")
        elif case == "broken":
            self.file.write_text("{not json", encoding="utf-8")
        elif case == "list":
            self.file.write_text("[]", encoding="utf-8")
        elif case == "linked":
            target = self.base / "elsewhere.json"
            target.write_text(json.dumps({self.source: {"on": False, "until": 0}}), encoding="utf-8")
            self.file.symlink_to(target)


class TestAllowed(PopupCase):
    def test_only_a_source_switched_off_or_snoozed_past_now_is_muted_and_every_unreadable_state_allows_it(self):
        popups = load("popups_allowed", POPUPS)
        now = time.time()
        for case, shown in SHOWN.items():
            with self.subTest(case=case):
                self.put(case, now)
                self.assertIs(popups.allowed(self.root, self.source, now), shown)

    def test_a_snooze_ends_at_its_until_second(self):
        popups = load("popups_until", POPUPS)
        self.file.write_text(json.dumps({"resources": {"on": True, "until": 1000}}), encoding="utf-8")
        self.assertEqual([popups.allowed(self.root, "resources", now) for now in (999.5, 1000, 1000.5)], [False, True, True])
        self.assertTrue(popups.allowed(self.root, "mayday", 999))


class TestCli(PopupCase):
    def run_cli(self, *args: str) -> int:
        env = {"PATH": "/usr/bin:/bin", "HOME": str(self.base), "AGENTS_COUNCIL_ROOT": str(self.root)}
        return subprocess.run([sys.executable, "-I", str(POPUPS), *args], capture_output=True, text=True, timeout=30, check=False, env=env).returncode

    def test_the_exit_status_is_0_when_allowed_3_when_muted_and_2_on_a_wrong_call(self):
        now = time.time()
        for case, shown in SHOWN.items():
            with self.subTest(case=case):
                self.put(case, now)
                self.assertEqual(self.run_cli("allowed", self.source), 0 if shown else 3)
        for wrong in ((), ("allowed",), ("allowed", "email"), ("muted", "resources"), ("allowed", "resources", "extra")):
            with self.subTest(wrong=wrong):
                self.assertEqual(self.run_cli(*wrong), 2)


class TestWatchPopup(PopupCase):
    def test_watch_runs_its_notify_command_only_for_resources_on_and_not_snoozed(self):
        watch = load("watch_popups", WATCH)
        watch.ROOT = self.root
        log = self.base / "notified.log"
        cfg = {"notify": [sys.executable, "-c", RECORD, str(log)]}
        now = time.time()
        for case, shown in SHOWN.items():
            with self.subTest(case=case):
                log.unlink(missing_ok=True)
                self.put(case, now)
                watch.notify(cfg, f"RESOURCE {case}")
                self.assertEqual(log.read_text(encoding="utf-8") if log.exists() else "", f"RESOURCE {case}\n" if shown else "")


class TestDreamPopup(PopupCase):
    source = "dream"

    def test_the_dream_reminder_reaches_notify_send_only_while_dream_is_on_and_not_snoozed(self):
        bin_dir = self.base / "bin"
        bin_dir.mkdir()
        calls = self.base / "calls"
        fake = bin_dir / "notify-send"
        fake.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" >> "{calls}"\n', encoding="utf-8")
        fake.chmod(0o755)
        env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "XDG_CURRENT_DESKTOP": "ubuntu:GNOME", "AGENTS_COUNCIL_ROOT": str(self.root)}
        (self.root / "schedules.json").write_text(json.dumps({"dream-popup": {"on": True, "at": ["17:00"]}}), encoding="utf-8")
        now = time.time()
        for case, shown in SHOWN.items():
            with self.subTest(case=case):
                calls.unlink(missing_ok=True)
                self.put(case, now)
                done = subprocess.run(["bash", str(DREAM)], capture_output=True, text=True, timeout=30, check=False, env=env)
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertEqual(calls.exists() and "/kvb-dream" in calls.read_text(encoding="utf-8"), shown)


if __name__ == "__main__":
    unittest.main()
