"""Requirement 062: capped register table, MEMORY.md budget, narrowed graph hooks, velocity in kvb-check-efficiency."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RASCI = REPO_ROOT / "skills" / "kvb-org-rasci" / "scripts" / "rasci.py"
BUDGET = REPO_ROOT / "scripts" / "budget.py"
GRAPH_HOOKS = REPO_ROOT / "scripts" / "graph-hooks.js"
GRAPH = "/home/op/.local/bin/codebase-memory-mcp"
OPEN_ROWS = 600


class Scratch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

    def run_script(self, command: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            command, capture_output=True, text=True, env=env, cwd=self.base, check=False, timeout=120
        )


class TestRegisterTable(Scratch):
    def show(self, roles: dict[str, str], results: list[dict], *args: str) -> list[str]:
        root = self.base / "council"
        root.mkdir()
        rows = {
            f"work/t{n:03d}": {"title": f"T{n}", "prio": n, "roles": roles, "key_results": results}
            for n in range(1, OPEN_ROWS + 1)
        }
        (root / "rasci.json").write_text(json.dumps(rows), encoding="utf-8")
        env = {"PATH": "/usr/bin:/bin", "HOME": str(self.base / "home"),
               "AGENTS_COUNCIL_ROOT": str(root), "CLAUDE_CODE_SESSION_ID": "s1"}
        done = self.run_script([sys.executable, str(RASCI), "show", *args], env)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.splitlines()

    def test_show_prints_the_top_30_rows_and_counts_the_rest(self):
        lines = self.show({"One": "AR"}, [{"text": "k", "met": False}])
        self.assertLessEqual(len(lines), 33)
        self.assertTrue(lines[31].startswith("| 30 | - | work/t030: T30 |"), lines[31])
        self.assertEqual(lines[-1], f"{OPEN_ROWS - 30} more (show --all)")

    def test_show_all_lists_every_row_without_the_more_line(self):
        lines = self.show({"One": "AR"}, [{"text": "k", "met": False}], "--all")
        self.assertEqual(len(lines), OPEN_ROWS + 2)
        self.assertNotIn("more (show --all)", lines[-1])

    def test_gaps_name_only_the_shown_rows(self):
        lines = self.show({}, [])
        self.assertEqual(lines[-2], f"{OPEN_ROWS - 30} more (show --all)")
        self.assertIn("work/t030 has 0 A", lines[-1])
        self.assertNotIn("work/t031", lines[-1])


class TestMemoryBudget(Scratch):
    def budget(self, memory: Path, memory_words: int | None) -> subprocess.CompletedProcess:
        skill = self.base / "skills" / "x" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("---\nname: x\ndescription: short\n---\nbody\n", encoding="utf-8")
        if memory_words is not None:
            memory.write_text(" ".join(["word"] * memory_words) + "\n", encoding="utf-8")
        return self.run_script([sys.executable, str(BUDGET), "--repo", str(self.base), "--top", "1",
                                "--memory", str(memory)])

    def test_a_memory_index_of_400_words_passes(self):
        done = self.budget(self.base / "MEMORY.md", 400)
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn(f"400/400 words in {self.base / 'MEMORY.md'}", done.stdout)

    def test_a_memory_index_of_401_words_fails(self):
        done = self.budget(self.base / "MEMORY.md", 401)
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn(f"MEMORY.md over 400: {self.base / 'MEMORY.md'} (401)", done.stdout)

    def test_a_missing_memory_index_counts_as_empty(self):
        done = self.budget(self.base / "absent.md", None)
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn(f"0/400 words in {self.base / 'absent.md'}", done.stdout)


def graph_entry(matcher: str) -> dict:
    return {"matcher": matcher, "hooks": [{"type": "command", "command": GRAPH}]}


@unittest.skipUnless(shutil.which("node"), "node not installed")
class TestGraphHooks(Scratch):
    def test_graph_hooks_run_on_grep_and_glob_only_and_never_after_read(self):
        other = {"matcher": "Bash", "hooks": [{"type": "command", "command": "/usr/bin/guard"}]}
        mixed = {"matcher": "Read", "hooks": [{"type": "command", "command": GRAPH},
                                              {"type": "command", "command": "/usr/bin/audit"}]}
        settings = self.base / "settings.json"
        settings.write_text(json.dumps({"model": "x", "hooks": {
            "PreToolUse": [graph_entry("Grep|Glob|Bash"), other, graph_entry("Grep|Glob|Bash")],
            "PostToolUse": [graph_entry("Read"), mixed],
        }}), encoding="utf-8")
        settings.chmod(0o640)
        done = self.run_script(["node", str(GRAPH_HOOKS), str(settings)])
        self.assertEqual(done.returncode, 0, done.stderr)
        data = json.loads(settings.read_text(encoding="utf-8"))
        self.assertEqual(data["model"], "x")
        self.assertEqual(data["hooks"]["PreToolUse"], [graph_entry("Grep|Glob"), other])
        self.assertEqual(data["hooks"]["PostToolUse"], [mixed])
        self.assertEqual(settings.stat().st_mode & 0o777, 0o640)

    def test_a_second_run_changes_nothing(self):
        settings = self.base / "settings.json"
        settings.write_text(json.dumps({"hooks": {"PreToolUse": [graph_entry("Grep|Glob|Bash")]}}), encoding="utf-8")
        self.run_script(["node", str(GRAPH_HOOKS), str(settings)])
        first = settings.read_text(encoding="utf-8")
        done = self.run_script(["node", str(GRAPH_HOOKS), str(settings)])
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(settings.read_text(encoding="utf-8"), first)

    def test_a_settings_file_without_json_stays_untouched(self):
        settings = self.base / "settings.json"
        settings.write_text("not json", encoding="utf-8")
        done = self.run_script(["node", str(GRAPH_HOOKS), str(settings)])
        self.assertEqual(done.returncode, 1)
        self.assertEqual(settings.read_text(encoding="utf-8"), "not json")


class TestVelocityFold(unittest.TestCase):
    def test_no_skill_or_readme_names_the_folded_speed_skill(self):
        texts = [REPO_ROOT / "README.md", *sorted((REPO_ROOT / "skills").glob("*/SKILL.md"))]
        named = [str(path.relative_to(REPO_ROOT)) for path in texts
                 if "kvb-check-speed" in path.read_text(encoding="utf-8")]
        self.assertEqual(named, [])
        self.assertFalse((REPO_ROOT / "skills" / "kvb-check-speed").exists())

    def test_the_efficiency_skill_measures_velocity(self):
        text = (REPO_ROOT / "skills" / "kvb-check-efficiency" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("## Code: velocity", text)


if __name__ == "__main__":
    unittest.main()
