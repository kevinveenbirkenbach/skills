from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKFILL = REPO_ROOT / "skills" / "kvb-check-score" / "scripts" / "backfill.py"
EPOCH = 1_760_000_000
HANG = 60
OLD_BLOCK = "🎯 Fix: 95 %\n💥 Break: 2 %\n💸 Cost: 97 %\n⏱️ Time: –\n🛡️ Security: 100 %\n🏆 Score: 96\n🚦 Gate: ✅ 90/5, cost and time <= 100, security 100 %"
NEW_BLOCK = "🎯 Fix: 92 %\n💥 Break: 3 %\n💸 Tokens: 110 %\n⏱️ Velocity: 90 %\n🛡️ Security: 100 %\n💰 Value: 1:20\n🧪 Coverage: 80 %\n🏆 Score: 81\n🚦 Gate: ⚠️ tokens 110 % > 100: ask the operator before the commit"
ESTIMATED_BLOCK = "🎯 Fix: 90 %\n💥 Break: 5 %\n💸 Tokens: new\n⏱️ Velocity: 130 %\n🛡️ Security: ~80 %\n🌡️ Heat: 5\n🧪 Coverage: 70 %\n🏆 Score: 52\n🚦 Gate: ⚠️ tokens new: ask the operator before the commit"
MALFORMED_BLOCK = "🎯 Fix: 95 %\n💥 Break: 2 %\n🏆 Score: high"
TRAILER = "Co-Authored-By: Test <test@example.org>"


def git_env(home: Path) -> dict[str, str]:
    """Args:
        home: a scratch HOME, so no user or system git configuration applies.

    Returns:
        The environment for fixture git calls.
    """
    return {
        "PATH": os.path.dirname(shutil.which("git")),
        "HOME": str(home),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.org",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.org",
    }


class Fixture:
    """Args:
        base: a scratch directory for upstream.git, the work clone a and the clone b.
    """

    def __init__(self, base: Path) -> None:
        self.base = base
        self.env = git_env(base)
        self.upstream = base / "upstream.git"
        self.a = base / "a"
        self.b = base / "b"
        self.step = 0
        base.mkdir(parents=True)
        self.git(base, "init", "-q", "--bare", "-b", "main", str(self.upstream))
        self.a.mkdir()
        self.git(self.a, "init", "-q", "-b", "main")
        self.git(self.a, "remote", "add", "origin", str(self.upstream))
        self.old = self.commit("feat: old labels", OLD_BLOCK)
        self.git(self.a, "checkout", "-q", "-b", "feature/two")
        self.new = self.commit("feat: new labels", NEW_BLOCK)
        self.git(self.a, "checkout", "-q", "main")
        self.tick()
        self.git(self.a, "merge", "-q", "--no-ff", "-m", "Merge branch 'feature/two'", "feature/two")
        self.estimated = self.commit("fix: estimated", ESTIMATED_BLOCK)
        self.malformed = self.commit("chore: malformed", MALFORMED_BLOCK)
        self.plain = self.commit("docs: no block", "")
        self.git(self.a, "push", "-q", "origin", "main", "feature/two")
        self.git(base, "clone", "-q", str(self.upstream), str(self.b))

    def tick(self) -> None:
        self.step += 1
        stamp = f"{EPOCH + self.step * 3600} +0000"
        self.env["GIT_AUTHOR_DATE"] = stamp
        self.env["GIT_COMMITTER_DATE"] = stamp

    def git(self, cwd: Path, *args: str) -> str:
        return subprocess.run(["git", *args], cwd=cwd, env=self.env, capture_output=True, text=True, check=True).stdout.strip()

    def commit(self, subject: str, block: str) -> str:
        self.tick()
        messages = [item for part in (subject, block, TRAILER) if part for item in ("-m", part)]
        self.git(self.a, "commit", "-q", "--allow-empty", *messages)
        return self.git(self.a, "rev-parse", "HEAD")

    def time_of(self, sha: str) -> int:
        return int(self.git(self.a, "show", "-s", "--format=%ct", sha))


def backfill(council: Path, *args: str) -> subprocess.CompletedProcess:
    env = {"PATH": os.environ["PATH"], "AGENTS_COUNCIL_ROOT": str(council)}
    return subprocess.run([sys.executable, "-B", str(BACKFILL), *args], env=env, capture_output=True, text=True, check=False, timeout=HANG)
