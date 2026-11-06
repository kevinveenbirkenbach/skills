"""update.py tells every agent once which skills changed, as one newsletter through radio.py."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
UPDATE = REPO_ROOT / "skills" / "kvb-org-update" / "scripts" / "update.py"


class TestOrgUpdate(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        self.home = base / "home"
        self.root = base / "council"
        self.repo = base / "skills"
        sessions = self.home / ".claude" / "sessions"
        sessions.mkdir(parents=True)
        (sessions / "s1.json").write_text(json.dumps({"sessionId": "s1", "name": "One"}), encoding="utf-8")
        self.env = {
            "PATH": "/usr/bin:/bin",
            "HOME": str(self.home),
            "AGENTS_COUNCIL_ROOT": str(self.root),
            "AGENTS_COUNCIL_CONFIG": str(base / "config.json"),
            "CLAUDE_CODE_SESSION_ID": "s1",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.invalid",
        }
        self._git("init", "-q", str(self.repo))
        self._commit("skills/kvb-a/SKILL.md", "a1", "feat(kvb-a): first")

    def _git(self, *args: str) -> str:
        cwd = self.repo if self.repo.is_dir() else None
        return subprocess.run(["git", *args], cwd=cwd, env=self.env, capture_output=True, text=True, check=True).stdout

    def _commit(self, path: str, text: str, subject: str) -> None:
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        self._git("add", "-A")
        self._git("commit", "-q", "-m", subject)

    def _update(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(UPDATE), "--repo", str(self.repo), *args],
            env=self.env, capture_output=True, text=True, check=False, timeout=60,
        )

    def _rows(self) -> list[dict]:
        news = self.root / "news.jsonl"
        return [json.loads(line) for line in news.read_text(encoding="utf-8").splitlines()] if news.exists() else []

    def _announced(self) -> str | None:
        marks = self.root / "skills-announced.json"
        return json.loads(marks.read_text(encoding="utf-8")).get(str(self.repo.resolve())) if marks.exists() else None

    def test_the_first_run_records_head_and_sends_nothing(self):
        result = self._update()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._rows(), [])
        self.assertEqual(self._announced(), self._git("rev-parse", "HEAD").strip())

    def test_changed_skills_go_out_once_as_one_newsletter(self):
        self._update()
        self._commit("skills/kvb-a/SKILL.md", "a2", "fix(kvb-a): sharper step")
        self._commit("skills/kvb-b/SKILL.md", "b1", "feat(kvb-b): new skill")
        self._commit("README.md", "readme", "docs: readme only")
        before = self._announced()
        dry = self._update("--dry-run")
        self.assertEqual(dry.returncode, 0, dry.stderr)
        self.assertIn("kvb-a (fix(kvb-a): sharper step)", dry.stdout)
        self.assertIn("kvb-b (feat(kvb-b): new skill)", dry.stdout)
        self.assertNotIn("readme", dry.stdout)
        self.assertIn("Re-read each changed SKILL.md before its next use.", dry.stdout)
        self.assertEqual((self._rows(), self._announced()), ([], before))
        sent = self._update()
        self.assertEqual(sent.returncode, 0, sent.stderr)
        (row,) = self._rows()
        self.assertEqual((row["class"], row["v"], row["from"], row["to"]), ("newsletter", 2, "One", []))
        self.assertIn("kvb-a (fix(kvb-a): sharper step), kvb-b (feat(kvb-b): new skill)", row["text"])
        self.assertEqual(self._announced(), self._git("rev-parse", "HEAD").strip())
        again = self._update()
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertIn("nothing new", again.stdout)
        self.assertEqual(len(self._rows()), 1)

    def test_since_names_the_base_and_a_removed_skill_says_so(self):
        self._commit("skills/kvb-b/SKILL.md", "b1", "feat(kvb-b): new skill")
        self._git("rm", "-q", "-r", "skills/kvb-a")
        self._git("commit", "-q", "-m", "refactor: drop kvb-a")
        result = self._update("--since", "HEAD~2", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("kvb-a (removed), kvb-b (feat(kvb-b): new skill)", result.stdout)

    def test_more_than_three_subjects_are_counted(self):
        self._update()
        for n in range(5):
            self._commit("skills/kvb-a/SKILL.md", f"a{n}", f"fix(kvb-a): step {n}")
        result = self._update("--dry-run")
        self.assertIn("kvb-a (fix(kvb-a): step 4; fix(kvb-a): step 3; fix(kvb-a): step 2; +2 more)", result.stdout)

    def test_an_unknown_base_is_a_usage_error(self):
        result = self._update("--since", "no-such-rev")
        self.assertEqual(result.returncode, 2)
        self.assertIn("no-such-rev", result.stderr)


if __name__ == "__main__":
    unittest.main()
