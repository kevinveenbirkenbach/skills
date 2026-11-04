"""Exercise security.py of kvb-check-security against a fake medusa: weights, locations, exit codes, hand review."""

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

REPO_ROOT = Path(__file__).resolve().parents[1]
SECURITY = REPO_ROOT / "skills" / "kvb-check-security" / "scripts" / "security.py"
GIT_DIR = os.path.dirname(shutil.which("git"))
PLACEHOLDER = "placeholder-value-never-shown"
FAKE = """#!{python}
import json, os, pathlib, sys
args = sys.argv[1:]
pathlib.Path(__file__).with_name("argv.json").write_text(json.dumps(args))
pathlib.Path(__file__).with_name("home.txt").write_text(os.environ["HOME"])
pathlib.Path(os.environ["HOME"], ".medusa").mkdir()
target, out = pathlib.Path(args[1]), pathlib.Path(args[args.index("-o") + 1])
out.mkdir(parents=True)
findings = []
for path in sorted(p for p in target.rglob("*") if p.is_file()):
    for number, text in enumerate(path.read_text().splitlines(), 1):
        for severity in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"):
            if "MARK-" + severity in text:
                findings.append({{
                    "severity": severity, "rule_id": "FAKE-" + severity, "file": str(path), "line": number,
                    "code": text,
                }})
report = {{"issues": findings}} if os.environ.get("FAKE_MEDUSA_SHAPE") == "other" else {{"findings": findings}}
(out / "medusa-scan-20261104-120000.json").write_text(json.dumps(report))
"""
HAND = "review trust boundaries, secrets and injection in the diff by hand, then pass --security '~<n>' to kvb-check-score"


class TestSecurity(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.bin = self.base / "bin"
        self.bin.mkdir()
        medusa = self.bin / "medusa"
        medusa.write_text(FAKE.format(python=sys.executable), encoding="utf-8")
        medusa.chmod(0o755)
        self.repo = self.base / "repo"
        self.repo.mkdir()
        self.env = {
            "PATH": f"{self.bin}:{GIT_DIR}",
            "HOME": str(self.base),
            "AGENTS_COUNCIL_ROOT": str(self.base / "council"),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.org",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.org",
        }
        self.git("init", "-q", "-b", "main")
        self.write("app.py", "print(1)\n")
        self.write("old.py", "x = 1  # MARK-CRITICAL\n")
        self.write("gone.py", "y = 2  # MARK-HIGH\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "base")

    def git(self, *args: str) -> None:
        subprocess.run(["git", *args], cwd=self.repo, env=self.env, capture_output=True, check=True)

    def write(self, path: str, text: str) -> None:
        (self.repo / path).write_text(text, encoding="utf-8")

    def scan(self, *extra: str, env: dict[str, str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SECURITY), "--repo", str(self.repo), "--base", "HEAD", *extra],
            cwd=self.base, env=env, capture_output=True, text=True, check=False,
        )

    def test_changed_and_untracked_files_are_weighted(self):
        self.write("app.py", f"print(1)\ntoken = '{PLACEHOLDER}'  # MARK-HIGH\n")
        self.write("new.py", "a = 1  # MARK-LOW\nb = 2\nc = 3  # MARK-MEDIUM\nd = 4  # MARK-INFO\n")
        (self.repo / "gone.py").unlink()
        (self.repo / "link.py").symlink_to(self.repo / "old.py")
        result = self.scan(env=self.env)
        self.assertEqual(
            result.stdout,
            "🛡️ security 63 % (medusa: 4 findings in 2 files: high app.py:2, medium new.py:3, low new.py:1, "
            "info new.py:4)\n",
        )
        self.assertEqual(result.returncode, 3, result.stderr)
        argv = json.loads((self.bin / "argv.json").read_text(encoding="utf-8"))
        self.assertEqual([argv[0], *argv[2:4], argv[4], argv[6]], ["scan", "--format", "json", "-o", "--no-cache"])
        result = self.scan("--json", env=self.env)
        self.assertNotIn(PLACEHOLDER, result.stdout + result.stderr)
        found = json.loads(result.stdout)
        self.assertEqual(
            {k: found[k] for k in ("security", "files", "critical", "high", "medium", "low", "info")},
            {"security": 63, "files": 2, "critical": 0, "high": 1, "medium": 1, "low": 1, "info": 1},
        )
        self.assertEqual(
            found["findings"][0],
            {
                "severity": "high", "rule": "FAKE-HIGH", "path": "app.py", "line": 2,
                "sha1": hashlib.sha1(f"token = '{PLACEHOLDER}'  # MARK-HIGH".encode()).hexdigest(),
            },
        )
        self.assertEqual(found["accepted"], [])
        home = Path((self.bin / "home.txt").read_text(encoding="utf-8"))
        self.assertNotEqual(home, self.base)
        self.assertTrue(home.name == "home" and home.parent.name.startswith("kvb-security-"), home)

    def accept(self, *flags: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SECURITY), "accept", "--repo", str(self.repo), *flags],
            cwd=self.base, env=self.env, capture_output=True, text=True, check=False,
        )

    def test_accepted_false_positive_leaves_the_score_until_its_line_changes(self):
        line = "x = compute()  # MARK-CRITICAL"
        self.write("app.py", f"print(1)\n{line}\n")
        sha1 = hashlib.sha1(line.encode()).hexdigest()
        result = self.accept("--rule", "FAKE-CRITICAL", "--path", "app.py", "--sha1", sha1, "--reason", "fixture marker")
        self.assertEqual(result.returncode, 0, result.stderr)
        listing = self.base / "council" / "security-accepted.jsonl"
        row = json.loads(listing.read_text(encoding="utf-8"))
        self.assertEqual(
            {k: row[k] for k in ("rule", "path", "sha1", "reason", "repo")},
            {"rule": "FAKE-CRITICAL", "path": "app.py", "sha1": sha1, "reason": "fixture marker",
             "repo": str(self.repo.resolve())},
        )
        result = self.scan(env=self.env)
        self.assertEqual(
            (result.stdout, result.returncode),
            ("🛡️ security 100 % (medusa: 0 findings, 1 accepted in 1 file)\n", 0),
        )
        accepted = json.loads(self.scan("--json", env=self.env).stdout)["accepted"]
        self.assertEqual([(a["rule"], a["path"], a["line"]) for a in accepted], [("FAKE-CRITICAL", "app.py", 2)])
        self.write("app.py", "print(1)\nx = compute(2)  # MARK-CRITICAL\n")
        result = self.scan(env=self.env)
        self.assertEqual(
            (result.stdout, result.returncode),
            ("🛡️ security 50 % (medusa: 1 finding in 1 file: critical app.py:2)\n", 1),
        )

    def test_kept_rows_count_and_broken_rows_stop(self):
        line = "y = other()  # MARK-HIGH"
        self.write("app.py", f"{line}\n")
        kept = self.base / ".local" / "state" / "agents-council" / "security-accepted.jsonl"
        kept.parent.mkdir(parents=True)
        sha1 = hashlib.sha1(line.encode()).hexdigest()
        kept.write_text(json.dumps({"rule": "FAKE-HIGH", "path": "app.py", "sha1": sha1}) + "\n", encoding="utf-8")
        result = self.scan(env=self.env)
        self.assertEqual(result.stdout, "🛡️ security 100 % (medusa: 0 findings, 1 accepted in 1 file)\n")
        kept.write_text('{"rule": "FAKE-HIGH"}\n', encoding="utf-8")
        result = self.scan(env=self.env)
        self.assertEqual(result.returncode, 2)
        self.assertIn("security-accepted.jsonl:1: want a JSON row with rule, path and sha1", result.stderr)
        result = self.accept("--rule", "R", "--path", "app.py", "--sha1", "XYZ", "--reason", "r")
        self.assertEqual(result.returncode, 2)
        self.assertIn("--sha1 must be 40 lowercase hex digits", result.stderr)

    def test_critical_exits_1_and_floors_at_0(self):
        self.write("app.py", "a  # MARK-CRITICAL\nb  # MARK-CRITICAL\nc  # MARK-CRITICAL\n")
        result = self.scan(env=self.env)
        self.assertTrue(result.stdout.startswith("🛡️ security 0 % (medusa: 3 findings in 1 file: critical app.py:1, "))
        self.assertEqual(result.returncode, 1)

    def test_more_than_five_locations_are_cut(self):
        self.write("app.py", "".join(f"v{n}  # MARK-LOW\n" for n in range(7)))
        result = self.scan(env=self.env)
        self.assertEqual(
            result.stdout,
            "🛡️ security 86 % (medusa: 7 findings in 1 file: low app.py:1, low app.py:2, low app.py:3, "
            "low app.py:4, low app.py:5, +2 more)\n",
        )
        self.assertEqual(result.returncode, 3)

    def test_clean_and_empty_changes_are_100(self):
        result = self.scan(env=self.env)
        self.assertEqual((result.stdout, result.returncode), ("🛡️ security 100 % (medusa: 0 findings in 0 files)\n", 0))
        self.assertFalse((self.bin / "argv.json").exists())
        self.write("app.py", "print(2)\n")
        result = self.scan(env=self.env)
        self.assertEqual((result.stdout, result.returncode), ("🛡️ security 100 % (medusa: 0 findings in 1 file)\n", 0))

    def test_missing_medusa_asks_for_a_review_by_hand(self):
        if shutil.which("medusa", path=GIT_DIR):
            self.skipTest("a real medusa sits next to git")
        self.write("app.py", "print(2)\n")
        result = self.scan(env={**self.env, "PATH": GIT_DIR})
        self.assertEqual((result.stdout, result.returncode), (f"🛡️ security – (medusa missing: {HAND})\n", 4))
        result = self.scan("--json", env={**self.env, "PATH": GIT_DIR})
        self.assertEqual(json.loads(result.stdout), {"security": None, "problem": "medusa missing"})

    def test_unreadable_report_asks_for_a_review_by_hand(self):
        self.write("app.py", "print(2)\n")
        result = self.scan(env={**self.env, "FAKE_MEDUSA_SHAPE": "other"})
        self.assertEqual(result.returncode, 4)
        self.assertRegex(result.stdout, r"^🛡️ security – \(medusa report unreadable: .*holds no findings list")

    def test_usage_errors_exit_2(self):
        result = subprocess.run(
            [sys.executable, str(SECURITY), "--repo", str(self.repo), "--base", "nope"],
            env=self.env, capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 2)
        result = subprocess.run(
            [sys.executable, str(SECURITY), "--repo", str(self.base / "absent"), "--base", "HEAD"],
            env=self.env, capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
