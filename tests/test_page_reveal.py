from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from hub_support import signing

TEMPLATES = Path(__file__).resolve().parent.parent / "orchestrator" / "templates"
MODULES = ["page-constants.js", "ancestry.js", "page-reveal.js", "page-dom.js", "page-diff.js", "page-rule-request.js", "page-inbox.js", "page-firewall.js", "page-review.js", "page-cleanup.js", "page-offices.js", "page-ancestry.js", "page-tasks-prio.js"]
RLO, ZWSP, LRI, SEPARATOR, CARRIAGE = chr(0x202E), chr(0x200B), chr(0x2066), chr(0x2028), chr(0x0D)
FILLER, NBSP, CGJ, VS15, VS16 = chr(0x3164), chr(0xA0), chr(0x34F), chr(0xFE0E), chr(0xFE0F)
HIDDEN = (RLO, ZWSP, LRI, SEPARATOR, CARRIAGE, FILLER, NBSP, CGJ, VS16)
STOPWATCH, SHIELD, HEART = chr(0x23F1), chr(0x1F6E1), chr(0x2764)
CONTEXTS = (
    ("score line", f"🎯 fix 93 · {STOPWATCH}{VS16} time 20 · {SHIELD}{VS16} security 100", True),
    ("text presentation", f"{STOPWATCH}{VS15} 20", True),
    ("heart", f"thanks {HEART}{VS16}", True),
    ("stacked selectors", f"{STOPWATCH}{VS16}{VS16} 20", False),
    ("joiner after a sequence", f"{SHIELD}{VS16}{chr(0x200D)}", False),
    ("leading selector", f"{VS16}stop {STOPWATCH}", False),
    ("ASCII letter", f"a{VS16}", False),
    ("combining mark", f"e{chr(0x301)}{VS16}", False),
    ("keycap", f"1{VS16}{chr(0x20E3)}", False),
    ("number sign", f"#{VS16}", False),
    ("command", f"make test{VS16}", False),
    ("emoji without a sequence", f"🎯{VS16}", False),
    ("other selector", f"{STOPWATCH}{chr(0xFE00)}", False),
    ("no-break space", f"rm{NBSP}-rf", False),
    ("Hangul filler", f"main{FILLER}", False),
)
HARNESS = r"""const fs = require("fs");
const [dir, given] = [process.argv[2], JSON.parse(fs.readFileSync(process.argv[3], "utf8"))];
const source = given.files.map((name) => fs.readFileSync(`${dir}/${name}`, "utf8")).join("\n");
class FakeNode {
  constructor(tag) { this.tag = tag; this.attrs = {}; this.children = []; }
  setAttribute(key, value) { this.attrs[key] = value; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  addEventListener() {}
  focus() {}
  get value() { return this.attrs.value ?? ""; }
}
const stub = new Proxy(function () {}, {get: (target, key) => (key === Symbol.toPrimitive ? () => "" : key === Symbol.iterator ? [][Symbol.iterator].bind([]) : stub), apply: () => stub});
const sheet = new FakeNode("div");
const provided = {document: {createElement: (tag) => new FakeNode(tag), createElementNS: (ns, tag) => new FakeNode(tag), getElementById: (id) => (id === "emoji-bases" ? {textContent: JSON.stringify(given.bases)} : sheet), addEventListener() {}}, Node: FakeNode, ...given.globals};
const scope = new Proxy({}, {has: (target, key) => typeof key === "string" && (key in provided || !(key in globalThis)), get: (target, key) => (key === Symbol.unscopables ? undefined : key in provided ? provided[key] : stub)});
const page = new Function("scope", `with (scope) {\n${source}\nreturn {${given.calls.map(([name]) => name).join(", ")}};\n}`)(scope);
const own = (node) => [node.attrs.title, node.textContent].filter((text) => typeof text === "string");
const texts = (node) => (typeof node === "string" ? [node] : Array.isArray(node) ? node.flatMap(texts) : node instanceof FakeNode ? [...own(node), ...node.children.flatMap(texts)] : []);
console.log(JSON.stringify(given.calls.map(([name, args]) => {
  const drawn = page[name](...args);
  return texts(drawn === undefined ? sheet : drawn);
})));
"""
PROBE = r"""const fs = require("fs");
const given = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const revealed = new Function("document", `${fs.readFileSync(process.argv[1], "utf8")}\nreturn revealed;`)({getElementById: () => ({textContent: JSON.stringify(given.bases)})});
console.log(JSON.stringify(given.texts.map(revealed)));
"""


def shown(templates: Path, calls: list[list[object]], globals_: dict | None = None) -> list[list[str]]:
    """Args:
        templates: the folder of the page modules.
        calls: each [function, arguments] of the page to render.
        globals_: page state the calls read, such as state, ui and tree.

    Returns:
        Every text, text content and title each rendered node shows, or the
        sheet a call opens, in order.
    """
    with tempfile.TemporaryDirectory() as scratch:
        harness, given = Path(scratch) / "harness.js", Path(scratch) / "given.json"
        harness.write_text(HARNESS, encoding="utf-8")
        given.write_text(json.dumps({"files": MODULES, "calls": calls, "globals": globals_ or {}, "bases": sorted(signing.EMOJI_BASES)}), encoding="utf-8")
        done = subprocess.run(["node", str(harness), str(templates), str(given)], capture_output=True, text=True, timeout=60, check=False)
    if done.returncode != 0:
        raise AssertionError(done.stderr.strip()[:800])
    return json.loads(done.stdout)


def item(kind: str, **fields: object) -> dict:
    base = {"kind": kind, "id": "0123456789abcdef", "title": "Bash: make test", "command": "", "directory": "", "agent": "Skills", "to": "Skills", "ts": 1_800_000_000, "warnings": [], "options": [], "recommended": "", "held": False, "until": 0, "pinned": False, "diff": None, "job": None, "rule": None, "detail": "", "green": False, "gate": "", "score": "", "runnable": True, "deniable": True, "sha256": ""}
    return {**base, **fields}


@unittest.skipUnless(shutil.which("node"), "no node")
class TestPageReveal(unittest.TestCase):
    def assertRevealed(self, texts: list[str], codes: list[str]) -> None:
        joined = "\n".join(texts)
        for char in HIDDEN:
            self.assertNotIn(char, joined)
        for code in codes:
            self.assertIn(f"⟨U+{code}⟩", joined)

    def test_the_sink_marks_every_control_format_separator_and_ignorable_character_but_the_tab(self):
        probe = "".join(chr(code) for code in (0x202E, 0x200B, 0x2028, 0x2029, 0x85, 0x0B, 0x0D, 0x0A, 0x34F, 0xFE0F, 0x3164, 0xE0041, 0xAD, 0xA0, 0x3000))
        found = shown(TEMPLATES, [["revealed", [f"a{probe}\tb ✓"]], ["revealedLines", [f"one{NBSP}\ntwo"]]])
        self.assertEqual(found, [["a⟨U+202E⟩⟨U+200B⟩⟨U+2028⟩⟨U+2029⟩⟨U+0085⟩⟨U+000B⟩⟨U+000D⟩⟨U+000A⟩⟨U+034F⟩⟨U+FE0F⟩⟨U+3164⟩⟨U+E0041⟩⟨U+00AD⟩⟨U+00A0⟩⟨U+3000⟩\tb ✓"], ["one⟨U+00A0⟩\ntwo"]])

    def test_both_sinks_accept_exactly_an_emoji_variation_sequence(self):
        with tempfile.TemporaryDirectory() as scratch:
            given = Path(scratch) / "given.json"
            given.write_text(json.dumps({"bases": sorted(signing.EMOJI_BASES), "texts": [text for _, text, _ in CONTEXTS]}), encoding="utf-8")
            done = subprocess.run(["node", "-e", PROBE, str(TEMPLATES / "page-reveal.js"), str(given)], capture_output=True, text=True, timeout=60, check=True)
        for (name, text, accepted), page in zip(CONTEXTS, json.loads(done.stdout), strict=True):
            with self.subTest(name=name):
                self.assertEqual(signing.hidden_problem({"command": text}, "value") is None, accepted)
                self.assertEqual(page == text, accepted)
                self.assertEqual("⟨U+" in page, not accepted)

    def test_the_variation_table_names_its_source_and_holds_no_ascii_base(self):
        table = json.loads(signing.EMOJI_TABLE.read_text(encoding="utf-8"))
        self.assertEqual(sorted(table), ["bases", "source", "unicode"])
        self.assertEqual(table["source"], f"https://www.unicode.org/Public/{table['unicode']}/ucd/emoji/emoji-variation-sequences.txt")
        self.assertEqual(min(signing.EMOJI_BASES), 0xA9)
        self.assertLessEqual({0x23F1, 0x1F6E1, 0x2764, 0x26A0}, signing.EMOJI_BASES)

    def test_a_variation_table_with_a_wrong_base_stops_the_load(self):
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / "emoji-variation.json"
            for name, bases in (("short ASCII base", ["41"]), ("number sign base", ["0023"]), ("digit base", ["0031"]),("string value", "23F1"), ("object value", {"23F1": 1}), ("number", [0x23F1]), ("C1 control", ["009B"]), ("joiner", ["200D"]), ("surrogate", ["D800"]), ("lower case", ["23f1"])):
                with self.subTest(name=name):
                    path.write_text(json.dumps({"bases": bases}), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        signing.variation_table(path)
            path.write_text(json.dumps({"bases": ["23F1", "1F6E1"]}), encoding="utf-8")
            self.assertEqual(signing.variation_table(path), {0x23F1, 0x1F6E1})
            path.unlink()
            with self.assertRaises(OSError):
                signing.variation_table(path)

    def test_a_review_cleanup_office_ancestry_and_task_preview_show_every_look_alike_character_as_a_marker(self):
        review = {"id": "r1", "title": f"feat: x{RLO}", "notes": f"score{NBSP}90\nline{CGJ}", "created_ts": 1_800_000_000, "worktree": "/repo/.worktrees/x", "branch": f"main{FILLER}", "tree": "a" * 40, "gate": "pass", "score": f"🎯{VS16} 90", "status": "pending"}
        repo = {"path": "/r", "name": "skills", "branches": [{"name": f"main{FILLER}", "plan": [f"git branch -D main{FILLER}"], "held": None}, {"name": "feature/a", "plan": [], "held": None}]}
        page_state = {
            "state": {"reviews": [review], "inbox": [], "jobs": [{"kind": "task", "task": "T1", "command": f"rasci.py set T1{RLO} --prio 3", "status": "done"}], "graph": {"nodes": []}, "claims": []},
            "ui": {"review": None, "file": 0},
            "tree": {"data": {"repos": [repo], "gates": {"/r": {"feature/a": {"parents": [{"parent": f"main{FILLER}", "source": "own"}], "rules": {}}}}}},
        }
        calls = [
            ["reviewSheet", ["r1"]],
            ["deleteDialog", [[{"repository": "/r", "branch": f"main{FILLER}", "tip": "b" * 40}]]],
            ["officeSheet", ["takeover", {"office": f"work/x{FILLER}", "session": "s1", "work": "-"}]],
            ["branchAncestry", [repo]],
            ["priorityForm", [{"task": f"T1{FILLER}", "estimates": {}, "prio": 3}]],
            ["taskJobs", [{"task": "T1"}]],
        ]
        found = shown(TEMPLATES, calls, page_state)
        self.assertRevealed(found[0], ["202E", "3164", "00A0", "034F", "FE0F"])
        for drawn in found[1:5]:
            self.assertRevealed(drawn, ["3164"])
        self.assertRevealed(found[5], ["202E"])

    def test_an_inbox_ask_operator_row_and_decision_show_every_hidden_character_as_a_marker(self):
        ask = item("ask", command=f"git status{RLO} && rm -rf ~", directory=f"/repo{ZWSP}", agent=f"Skills{RLO}")
        operator = item("operator", id="operator/run", title=f"make{CARRIAGE} test", command=f"make{CARRIAGE} test", directory=f"/repo{LRI}", detail=f"why{SEPARATOR}not")
        decision = item("decision", title=f"Merge{RLO}?", options=[{"label": f"Merge now{RLO}", "description": f"Gate{ZWSP} is green"}], recommended=f"Merge now{RLO}")
        found = shown(TEMPLATES, [["inboxItem", [ask, 0]], ["inboxItem", [operator, 1]], ["inboxItem", [decision, 2]]])
        self.assertRevealed(found[0], ["202E", "200B"])
        self.assertRevealed(found[1], ["000D", "2066", "2028"])
        self.assertRevealed(found[2], ["202E", "200B"])

    def test_a_diff_row_and_a_rule_request_show_every_hidden_character_as_a_marker(self):
        rule = item("rule", detail=f"needed{ZWSP} daily", rule={"kind": "ask", "tool": "Bash", "pattern": f"make test{RLO}*", "scope": f"/repo{SEPARATOR}*", "expires": 1_800_000_000}, dry_run={"matched": 0, "total": 0, "days": 7})
        found = shown(TEMPLATES, [["patchRow", [{"kind": "add", "old": None, "new": 3, "text": f"access = 'user'{RLO} # admin"}]], ["ruleRequestBody", [rule]]])
        self.assertRevealed(found[0], ["202E"])
        self.assertRevealed(found[1], ["200B", "202E", "2028"])

    def test_a_settings_entry_staged_for_removal_and_its_diff_show_every_hidden_character_as_a_marker(self):
        entry = f"Read(~/.ssh/**{RLO})"
        found = shown(TEMPLATES, [["entryRow", ["/home/op/.claude/settings.json", "permissions.deny", entry]], ["diffLines", [f'-      "{entry}",\n+      "Bash(make{ZWSP} build:*)"']]])
        self.assertRevealed(found[0], ["202E"])
        self.assertRevealed(found[1], ["202E", "200B"])


if __name__ == "__main__":
    unittest.main()
