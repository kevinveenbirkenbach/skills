"""Exercise kvb-git-orphans-find: merged, stale and active branches and worktrees, read only."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ORPHANS = REPO_ROOT / "skills" / "kvb-git-orphans-find" / "scripts" / "orphans.py"
DAY = 86400
OLD = time.time() - 30 * DAY
AGES = {"stale": OLD, "claimed": OLD, "ended": OLD - 5 * DAY, "busy": OLD, "recent": OLD}
BIG = 50_000
IDENTITY = {
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.org",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.org",
    "GIT_CONFIG_NOSYSTEM": "1",
}
TABLE = {
    "merged": ("merged-clean", "kvb-git-branch-gc"),
    "squashed": ("merged-clean", "kvb-git-branch-gc"),
    "mdirty": ("merged-dirty", "ask"),
    "ended": ("stale-open", "ask"),
    "stale": ("stale-open", "ask"),
}
ACTIVE = ("archive/old", "busy", "claimed", "main", "recent")
COUNTS = [
    "- merged-clean: 2 (kvb-git-branch-gc)",
    "- merged-dirty: 1 (ask)",
    "- stale-open: 2 (ask)",
    "- active: 5 (keep, listed by --json)",
]


def rows_of(text: str) -> list[dict[str, str]]:
    lines = [line for line in text.splitlines() if line.startswith("| ")]
    if not lines:
        return []
    header = lines[0].strip("| ").split(" | ")
    return [dict(zip(header, line.strip("| ").split(" | "), strict=True)) for line in lines[2:]]


class TestOrphans(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        cls.base = Path(tmp.name).resolve()
        home = cls.base / "home"
        (home / ".claude" / "sessions").mkdir(parents=True)
        cls.root = cls.base / "council"
        config = cls.base / "config.json"
        config.write_text(json.dumps({"busy_processes": ["sleep"]}), encoding="utf-8")
        cls.env = {
            "PATH": "/usr/bin:/bin",
            "HOME": str(home),
            "AGENTS_COUNCIL_ROOT": str(cls.root),
            "AGENTS_COUNCIL_CONFIG": str(config),
            "GIT_CEILING_DIRECTORIES": str(cls.base),
            **IDENTITY,
        }
        origin = cls.base / "origin.git"
        cls.git(cls.base, "init", "-q", "--bare", "-b", "main", str(origin))
        cls.main = cls.base / "main"
        cls.main.mkdir()
        cls.git(cls.main, "init", "-q", "-b", "main")
        cls.commit(cls.main, "app.txt", "one\n", "init", None)
        cls.git(cls.main, "remote", "add", "origin", str(origin))
        cls.git(cls.main, "push", "-q", "-u", "origin", "main")

        cls.trees = {name: cls.base / f"wt-{name}" for name in ("merged", "mdirty", *AGES)}
        cls.add_tree("merged")
        cls.commit(cls.trees["merged"], "m.txt", "m\n", "merged work", None)
        cls.git(cls.main, "merge", "-q", "--ff-only", "merged")

        cls.git(cls.main, "switch", "-q", "-c", "squashed")
        cls.commit(cls.main, "sq.txt", "sq\n", "squashed work", OLD)
        cls.git(cls.main, "switch", "-q", "main")
        cls.git(cls.main, "merge", "-q", "--squash", "squashed")
        cls.git(cls.main, "commit", "-q", "-m", "squashed work, squashed")
        cls.git(cls.main, "push", "-q", "origin", "main")

        cls.add_tree("mdirty")
        (cls.trees["mdirty"] / "scratch.txt").write_text("left over\n", encoding="utf-8")
        for name, when in AGES.items():
            cls.add_tree(name)
            cls.commit(cls.trees[name], f"{name}.txt", "one\n", f"{name} work", when)
            (cls.trees[name] / f"{name}.txt").write_text("two\n", encoding="utf-8")
            if name != "recent":
                os.utime(cls.trees[name] / f"{name}.txt", (when, when))
            os.utime(cls.index(cls.trees[name]), (when, when))
        huge = cls.base / "huge.bin"
        huge.write_bytes(b"x" * 4 * BIG)
        big, link = cls.trees["stale"] / "big.bin", cls.trees["stale"] / "outside"
        big.write_bytes(b"x" * BIG)
        link.symlink_to(huge)
        os.utime(big, (OLD, OLD))
        os.utime(link, (OLD, OLD), follow_symlinks=False)
        cls.git(cls.main, "branch", "archive/old", "stale")
        notes = cls.main / "notes.txt"
        notes.write_text("main worktree scratch\n", encoding="utf-8")
        os.utime(notes, (OLD, OLD))

        cls.claim("work/claimed-job", {"session": "peer", "runtime": "other", "name": "Peer", "beat": time.time(),
                                        "work": f"finish {cls.trees['claimed']}"})
        cls.claim("work/ended-job", {"session": "gone", "runtime": "claude-code", "name": None, "beat": OLD,
                                      "work": "rebase ended onto main"})
        cls.sleeper = subprocess.Popen(["sleep", "120"], cwd=cls.trees["busy"])
        cls.addClassCleanup(cls.sleeper.wait)
        cls.addClassCleanup(cls.sleeper.kill)

    @classmethod
    def run_git(cls, cwd: Path, env: dict[str, str], *args: str) -> str:
        return subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True, check=True).stdout

    @classmethod
    def git(cls, cwd: Path, *args: str) -> str:
        return cls.run_git(cwd, cls.env, *args)

    @classmethod
    def commit(cls, repo: Path, name: str, text: str, message: str, when: float | None) -> None:
        """Commit one file.

        Args:
          when: author and committer date as epoch seconds; None means now.
        """
        (repo / name).write_text(text, encoding="utf-8")
        cls.git(repo, "add", name)
        dated = {} if when is None else {"GIT_AUTHOR_DATE": f"@{int(when)} +0000", "GIT_COMMITTER_DATE": f"@{int(when)} +0000"}
        cls.run_git(repo, {**cls.env, **dated}, "commit", "-q", "-m", message)

    @classmethod
    def add_tree(cls, name: str) -> None:
        cls.git(cls.main, "worktree", "add", "-q", "-b", name, str(cls.trees[name]), "main")

    @classmethod
    def index(cls, tree: Path) -> Path:
        return Path(cls.git(tree, "rev-parse", "--path-format=absolute", "--git-path", "index").strip())

    @classmethod
    def claim(cls, office: str, fields: dict) -> None:
        path = cls.root / office
        path.mkdir(parents=True)
        claim = {"office": office, "since": "2026-11-01T00:00:00+00:00", **fields}
        (path / "claim.json").write_text(json.dumps(claim), encoding="utf-8")

    def orphans(self, *extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(ORPHANS), "--repo", str(self.main), "--default", "main", "--stale-days", "7", *extra],
            capture_output=True, text=True, env=self.env, cwd=self.base, check=False,
        )

    def out(self, *extra: str) -> str:
        result = self.orphans(*extra)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def rows(self, *extra: str) -> dict[str, dict]:
        return {row["branch"]: row for row in json.loads(self.out("--json", "--top", "1", *extra))["rows"]}

    def test_the_summary_counts_every_class_then_shows_the_oldest_rows_per_class(self):
        lines = self.out("--top", "1").splitlines()
        self.assertEqual(lines[1:5], COUNTS)
        self.assertNotIn("busy unknown", "\n".join(lines))
        self.assertIn("Top 1 per class, oldest first:", lines)
        self.assertEqual([(row["Branch"], row["Class"], row["Proposal"]) for row in rows_of("\n".join(lines))],
                         [("squashed", *TABLE["squashed"]), ("mdirty", *TABLE["mdirty"]),
                          ("ended", *TABLE["ended"])])
        self.assertEqual([row["Branch"] for row in rows_of(self.out("--top", "2"))],
                         ["squashed", "merged", "mdirty", "ended", "stale"])
        counts_only = self.out("--top", "0")
        self.assertEqual((counts_only.splitlines()[1:5], rows_of(counts_only)), (COUNTS, []))

    def test_the_full_file_holds_every_row_but_the_active_ones(self):
        full = self.base / "full.md"
        lines = self.out("--top", "1", "--full", str(full)).splitlines()
        self.assertIn(f"- full table: {full}", lines)
        rows = {row["Branch"]: row for row in rows_of(full.read_text(encoding="utf-8"))}
        self.assertEqual({branch: (row["Class"], row["Proposal"]) for branch, row in rows.items()}, TABLE)
        stale = rows["stale"]
        self.assertEqual((stale["Worktree"], stale["Dirty"], stale["Unpushed"]), (str(self.trees["stale"]), "3",
                                                                                 "1 (no upstream)"))
        self.assertTrue(stale["Last activity"].endswith("(30 d)"), stale["Last activity"])
        self.assertEqual(rows["ended"]["Claim"], "work/ended-job (gone, ended)")
        self.assertEqual((rows["squashed"]["Worktree"], rows["squashed"]["Dirty"], rows["squashed"]["Unpushed"]),
                         ("-", "-", "0"))
        self.assertNotIn("Size", rows["stale"])

    def test_sizes_order_the_largest_first_and_never_follow_a_symlink(self):
        shown = rows_of(self.out("--top", "1", "--sizes"))
        self.assertEqual([(row["Branch"], row["Size"]) for row in shown],
                         [("merged", "6 B"), ("mdirty", "19 B"), ("stale", "48.8 KiB")])
        rows = self.rows("--sizes")
        self.assertEqual({branch: rows[branch]["size"] for branch in ("stale", "ended", "merged", "mdirty")},
                         {"stale": BIG + 13, "ended": 13, "merged": 6, "mdirty": 19})
        for branch in ("squashed", *ACTIVE):
            with self.subTest(branch=branch):
                self.assertIsNone(rows[branch]["size"])
        self.assertIsNone(self.rows()["stale"]["size"])

    def test_json_keeps_the_main_worktree_claimed_busy_recent_and_archived_rows(self):
        rows = self.rows()
        self.assertEqual(sorted(rows), sorted([*TABLE, *ACTIVE]))
        for branch in ACTIVE:
            with self.subTest(branch=branch):
                self.assertEqual((rows[branch]["class"], rows[branch]["proposal"]), ("active", "keep"))
        self.assertEqual((rows["merged"]["merged"], rows["squashed"]["merged"]), ("ancestor", "patch"))
        self.assertTrue(rows["main"]["main"])
        self.assertEqual(rows["main"]["dirty"], 1)
        self.assertEqual(rows["claimed"]["claims"], [{"office": "work/claimed-job", "holder": "Peer", "live": True}])
        self.assertTrue(rows["busy"]["busy"])
        self.assertFalse(rows["stale"]["busy"])
        self.assertGreater(rows["recent"]["last_activity"], time.time() - DAY)
        self.assertIsNone(rows["stale"]["merged"])
        self.assertIsNone(rows["merged"]["upstream"])

    def test_the_scan_changes_nothing_in_the_repository(self):
        indexes = [self.index(tree) for tree in (self.main, *self.trees.values())]
        before = [os.stat(index).st_mtime_ns for index in indexes]
        refs = self.git(self.main, "for-each-ref")
        self.out("--top", "5", "--sizes")
        self.out("--json", "--top", "5")
        self.assertEqual([os.stat(index).st_mtime_ns for index in indexes], before)
        self.assertEqual(self.git(self.main, "for-each-ref"), refs)

    def test_a_missing_origin_default_or_bad_input_exits_2(self):
        for args in (("--default", "nope"), ("--stale-days", "-1"), ("--default", "a..b"), ("--top", "-1"),
                     ("--full", str(self.base / "absent" / "full.md"))):
            with self.subTest(args=args):
                result = self.orphans("--top", "1", *args)
                self.assertEqual((result.returncode, result.stdout), (2, ""), result.stderr)
        self.assertEqual(self.orphans().returncode, 2)


if __name__ == "__main__":
    unittest.main()
