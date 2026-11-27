"""Pin requirements 057 and 068: schedules.json as the store of the Skills and Hub rows, the host reconciler over all four sources, signed foreign changes and the hub's tab."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from hub_case import HubCase
from hub_support import RUNNER, runner, signing
from kvb_orchestrator import schedules as hub_schedules
from kvb_orchestrator.errors import ToolError

REPO_ROOT = Path(__file__).resolve().parents[1]
ORGANIZE = REPO_ROOT / "skills" / "kvb-org-organize"
HELPER = ORGANIZE / "scripts" / "schedules.py"
SYSTEMD = ORGANIZE / "systemd"
TEMPLATES = REPO_ROOT / "orchestrator" / "templates"
MICRO = 1_000_000
TIMERS = [
    {"next": 1_800_000_000 * MICRO, "left": 1, "last": 1_799_990_000 * MICRO, "passed": 1, "unit": "kvb-dream-notify.timer", "activates": "kvb-dream-notify.service"},
    {"next": 1_800_000_500 * MICRO, "left": 1, "last": None, "passed": None, "unit": "kvb-orchestrator-tree.timer", "activates": "kvb-orchestrator-tree.service"},
    {"next": 0, "left": 0, "last": 0, "passed": 0, "unit": "backup.timer", "activates": "backup.service"},
]
TASKS = {"tasks": [
    {"id": "f08cfd39", "cron": "7 * * * *", "prompt": "Triage the last two CI runs", "createdAt": 1_790_000_000_000, "recurring": True, "lastFiredAt": 1_799_000_000_000},
    {"id": "a1b2c3d4", "cron": "0 9 * * 1-5", "prompt": "Morning digest", "createdAt": 1_790_000_100_000, "recurring": True},
]}
HUB_UNIT = "kvb-orchestrator-tree.timer"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


helper = load("kvb_schedules_helper", HELPER)


class Runner:
    def __init__(self, states: dict[str, str], refused: tuple[str, ...] = ()) -> None:
        self.states = states
        self.refused = refused
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str]) -> tuple[int, str]:
        self.calls.append(argv)
        if argv[:2] == list(helper.ANALYZE[:2]):
            return (1 if argv[-1] in self.refused else 0), ""
        if argv[2] == "is-enabled":
            states = [self.states.get(unit, "not-found") for unit in argv[3:]]
            return (0 if "enabled" in states else 1), "".join(f"{state}\n" for state in states)
        return 0, ""


def task_file(repos: Path, data: object, text: str | None = None) -> Path:
    path = repos / "github.com" / "me" / "repo" / ".claude" / "scheduled_tasks.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(data, indent=2) if text is None else text, encoding="utf-8")
    return path


class TestRows(unittest.TestCase):
    def test_host_and_hub_share_the_rows_the_limits_the_patterns_and_the_file_names(self):
        self.assertEqual(helper.ROWS, hub_schedules.ROWS)
        self.assertEqual((helper.HOURS, helper.TIMES_LIMIT, helper.SCHEDULES, helper.SCHEDULES_VIEW, helper.UNITS_KEY), (hub_schedules.HOURS, hub_schedules.TIMES_LIMIT, hub_schedules.SCHEDULES, hub_schedules.SCHEDULES_VIEW, hub_schedules.UNITS_KEY))
        self.assertEqual((helper.CALENDAR.pattern, helper.CRON.pattern, helper.HUB_UNIT.pattern), (signing.SCHEDULE_CALENDAR.pattern, signing.CRON.pattern, hub_schedules.HUB_UNIT.pattern))
        self.assertEqual(set(helper.UNITS) | {"coach", "dream"}, set(helper.ROWS))

    def test_coach_and_dream_start_off_cleanup_and_code_graph_on(self):
        self.assertEqual({name: row["on"] for name, row in helper.ROWS.items()}, {"coach": False, "dream": False, "dream-popup": False, "queue-cleanup": True, "code-graph": True})
        self.assertEqual((helper.ROWS["coach"]["every"], helper.ROWS["dream"]["every"], helper.ROWS["dream-popup"]["at"], helper.ROWS["queue-cleanup"]["at"]), (1, 12, ["17:00"], ["00:00", "12:00"]))

    def test_both_sides_refuse_the_same_bad_rows(self):
        bad = [
            ("nope", {"on": True}), ("coach", {"on": "yes", "every": 1}), ("coach", {"on": True, "every": 0}), ("coach", {"on": True, "every": 25}),
            ("coach", {"on": True, "every": True}), ("coach", {"on": True, "every": 1.5}), ("coach", {"on": True}), ("coach", {"on": True, "every": 1, "at": ["17:00"]}),
            ("dream-popup", {"on": True, "at": []}), ("dream-popup", {"on": True, "at": ["24:00"]}), ("dream-popup", {"on": True, "at": ["7:00"]}),
            ("queue-cleanup", {"on": True, "at": ["00:00", "00:00"]}), ("queue-cleanup", {"on": True, "at": [f"0{hour}:00" for hour in range(7)]}),
            ("code-graph", {"on": True, "every": 1}), ("coach", {"on": True, "calendar": "daily"}), ("dream-popup", {"on": True, "calendar": "daily\nExecStart=/bin/sh"}),
            ("dream-popup", {"on": True, "calendar": "--help"}), ("dream-popup", {"on": True, "at": ["17:00"], "calendar": "daily"}), ("code-graph", {"on": True, "calendar": "daily"}),
        ]
        for name, row in bad:
            with self.subTest(name=name, row=row):
                with self.assertRaises(hub_schedules.ToolError):
                    hub_schedules.valid_row(name, row)
                if name in helper.ROWS:
                    with self.assertRaises(ValueError):
                        helper.valid_row(name, row)
        for good in ({"on": True, "at": ["21:30", "06:00"]}, {"on": False, "calendar": "Mon..Fri *-*-* 08:15:00"}):
            with self.subTest(good=good):
                self.assertEqual(hub_schedules.valid_row("queue-cleanup", good), helper.valid_row("queue-cleanup", good))
        self.assertEqual(helper.valid_row("queue-cleanup", {"on": True, "at": ["21:30", "06:00"]})["at"], ["06:00", "21:30"])

    def test_both_sides_take_only_hub_timers_as_unsigned_overrides(self):
        for unit, value in ((HUB_UNIT, {"on": False}), (HUB_UNIT, {"on": True, "at": ["03:00"]}), (HUB_UNIT, {"on": True, "calendar": "hourly"})):
            with self.subTest(value=value):
                self.assertEqual(hub_schedules.valid_unit(unit, value), helper.valid_unit(unit, value))
        for unit, value in ((HUB_UNIT, {"on": 1}), (HUB_UNIT, {"on": True, "every": 2}), (HUB_UNIT, {"on": True, "at": ["03:00"], "calendar": "daily"}), ("kvb-orchestrator-runner.service", {"on": False})):
            with self.subTest(unit=unit, value=value):
                with self.assertRaises((ToolError, hub_schedules.Unsigned)):
                    hub_schedules.valid_unit(unit, value)
                with self.assertRaises(ValueError):
                    helper.valid_unit(unit, value)
        with self.assertRaises(hub_schedules.Unsigned):
            hub_schedules.valid_unit("backup.timer", {"on": False})

    def test_the_hub_names_the_cron_field_out_of_range(self):
        for cron in ("*/5 * * * *", "0 9 * * 1-5", "0,30 8-18/2 1 1-12 0", "15 3 * * *"):
            with self.subTest(cron=cron):
                self.assertEqual(hub_schedules.valid_cron(cron), cron)
        for cron, field in (("61 * * * *", "minute"), ("0 24 * * *", "hour"), ("0 0 0 * *", "day of month"), ("0 0 * 13 *", "month"), ("0 0 * * 7", "day of week"), ("*/0 * * * *", "minute"), ("0 9-5 * * *", "hour")):
            with self.subTest(cron=cron), self.assertRaisesRegex(ToolError, f"cron {field} field"):
                hub_schedules.valid_cron(cron)
        with self.assertRaisesRegex(ToolError, "5 fields"):
            hub_schedules.valid_cron("0 9 * *")


class TestScheduleArgv(unittest.TestCase):
    FILE = "/home/u/Repositories/github.com/me/repo/.claude/scheduled_tasks.json"

    def test_exactly_the_foreign_timer_and_cron_changes_pass(self):
        for argv in (["timer", "backup.timer", "--on"], ["timer", "backup.timer", "--off"], ["timer", "backup.timer", "--reset"], ["timer", "backup.timer", "--at", "17:00", "21:30"],
                     ["timer", "backup.timer", "--calendar", "Mon *-*-* 08:00:00"], ["cron", self.FILE, "f08cfd39", "--cron", "0 9 * * 1-5"], ["cron", self.FILE, "f08cfd39", "--remove"]):
            with self.subTest(argv=argv):
                self.assertEqual(signing.schedule_argv(argv), argv)
                self.assertEqual(signing.schedule_item(argv), {"kind": "schedule", "argv": argv})

    def test_every_other_argv_is_refused(self):
        cases = {
            "not a list": "timer backup.timer --on", "hub unit": ["timer", HUB_UNIT, "--off"], "service": ["timer", "backup.service", "--off"], "slash": ["timer", "../x.timer", "--off"],
            "two switches": ["timer", "backup.timer", "--on", "--off"], "bare": ["timer", "backup.timer"], "bad time": ["timer", "backup.timer", "--at", "7:00"],
            "twice": ["timer", "backup.timer", "--at", "17:00", "17:00"], "seven times": ["timer", "backup.timer", "--at", *[f"0{hour}:00" for hour in range(7)]],
            "newline calendar": ["timer", "backup.timer", "--calendar", "daily\nExecStart=/bin/sh"], "option calendar": ["timer", "backup.timer", "--calendar", "--help"],
            "relative file": ["cron", "repo/.claude/scheduled_tasks.json", "x", "--remove"], "dotdot": ["cron", "/home/u/../etc/.claude/scheduled_tasks.json", "x", "--remove"],
            "other file": ["cron", "/home/u/.claude/settings.json", "x", "--remove"], "bad id": ["cron", self.FILE, "a b", "--remove"], "four fields": ["cron", self.FILE, "x", "--cron", "0 9 * *"],
            "letters": ["cron", self.FILE, "x", "--cron", "0 9 * * MON"], "run": ["run"], "set": ["set", "coach", "--on"],
        }
        for name, argv in cases.items():
            with self.subTest(name=name):
                self.assertRaises(signing.Refused, signing.schedule_argv, argv)


class HelperCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.root = self.base / "council"
        self.root.mkdir(mode=0o700)
        self.file = self.root / helper.SCHEDULES
        self.units = self.base / "units"
        self.units.mkdir()
        self.repos = self.base / "Repositories"
        self.repos.mkdir()

    def cli(self, *args: str) -> subprocess.CompletedProcess:
        env = {"PATH": "/usr/bin:/bin", "HOME": str(self.base), "AGENTS_COUNCIL_ROOT": str(self.root)}
        return subprocess.run([sys.executable, "-I", str(HELPER), *args], capture_output=True, text=True, timeout=30, check=False, env=env)


class TestCheckAndSet(HelperCase):
    def test_check_answers_the_defaults_for_a_missing_linked_or_malformed_file(self):
        target = self.base / "elsewhere.json"
        target.write_text(json.dumps({"dream": {"on": True, "every": 3}}), encoding="utf-8")
        for case in ("missing", "linked", "broken", "list"):
            with self.subTest(case=case):
                self.file.unlink(missing_ok=True)
                if case == "linked":
                    self.file.symlink_to(target)
                elif case == "broken":
                    self.file.write_text("{", encoding="utf-8")
                elif case == "list":
                    self.file.write_text("[]", encoding="utf-8")
                self.assertEqual(self.cli("check", "dream").returncode, helper.OFF)
                self.assertEqual(self.cli("check", "queue-cleanup").returncode, 0)

    def test_check_prints_the_hours_of_a_reminder_that_is_on(self):
        self.file.write_text(json.dumps({"coach": {"on": True, "every": 3}}), encoding="utf-8")
        done = self.cli("check", "coach")
        self.assertEqual((done.returncode, done.stdout), (0, "3\n"))

    def test_set_writes_only_its_row_and_keeps_every_other_row_and_the_hub_overrides(self):
        rows = {**helper.ROWS, "dream": {"on": True, "every": 6}, "queue-cleanup": {"on": True, "calendar": "hourly"}, helper.UNITS_KEY: {HUB_UNIT: {"on": False}}}
        self.file.write_text(json.dumps(rows, sort_keys=True), encoding="utf-8")
        before = json.loads(self.file.read_text(encoding="utf-8"))
        done = self.cli("set", "coach", "--on", "--every", "2")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout), {"on": True, "every": 2})
        after = json.loads(self.file.read_text(encoding="utf-8"))
        self.assertEqual({name: row for name, row in after.items() if name != "coach"}, {name: row for name, row in before.items() if name != "coach"})
        self.assertEqual(after["coach"], {"on": True, "every": 2})
        self.assertEqual(self.file.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.cli("set", "queue-cleanup", "--at", "03:00").returncode, 0)
        self.assertEqual(json.loads(self.file.read_text(encoding="utf-8"))["queue-cleanup"], {"on": True, "at": ["03:00"]})

    def test_set_refuses_a_bad_value_and_a_key_the_row_does_not_take(self):
        for args in (("coach", "--every", "30"), ("coach", "--at", "17:00"), ("dream-popup", "--at", "25:00"), ("code-graph", "--every", "1")):
            with self.subTest(args=args):
                self.assertEqual(self.cli("set", *args).returncode, 2)
        self.assertFalse(self.file.exists())


class TestView(HelperCase):
    def test_view_lists_rows_of_all_four_sources(self):
        (self.units / "kvb-dream-notify.timer").write_text("[Timer]\nOnCalendar=*-*-* 17:00:00\nPersistent=true\n", encoding="utf-8")
        (self.units / "kvb-dream-notify.timer.d").mkdir()
        (self.units / "kvb-dream-notify.timer.d" / "schedule.conf").write_text("[Timer]\nOnCalendar=\nOnCalendar=*-*-* 21:30:00\n", encoding="utf-8")
        (self.units / "backup.timer").write_text("[Timer]\nOnBootSec=5min\nOnUnitActiveSec=1d\n", encoding="utf-8")
        path = task_file(self.repos, TASKS)
        states = Runner({"kvb-dream-notify.timer": "enabled", HUB_UNIT: "enabled", "backup.timer": "disabled"})
        rows = {row["name"]: row for row in helper.view(TIMERS, self.units, self.repos, states, {"backup.timer": "refused"})}
        self.assertEqual({row["source"] for row in rows.values()}, {"skills", "hub", "system", "claude"})
        for row in rows.values():
            self.assertEqual(set(row), set(hub_schedules.VIEW_KEYS))
        dream = rows["kvb-dream-notify.timer"]
        self.assertEqual((dream["source"], dream["schedule"], dream["next"], dream["last"], dream["on"], dream["dropin"]), ("skills", "OnCalendar=*-*-* 21:30:00", 1_800_000_000, 1_799_990_000, True, True))
        self.assertEqual((rows[HUB_UNIT]["source"], rows[HUB_UNIT]["last"], rows[HUB_UNIT]["on"]), ("hub", None, True))
        backup = rows["backup.timer"]
        self.assertEqual((backup["source"], backup["schedule"], backup["next"], backup["on"], backup["dropin"], backup["error"]), ("system", "OnBootSec=5min; OnUnitActiveSec=1d", None, False, False, "refused"))
        triage = rows["repo f08cfd39"]
        self.assertEqual((triage["source"], triage["kind"], triage["file"], triage["task"], triage["schedule"], triage["last"], triage["next"], triage["on"]),
                         ("claude", "cron", str(path), "f08cfd39", "7 * * * *", 1_799_000_000, None, True))
        self.assertEqual(triage["command"], "Triage the last two CI runs")
        self.assertEqual(states.calls, [["systemctl", "--user", "is-enabled", *[entry["unit"] for entry in TIMERS]]])

    def test_view_survives_a_broken_timer_answer_a_broken_task_file_and_a_linked_one(self):
        self.assertEqual(helper.view({"not": "a list"}, self.units, self.repos, Runner({}), {}), [])
        self.assertEqual(helper.view([{"unit": 5}, "x"], self.units, self.repos, Runner({}), {}), [])
        task_file(self.repos, {}, "{")
        target = self.base / "tasks.json"
        target.write_text(json.dumps(TASKS), encoding="utf-8")
        linked = self.repos / "github.com" / "me" / "other" / ".claude"
        linked.mkdir(parents=True)
        (linked / "scheduled_tasks.json").symlink_to(target)
        self.assertEqual(helper.view([], self.units, self.repos, Runner({}), {}), [])

    def test_view_through_the_cli_reads_a_timer_fixture(self):
        fixture = self.base / "timers.json"
        fixture.write_text(json.dumps(TIMERS), encoding="utf-8")
        done = self.cli("view", "--timers", str(fixture), "--units", str(self.units), "--repos", str(self.repos))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual([row["name"] for row in json.loads(done.stdout)], [entry["unit"] for entry in TIMERS])


class TestApply(HelperCase):
    def setUp(self):
        super().setUp()
        for unit in (*helper.UNITS.values(), HUB_UNIT, "backup.timer"):
            (self.units / unit).write_text("[Unit]\n", encoding="utf-8")

    def test_apply_switches_only_first_party_and_hub_units_whose_state_differs(self):
        rows = {**helper.ROWS, "dream-popup": {"on": True, "at": ["17:00"]}, "code-graph": {"on": False}}
        runner_ = Runner({"kvb-dream-notify.timer": "disabled", "kvb-org-queue-cleanup.timer": "enabled", "kvb-code-graph.service": "enabled", HUB_UNIT: "enabled", "backup.timer": "enabled"})
        calls, errors = helper.apply(rows, {HUB_UNIT: {"on": False}}, runner_, self.units)
        self.assertIn("enable --now kvb-dream-notify.timer", calls)
        self.assertIn("disable --now kvb-code-graph.service", calls)
        self.assertIn(f"disable --now {HUB_UNIT}", calls)
        self.assertEqual(errors, {})
        self.assertFalse([call for call in calls if "queue-cleanup" in call and "able" in call])
        self.assertFalse([argv for argv in runner_.calls if "backup.timer" in argv])

    def test_a_retime_writes_the_drop_in_reloads_once_and_a_second_apply_changes_nothing(self):
        rows = {**helper.ROWS, "queue-cleanup": {"on": True, "at": ["03:00", "15:30"]}}
        states = {unit: "enabled" for unit in helper.UNITS.values()} | {"kvb-dream-notify.timer": "disabled", HUB_UNIT: "enabled"}
        calls, _ = helper.apply(rows, {HUB_UNIT: {"on": True, "calendar": "hourly"}}, Runner(states), self.units)
        drop_in = self.units / "kvb-org-queue-cleanup.timer.d" / "schedule.conf"
        self.assertEqual(drop_in.read_text(encoding="utf-8"), "[Timer]\nOnCalendar=\nOnCalendar=*-*-* 03:00:00\nOnCalendar=*-*-* 15:30:00\n")
        self.assertEqual((self.units / f"{HUB_UNIT}.d" / "schedule.conf").read_text(encoding="utf-8"), "[Timer]\nOnCalendar=\nOnCalendar=hourly\n")
        self.assertEqual(calls.count("daemon-reload"), 1)
        self.assertIn("try-restart kvb-org-queue-cleanup.timer", calls)
        self.assertEqual(helper.apply(rows, {HUB_UNIT: {"on": True, "calendar": "hourly"}}, Runner(states), self.units)[0], [])

    def test_an_invalid_calendar_keeps_the_old_schedule_and_names_the_rows_error(self):
        drop_in = self.units / "kvb-org-queue-cleanup.timer.d" / "schedule.conf"
        drop_in.parent.mkdir()
        drop_in.write_text("[Timer]\nOnCalendar=\nOnCalendar=*-*-* 03:00:00\n", encoding="utf-8")
        rows = {**helper.ROWS, "queue-cleanup": {"on": True, "calendar": "every blue moon"}}
        calls, errors = helper.apply(rows, {}, Runner({}, refused=("every blue moon",)), self.units)
        self.assertEqual(drop_in.read_text(encoding="utf-8"), "[Timer]\nOnCalendar=\nOnCalendar=*-*-* 03:00:00\n")
        self.assertIn("every blue moon", errors["kvb-org-queue-cleanup.timer"])
        self.assertNotIn("try-restart kvb-org-queue-cleanup.timer", calls)

    def test_a_hub_override_without_a_retime_removes_only_the_drop_in(self):
        drop_in = self.units / f"{HUB_UNIT}.d" / "schedule.conf"
        drop_in.parent.mkdir()
        drop_in.write_text("[Timer]\nOnCalendar=\nOnCalendar=hourly\n", encoding="utf-8")
        calls, _ = helper.apply(helper.ROWS, {HUB_UNIT: {"on": True}}, Runner({HUB_UNIT: "enabled"}), self.units)
        self.assertFalse(drop_in.exists())
        self.assertTrue((self.units / HUB_UNIT).is_file())
        self.assertIn(f"try-restart {HUB_UNIT}", calls)

    def test_a_missing_masked_or_static_unit_is_never_switched(self):
        rows = {name: {**row, "on": not row["on"]} for name, row in helper.ROWS.items()}
        runner_ = Runner({"kvb-dream-notify.timer": "masked", "kvb-org-queue-cleanup.timer": "static"})
        self.assertEqual([call for call in helper.apply(rows, {}, runner_, self.units)[0] if "able" in call], [])


class TestHostChange(HelperCase):
    def args(self, **given: object) -> mock.Mock:
        return mock.Mock(**{"on": None, "reset": False, "calendar": None, "at": None, **given})

    def test_a_system_timer_retime_writes_the_drop_in_and_reset_removes_it(self):
        (self.units / "backup.timer").write_text("[Timer]\nOnBootSec=5min\n", encoding="utf-8")
        calls, error = helper.timer_change("backup.timer", self.args(at=["21:30", "06:00"]), Runner({}), self.units)
        drop_in = self.units / "backup.timer.d" / "schedule.conf"
        self.assertEqual((calls, error), (["daemon-reload", "try-restart backup.timer"], ""))
        self.assertEqual(drop_in.read_text(encoding="utf-8"), "[Timer]\nOnCalendar=\nOnCalendar=*-*-* 06:00:00\nOnCalendar=*-*-* 21:30:00\n")
        calls, error = helper.timer_change("backup.timer", self.args(reset=True), Runner({}), self.units)
        self.assertEqual((calls, error, drop_in.exists(), (self.units / "backup.timer").is_file()), (["daemon-reload", "try-restart backup.timer"], "", False, True))

    def test_a_refused_calendar_or_a_first_party_or_unknown_unit_changes_nothing(self):
        (self.units / "backup.timer").write_text("[Timer]\n", encoding="utf-8")
        _, error = helper.timer_change("backup.timer", self.args(calendar="nonsense"), Runner({}, refused=("nonsense",)), self.units)
        self.assertIn("systemd-analyze refuses", error)
        for unit in (HUB_UNIT, "kvb-dream-notify.timer", "gone.timer"):
            with self.subTest(unit=unit):
                runner_ = Runner({})
                self.assertNotEqual(helper.timer_change(unit, self.args(on=False), runner_, self.units)[1], "")
                self.assertEqual(runner_.calls, [])
        self.assertFalse((self.units / "backup.timer.d").exists())

    def test_on_and_off_switch_a_system_timer_whose_state_differs(self):
        (self.units / "backup.timer").write_text("[Timer]\n", encoding="utf-8")
        self.assertEqual(helper.timer_change("backup.timer", self.args(on=False), Runner({"backup.timer": "enabled"}), self.units), (["disable --now backup.timer"], ""))
        self.assertEqual(helper.timer_change("backup.timer", self.args(on=False), Runner({"backup.timer": "disabled"}), self.units), ([], ""))

    def test_a_cron_change_keeps_every_other_byte_and_remove_drops_only_the_task(self):
        for indent in (2, None):
            with self.subTest(indent=indent):
                repos = self.repos / f"i{indent}"
                path = task_file(repos, TASKS, json.dumps(TASKS, indent=indent, ensure_ascii=False) + "\n")
                before = path.read_text(encoding="utf-8")
                self.assertEqual(helper.cron_change(path, "f08cfd39", "15 * * * *", repos), "")
                after = path.read_text(encoding="utf-8")
                self.assertEqual(after, before.replace('"7 * * * *"', '"15 * * * *"'))
                self.assertEqual(helper.cron_change(path, "a1b2c3d4", None, repos), "")
                self.assertEqual([task["id"] for task in json.loads(path.read_text(encoding="utf-8"))["tasks"]], ["f08cfd39"])

    def test_a_cron_change_refuses_an_unlisted_file_an_unknown_task_and_an_unknown_layout(self):
        path = task_file(self.repos, TASKS, '{"tasks":  [ ]}')
        self.assertIn("no task", helper.cron_change(path, "f08cfd39", "15 * * * *", self.repos))
        outside = self.base / "elsewhere" / ".claude" / "scheduled_tasks.json"
        outside.parent.mkdir(parents=True)
        outside.write_text(json.dumps(TASKS), encoding="utf-8")
        self.assertIn("no task file", helper.cron_change(outside, "f08cfd39", "15 * * * *", self.repos))
        self.assertEqual(json.loads(outside.read_text(encoding="utf-8")), TASKS)

    def test_the_cron_command_refreshes_the_view_with_the_new_cron(self):
        path = task_file(self.repos, TASKS)
        done = self.cli("cron", str(path), "f08cfd39", "--cron", "15 * * * *", "--units", str(self.units), "--repos", str(self.repos))
        self.assertEqual(done.returncode, 0, done.stderr)
        rows = json.loads((self.root / helper.SCHEDULES_VIEW).read_text(encoding="utf-8"))["rows"]
        self.assertIn(("f08cfd39", "15 * * * *"), [(row["task"], row["schedule"]) for row in rows])
        self.assertEqual(self.cli("cron", str(path), "nope", "--cron", "15 * * * *", "--units", str(self.units), "--repos", str(self.repos)).returncode, 2)


class TestUnits(unittest.TestCase):
    def test_the_path_unit_watches_schedules_json_and_the_timer_refreshes_every_five_minutes(self):
        self.assertIn("PathModified=%S/agents-shared/schedules.json", (SYSTEMD / "kvb-schedules.path").read_text(encoding="utf-8"))
        self.assertIn("OnUnitActiveSec=5min", (SYSTEMD / "kvb-schedules.timer").read_text(encoding="utf-8"))
        self.assertIn("kvb-org-organize/scripts/schedules.py run", (SYSTEMD / "kvb-schedules.service").read_text(encoding="utf-8"))

    def test_the_installer_no_longer_enables_the_dream_timer(self):
        text = (REPO_ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
        enables = [line for line in text.splitlines() if "enable --now" in line]
        self.assertTrue(enables)
        self.assertFalse([line for line in enables if "kvb-dream-notify" in line])
        self.assertTrue([line for line in enables if "kvb-schedules.path kvb-schedules.timer" in line])

    def test_the_runner_unit_passes_the_schedules_script(self):
        unit = (REPO_ROOT / "orchestrator" / "systemd" / "kvb-orchestrator-runner.service").read_text(encoding="utf-8")
        self.assertIn("--schedules %h/.claude/skills/kvb-org-organize/scripts/schedules.py", unit)


def timer(*rest: str) -> dict:
    return {"kind": "schedule", "argv": ["timer", "backup.timer", *rest]}


class TestSchedulesApi(HubCase):
    def post(self, payload: object) -> tuple[int, bytes]:
        status, _, body = self.post_json("/api/schedules", payload, self.guard(self.host))
        return status, body

    def test_a_row_change_reaches_schedules_json_and_the_state_and_keeps_the_other_rows(self):
        status, body = self.post({"row": "coach", "value": {"on": True, "every": 2}})
        self.assertEqual(status, 200, body)
        stored = json.loads((self.council / hub_schedules.SCHEDULES).read_text(encoding="utf-8"))
        self.assertEqual(stored, {**hub_schedules.ROWS, "coach": {"on": True, "every": 2}, hub_schedules.UNITS_KEY: {}})
        status, body = self.post({"row": "dream-popup", "value": {"on": True, "calendar": "Mon *-*-* 21:30:00"}})
        self.assertEqual(status, 200, body)
        rows = self.snapshot()["schedules"]["rows"]
        self.assertEqual((rows["coach"], rows["dream-popup"]), ({"on": True, "every": 2}, {"on": True, "calendar": "Mon *-*-* 21:30:00"}))
        self.assertEqual(helper.stored(self.council), rows)

    def test_a_hub_timer_saves_without_a_proof_and_keeps_the_skills_rows(self):
        self.assertEqual(self.post({"row": "coach", "value": {"on": True, "every": 2}})[0], 200)
        status, body = self.post({"unit": HUB_UNIT, "value": {"on": True, "at": ["04:00"]}})
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)["units"], {HUB_UNIT: {"on": True, "at": ["04:00"]}})
        self.assertEqual(helper.stored_units(self.council), {HUB_UNIT: {"on": True, "at": ["04:00"]}})
        self.assertEqual(helper.stored(self.council)["coach"], {"on": True, "every": 2})
        self.assertEqual(self.runner_jobs(), [])

    def test_a_system_row_or_a_claude_task_without_a_valid_proof_answers_403_and_stores_nothing(self):
        cron = {"kind": "schedule", "argv": ["cron", "/home/u/Repositories/github.com/me/repo/.claude/scheduled_tasks.json", "f08cfd39", "--cron", "0 9 * * *"]}
        for payload in ({"unit": "backup.timer", "value": {"on": False}}, {"items": [timer("--off")], "proof": None}, {"items": [cron], "proof": None},
                        {"items": [timer("--off")], "proof": {"payload": {}, "assertion": {}}}):
            with self.subTest(payload=payload):
                self.assertEqual(self.post(payload)[0], 403)
        proof = self.signed([timer("--off")], self.pin())
        self.assertEqual(self.post({"items": [timer("--on")], "proof": proof})[0], 403)
        self.assertFalse((self.council / hub_schedules.SCHEDULES).exists())
        self.assertEqual(self.runner_jobs(), [])

    def test_a_signed_system_row_answers_200_and_becomes_one_runner_job(self):
        items = [timer("--at", "21:30", "06:00")]
        status, body = self.post({"items": items, "proof": self.signed(items, self.pin())})
        self.assertEqual(status, 200, body)
        jobs = self.runner_jobs()
        self.assertEqual([(job["kind"], job["argv"], job["command"]) for job in jobs], [("schedule", items[0]["argv"], "schedules.py timer backup.timer --at 21:30 06:00")])
        self.assertFalse((self.council / hub_schedules.SCHEDULES).exists())

    def test_a_bad_cron_answers_400_naming_the_field(self):
        cron = {"kind": "schedule", "argv": ["cron", "/home/u/Repositories/github.com/me/repo/.claude/scheduled_tasks.json", "f08cfd39", "--cron", "0 25 * * *"]}
        for path, payload in (("/api/sign", {"items": [cron]}), ("/api/schedules", {"items": [cron], "proof": None})):
            with self.subTest(path=path):
                status, _, body = self.post_json(path, payload, self.guard(self.host))
                self.assertEqual(status, 400, body)
                self.assertIn(b"cron hour field 25", body)

    def test_bad_rows_answer_400_and_leave_the_file_alone(self):
        for payload in ({"row": "nope", "value": {"on": True}}, {"row": "coach", "value": {"on": True, "every": 0}}, {"row": ["coach"], "value": {}}, {"row": "coach"}, [1],
                        {"unit": HUB_UNIT, "value": {"on": True, "calendar": "daily\n[Service]"}}, {"items": [timer("--off", "--on")], "proof": None}):
            with self.subTest(payload=payload):
                self.assertEqual(self.post(payload)[0], 400)
        self.assertFalse((self.council / hub_schedules.SCHEDULES).exists())

    def test_the_state_carries_the_host_view_and_drops_a_malformed_one(self):
        self.council.mkdir(parents=True, exist_ok=True)
        view = self.council / hub_schedules.SCHEDULES_VIEW
        self.assertEqual(self.snapshot()["schedules"]["host"], {"at": None, "rows": []})
        row = {"name": "backup.timer", "source": "system", "kind": "timer", "unit": "backup.timer", "file": "/u/backup.timer", "task": "", "schedule": "OnBootSec=5min", "next": 1.5, "last": None,
               "on": True, "dropin": False, "error": "", "command": ""}
        view.write_text(json.dumps({"at": 100, "rows": [row, {"name": 3}, "x"]}), encoding="utf-8")
        self.assertEqual(self.snapshot()["schedules"]["host"], {"at": 100, "rows": [row]})
        view.write_text(json.dumps({"at": True, "rows": [row]}), encoding="utf-8")
        self.assertEqual(self.snapshot()["schedules"]["host"], {"at": None, "rows": []})

    def test_a_get_of_the_route_is_not_allowed(self):
        self.assertEqual(self.get("/api/schedules")[0], 405)


class TestRunnerSchedule(HubCase):
    def setUp(self):
        super().setUp()
        self.home = self.outside / "home"
        self.repos = self.home / "Repositories"
        self.council.mkdir(exist_ok=True)
        self.tasks = task_file(self.repos, TASKS)

    def change(self, argv: list[str]) -> None:
        items = [{"kind": "schedule", "argv": argv}]
        status, _, body = self.post_json("/api/schedules", {"items": items, "proof": self.signed(items, self.pin())}, self.guard(self.host))
        self.assertEqual(status, 200, body)

    def run_schedule_runner(self, flags: list[str]) -> None:
        trust = ["--approvers", str(self.approvers), "--replay", str(self.replay / "runner.json"), "--state", str(self.state)]
        command = [sys.executable, str(RUNNER), "--port", str(self.port), "--interval", "0.1", *trust, *flags, "--once"]
        done = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False, env={**os.environ, "HOME": str(self.home)})
        self.assertEqual(done.returncode, 0, done.stderr)

    def flags(self) -> list[str]:
        return ["--schedules", str(HELPER), "--council", str(self.council), "--rasci", str(REPO_ROOT / "skills" / "kvb-org-rasci" / "scripts" / "rasci.py")]

    def test_the_runner_changes_the_signed_cron_by_argv_and_refreshes_the_view(self):
        before = self.tasks.read_text(encoding="utf-8")
        self.change(["cron", str(self.tasks), "f08cfd39", "--cron", "15 * * * *"])
        self.run_schedule_runner(self.flags())
        self.assertEqual([(job["status"], job["code"]) for job in self.httpd.hub.jobs.listed()], [("done", 0)])
        self.assertEqual(self.tasks.read_text(encoding="utf-8"), before.replace('"7 * * * *"', '"15 * * * *"'))
        rows = self.snapshot()["schedules"]["host"]["rows"]
        self.assertIn(("claude", "f08cfd39", "15 * * * *"), [(row["source"], row["task"], row["schedule"]) for row in rows])

    def test_without_schedules_the_runner_refuses_and_writes_nothing(self):
        before = self.tasks.read_bytes()
        self.change(["cron", str(self.tasks), "f08cfd39", "--remove"])
        self.run_schedule_runner([])
        self.assertEqual([(job["status"], job["output"]) for job in self.httpd.hub.jobs.listed()], [("refused", runner.UNSCHEDULED)])
        self.assertEqual(self.tasks.read_bytes(), before)

    def test_the_runner_refuses_an_argv_that_differs_from_the_signed_one(self):
        before = self.tasks.read_bytes()
        self.change(["cron", str(self.tasks), "f08cfd39", "--cron", "15 * * * *"])
        job = self.httpd.hub.jobs.listed()[0]
        self.httpd.hub.jobs.change(job["id"], {"argv": ["cron", str(self.tasks), "f08cfd39", "--remove"]})
        self.run_schedule_runner(self.flags())
        refused = self.httpd.hub.jobs.listed()[0]
        self.assertEqual(refused["status"], "refused")
        self.assertIn("does not list this item", refused["output"])
        self.assertEqual(self.tasks.read_bytes(), before)

    def test_schedule_refusal_checks_the_argv_shape_before_any_signature(self):
        reason = runner.schedule_refusal({"argv": ["run"], "proof": None}, mock.Mock(), time.time())
        self.assertIn("timer <unit> change or cron <file> <id> change", reason)
        with self.assertRaises(signing.Refused):
            runner.schedule({"argv": ["timer", HUB_UNIT, "--off"]}, runner.Scripts(register=None, gates=None, queue=None, schedules=HELPER, radio=None), print)


@unittest.skipUnless(shutil.which("node"), "node not installed")
class TestRoute(unittest.TestCase):
    def test_stream_schedules_opens_the_controls_screen_on_its_tab_and_back(self):
        probe = (
            "const Nav = require(process.argv[1]);"
            "console.log(JSON.stringify([Nav.route('#stream/schedules', 0), Nav.hashOf('rules', 'schedules'), Nav.hashOf('rules', null)]));"
        )
        done = subprocess.run(["node", "-e", probe, str(TEMPLATES / "nav.js")], capture_output=True, text=True, timeout=30, check=True)
        self.assertEqual(json.loads(done.stdout), [{"screen": "rules", "view": "schedules", "redirect": None}, "#stream/schedules", "#stream/rules"])

    def test_the_controls_tabs_hold_schedules_and_the_home_panel_is_registered(self):
        firewall = (TEMPLATES / "page-firewall.js").read_text(encoding="utf-8")
        self.assertIn('["schedules", "Schedules", "bi-clock"]', firewall)
        self.assertIn('Panels.panel("stream/schedules",', (TEMPLATES / "page-home.js").read_text(encoding="utf-8"))
        page = (TEMPLATES / "page-schedules.js").read_text(encoding="utf-8")
        for marker in ('"data-panel": "stream/schedules"', '"data-source-chip": id', '["Source", "Name", "Schedule", "Next", "Last", "On"]', 'kind: "schedule"'):
            with self.subTest(marker=marker):
                self.assertIn(marker, page)
        index = (TEMPLATES / "index.html.j2").read_text(encoding="utf-8")
        self.assertLess(index.index('"page-schedules.js"'), index.index('"page-home.js"'))


if __name__ == "__main__":
    unittest.main()
