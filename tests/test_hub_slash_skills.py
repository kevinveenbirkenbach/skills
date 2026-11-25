from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import hub_support
import skills_index
from hub_case import HubCase
from kvb_orchestrator.skillindex import SKILLS_INDEX, served

HUB = hub_support.HUB
TEMPLATES = HUB / "templates"
SCRIPT = HUB / "client" / "skills_index.py"
TREE_UNIT = HUB / "systemd" / "kvb-orchestrator-tree.service"
FIELDS = {
    "page-composer.js": r'h\("textarea", \{"aria-label": "Message", [^}]*"data-skills": ""',
    "page-agent.js": r'h\("textarea", \{"aria-label": `Message to \$\{name\}`, placeholder: `Message to \$\{name\} …`, "data-skills": ""',
    "page-match.js": r'"aria-label": "Comment", [^}]*"data-skills": card\.repo \|\| ""',
    "page-dialog.js": r'"aria-label": `Other answer to \$\{item\.id\}`[^}]*"data-skills": item\.repo \|\| ""',
    "page-deny.js": r'placeholder: "e\.g\. make the gate green first", "data-skills": item\.repo \|\| ""',
    "page-inbox.js": r'placeholder: "e\.g\. make the gate green first", "data-skills": ""',
    "page-diff.js": r'"aria-label": "Comment", placeholder: "Comment on these lines", "data-skills": ""',
}
FEEDBACK = r'class: "field match-feedback", [^}]*"data-skills": card\.repo \|\| ""'
RANK = r"""
const fs = require("fs");
const vm = require("vm");
const context = {JSON, Math, Number, String, Array, Object, RegExp, Set, Map, Boolean, WeakSet, console};
const source = fs.readFileSync(process.argv[1], "utf8");
const skills = [
  {name: "kvb-org-robot", description: "", source: "~/.claude/skills"},
  {name: "kvb-org-radio", description: "", source: "~/.claude/skills"},
  {name: "kvb-org-radio", description: "", source: "~/.agents/skills"},
  {name: "kvb-org-rasci", description: "", source: "~/.claude/skills"},
  {name: "i8-alpha", description: "", source: "~/.claude/skills"},
  {name: "i8-zeta", description: "", source: "/repo"},
  {name: "make-kvb-org-r", description: "", source: "~/.claude/skills"},
];
const probe = `JSON.stringify({
  radio: slashRank(${JSON.stringify(skills)}, "kvb-org-r", "").map((skill) => skill.name),
  core: slashRank(${JSON.stringify(skills)}, "i8-", "/repo").map((skill) => skill.name),
  plain: slashRank(${JSON.stringify(skills)}, "i8-", "").map((skill) => skill.name),
  tokens: [slashToken("/kvb", 4), slashToken("say /kvb-org", 12), slashToken("a/b", 3), slashToken("path/to", 7), slashToken("x /", 3)],
  inserted: slashInsert("ask /kvb-org-r now", {start: 4, prefix: "kvb-org-r"}, 14, "kvb-org-radio"),
})`;
console.log(vm.runInNewContext(`${source}\n${probe}`, context));
"""


def skill(root: Path, folder: str, text: str | None) -> None:
    path = root / folder
    path.mkdir(parents=True)
    if text is not None:
        (path / "SKILL.md").write_text(text, encoding="utf-8")


class TestIndex(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.home, self.repo = self.root / "home", self.root / "repo"
        skill(self.home / ".claude/skills", "kvb-org-radio", "---\nname: kvb-org-radio\ndescription: Default channel to other agents.\n---\nbody\n")
        skill(self.home / ".agents/skills", "kvb-org-radio", "---\nname: kvb-org-radio\ndescription: \"Agents copy\"\n---\n")
        skill(self.home / ".agents/skills", "folded", "---\nname: folded\ndescription: >\n  Two lines\n  joined.\n---\n")
        skill(self.home / ".claude/skills", "no-file", None)
        skill(self.home / ".claude/skills", "bare", "---\nname: bare\n---\n")
        skill(self.repo / ".claude/skills", "i8-commit", "---\nname: i8-commit\ndescription: Commit the staged changes.\n---\n")
        skill(self.repo / ".claude/skills", "open", "---\nname: open\ndescription: never closed\n")
        self.tree = self.root / "branch-tree.json"
        self.tree.write_text(json.dumps({"repos": [{"path": str(self.repo)}, {"path": "relative"}]}), encoding="utf-8")

    def test_the_index_lists_every_source_once_per_name_and_source_without_paths_or_bodies(self):
        output = self.root / SKILLS_INDEX
        done = subprocess.run([sys.executable, str(SCRIPT), "--home", str(self.home), "--tree", str(self.tree), "--output", str(output)], capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        rows = json.loads(output.read_text(encoding="utf-8"))["skills"]
        self.assertEqual([(row["name"], row["source"], row["description"]) for row in rows], [
            ("bare", "~/.claude/skills", ""),
            ("folded", "~/.agents/skills", "Two lines joined."),
            ("i8-commit", str(self.repo), "Commit the staged changes."),
            ("kvb-org-radio", "~/.agents/skills", "Agents copy"),
            ("kvb-org-radio", "~/.claude/skills", "Default channel to other agents."),
            ("open", str(self.repo), ""),
        ])
        self.assertEqual({key for row in rows for key in row}, {"name", "description", "source"})

    def test_the_front_matter_parser_needs_an_opening_and_a_closing_rule(self):
        self.assertEqual(skills_index.front_matter("name: x\n"), {})
        self.assertEqual(skills_index.front_matter("---\nname: x\n"), {})
        self.assertEqual(skills_index.front_matter("---\nname: x\ndescription: 'quoted'\n---\n"), {"name": "x", "description": "quoted"})

    def test_the_tree_timer_writes_the_index_next_to_the_tree(self):
        starts = [line.split("=", 1)[1] for line in TREE_UNIT.read_text(encoding="utf-8").splitlines() if line.startswith("ExecStart=")]
        self.assertEqual(starts[2], "/usr/bin/env python3 %h/.local/share/kvb-orchestrator/client/skills_index.py --home %h --tree %h/.local/state/pkgmgr/tree/branch-tree.json --output %h/.local/state/pkgmgr/tree/skills-index.json")


class TestServed(unittest.TestCase):
    def test_the_hub_keeps_valid_rows_only_sorted_and_without_extra_keys(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        file = Path(folder.name) / SKILLS_INDEX
        self.assertEqual(served(file), {"skills": []})
        rows = [{"name": "zeta", "description": "z", "source": "~/.claude/skills", "path": "/home/x/SKILL.md"}, {"name": "has space", "description": "", "source": "x"}, {"name": "alpha", "description": 3, "source": "x"}, {"name": "alpha", "description": "a", "source": "~/.claude/skills"}, "row"]
        file.write_text(json.dumps({"skills": rows}), encoding="utf-8")
        self.assertEqual(served(file), {"skills": [{"name": "alpha", "description": "a", "source": "~/.claude/skills"}, {"name": "zeta", "description": "z", "source": "~/.claude/skills"}]})


class TestSuggestions(unittest.TestCase):
    def test_rank_token_and_insert(self):
        done = subprocess.run(["node", "-e", RANK, str(TEMPLATES / "page-slash.js")], capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        out = json.loads(done.stdout)
        self.assertEqual(out["radio"], ["kvb-org-radio", "kvb-org-rasci", "kvb-org-robot", "make-kvb-org-r"])
        self.assertEqual((out["core"], out["plain"]), (["i8-zeta", "i8-alpha"], ["i8-alpha", "i8-zeta"]))
        self.assertEqual(out["tokens"], [{"start": 0, "prefix": "kvb"}, {"start": 4, "prefix": "kvb-org"}, None, None, {"start": 2, "prefix": ""}])
        self.assertEqual(out["inserted"], {"value": "ask /kvb-org-radio  now", "caret": 19})

    def test_every_field_whose_text_reaches_an_agent_carries_the_marker(self):
        for name, pattern in FIELDS.items():
            with self.subTest(file=name):
                self.assertRegex((TEMPLATES / name).read_text(encoding="utf-8"), pattern)
        self.assertRegex((TEMPLATES / "page-match.js").read_text(encoding="utf-8"), FEEDBACK)
        self.assertIn('const SLASH_FIELDS = "textarea[data-skills], input[data-skills]";', (TEMPLATES / "page-slash.js").read_text(encoding="utf-8"))
        self.assertIn("slashWatch();", (TEMPLATES / "page-boot.js").read_text(encoding="utf-8"))
        self.assertEqual(re.findall(r'\{% include "page-(?:mic|slash)\.js" %\}', (TEMPLATES / "index.html.j2").read_text(encoding="utf-8")), ['{% include "page-mic.js" %}', '{% include "page-slash.js" %}'])


class TestSkillsRoute(HubCase):
    def test_api_skills_serves_the_index_and_follows_the_next_timer_run(self):
        index = self.tree_file.with_name(SKILLS_INDEX)
        self.assertEqual(json.loads(self.get("/api/skills")[2]), {"skills": []})
        index.write_text(json.dumps({"written": 1, "skills": [{"name": "kvb-org-radio", "description": "Radio", "source": "~/.claude/skills"}]}), encoding="utf-8")
        self.assertEqual(json.loads(self.get("/api/skills")[2])["skills"], [{"name": "kvb-org-radio", "description": "Radio", "source": "~/.claude/skills"}])
        index.write_text(json.dumps({"written": 2, "skills": [{"name": "new-skill", "description": "", "source": "~/.agents/skills"}, {"name": "kvb-org-radio", "description": "Radio", "source": "~/.claude/skills"}]}), encoding="utf-8")
        self.assertEqual([row["name"] for row in json.loads(self.get("/api/skills")[2])["skills"]], ["kvb-org-radio", "new-skill"])


if __name__ == "__main__":
    unittest.main()
