from __future__ import annotations

import copy
import datetime
import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import hub_support
from hub_case import HubCase
from kvb_orchestrator import accounts, calibration, settings
from kvb_orchestrator.errors import ToolError
from kvb_orchestrator.viewstore import VIEW, upgraded, valid_view

HUB = hub_support.HUB
REPO = hub_support.REPO_ROOT
HOOK = REPO / "skills" / "kvb-org-organize" / "scripts" / "account.py"
SAMPLER = HUB / "client" / "resources.py"
MODULE = HUB / "templates" / "resources.js"
BAR = HUB / "templates" / "usagebar.js"
ACCOUNT = {
    "provider": "Anthropic", "email": "one@example.org", "renewal": {"day": 1, "time": "09:00"}, "reset": {"day": 4, "time": "18:30"},
    "resubscribe": "2026-12-01", "autorenew": True, "limit": 1000, "note": "team seat",
}
MOMENTS = r"""
const R = require(process.argv[1]);
const at = (text) => new Date(text).getTime();
const iso = (ms) => new Date(ms).toISOString();
const reset = {day: 0, time: "03:30"};
const entry = {total: 900, hours: [[at("2026-10-24T22:00:00Z") / 1000, 100], [at("2026-10-25T03:00:00Z") / 1000, 200], [at("2026-10-26T08:00:00Z") / 1000, 300]]};
console.log(JSON.stringify({
  before: iso(R.lastMoment(reset, at("2026-10-25T01:00:00Z"))),
  after: iso(R.lastMoment(reset, at("2026-10-25T04:00:00Z"))),
  next: iso(R.nextMoment(reset, at("2026-10-25T04:00:00Z"))),
  exact: iso(R.lastMoment(reset, at("2026-10-25T02:30:00Z"))),
  used: R.accountUsage(entry, reset, at("2026-10-26T09:00:00Z")),
  unassigned: R.accountUsage(entry, null, at("2026-10-26T09:00:00Z")),
}));
"""

COLOURS = r"""
const U = require(process.argv[1]);
const HOUR = 3600;
const LAST = Date.UTC(2026, 10, 23, 8, 0) / 1000;
const AT = LAST + 2 * HOUR;
const NOW = Date.UTC(2026, 10, 25, 12, 0);
const DAY = 86400000;
const entry = {total: 150, hours: [[LAST + HOUR, 100], [AT + HOUR, 50]]};
const recent = {total: 240, hours: [[NOW / 1000 - HOUR, 240]]};
console.log(JSON.stringify({
  stops: [0, 50, 75, 100].map(U.fillColor),
  named: ["green", "yellow", "orange", "red"].map((name) => U.css(U.COLORS[name])),
  colors: U.COLORS,
  sixty: U.fillStop(60),
  hues: Array.from({length: 1001}, (_, tenth) => U.fillStop(tenth / 10)[2]),
  ends: [U.fillColor(-5), U.fillColor(140)],
  calibrated: U.usage(1000, entry, {share: 40, at: AT}, LAST * 1000),
  stale: U.usage(1000, entry, {share: 40, at: LAST - 60}, LAST * 1000),
  plain: U.usage(1000, entry, undefined, LAST * 1000),
  empty: U.usage(0, {total: 0, hours: []}, undefined, LAST * 1000),
  full: U.forecast(1000, recent, 40, NOW, NOW + 5 * DAY),
  late: U.forecast(1000, recent, 40, NOW, NOW + 2 * DAY),
  idle: U.forecast(1000, {total: 0, hours: []}, 40, NOW, NOW + 2 * DAY),
  over: U.forecast(1000, {total: 0, hours: []}, 100, NOW, NOW + 2 * DAY),
  now: NOW, day: DAY,
}));
"""


def epoch(text: str) -> float:
    return datetime.datetime.fromisoformat(text).timestamp()


def in_berlin(case: unittest.TestCase) -> None:
    zone = mock.patch.dict(os.environ, {"TZ": "Europe/Berlin"})
    zone.start()
    case.addCleanup(time.tzset)
    case.addCleanup(zone.stop)
    time.tzset()


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestValidation(unittest.TestCase):
    def test_a_full_account_passes_and_every_bad_field_is_refused(self):
        self.assertEqual(accounts.valid_account(copy.deepcopy(ACCOUNT)), ACCOUNT)
        self.assertEqual(accounts.valid_account({**ACCOUNT, "limit": None, "resubscribe": ""})["limit"], None)
        bad = {
            "email": "not-an-address", "renewal": {"day": 7, "time": "09:00"}, "reset": {"day": 1, "time": "24:00"},
            "resubscribe": "2026-02-30", "autorenew": "yes", "limit": -1, "provider": "", "note": "x" * 201,
        }
        for key, value in bad.items():
            with self.subTest(key=key), self.assertRaises(ToolError):
                accounts.valid_account({**ACCOUNT, key: value})
        with self.assertRaises(ToolError):
            accounts.valid_account({**ACCOUNT, "extra": 1})

    def test_usage_sums_per_account_with_recent_hours_and_unmapped_rows_under_the_empty_key(self):
        now = 1_000_000.0
        rows = [
            {"t": now - 7200, "agent": "A", "model": "m", "input": 10, "output": 5, "cache_read": 0, "cache_write": 0, "account": "one@example.org"},
            {"t": now - 3600, "agent": "B", "model": "m", "input": 1, "output": 1, "cache_read": 1, "cache_write": 1, "account": "two@example.org"},
            {"t": now - 3600, "agent": "A", "model": "m", "input": 20, "output": 0, "cache_read": 0, "cache_write": 0, "account": "one@example.org"},
            {"t": now - 30 * 86400, "agent": "A", "model": "m", "input": 100, "output": 0, "cache_read": 0, "cache_write": 0, "account": "one@example.org", "width": 86400},
            {"t": now - 3600, "agent": "C", "model": "m", "input": 7, "output": 0, "cache_read": 0, "cache_write": 0},
        ]
        self.assertEqual(accounts.usage(rows, now), {
            "one@example.org": {"total": 135, "hours": [(int(now - 7200), 15), (int(now - 3600), 20)]},
            "two@example.org": {"total": 4, "hours": [(int(now - 3600), 4)]},
            "": {"total": 7, "hours": [(int(now - 3600), 7)]},
        })


class TestResetMath(unittest.TestCase):
    def test_the_weekly_reset_keeps_its_wall_clock_across_the_october_dst_change(self):
        done = subprocess.run(["node", "-e", MOMENTS, str(MODULE)], capture_output=True, text=True, timeout=60, check=False, env={**os.environ, "TZ": "Europe/Berlin"})
        self.assertEqual(done.returncode, 0, done.stderr)
        found = json.loads(done.stdout)
        self.assertEqual(found["before"], "2026-10-18T01:30:00.000Z")
        self.assertEqual(found["after"], "2026-10-25T02:30:00.000Z")
        self.assertEqual(found["exact"], "2026-10-25T02:30:00.000Z")
        self.assertEqual(found["next"], "2026-11-01T02:30:00.000Z")
        self.assertEqual(found["used"], {"since": 500, "today": 300, "total": 900})
        self.assertEqual(found["unassigned"], {"since": None, "today": 300, "total": 900})


class TestUsageBar(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        done = subprocess.run(["node", "-e", COLOURS, str(BAR)], capture_output=True, text=True, timeout=60, check=False)
        if done.returncode != 0:
            raise AssertionError(done.stderr[-2000:])
        cls.found = json.loads(done.stdout)

    def test_the_fill_is_green_yellow_orange_and_red_at_the_stops_and_flows_between_them_without_steps(self):
        found = self.found
        self.assertEqual(found["stops"], found["named"])
        hues = {name: found["colors"][name][2] for name in ("green", "yellow", "orange", "red")}
        for name, (low, high) in {"green": (120, 160), "yellow": (85, 105), "orange": (45, 70), "red": (15, 35)}.items():
            with self.subTest(colour=name):
                self.assertTrue(low <= hues[name] <= high, hues[name])
        self.assertTrue(hues["orange"] < found["sixty"][2] < hues["yellow"], found["sixty"])
        steps = [before - after for before, after in zip(found["hues"], found["hues"][1:], strict=False)]
        self.assertTrue(all(0 <= step < 0.5 for step in steps), max(steps))
        self.assertEqual(found["ends"], [found["named"][0], found["named"][3]])

    def test_the_share_is_the_calibration_plus_the_tokens_since_it_and_a_calibration_older_than_the_reset_counts_nothing(self):
        found = self.found
        self.assertEqual(found["calibrated"], {"share": 45, "used": 450, "calibrated": True})
        self.assertEqual(found["stale"], {"share": 15, "used": 150, "calibrated": False})
        self.assertEqual(found["plain"], found["stale"])
        self.assertEqual(found["empty"], {"share": 0, "used": 0, "calibrated": False})

    def test_the_forecast_extends_the_rate_of_the_last_24_hours_to_the_reset_and_names_when_it_reaches_100(self):
        found = self.found
        now, day = found["now"], found["day"]
        self.assertAlmostEqual(found["full"]["share"], 160)
        self.assertAlmostEqual(found["full"]["full"], now + 2.5 * day, delta=1)
        self.assertAlmostEqual(found["late"]["share"], 88)
        self.assertIsNone(found["late"]["full"])
        self.assertEqual(found["idle"], {"share": 40, "full": None})
        self.assertEqual(found["over"], {"share": 100, "full": now})


class TestCalibration(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.file = Path(folder.name) / calibration.CALIBRATION

    def test_a_share_from_0_to_100_passes_and_anything_else_is_refused(self):
        for share in (0, 40.5, 100):
            with self.subTest(share=share):
                self.assertEqual(calibration.valid_share(json.dumps({"share": share}).encode()), float(share))
        for body in ({"share": -0.1}, {"share": 100.1}, {"share": True}, {"share": "40"}, {"share": None}, {}, {"share": 40, "at": 1}, [40]):
            with self.subTest(body=body), self.assertRaises(ToolError):
                calibration.valid_share(json.dumps(body).encode())
        with self.assertRaises(ToolError):
            calibration.valid_share(b"not json")

    def test_the_last_reset_keeps_its_wall_clock_across_the_october_dst_change_as_the_page_counts_it(self):
        in_berlin(self)
        reset = {"day": 0, "time": "03:30"}
        self.assertEqual(calibration.last_reset(reset, epoch("2026-10-25T01:00:00+00:00")), epoch("2026-10-18T01:30:00+00:00"))
        self.assertEqual(calibration.last_reset(reset, epoch("2026-10-25T04:00:00+00:00")), epoch("2026-10-25T02:30:00+00:00"))
        self.assertEqual(calibration.last_reset(reset, epoch("2026-10-25T02:30:00+00:00")), epoch("2026-10-25T02:30:00+00:00"))

    def test_a_calibration_holds_until_the_account_resets_or_goes_and_the_file_stays_0600(self):
        in_berlin(self)
        now = epoch("2026-11-25T10:00:00+00:00")
        soon = datetime.datetime.fromtimestamp(now + 3600)
        listed = [{"id": "a" * 16, "reset": {"day": soon.isoweekday() % 7, "time": soon.strftime("%H:%M")}}]
        store = calibration.Calibrations(self.file)
        self.assertEqual(store.put("a" * 16, 40.0, now + 0.7), {"share": 40.0, "at": int(now)})
        store.put("b" * 16, 10.0, now)
        self.assertEqual(stat.S_IMODE(self.file.stat().st_mode), 0o600)
        self.assertEqual(store.current(listed, now + 60), {"a" * 16: {"share": 40.0, "at": int(now)}})
        self.assertEqual(json.loads(self.file.read_text(encoding="utf-8")), {"a" * 16: {"share": 40.0, "at": int(now)}})
        self.assertEqual(calibration.Calibrations(self.file).current(listed, now + 60), {"a" * 16: {"share": 40.0, "at": int(now)}})
        self.assertEqual(store.current(listed, now + 7200), {})
        self.assertEqual(json.loads(self.file.read_text(encoding="utf-8")), {})
        self.assertEqual(stat.S_IMODE(self.file.stat().st_mode), 0o600)

    def test_malformed_stored_entries_are_ignored_on_load(self):
        self.file.write_text(json.dumps({"a" * 16: {"share": 140, "at": 1}, "b" * 16: {"share": 5, "at": "x"}, "c" * 16: {"share": 5, "at": 1, "x": 1}, "d" * 16: {"share": 5, "at": 9}}), encoding="utf-8")
        self.assertEqual(calibration.Calibrations(self.file).items, {"d" * 16: {"share": 5, "at": 9}})


class TestHook(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.home, self.council = self.root / "home", self.root / "council"
        self.home.mkdir()
        profile = {"oauthAccount": {"emailAddress": "one@example.org", "accountUuid": "u-1", "organizationName": "Org"}, "projects": {"/x": {"history": ["secret"]}}}
        (self.home / ".claude.json").write_text(json.dumps(profile), encoding="utf-8")

    def hook(self, payload: dict) -> subprocess.CompletedProcess:
        env = {"PATH": os.environ["PATH"], "HOME": str(self.home), "AGENTS_COUNCIL_ROOT": str(self.council)}
        return subprocess.run([sys.executable, str(HOOK), "hook"], input=json.dumps(payload), capture_output=True, text=True, timeout=60, check=False, env=env)

    def test_the_hook_writes_one_line_of_session_and_email_only_mode_0600_and_no_repeat(self):
        for payload in ({"session_id": "s1"}, {"session_id": "s1"}, {"session_id": "s2", "agent_id": "sub"}, {}):
            self.assertEqual(self.hook(payload).returncode, 0)
        path = self.council / accounts.SESSION_ACCOUNTS
        self.assertEqual(path.read_text(encoding="utf-8").splitlines(), ['{"session": "s1", "email": "one@example.org"}'])
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(accounts.mapping(path), {"s1": "one@example.org"})
        self.assertEqual(accounts.active(path), "one@example.org")

    def test_a_profile_without_the_field_writes_nothing(self):
        (self.home / ".claude.json").write_text(json.dumps({"oauthAccount": {}}), encoding="utf-8")
        self.assertEqual(self.hook({"session_id": "s1"}).returncode, 0)
        self.assertFalse((self.council / accounts.SESSION_ACCOUNTS).exists())


class TestSampler(unittest.TestCase):
    def test_token_rows_carry_the_account_of_their_session_and_merge_per_account(self):
        sampler = load(SAMPLER, "kvb_resources_sampler")
        sums: dict = {}
        sampler.add(sums, (3600, "A", "m", 3600, "one@example.org"), (1, 2, 0, 0))
        sampler.add(sums, (3600, "A", "m", 3600, ""), (5, 0, 0, 0))
        rows = sampler.token_rows(sums)
        self.assertEqual([(row["input"], row.get("account")) for row in rows], [(5, None), (1, "one@example.org")])
        merged = sampler.compact(rows + rows, 7200)
        self.assertEqual([(row["input"], row.get("account")) for row in merged], [(10, None), (2, "one@example.org")])
        with tempfile.TemporaryDirectory() as folder:
            council = Path(folder)
            (council / sampler.SESSION_ACCOUNTS).write_text('{"session": "s1", "email": "a@example.org"}\n{"session": "s1", "email": "b@example.org"}\nnot json\n', encoding="utf-8")
            self.assertEqual(sampler.session_accounts(council), {"s1": "b@example.org"})

    def test_an_agent_written_mapping_that_is_a_link_a_fifo_too_big_or_too_long_maps_nothing(self):
        sampler = load(SAMPLER, "kvb_resources_sampler")
        line = '{"session": "s1", "email": "a@example.org"}\n'
        with tempfile.TemporaryDirectory() as folder:
            council = Path(folder)
            path = council / sampler.SESSION_ACCOUNTS
            target = council / "target.jsonl"
            target.write_text(line, encoding="utf-8")
            path.symlink_to(target)
            self.assertEqual(sampler.session_accounts(council), {})
            path.unlink()
            os.mkfifo(path)
            self.assertEqual(sampler.session_accounts(council), {})
            path.unlink()
            path.write_text(line + " " * sampler.JSON_BYTES, encoding="utf-8")
            self.assertEqual(sampler.session_accounts(council), {})
            path.write_text(line + json.dumps({"session": "s2", "email": "x" * (sampler.EMAIL_CHARS + 1)}) + "\n", encoding="utf-8")
            self.assertEqual(sampler.session_accounts(council), {"s1": "a@example.org"})


class TestView(unittest.TestCase):
    def test_the_panels_list_replaces_the_combined_flag_of_older_documents(self):
        for combined, panels in ((True, ["combined", "accounts"]), (False, ["hardware", "tokens", "accounts"])):
            with self.subTest(combined=combined):
                old = copy.deepcopy(VIEW)
                old["resources"] = {key: value for key, value in old["resources"].items() if key != "panels"} | {"combined": combined}
                self.assertEqual(valid_view(upgraded(old))["resources"]["panels"], panels)


class TestAccountsApi(HubCase):
    def post(self, path: str, payload: object) -> tuple[int, bytes]:
        status, _, body = self.post_json(path, payload, self.guard(self.host))
        return status, body

    def test_add_edit_and_remove_keep_the_file_0600_outside_the_repo_and_refuse_bad_input(self):
        status, body = self.post("/api/accounts", {"id": "", "account": ACCOUNT})
        self.assertEqual(status, 200, body)
        added = json.loads(body)
        file = self.state / accounts.ACCOUNTS
        self.assertEqual(stat.S_IMODE(file.stat().st_mode), 0o600)
        status, body = self.post("/api/accounts", {"id": added["id"], "account": {**ACCOUNT, "limit": None}})
        self.assertEqual((status, json.loads(body)["limit"]), (200, None))
        for payload in ({"id": "", "account": {**ACCOUNT, "email": "x"}}, {"id": "", "account": {**ACCOUNT, "limit": -5}}, {"id": "zz", "account": ACCOUNT}, {"account": ACCOUNT}):
            with self.subTest(payload=str(payload)[:60]):
                self.assertEqual(self.post("/api/accounts", payload)[0], 400)
        self.assertEqual(self.post("/api/accounts", {"id": "0" * 16, "account": ACCOUNT})[0], 404)
        status, _, body = self.get("/api/accounts")
        self.assertEqual(status, 200, body)
        view = json.loads(body)
        self.assertEqual(([row["email"] for row in view["accounts"]], view["active"], view["usage"]), (["one@example.org"], None, {}))
        self.assertEqual(self.post(f"/api/accounts/{added['id']}/delete", {})[0], 200)
        self.assertEqual(self.post(f"/api/accounts/{added['id']}/delete", {})[0], 404)
        view_file = self.state / "view.json"
        self.assertNotIn("example.org", view_file.read_text(encoding="utf-8") if view_file.exists() else "")
        self.assertFalse(str(file).startswith(str(REPO)))

    def test_the_view_maps_usage_and_the_active_account_from_the_hook_and_the_sampler_rows(self):
        self.post("/api/accounts", {"id": "", "account": ACCOUNT})
        self.council.mkdir(parents=True, exist_ok=True)
        (self.council / accounts.SESSION_ACCOUNTS).write_text('{"session": "s1", "email": "one@example.org"}\n', encoding="utf-8")
        folder = self.kept / "resources"
        folder.mkdir(parents=True, exist_ok=True)
        hour = int(time.time() // 3600 * 3600)
        rows = [{"t": hour, "agent": "A", "model": "m", "input": 40, "output": 2, "cache_read": 0, "cache_write": 0, "account": "one@example.org"}, {"t": hour, "agent": "B", "model": "m", "input": 3, "output": 0, "cache_read": 0, "cache_write": 0}]
        (folder / "tokens.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        status, _, body = self.get("/api/accounts")
        self.assertEqual(status, 200, body)
        view = json.loads(body)
        self.assertEqual(view["active"], "one@example.org")
        self.assertEqual(view["usage"], {"one@example.org": {"total": 42, "hours": [[hour, 42]]}, "": {"total": 3, "hours": [[hour, 3]]}})

    def test_the_calibrate_route_stores_share_and_time_0600_refuses_bad_input_and_guards_like_the_other_account_routes(self):
        added = json.loads(self.post("/api/accounts", {"id": "", "account": ACCOUNT})[1])
        route = f"/api/accounts/{added['id']}/calibrate"
        before = int(time.time())
        status, body = self.post(route, {"share": 40})
        self.assertEqual(status, 200, body)
        stored = json.loads(body)
        self.assertEqual(stored["share"], 40.0)
        self.assertTrue(before <= stored["at"] <= time.time())
        file = self.state / calibration.CALIBRATION
        self.assertEqual(stat.S_IMODE(file.stat().st_mode), 0o600)
        self.assertEqual(json.loads(self.get("/api/accounts")[2])["calibrations"], {added["id"]: stored})
        for payload in ({"share": 100.5}, {"share": -1}, {"share": "40"}, {}, {"share": 40, "extra": 1}):
            with self.subTest(payload=payload):
                self.assertEqual(self.post(route, payload)[0], 400)
        self.assertEqual(self.post(f"/api/accounts/{'0' * 16}/calibrate", {"share": 40})[0], 404)
        self.assertEqual(self.post("/api/accounts/zz/calibrate", {"share": 40})[0], 404)
        self.assertEqual(self.post_json(route, {"share": 50}, {"Host": self.host, "X-Kvb-Orchestrator": "1"})[0], 403)
        self.assertEqual(self.post_json(route, {"share": 50}, {**self.guard(self.host), "Origin": "http://evil.example"})[0], 403)
        self.assertEqual(self.get(route)[0], 405)
        self.assertEqual(json.loads(self.get("/api/accounts")[2])["calibrations"], {added["id"]: stored})

    def test_the_payload_drops_a_calibration_older_than_the_last_reset_and_one_of_a_removed_account(self):
        added = json.loads(self.post("/api/accounts", {"id": "", "account": ACCOUNT})[1])
        other = json.loads(self.post("/api/accounts", {"id": "", "account": {**ACCOUNT, "email": "two@example.org"}})[1])
        hub = self.httpd.hub.accounts
        hub.calibrations.put(added["id"], 30.0, time.time() - 8 * 86400)
        self.assertEqual(self.post(f"/api/accounts/{other['id']}/calibrate", {"share": 12.5})[0], 200)
        calibrations = json.loads(self.get("/api/accounts")[2])["calibrations"]
        self.assertEqual(list(calibrations), [other["id"]])
        self.assertEqual(list(json.loads((self.state / calibration.CALIBRATION).read_text(encoding="utf-8"))), [other["id"]])
        self.assertEqual(self.post(f"/api/accounts/{other['id']}/delete", {})[0], 200)
        self.assertEqual(json.loads(self.get("/api/accounts")[2])["calibrations"], {})

    def test_the_forecast_toggle_is_a_hub_setting_that_needs_no_passkey_and_survives_a_page_that_omits_it(self):
        guard = self.guard(self.host)
        status, _, body = self.post_json("/api/settings", {**settings.SETTINGS, "forecast": True}, guard)
        self.assertEqual(status, 200, body)
        self.assertTrue(json.loads(body)["settings"]["forecast"])
        older = {key: value for key, value in settings.SETTINGS.items() if key != "forecast"}
        status, _, body = self.post_json("/api/settings", older, guard)
        self.assertEqual(status, 200, body)
        self.assertTrue(json.loads(body)["settings"]["forecast"])
        self.assertEqual(self.post_json("/api/settings", {**settings.SETTINGS, "forecast": "yes"}, guard)[0], 400)
        self.assertTrue(json.loads((self.state / "settings.json").read_text(encoding="utf-8"))["forecast"])


if __name__ == "__main__":
    unittest.main()
