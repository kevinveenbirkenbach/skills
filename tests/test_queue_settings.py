from __future__ import annotations

import json
import unittest

import test_queue as fixtures


class TestQueueSettings(unittest.TestCase):
    setUp = fixtures.TestQueueCommands.setUp
    write_config = fixtures.TestQueueCommands.write_config
    write_history = fixtures.TestQueueCommands.write_history
    run_queue = fixtures.TestQueueCommands.run_queue

    def learned(self) -> dict:
        done = self.run_queue("learned", "--json")
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def test_learned_json_lists_kinds_signatures_settings_and_the_last_20_rows_and_writes_nothing(self):
        rows = [fixtures.history_row(n, end=fixtures.NOW - n, signature="make test" if n % 2 else "make deploy", kind="test" if n % 2 else "deploy") for n in range(1, 31)]
        self.write_history(self.history_file, rows)
        self.cfg["ram_cap_percent"] = {"test": 20}
        self.write_config()
        before = sorted(path.name for path in self.root.iterdir())
        shown = self.learned()
        self.assertEqual(sorted(shown), ["budget_percent", "history", "kinds", "load_limits", "ram_cap_percent", "signatures", "slot_limits"])
        self.assertEqual((shown["budget_percent"], shown["ram_cap_percent"], shown["slot_limits"]), (self.cfg["budget_percent"], {"test": 20}, self.cfg["slot_limits"]))
        self.assertEqual(shown["load_limits"], self.cfg["load_limits"])
        self.assertEqual(sorted(shown["kinds"]), ["deploy", "test"])
        self.assertEqual({key: shown["kinds"]["test"][key] for key in ("runs", "ram_cap", "slot_limit", "slot_source")}, {"runs": 15, "ram_cap": 20, "slot_limit": 1, "slot_source": "capped by config"})
        self.assertEqual(sorted((row["kind"], row["signature"], row["runs"]) for row in shown["signatures"]), [("deploy", "make deploy", 15), ("test", "make test", 15)])
        self.assertEqual([row["id"] for row in shown["history"]], [f"r{n}" for n in range(20, 0, -1)])
        self.assertEqual(sorted(path.name for path in self.root.iterdir()), before)

    def test_learned_json_lists_a_configured_kind_without_rows_with_runs_0(self):
        shown = self.learned()
        self.assertEqual(shown["history"], [])
        self.assertEqual({kind: (stats["runs"], stats["ram_share"], stats["slot_source"]) for kind, stats in shown["kinds"].items()}, {"deploy": (0, None, "seed"), "test": (0, None, "seed")})

    def test_a_good_value_changes_only_its_key_and_keeps_unknown_keys_and_the_mode(self):
        self.cfg["operator_note"] = {"kept": [1, 2]}
        self.write_config()
        self.config.chmod(0o640)
        for key, value, path, expected in (
            ("budget_percent.cpu", "180", ("budget_percent", "cpu"), 180),
            ("ram_cap_percent.test", "35.5", ("ram_cap_percent", "test"), 35.5),
            ("slot_limits.deploy", "3", ("slot_limits", "deploy"), 3),
            ("load_limits.cpu_percent", "95", ("load_limits", "cpu_percent"), 95),
            ("load_limits.band_low", "70", ("load_limits", "band_low"), 70),
        ):
            with self.subTest(key=key):
                before = json.loads(self.config.read_text(encoding="utf-8"))
                done = self.run_queue("config", "set", key, value)
                self.assertEqual(done.returncode, 0, done.stderr)
                after = json.loads(self.config.read_text(encoding="utf-8"))
                section, name = path
                self.assertEqual(after[section][name], expected)
                after[section] = {k: v for k, v in after[section].items() if k != name}
                before[section] = {k: v for k, v in before.get(section, {}).items() if k != name}
                self.assertEqual(after, before)
                self.assertEqual(self.config.stat().st_mode & 0o777, 0o640)

    def test_a_bad_value_or_key_exits_2_and_leaves_the_file_byte_identical(self):
        before = self.config.read_bytes()
        for key, value in (
            ("budget_percent.cpu", "0"), ("budget_percent.cpu", "-5"), ("budget_percent.cpu", "1e3"), ("budget_percent.cpu", "NaN"),
            ("ram_cap_percent.test", "120"), ("ram_cap_percent.ghost", "20"), ("slot_limits.test", "1.5"), ("load_limits.mem_percent", "101"),
            ("cpu_cap_percent.test", "50"), ("budget_percent", "50"), ("thresholds_gb.stop", "1"), ("load_limits.kinds", "1"),
            ("load_limits.band_high", "101"), ("load_limits.band_low", "100"), ("load_limits.band_low", "0"), ("load_limits.band_high", "98"),
        ):
            with self.subTest(key=key, value=value):
                done = self.run_queue("config", "set", key, value)
                self.assertEqual(done.returncode, 2, done.stderr)
                self.assertEqual(self.config.read_bytes(), before)

    def test_a_linked_or_broken_config_is_refused_without_a_write(self):
        target = self.base / "target.json"
        target.write_text(self.config.read_text(encoding="utf-8"), encoding="utf-8")
        self.config.unlink()
        self.config.symlink_to(target)
        self.assertEqual(self.run_queue("config", "set", "budget_percent.cpu", "90").returncode, 2)
        self.assertTrue(self.config.is_symlink())
        self.config.unlink()
        self.config.write_text("{not json", encoding="utf-8")
        self.assertEqual(self.run_queue("config", "set", "budget_percent.cpu", "90").returncode, 2)
        self.assertEqual(self.config.read_text(encoding="utf-8"), "{not json")


if __name__ == "__main__":
    unittest.main()
