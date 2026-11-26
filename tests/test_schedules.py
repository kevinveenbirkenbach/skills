"""Pin requirement 057: schedules.json as the one store of the Schedules rows, the host reconciler and the hub's tab."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from hub_case import HubCase
from kvb_orchestrator import schedules as hub_schedules

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
SETTINGS = {
    "hooks": {
        "UserPromptSubmit": [{"hooks": [
            {"type": "command", "command": "/usr/bin/bash /home/u/.claude/skills/kvb-dream/hooks/reminder.sh"},
            {"type": "command", "command": "/usr/bin/bash /home/u/.claude/skills/kvb-coach/hooks/reminder.sh"},
        ]}],
        "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "python3 /opt/guard.py"}]}],
    },
}


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


helper = load("kvb_schedules_helper", HELPER)


class Runner:
    def __init__(self, states: dict[str, str]) -> None:
        self.states = states
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str]) -> tuple[int, str]:
        self.calls.append(argv)
        if argv[2] == "is-enabled":
            states = [self.states.get(unit, "not-found") for unit in argv[3:]]
            return (0 if "enabled" in states else 1), "".join(f"{state}\n" for state in states)
        return 0, ""


class TestRows(unittest.TestCase):
    def test_host_and_hub_share_the_rows_the_limits_and_the_file_names(self):
        self.assertEqual(helper.ROWS, hub_schedules.ROWS)
        self.assertEqual((helper.HOURS, helper.TIMES_LIMIT, helper.SCHEDULES, helper.SCHEDULES_VIEW), (hub_schedules.HOURS, hub_schedules.TIMES_LIMIT, hub_schedules.SCHEDULES, hub_schedules.SCHEDULES_VIEW))
        self.assertEqual(set(helper.UNITS) | set(helper.HOOKS), set(helper.ROWS))

    def test_coach_and_dream_start_off_cleanup_and_code_graph_on(self):
        self.assertEqual({name: row["on"] for name, row in helper.ROWS.items()}, {"coach": False, "dream": False, "dream-popup": False, "queue-cleanup": True, "code-graph": True})
        self.assertEqual((helper.ROWS["coach"]["every"], helper.ROWS["dream"]["every"], helper.ROWS["dream-popup"]["at"], helper.ROWS["queue-cleanup"]["at"]), (1, 12, ["17:00"], ["00:00", "12:00"]))

    def test_both_sides_refuse_the_same_bad_rows(self):
        bad = [
            ("nope", {"on": True}), ("coach", {"on": "yes", "every": 1}), ("coach", {"on": True, "every": 0}), ("coach", {"on": True, "every": 25}),
            ("coach", {"on": True, "every": True}), ("coach", {"on": True, "every": 1.5}), ("coach", {"on": True}), ("coach", {"on": True, "every": 1, "at": ["17:00"]}),
            ("dream-popup", {"on": True, "at": []}), ("dream-popup", {"on": True, "at": ["24:00"]}), ("dream-popup", {"on": True, "at": ["7:00"]}),
            ("queue-cleanup", {"on": True, "at": ["00:00", "00:00"]}), ("queue-cleanup", {"on": True, "at": [f"0{hour}:00" for hour in range(7)]}),
            ("code-graph", {"on": True, "every": 1}),
        ]
        for name, row in bad:
            with self.subTest(name=name, row=row):
                with self.assertRaises(hub_schedules.ToolError):
                    hub_schedules.valid_row(name, row)
                if name in helper.ROWS:
                    with self.assertRaises(ValueError):
                        helper.valid_row(name, row)
        good = {"on": True, "at": ["21:30", "06:00"]}
        self.assertEqual(hub_schedules.valid_row("queue-cleanup", good), helper.valid_row("queue-cleanup", good))
        self.assertEqual(helper.valid_row("queue-cleanup", good)["at"], ["06:00", "21:30"])


class HelperCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.root = self.base / "council"
        self.root.mkdir(mode=0o700)
        self.file = self.root / helper.SCHEDULES

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

    def test_set_writes_only_its_row_and_keeps_every_other_row_byte_for_byte(self):
        rows = {**helper.ROWS, "dream": {"on": True, "every": 6}, "queue-cleanup": {"on": True, "at": ["03:00"]}}
        self.file.write_text(json.dumps(rows, sort_keys=True), encoding="utf-8")
        before = json.loads(self.file.read_text(encoding="utf-8"))
        done = self.cli("set", "coach", "--on", "--every", "2")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout), {"on": True, "every": 2})
        after = json.loads(self.file.read_text(encoding="utf-8"))
        self.assertEqual({name: row for name, row in after.items() if name != "coach"}, {name: row for name, row in before.items() if name != "coach"})
        self.assertEqual(after["coach"], {"on": True, "every": 2})
        self.assertEqual(self.file.read_text(encoding="utf-8"), json.dumps(after, sort_keys=True))
        self.assertEqual(self.file.stat().st_mode & 0o777, 0o600)

    def test_set_refuses_a_bad_value_and_a_key_the_row_does_not_take(self):
        for args in (("coach", "--every", "30"), ("coach", "--at", "17:00"), ("dream-popup", "--at", "25:00"), ("code-graph", "--every", "1")):
            with self.subTest(args=args):
                self.assertEqual(self.cli("set", *args).returncode, 2)
        self.assertFalse(self.file.exists())


class TestView(HelperCase):
    def test_view_rows_name_owner_unit_file_schedule_runs_and_hooks(self):
        units = self.base / "units"
        units.mkdir()
        (units / "kvb-dream-notify.timer").write_text("[Timer]\nOnCalendar=*-*-* 17:00:00\nPersistent=true\n", encoding="utf-8")
        (units / "kvb-dream-notify.timer.d").mkdir()
        (units / "kvb-dream-notify.timer.d" / "schedule.conf").write_text("[Timer]\nOnCalendar=\nOnCalendar=*-*-* 21:30:00\n", encoding="utf-8")
        (units / "backup.timer").write_text("[Timer]\nOnBootSec=5min\nOnUnitActiveSec=1d\n", encoding="utf-8")
        settings = self.base / "settings.json"
        settings.write_text(json.dumps(SETTINGS), encoding="utf-8")
        rows = {row["name"]: row for row in helper.view(TIMERS, settings, units)}
        dream = rows["kvb-dream-notify.timer"]
        self.assertEqual((dream["owner"], dream["schedule"], dream["next"], dream["last"], dream["off"]), ("skills", "OnCalendar=*-*-* 21:30:00", 1_800_000_000, 1_799_990_000, ""))
        self.assertEqual(dream["file"], str(units / "kvb-dream-notify.timer"))
        hub = rows["kvb-orchestrator-tree.timer"]
        self.assertEqual((hub["owner"], hub["last"], hub["off"]), ("hub", None, ""))
        backup = rows["backup.timer"]
        self.assertEqual((backup["owner"], backup["schedule"], backup["next"], backup["off"]), ("other", "OnBootSec=5min; OnUnitActiveSec=1d", None, "systemctl --user disable --now backup.timer"))
        self.assertEqual((rows["dream"]["owner"], rows["coach"]["owner"], rows["dream"]["event"]), ("skills", "skills", "UserPromptSubmit"))
        guard = rows["PreToolUse hook"]
        self.assertEqual((guard["owner"], guard["command"], guard["kind"]), ("other", "python3 /opt/guard.py", "hook"))
        self.assertIn(str(settings), guard["off"])

    def test_view_survives_a_broken_timer_answer_and_a_missing_settings_file(self):
        self.assertEqual(helper.view({"not": "a list"}, self.base / "missing.json", self.base), [])
        self.assertEqual(helper.view([{"unit": 5}, "x"], self.base / "missing.json", self.base), [])

    def test_view_through_the_cli_reads_a_timer_fixture(self):
        fixture = self.base / "timers.json"
        fixture.write_text(json.dumps(TIMERS), encoding="utf-8")
        done = self.cli("view", "--timers", str(fixture), "--settings", str(self.base / "none.json"), "--units", str(self.base))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual([row["name"] for row in json.loads(done.stdout)], [entry["unit"] for entry in TIMERS])


class TestApply(HelperCase):
    def setUp(self):
        super().setUp()
        self.units = self.base / "units"
        self.units.mkdir()
        for unit in helper.UNITS.values():
            (self.units / unit).write_text("[Unit]\n", encoding="utf-8")

    def test_apply_switches_only_first_party_units_whose_state_differs(self):
        rows = {**helper.ROWS, "dream-popup": {"on": True, "at": ["17:00"]}, "code-graph": {"on": False}}
        runner = Runner({"kvb-dream-notify.timer": "disabled", "kvb-org-queue-cleanup.timer": "enabled", "kvb-code-graph.service": "enabled"})
        calls = helper.apply(rows, runner, self.units)
        self.assertIn("enable --now kvb-dream-notify.timer", calls)
        self.assertIn("disable --now kvb-code-graph.service", calls)
        self.assertFalse([call for call in calls if "queue-cleanup" in call and "able" in call])
        named = {unit for argv in runner.calls if argv[2] != "daemon-reload" for unit in argv[3:] if unit != "--now"}
        self.assertLessEqual(named, set(helper.UNITS.values()))
        self.assertFalse([argv for argv in runner.calls if any(part.startswith("kvb-orchestrator-") for part in argv)])

    def test_a_retime_writes_the_drop_in_reloads_once_and_a_second_apply_changes_nothing(self):
        rows = {**helper.ROWS, "queue-cleanup": {"on": True, "at": ["03:00", "15:30"]}}
        runner = Runner({unit: "enabled" for unit in helper.UNITS.values()} | {"kvb-dream-notify.timer": "disabled"})
        calls = helper.apply(rows, runner, self.units)
        drop_in = self.units / "kvb-org-queue-cleanup.timer.d" / "schedule.conf"
        self.assertEqual(drop_in.read_text(encoding="utf-8"), "[Timer]\nOnCalendar=\nOnCalendar=*-*-* 03:00:00\nOnCalendar=*-*-* 15:30:00\n")
        self.assertEqual(calls.count("daemon-reload"), 1)
        self.assertIn("try-restart kvb-org-queue-cleanup.timer", calls)
        self.assertEqual(helper.apply(rows, Runner(runner.states), self.units), [])

    def test_a_missing_masked_or_static_unit_is_never_switched(self):
        rows = {name: {**row, "on": not row["on"]} for name, row in helper.ROWS.items()}
        runner = Runner({"kvb-dream-notify.timer": "masked", "kvb-org-queue-cleanup.timer": "static"})
        self.assertEqual([call for call in helper.apply(rows, runner, self.units) if "able" in call], [])


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


class TestSchedulesApi(HubCase):
    def post(self, payload: object) -> tuple[int, bytes]:
        status, _, body = self.post_json("/api/schedules", payload, self.guard(self.host))
        return status, body

    def test_a_row_change_reaches_schedules_json_and_the_state_and_keeps_the_other_rows(self):
        status, body = self.post({"row": "coach", "value": {"on": True, "every": 2}})
        self.assertEqual(status, 200, body)
        stored = json.loads((self.council / hub_schedules.SCHEDULES).read_text(encoding="utf-8"))
        self.assertEqual(stored, {**hub_schedules.ROWS, "coach": {"on": True, "every": 2}})
        status, body = self.post({"row": "dream-popup", "value": {"on": True, "at": ["21:30"]}})
        self.assertEqual(status, 200, body)
        rows = self.snapshot()["schedules"]["rows"]
        self.assertEqual((rows["coach"], rows["dream-popup"]), ({"on": True, "every": 2}, {"on": True, "at": ["21:30"]}))
        self.assertEqual(helper.stored(self.council), rows)

    def test_bad_rows_answer_400_and_leave_the_file_alone(self):
        for payload in ({"row": "nope", "value": {"on": True}}, {"row": "coach", "value": {"on": True, "every": 0}}, {"row": ["coach"], "value": {}}, {"row": "coach"}, [1]):
            with self.subTest(payload=payload):
                self.assertEqual(self.post(payload)[0], 400)
        self.assertFalse((self.council / hub_schedules.SCHEDULES).exists())

    def test_the_state_carries_the_host_view_and_drops_a_malformed_one(self):
        self.council.mkdir(parents=True, exist_ok=True)
        view = self.council / hub_schedules.SCHEDULES_VIEW
        self.assertEqual(self.snapshot()["schedules"]["host"], {"at": None, "rows": []})
        row = {"name": "backup.timer", "kind": "timer", "owner": "other", "unit": "backup.timer", "file": "/u/backup.timer", "schedule": "OnBootSec=5min", "next": 1.5, "last": None, "event": "", "command": "", "off": "systemctl --user disable --now backup.timer"}
        view.write_text(json.dumps({"at": 100, "rows": [row, {"name": 3}, "x"]}), encoding="utf-8")
        self.assertEqual(self.snapshot()["schedules"]["host"], {"at": 100, "rows": [row]})
        view.write_text(json.dumps({"at": True, "rows": [row]}), encoding="utf-8")
        self.assertEqual(self.snapshot()["schedules"]["host"], {"at": None, "rows": []})

    def test_a_get_of_the_route_is_not_allowed(self):
        self.assertEqual(self.get("/api/schedules")[0], 405)


@unittest.skipUnless(shutil.which("node"), "node not installed")
class TestRoute(unittest.TestCase):
    def test_stream_schedules_opens_the_controls_screen_on_its_tab_and_back(self):
        probe = (
            "const Nav = require(process.argv[1]);"
            "console.log(JSON.stringify([Nav.route('#stream/schedules', 0), Nav.hashOf('rules', 'schedules'), Nav.hashOf('rules', null)]));"
        )
        done = subprocess.run(["node", "-e", probe, str(TEMPLATES / "nav.js")], capture_output=True, text=True, timeout=30, check=True)
        self.assertEqual(json.loads(done.stdout), [{"screen": "rules", "view": "schedules", "redirect": None}, "#stream/schedules", "#stream/rules"])

    def test_the_controls_tabs_end_with_schedules_and_the_home_panel_is_registered(self):
        firewall = (TEMPLATES / "page-firewall.js").read_text(encoding="utf-8")
        self.assertIn('["groups", "Groups", "bi-people"], ["schedules", "Schedules", "bi-clock"]];', firewall)
        self.assertIn('Panels.panel("stream/schedules",', (TEMPLATES / "page-home.js").read_text(encoding="utf-8"))
        self.assertIn('"data-panel": "stream/schedules"', (TEMPLATES / "page-schedules.js").read_text(encoding="utf-8"))
        index = (TEMPLATES / "index.html.j2").read_text(encoding="utf-8")
        self.assertLess(index.index('"page-schedules.js"'), index.index('"page-home.js"'))


if __name__ == "__main__":
    unittest.main()
