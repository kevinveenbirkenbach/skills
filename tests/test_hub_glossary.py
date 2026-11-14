from __future__ import annotations

import json
import re
import subprocess
import unittest

from hub_case import HubCase
from hub_support import HUB, signing

TEMPLATES = HUB / "templates"
GLOSSARY = TEMPLATES / "glossary.js"
ANCESTRY = TEMPLATES / "ancestry.js"
MODULES = ["page-constants.js", "glossary.js", "ancestry.js", "page-reveal.js", "page-dom.js", "page-ancestry.js"]
RESOLVED = {"commit": {"level": "test", "source": "feature/a"}, "merge": {"level": "quality-high", "source": "main"}, "push": {"level": "none", "source": None}, "pr": {"level": "e2e", "source": "feature/a"}}
CHIPS = ["commit: test (own rule)", "merge: quality-high (inherited from main)", "push: none (no rule)", "pr: e2e (own rule)"]
# Param: argv[1] is glossary.js, argv[2] ancestry.js, argv[3] the resolved gates; prints the glossary tables, chip texts and Explain sections.
PROBE = """
const G = require(process.argv[1]);
const A = require(process.argv[2]);
const marks = A.gateMarks("feature/a", {resolved: JSON.parse(process.argv[3])});
console.log(JSON.stringify({
  actions: A.ACTIONS, levels: A.LEVELS, gateActions: G.GATE_ACTIONS, gateLevels: G.GATE_LEVELS, sources: G.GATE_SOURCES, cycle: G.GATE_CYCLE, receipt: G.RECEIPT,
  ruleHints: G.RULE_HINTS, officeVerbs: G.OFFICE_VERBS, branchMarks: G.BRANCH_MARKS,
  chips: marks.map((mark) => G.gateChip(mark, null)),
  staged: [G.gateChip(marks[2], {level: "quality-high"}), G.gateChip(marks[0], {level: null})],
  explain: G.explain(),
}));
"""
# Param: argv[1] is the templates folder, argv[2] the module list and tree as JSON; prints the gate chips and the Explain block the page builds.
RENDER = r"""
const fs = require("fs");
const [dir, given] = [process.argv[1], JSON.parse(process.argv[2])];
const source = given.files.map((name) => fs.readFileSync(`${dir}/${name}`, "utf8")).join("\n");
class FakeNode {
  constructor(tag) { this.tag = tag; this.attrs = {}; this.children = []; this.on = []; }
  setAttribute(key, value) { this.attrs[key] = value; }
  append(...children) { this.children.push(...children); }
  addEventListener(name) { this.on.push(name); }
}
const stub = new Proxy(function () {}, {get: (target, key) => (key === Symbol.toPrimitive ? () => "" : key === Symbol.iterator ? [][Symbol.iterator].bind([]) : stub), apply: () => stub});
const sheet = new FakeNode("div");
const provided = {document: {createElement: (tag) => new FakeNode(tag), createElementNS: (ns, tag) => new FakeNode(tag), getElementById: (id) => (id === "emoji-bases" ? {textContent: "[]"} : sheet), addEventListener() {}}, Node: FakeNode, tree: given.tree};
const scope = new Proxy({}, {has: (target, key) => typeof key === "string" && (key in provided || !(key in globalThis)), get: (target, key) => (key === Symbol.unscopables ? undefined : key in provided ? provided[key] : stub)});
const page = new Function("scope", `with (scope) {\n${source}\nreturn {gateChips, gateExplain};\n}`)(scope);
const dump = (node) => (node instanceof FakeNode ? {tag: node.tag, attrs: node.attrs, on: node.on, children: node.children.map(dump)} : String(node));
console.log(JSON.stringify({chips: dump(page.gateChips("/r", "feature/a")), explain: dump(page.gateExplain())}));
"""


def text_of(node: dict | str) -> str:
    return node if isinstance(node, str) else "".join(text_of(child) for child in node["children"])


def find(node: dict | str, tag: str) -> list[dict]:
    if isinstance(node, str):
        return []
    return ([node] if node["tag"] == tag else []) + [hit for child in node["children"] for hit in find(child, tag)]


class TestGlossaryTables(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        done = subprocess.run(["node", "-e", PROBE, str(GLOSSARY), str(ANCESTRY), json.dumps(RESOLVED)], capture_output=True, text=True, timeout=60, check=True)
        cls.data = json.loads(done.stdout)

    def assertTexts(self, values: list[str]) -> None:
        for value in values:
            with self.subTest(value=value):
                self.assertIsInstance(value, str)
                self.assertGreater(len(value.strip()), 3)
                self.assertNotIn(chr(0x2014), value)

    def test_every_gate_action_and_level_of_gates_py_has_a_meaning(self):
        self.assertEqual(list(self.data["gateActions"]), list(signing.GATE_ACTIONS))
        self.assertEqual(list(self.data["gateLevels"]), list(signing.GATE_LEVELS))
        self.assertEqual((self.data["actions"], self.data["levels"]), (list(signing.GATE_ACTIONS), list(signing.GATE_LEVELS)))
        self.assertTexts([*self.data["gateActions"].values(), *self.data["gateLevels"].values()])

    def test_every_rule_hint_and_office_verb_keeps_its_key_and_has_a_text(self):
        kinds = re.search(r"const RULE_KINDS = \{([^}]*)\}", (TEMPLATES / "page-rules.js").read_text(encoding="utf-8")).group(1)
        self.assertEqual(sorted(self.data["ruleHints"]), sorted(re.findall(r"(\w+): \"", kinds)))
        self.assertEqual(sorted(self.data["ruleHints"]), ["ask", "decision", "review"])
        self.assertEqual(sorted(self.data["officeVerbs"]), ["appoint", "recall", "takeover"])
        self.assertTexts(list(self.data["ruleHints"].values()))
        for action, (verb, glyph, words) in self.data["officeVerbs"].items():
            with self.subTest(action=action):
                self.assertRegex(glyph, r"^bi-[a-z0-9-]+$")
                self.assertTexts([verb, words])

    def test_every_source_branch_mark_receipt_and_the_click_have_a_term_and_a_meaning(self):
        self.assertEqual(sorted(self.data["sources"]), ["inherited", "own", "staged", "unset"])
        pairs = [*self.data["sources"].values(), *self.data["branchMarks"].values(), self.data["receipt"], self.data["cycle"]]
        for pair in pairs:
            with self.subTest(pair=pair):
                self.assertEqual(len(pair), 2)
                self.assertTexts(pair)

    def test_a_chip_names_action_level_and_where_the_level_comes_from(self):
        self.assertEqual([chip["text"] for chip in self.data["chips"]], CHIPS)
        self.assertEqual([chip["text"] for chip in self.data["staged"]], ["push: quality-high (staged)", "commit: inherited (staged)"])

    def test_the_chip_tooltip_starts_with_the_chip_text_and_explains_action_level_source_and_click(self):
        tables = self.data
        merge = tables["chips"][1]["hint"].split("\n")
        self.assertEqual(merge, [
            CHIPS[1],
            f"merge: {tables['gateActions']['merge']}",
            f"quality-high: {tables['gateLevels']['quality-high']}",
            f"inherited from main: {tables['sources']['inherited'][1]}",
            f"{tables['cycle'][0]}: {tables['cycle'][1]}",
        ])
        dropped = tables["staged"][1]["hint"].split("\n")
        self.assertEqual(dropped[2:4], [f"inherited: {tables['sources']['inherited'][1]}", f"staged: {tables['sources']['staged'][1]}"])

    def test_explain_lists_every_term_of_the_glossary_once(self):
        sections = dict(self.data["explain"])
        self.assertEqual(list(sections), ["Gate actions", "Gate levels", "Where a level comes from", "Branch marks"])
        terms = [term for rows in sections.values() for term, _ in rows]
        self.assertEqual(len(terms), len(set(terms)))
        expected = [*signing.GATE_ACTIONS, *signing.GATE_LEVELS, self.data["receipt"][0], *(pair[0] for pair in self.data["sources"].values()), self.data["cycle"][0], *(pair[0] for pair in self.data["branchMarks"].values())]
        self.assertEqual(terms, expected)


class TestGlossarySource(unittest.TestCase):
    def test_rule_hints_and_office_verbs_are_written_only_in_the_glossary_and_re_exported_under_their_old_names(self):
        rules = (TEMPLATES / "page-rules.js").read_text(encoding="utf-8")
        offices = (TEMPLATES / "page-offices.js").read_text(encoding="utf-8")
        self.assertIn("  const RULE_HINTS = Glossary.RULE_HINTS;\n", rules)
        self.assertIn("  const OFFICE_VERBS = Glossary.OFFICE_VERBS;\n", offices)
        sources = {path.name: path.read_text(encoding="utf-8") for path in TEMPLATES.glob("*.js")}
        for words in ("Grants matching asks in matching directories", "Takes the recommended option", "council.py claim --operator on the host", "council.py release --operator on the host"):
            with self.subTest(words=words):
                self.assertEqual([name for name, text in sources.items() if words in text], ["glossary.js"])

    def test_the_glossary_module_parses_on_its_own(self):
        done = subprocess.run(["node", "--check", str(GLOSSARY)], capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(done.returncode, 0, done.stderr)


class TestGateChipsRender(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = {"data": {"gates": {"/r": {"feature/a": {"resolved": RESOLVED, "rules": {"commit": "test", "pr": "e2e"}, "parents": []}}}}}
        done = subprocess.run(["node", "-e", RENDER, str(TEMPLATES), json.dumps({"files": MODULES, "tree": tree})], capture_output=True, text=True, timeout=60, check=False)
        if done.returncode != 0:
            raise AssertionError(done.stderr.strip()[:800])
        cls.data = json.loads(done.stdout)

    def test_each_gate_is_a_focusable_text_chip_whose_aria_label_is_its_visible_text(self):
        group = self.data["chips"]
        self.assertEqual((group["tag"], group["attrs"]["role"], group["attrs"]["aria-label"]), ("span", "group", "Gates of feature/a"))
        buttons = [child for child in group["children"] if isinstance(child, dict)]
        self.assertEqual([button["tag"] for button in buttons], ["button"] * 4)
        for button, words in zip(buttons, CHIPS, strict=True):
            with self.subTest(chip=words):
                self.assertEqual(button["attrs"]["type"], "button")
                self.assertNotIn("tabindex", button["attrs"])
                self.assertNotIn("icon-only", button["attrs"]["class"].split())
                self.assertEqual(button["on"], ["click"])
                self.assertEqual(text_of(button), words)
                self.assertEqual(button["attrs"]["aria-label"], words)
                self.assertTrue(button["attrs"]["title"].startswith(f"{words}\n"))
        self.assertEqual([("inherited" in button["attrs"]["class"].split()) for button in buttons], [False, True, True, False])

    def test_the_explain_action_is_a_disclosure_listing_every_glossary_term(self):
        block = self.data["explain"]
        self.assertEqual((block["tag"], block["attrs"]["class"]), ("details", "gate-explain"))
        summary = block["children"][0]
        self.assertEqual((summary["tag"], text_of(summary)), ("summary", "Explain"))
        self.assertEqual([text_of(head) for head in find(block, "h4")], ["Gate actions", "Gate levels", "Where a level comes from", "Branch marks"])
        terms = [text_of(term) for term in find(block, "dt")]
        self.assertLessEqual({*signing.GATE_ACTIONS, *signing.GATE_LEVELS, "own rule", "inherited from", "no rule", "staged", "merged", "not merged", "Reason"}, set(terms))
        self.assertEqual(len(find(block, "dd")), len(terms))


class TestHubGlossary(HubCase):
    def test_the_page_ships_the_glossary_before_the_page_scripts_and_the_explain_icon(self):
        html = self.index()
        module = GLOSSARY.read_text(encoding="utf-8").strip()
        self.assertIn(module, html)
        self.assertLess(html.index(module), html.index("const RULE_HINTS = Glossary.RULE_HINTS;"))
        self.assertIn('<symbol id="bi-question-circle"', html)


if __name__ == "__main__":
    unittest.main()
