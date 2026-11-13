"""Exercise backfill.py of kvb-check-score over a fixture repository: rows, idempotence, determinism, labels, clones."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from score_fixture import (
    BACKFILL,
    ESTIMATED_BLOCK,
    HANG,
    NEW_BLOCK,
    OLD_BLOCK,
    REPO_ROOT,
    Fixture,
    backfill,
)

JOURNAL_NAME = "scores.jsonl"
LABELS = REPO_ROOT / "skills" / "kvb-check-score" / "labels.json"
UNKNOWN = ["backfill: unknown label Coverage, skipped", "backfill: unknown label Heat, skipped"]


class TestBackfill(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.fixture = Fixture(Path(cls.tmp.name) / "fixture")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.scratch = Path(scratch.name)

    def council(self, name: str) -> Path:
        return self.scratch / name

    def rows(self, council: Path) -> list[dict]:
        return [json.loads(line) for line in (council / JOURNAL_NAME).read_text(encoding="utf-8").splitlines()]

    def test_three_commits_with_blocks_give_three_rows_then_none(self):
        council = self.council("one")
        first = backfill(council, "--repo", str(self.fixture.a))
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stdout, f"{self.fixture.a.resolve()}: 3 blocks, 3 rows added\n")
        written = (council / JOURNAL_NAME).read_bytes()
        second = backfill(council, "--repo", str(self.fixture.a))
        self.assertEqual((second.returncode, second.stdout), (0, f"{self.fixture.a.resolve()}: 3 blocks, 0 rows added\n"))
        self.assertEqual((council / JOURNAL_NAME).read_bytes(), written)

    def test_two_runs_from_an_empty_journal_give_byte_identical_journals(self):
        one, two = self.council("one"), self.council("two")
        self.assertEqual(backfill(one, "--repo", str(self.fixture.a)).returncode, 0)
        self.assertEqual(backfill(two, "--repo", str(self.fixture.a)).returncode, 0)
        self.assertEqual((one / JOURNAL_NAME).read_bytes(), (two / JOURNAL_NAME).read_bytes())

    def test_old_new_and_estimated_blocks_parse_and_a_malformed_one_is_skipped(self):
        council = self.council("one")
        backfill(council, "--repo", str(self.fixture.a))
        rows = self.rows(council)
        fixture = self.fixture
        self.assertEqual([row["sha"] for row in rows], [fixture.old, fixture.new, fixture.estimated])
        self.assertEqual([row["branch"] for row in rows], ["main", "feature/two", "main"])
        self.assertEqual([row["time"] for row in rows], [fixture.time_of(sha) for sha in (fixture.old, fixture.new, fixture.estimated)])
        self.assertEqual([row["values"] for row in rows], [
            {"fix": 95, "break": 2, "tokens": 97, "velocity": None, "security": 100, "score": 96},
            {"fix": 92, "break": 3, "tokens": 110, "velocity": 90, "security": 100, "score": 81},
            {"fix": 90, "break": 5, "tokens": None, "velocity": 130, "security": 80, "score": 52},
        ])
        self.assertEqual([row["digest"] for row in rows], [hashlib.sha256(block.encode("utf-8")).hexdigest() for block in (OLD_BLOCK, NEW_BLOCK, ESTIMATED_BLOCK)])
        self.assertEqual({(row["remote"], row["path"]) for row in rows}, {(str(fixture.upstream), str(fixture.a.resolve()))})

    def test_an_unknown_label_is_reported_once_per_label_and_skipped(self):
        done = backfill(self.council("one"), "--repo", str(self.fixture.a))
        self.assertEqual(done.stderr.splitlines(), UNKNOWN)
        for row in self.rows(self.council("one")):
            self.assertEqual(list(row["values"]), ["fix", "break", "tokens", "velocity", "security", "score"])

    def test_old_labels_map_through_the_label_file(self):
        labels = json.loads(LABELS.read_text(encoding="utf-8"))
        labels["metrics"]["tokens"]["former"] = []
        file = self.scratch / "labels.json"
        file.write_text(json.dumps(labels, ensure_ascii=False), encoding="utf-8")
        done = backfill(self.council("one"), "--repo", str(self.fixture.a), "--labels", str(file))
        self.assertIn("backfill: unknown label Cost, skipped", done.stderr.splitlines())
        self.assertIsNone(self.rows(self.council("one"))[0]["values"]["tokens"])

    def test_a_clone_at_another_path_yields_the_same_keys(self):
        one, two = self.council("one"), self.council("two")
        backfill(one, "--repo", str(self.fixture.a))
        backfill(two, "--repo", str(self.fixture.b))
        keys = [[(row["remote"], row["sha"]) for row in self.rows(council)] for council in (one, two)]
        self.assertEqual(keys[0], keys[1])
        self.assertEqual([row["branch"] for row in self.rows(two)], ["main", "feature/two", "main"])
        self.assertEqual({row["path"] for row in self.rows(two)}, {str(self.fixture.b.resolve())})
        again = backfill(one, "--repo", str(self.fixture.b))
        self.assertEqual(again.stdout, f"{self.fixture.b.resolve()}: 3 blocks, 0 rows added\n")

    def test_since_reads_only_newer_commits_and_a_bad_repository_writes_nothing(self):
        council = self.council("one")
        done = backfill(council, "--repo", str(self.fixture.a), "--since", self.fixture.old)
        self.assertEqual(done.stdout, f"{self.fixture.a.resolve()}: 2 blocks, 2 rows added\n")
        empty = self.council("two")
        failed = backfill(empty, "--repo", str(self.fixture.a), str(self.scratch))
        self.assertEqual(failed.returncode, 2)
        self.assertFalse((empty / JOURNAL_NAME).exists())

    def test_a_fifo_or_a_linked_council_root_exits_2_with_one_stderr_line(self):
        fifo = self.council("fifo")
        fifo.mkdir()
        os.mkfifo(fifo / JOURNAL_NAME)
        real = self.scratch / "real"
        real.mkdir()
        linked = self.council("linked")
        linked.symlink_to(real)
        for council in (fifo, linked):
            with self.subTest(council=council.name):
                done = backfill(council, "--repo", str(self.fixture.a))
                self.assertEqual(done.returncode, 2)
                self.assertEqual(len(done.stderr.splitlines()), 1, done.stderr)
                self.assertTrue(done.stderr.startswith(f"backfill: journal {council / JOURNAL_NAME}: "), done.stderr)
        self.assertEqual(list(real.iterdir()), [])

    def test_a_missing_nofollow_helper_is_named_in_the_one_stderr_line(self):
        scripts = self.scratch.resolve() / "skills" / "kvb-check-score" / "scripts"
        scripts.mkdir(parents=True)
        for name in ("backfill.py", "journal.py"):
            shutil.copy(BACKFILL.parent / name, scripts / name)
        shutil.copy(LABELS, scripts.parent / "labels.json")
        helper = scripts.parents[1] / "kvb-org-organize" / "scripts" / "nofollow.py"
        council = self.council("missing")
        env = {"PATH": os.environ["PATH"], "AGENTS_COUNCIL_ROOT": str(council)}
        done = subprocess.run([sys.executable, "-B", str(scripts / "backfill.py"), "--repo", str(self.fixture.a)], env=env, capture_output=True, text=True, check=False, timeout=HANG)
        self.assertEqual((done.returncode, done.stdout, done.stderr), (2, "", f"backfill: journal {council / JOURNAL_NAME}: helper {helper} unusable (FileNotFoundError): install or update kvb-org-organize\n"))
        self.assertFalse(council.exists())

    @unittest.skipIf(os.geteuid() == 0, "root writes into a mode 0500 directory")
    def test_a_failed_append_prints_no_summary(self):
        council = self.council("readonly")
        council.mkdir(mode=0o500)
        self.addCleanup(council.chmod, 0o700)
        done = backfill(council, "--repo", str(self.fixture.a))
        self.assertEqual((done.returncode, done.stdout), (2, ""))
        self.assertEqual(len(done.stderr.splitlines()), 1, done.stderr)
        self.assertTrue(done.stderr.startswith(f"backfill: journal {council / JOURNAL_NAME}: "), done.stderr)
        self.assertEqual(list(council.iterdir()), [])

    def test_a_repeated_repo_flag_reads_every_repository(self):
        done = backfill(self.council("one"), "--repo", str(self.fixture.a), "--repo", str(self.fixture.b))
        self.assertEqual(done.stdout.splitlines(), [f"{self.fixture.a.resolve()}: 3 blocks, 3 rows added", f"{self.fixture.b.resolve()}: 3 blocks, 0 rows added"])


if __name__ == "__main__":
    unittest.main()
