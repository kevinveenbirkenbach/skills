"""Exercise scripts/tokeneconomizer.sh: the pinned clone, both agents and the global settings."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "tokeneconomizer.sh"
TOOLS = ("git", "python3", "mkdir", "dirname", "cat")
GIT_ENV = {
    "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.invalid", "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
}
PROTECT = (
    "AskUserQuestion,Artifact,Skill,Agent,ToolSearch,mcp__kvb-orchestrator__*,"
    "mcp__codebase-memory-mcp__*,mcp__plugin_codebase-memory_*"
)
TE = '#!/bin/sh\necho "$*" >> "$CALLS/te.log"\n'
UNSAFE = 'env = {"PYTHONUTF8": "1"}\n'
SAFE = 'env = {"PYTHONUTF8": "1", "PYTHONSAFEPATH": "1"}\n'
CLAUDE = '#!/bin/sh\necho "$*" >> "$CALLS/claude.log"\n'
CODEX = """#!/bin/sh
echo "$*" >> "$CALLS/codex.log"
case "$*" in
  "plugin marketplace list") cat "$CALLS/codex.marketplaces" 2>/dev/null ;;
  "plugin marketplace add "*) echo "$4" >> "$CALLS/codex.marketplaces" ;;
esac
exit 0
"""


def git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, env={**os.environ, **GIT_ENV}, capture_output=True, text=True, check=True)
    return done.stdout.strip()


def lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines() if path.is_file() else []


class TestTokenEconomizerInstall(unittest.TestCase):
    def setUp(self):
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.root = Path(work.name)
        upstream = self.root / "upstream"
        (upstream / "plugin" / "scripts").mkdir(parents=True)
        git(upstream, "init", "-q", "-b", "main")
        te = upstream / "plugin" / "scripts" / "te"
        te.write_text(TE, encoding="utf-8")
        te.chmod(0o755)
        (upstream / "context.py").write_text(UNSAFE, encoding="utf-8")
        (upstream / "notes.txt").write_text("notes\n", encoding="utf-8")
        git(upstream, "add", "-A")
        git(upstream, "commit", "-q", "-m", "pinned")
        self.pin = git(upstream, "rev-parse", "HEAD")
        (self.root / "patches").mkdir()
        (upstream / "context.py").write_text(SAFE, encoding="utf-8")
        git(upstream, "diff", f"--output={self.root / 'patches' / 'tokeneconomizer.patch'}")
        git(upstream, "checkout", "-q", "--", "context.py")
        (upstream / "later.txt").write_text("later\n", encoding="utf-8")
        git(upstream, "add", "-A")
        git(upstream, "commit", "-q", "-m", "later")
        self.later = git(upstream, "rev-parse", "HEAD")
        self.upstream = upstream
        self.lock = self.root / "plugins-lock.json"
        self.lock.write_text(json.dumps({"tokeneconomizer": {
            "source": str(upstream), "commit": self.pin, "patch": "patches/tokeneconomizer.patch",
        }}), encoding="utf-8")
        self.clone = self.root / "home" / "Repositories" / "github.com" / "microsoft" / "TokenEconomizer"
        self.calls = self.root / "calls"
        self.calls.mkdir()

    def run_script(self, agents: tuple[str, ...]) -> subprocess.CompletedProcess:
        stubs = self.root / f"bin-{'-'.join(agents) or 'none'}"
        if not stubs.exists():
            stubs.mkdir()
            for tool in TOOLS:
                (stubs / tool).symlink_to(shutil.which(tool))
            for name, body in (("claude", CLAUDE), ("codex", CODEX)):
                if name in agents:
                    (stubs / name).write_text(body, encoding="utf-8")
                    (stubs / name).chmod(0o755)
        env = {"PATH": str(stubs), "HOME": str(self.root / "home"), "CALLS": str(self.calls), **GIT_ENV}
        return subprocess.run(["/bin/bash", str(SCRIPT), str(self.lock), str(self.clone)], env=env, capture_output=True, text=True, check=False)

    def test_a_fresh_host_gets_the_clone_at_the_pin_and_the_plugin_for_both_agents_with_the_chosen_settings(self):
        done = self.run_script(("claude", "codex"))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(git(self.clone, "rev-parse", "HEAD"), self.pin)
        self.assertEqual(lines(self.calls / "claude.log"), [f"plugin install tokeneconomizer --marketplace {self.clone} --scope user"])
        self.assertEqual(lines(self.calls / "codex.log"), [
            "plugin marketplace list", f"plugin marketplace add {self.clone}", "plugin add tokeneconomizer@tokeneconomizer",
        ])
        self.assertEqual(lines(self.calls / "te.log"), [f"config set toolprune=propose microskills=envfacts toolprune_protect={PROTECT} --global"])
        self.assertIn("run /hooks, choose Trust all", done.stdout)
        self.assertEqual(self.context(), SAFE)

    def context(self) -> str:
        return (self.clone / "context.py").read_text(encoding="utf-8")

    def test_a_second_run_keeps_the_pin_and_adds_the_codex_marketplace_only_once(self):
        self.assertEqual(self.run_script(("claude", "codex")).returncode, 0)
        done = self.run_script(("claude", "codex"))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(git(self.clone, "rev-parse", "HEAD"), self.pin)
        self.assertEqual([call for call in lines(self.calls / "codex.log") if call.startswith("plugin marketplace add")], [f"plugin marketplace add {self.clone}"])
        self.assertEqual(len(lines(self.calls / "codex.log")), 5)
        self.assertEqual(self.context(), SAFE)

    def test_a_clean_clone_on_another_commit_moves_to_the_pin(self):
        self.clone.parent.mkdir(parents=True)
        git(self.root, "clone", "-q", str(self.upstream), str(self.clone))
        self.assertEqual(git(self.clone, "rev-parse", "HEAD"), self.later)
        done = self.run_script(("claude",))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(git(self.clone, "rev-parse", "HEAD"), self.pin)
        self.assertEqual(self.context(), SAFE)

    def test_a_patched_clone_with_a_foreign_edit_keeps_both_and_the_step_fails(self):
        self.assertEqual(self.run_script(("claude",)).returncode, 0)
        (self.clone / "notes.txt").write_text("operator notes\n", encoding="utf-8")
        done = self.run_script(("claude",))
        self.assertEqual(done.returncode, 1)
        self.assertIn("has local changes; TokenEconomizer stays off its pin", done.stderr)
        self.assertEqual((self.context(), (self.clone / "notes.txt").read_text(encoding="utf-8")), (SAFE, "operator notes\n"))
        self.assertEqual(len(lines(self.calls / "claude.log")), 1)

    def test_a_clone_with_local_changes_stays_where_it_is_and_the_step_fails(self):
        self.clone.parent.mkdir(parents=True)
        git(self.root, "clone", "-q", str(self.upstream), str(self.clone))
        (self.clone / "later.txt").write_text("edited\n", encoding="utf-8")
        done = self.run_script(("claude", "codex"))
        self.assertEqual(done.returncode, 1)
        self.assertIn("has local changes; TokenEconomizer stays off its pin", done.stderr)
        self.assertEqual(git(self.clone, "rev-parse", "HEAD"), self.later)
        self.assertEqual(self.context(), UNSAFE)
        self.assertEqual((lines(self.calls / "claude.log"), lines(self.calls / "codex.log"), lines(self.calls / "te.log")), ([], [], []))

    def test_a_host_without_codex_installs_for_claude_only_and_says_so(self):
        done = self.run_script(("claude",))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(len(lines(self.calls / "claude.log")), 1)
        self.assertEqual(lines(self.calls / "codex.log"), [])
        self.assertIn("codex not found; TokenEconomizer skipped for Codex.", done.stdout)
        self.assertEqual(len(lines(self.calls / "te.log")), 1)


if __name__ == "__main__":
    unittest.main()
