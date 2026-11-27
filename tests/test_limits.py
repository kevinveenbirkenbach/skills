"""Exercise the council limits file of requirement 083: its checks, the last valid copy, and queue and watch reading it."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import test_queue as fixtures

LIMITS_PY = fixtures.REPO_ROOT / "skills" / "kvb-org-organize" / "scripts" / "limits.py"
WATCH = fixtures.REPO_ROOT / "skills" / "kvb-org-organize" / "scripts" / "watch.py"
SHIPPED = fixtures.REPO_ROOT / "skills" / "kvb-org-organize" / "config.default.json"
LIMITS = {
    "cpu": {"lower": 60, "upper": 80, "stop": 95, "mayday": 99},
    "ram": {"lower": 65, "upper": 70, "stop": 80, "mayday": 95},
    "swap": {"lower": 20, "upper": 50, "stop": 75, "mayday": 90},
    "disk": {"lower": 50, "upper": 80, "stop": 90, "mayday": 95},
    "psi": {"lower": 2, "upper": 10, "stop": 30, "mayday": 60},
}
CALM = {"available": 50.0, "swap_free": 80.0, "psi_some": 1.0, "psi_full": 0.0, "swap_out_mb_min": None, "container_swap_gb": 0.0}


def broken(metric: str, level: str, value: object) -> dict:
    data = copy.deepcopy(LIMITS)
    data[metric][level] = value
    return data


class Council(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.file = self.root / "limits.json"
        self.last = self.root / "limits.last.json"

    def write(self, data: object) -> None:
        self.file.write_text(json.dumps(data), encoding="utf-8")


class TestLimitsFile(Council):
    @classmethod
    def setUpClass(cls):
        cls.limits = fixtures._load(LIMITS_PY)

    def test_every_metric_needs_its_four_levels_as_percents_in_strict_order(self):
        self.assertIsNone(self.limits.problem(LIMITS))
        order = "breaks lower < upper < stop < mayday"
        cases = {
            "ram upper at its lower": (broken("ram", "upper", 65), f"ram {order}"),
            "psi stop above mayday": (broken("psi", "stop", 61), f"psi {order}"),
            "disk above 100": (broken("disk", "mayday", 101), "disk holds a value that is no percent from 0 to 100"),
            "cpu below 0": (broken("cpu", "lower", -1), "cpu holds a value that is no percent from 0 to 100"),
            "swap as text": (broken("swap", "upper", "50"), "swap holds a value that is no percent from 0 to 100"),
            "swap as bool": (broken("swap", "lower", True), "swap holds a value that is no percent from 0 to 100"),
            "cpu nan": (broken("cpu", "upper", float("nan")), "cpu holds a value that is no percent from 0 to 100"),
        }
        for name, (data, why) in cases.items():
            with self.subTest(name):
                self.assertEqual(self.limits.problem(data), why)
        shape = "the limits are no object of exactly cpu, ram, swap, disk, psi"
        self.assertEqual(self.limits.problem({k: v for k, v in LIMITS.items() if k != "psi"}), shape)
        self.assertEqual(self.limits.problem({**LIMITS, "gpu": LIMITS["cpu"]}), shape)
        self.assertEqual(self.limits.problem([LIMITS]), shape)
        self.assertEqual(self.limits.problem({**LIMITS, "ram": {**LIMITS["ram"], "uper": 70}}), "ram holds not exactly lower, upper, stop, mayday")

    def test_without_the_file_the_config_applies_and_a_valid_one_is_kept_as_the_last_copy(self):
        self.assertEqual(self.limits.read(self.root), (None, None))
        self.assertFalse(self.last.exists())
        self.write(LIMITS)
        self.assertEqual(self.limits.read(self.root), (LIMITS, None))
        self.assertEqual(json.loads(self.last.read_text(encoding="utf-8")), LIMITS)
        self.file.unlink()
        self.assertEqual(self.limits.read(self.root), (None, None))
        self.assertTrue(self.last.exists())

    def test_a_refused_file_keeps_the_previous_valid_limits_in_force(self):
        self.write(LIMITS)
        self.limits.read(self.root)
        self.write(broken("ram", "lower", 75))
        held, why = self.limits.read(self.root)
        self.assertEqual(held, LIMITS)
        self.assertEqual(why, f"{self.file} is refused: ram breaks lower < upper < stop < mayday; "
                              f"the last valid copy {self.last} stays in force")
        self.assertEqual(json.loads(self.last.read_text(encoding="utf-8")), LIMITS)
        self.file.write_text("{half", encoding="utf-8")
        held, why = self.limits.read(self.root)
        self.assertEqual(held, LIMITS)
        self.assertTrue(why.startswith(f"{self.file} is unreadable ("), why)
        tighter = broken("ram", "upper", 68)
        self.write(tighter)
        self.assertEqual(self.limits.read(self.root), (tighter, None))
        self.assertEqual(json.loads(self.last.read_text(encoding="utf-8")), tighter)

    def test_a_refused_file_without_a_valid_copy_leaves_the_config_in_force(self):
        self.write(broken("cpu", "stop", 100.5))
        held, why = self.limits.read(self.root)
        self.assertIsNone(held)
        self.assertTrue(why.endswith("; no valid copy is kept, so the config applies"), why)
        self.last.write_text(json.dumps(broken("cpu", "stop", 50)), encoding="utf-8")
        self.assertIsNone(self.limits.read(self.root)[0])

    def test_applied_maps_the_levels_onto_the_config_keys_their_readers_use(self):
        cfg = json.loads(SHIPPED.read_text(encoding="utf-8"))
        self.assertIs(self.limits.applied(cfg, None, 1000.0), cfg)
        out = self.limits.applied(cfg, LIMITS, 1000.0)
        self.assertEqual(out[self.limits.KEY], LIMITS)
        self.assertEqual((out["load_limits"]["cpu_percent"], out["load_limits"]["mem_percent"]), (95, 80))
        self.assertEqual(out["load_limits"]["sample_seconds"], cfg["load_limits"]["sample_seconds"])
        self.assertEqual(out["memory_limits"]["warn"], {**cfg["memory_limits"]["warn"], "available": 30, "swap_free": 50, "psi_some": 10})
        self.assertEqual(out["memory_limits"]["stop"], {**cfg["memory_limits"]["stop"], "available": 20, "swap_free": 25, "psi_some": 30})
        self.assertEqual(out["thresholds_gb"], {"warn": 200.0, "stop": 100.0, "critical": 50.0})
        self.assertEqual(self.limits.applied(cfg, LIMITS, None)["thresholds_gb"], cfg["thresholds_gb"])
        self.assertEqual(self.limits.applied({"memory_limits": "x"}, LIMITS, None), {"memory_limits": "x", self.limits.KEY: LIMITS})


class TestReaders(Council):
    def setUp(self):
        super().setUp()
        self.watch = fixtures._load(WATCH)
        self.watch.ROOT = self.root
        self.cfg = {**json.loads(SHIPPED.read_text(encoding="utf-8")), "disk": str(self.root)}

    def test_watch_reads_its_memory_stages_and_disk_stages_from_the_file(self):
        self.assertEqual(self.watch.memory_stage(CALM | {"available": 25.0}, self.cfg), "ok")
        self.assertEqual(self.watch.memory_stage(CALM | {"psi_some": 35.0}, self.cfg), "warn")
        self.write(LIMITS)
        cfg, why = self.watch.with_limits(self.cfg)
        self.assertIsNone(why)
        self.assertEqual(self.watch.memory_stage(CALM | {"available": 25.0}, cfg), "warn")
        self.assertEqual(self.watch.memory_stage(CALM | {"available": 15.0}, cfg), "stop")
        self.assertEqual(self.watch.memory_stage(CALM | {"swap_free": 45.0}, cfg), "warn")
        self.assertEqual(self.watch.memory_stage(CALM | {"psi_some": 35.0}, cfg), "stop")
        total = self.watch.disk(self.cfg)[1]
        self.assertEqual(cfg["thresholds_gb"]["stop"], round(total * 10 / 100, 1))
        free = cfg["thresholds_gb"]["warn"] - 0.5
        self.assertEqual(self.watch.stage_for(free, [], cfg, fixtures.NOW), "warn")

    def test_watch_names_a_refused_file_and_keeps_the_last_valid_limits(self):
        self.write(LIMITS)
        self.watch.with_limits(self.cfg)
        self.write(broken("swap", "stop", 40))
        cfg, why = self.watch.with_limits(self.cfg)
        self.assertIn("swap breaks lower < upper < stop < mayday", why)
        self.assertEqual(cfg["memory_limits"]["stop"]["available"], 20)

    def test_the_settled_config_of_every_command_comes_under_the_file(self):
        config = self.root / "config.json"
        config.write_text(json.dumps(self.cfg), encoding="utf-8")
        self.watch.CONFIG = config
        self.assertNotIn("limits", self.watch.settled_config()[0])
        self.write(LIMITS)
        cfg, warning = self.watch.settled_config()
        self.assertIsNone(warning)
        self.assertEqual((cfg["limits"], cfg["load_limits"]["mem_percent"]), (LIMITS, 80))

    def test_the_queue_takes_its_band_and_live_guard_from_the_file_and_the_list_header_names_them(self):
        queue = fixtures._load(fixtures.QUEUE)
        config = self.root / "config.json"
        config.write_text(json.dumps(self.cfg), encoding="utf-8")
        aim = {"cpu": 78.0, "ram": 68.5}
        with mock.patch.object(queue.watch, "ROOT", self.root), mock.patch.object(queue.watch, "CONFIG", config):
            plain = queue.fresh({})
            self.assertEqual(queue.band(plain), {"low": {"ram": 70, "cpu": 70}, "high": {"ram": 90, "cpu": 90}})
            self.assertEqual(queue.targets(plain, aim), "target CPU 78.0 % RAM 68.5 % in band CPU 70-90 % RAM 70-90 %, limits config")
            self.write(LIMITS)
            cfg = queue.fresh({})
            self.assertEqual(queue.band(cfg), {"low": {"ram": 65, "cpu": 60}, "high": {"ram": 70, "cpu": 80}})
            self.assertEqual(queue.load_reason(cfg["load_limits"], 10.0, 75.0, 5.0),
                             "RAM 75 % used + 5 % still to come reach the limit 80 %")
            self.assertEqual(queue.psi_calm(cfg), 2)
            self.assertEqual(queue.targets(cfg, aim),
                             f"target CPU 78.0 % RAM 68.5 % in band CPU 60-80 % RAM 65-70 %, limits {self.file}")
            self.write(broken("cpu", "lower", 85))
            header = queue.targets(queue.fresh({}), aim)
            self.assertTrue(header.startswith(f"target CPU 78.0 % RAM 68.5 % in band CPU 60-80 % RAM 65-70 %, limits {self.last}; "
                                              f"{self.file} is refused: cpu breaks"), header)


if __name__ == "__main__":
    unittest.main()
