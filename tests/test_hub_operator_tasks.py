from __future__ import annotations

import ast
import importlib
import json
import os
import shlex
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from hub_case import HubCase
from hub_support import APPROVAL, ASK, GIT_ENV, HUB, PAGE
from kvb_orchestrator import diffs, fields, reviewing, signed

permission_hook = importlib.import_module("permission_hook")
staged_diff = importlib.import_module("staged_diff")
sandbox_paths = importlib.import_module("sandbox_paths")
hub_limits = importlib.import_module("hub_limits")
approval = importlib.import_module("approval")
TEMPLATES = HUB / "templates"
DIFFS = TEMPLATES / "diffs.js"
PAGE_MODULES = ["page-constants.js", "page-reveal.js", "page-dom.js", "page-diff.js", "page-inbox.js", "page-stream.js", "page-screens.js", "page-keyboard.js"]
SECRET = 'api_key = "plain-example-words"'
ARMOURED = "before\n-----BEGIN EXAMPLE-----\nplain words only\n-----END EXAMPLE-----\nafter\n"
WITHHELD = "content withheld"
ALLOW = {"behavior": "allow"}
RULES = """
rules:
- id: TEST-SECRET-1
  cwe: 'CWE-798: Use of Hard-coded Credentials'
  patterns:
  - api_key\\s*=\\s*["'][^"']{8,}["']
  file_types:
  - '*.py'
- id: TEST-OTHER-1
  cwe: CWE-200
  patterns:
  - print
  file_types:
  - '*.py'
"""
DIFFS_PROBE = """
const D = require(process.argv[1]);
const patch = ["@@ -3,3 +3,4 @@", " keep", "-old", "+new", "+more", " tail"].join("\\n");
console.log(JSON.stringify({
  rows: D.rows(patch).map((row) => [row.kind, row.line, row.old, row.new, row.text]),
  collapsed: [[400, 0], [200, 201], [0, 401]].map(([additions, deletions]) => D.collapsed({additions, deletions})),
  span: [D.span([7, 3, 5]), D.span([]), D.span([0, 2])],
  lineSpan: [D.lineSpan("make\\n  deploy\\n  now", "deploy\\n  now"), D.lineSpan("one line", "nope"), D.lineSpan("a\\nb", "")],
  feedback: D.feedback("review:0123456789abcdef", "src/app.py", 4, 5, "  -old\\n+new  ", "  use the helper  "),
  quoted: [D.quoted("x".repeat(D.QUOTE_LIMIT + 5)).length, D.QUOTE_LIMIT],
  picked: D.feedbackOf([{text: "Feedback on review:abc a:1-1: \\"q\\" t"}, {text: "Feedback on review:abcd a:1-1"}, {text: "hello"}], "review:abc").length,
}));
"""
PAGE_PROBE = r"""
const fs = require("fs");
const vm = require("vm");
const [dir, names] = [process.argv[1], JSON.parse(process.argv[2])];
class Node {}
class El extends Node {
  constructor(tag) { super(); Object.assign(this, {tag, attrs: {}, children: [], listeners: {}, hidden: false, className: "", style: {}, dataset: {}, disabled: false, value: ""}); }
  setAttribute(key, value) {
    this.attrs[key] = String(value);
    if (key === "class") { this.className = String(value); }
    if (key === "hidden") { this.hidden = true; }
    if (key === "disabled") { this.disabled = true; }
    if (key.startsWith("data-")) { this.dataset[key.slice(5).replace(/-(\w)/g, (_, c) => c.toUpperCase())] = String(value); }
  }
  getAttribute(key) { return Object.hasOwn(this.attrs, key) ? this.attrs[key] : null; }
  removeAttribute(key) { delete this.attrs[key]; }
  addEventListener(name, run) { (this.listeners[name] ||= []).push(run); }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  get firstChild() { return this.children[0] || null; }
  get textContent() { return this.children.map((child) => (typeof child === "string" ? child : child.textContent)).join(""); }
  set textContent(value) { this.children = [String(value)]; }
  focus() {}
  contains() { return false; }
  querySelector() { return null; }
  querySelectorAll() { return []; }
  click() { for (const run of this.listeners.click || []) { run({target: this, preventDefault() {}}); } }
}
const elements = new Map();
const document = {
  currentScript: null, title: "", body: new El("body"), activeElement: null,
  createElement: (tag) => new El(tag), createElementNS: (ns, tag) => new El(tag),
  getElementById: (id) => {
    if (!elements.has(id)) { const made = new El("div"); made.hidden = ["palette", "sheet"].includes(id); elements.set(id, made); }
    return elements.get(id);
  },
  querySelectorAll: () => [],
};
document.activeElement = document.body;
document.getElementById("emoji-bases").textContent = "[]";
const all =(node) => (typeof node === "string" ? [] : [node, ...node.children.flatMap(all)]);
const classes = (node) => String(node.className || node.attrs.class || "").split(" ").filter(Boolean);
const labels = (node) => all(node).filter((el) => el.tag === "button").map((el) => el.getAttribute("aria-label") || el.textContent);
const calls = {proofs: [], posts: [], sheets: [], radio: []};
const now = 1_800_000_000;
const base = {agent: "Skills", to: "Skills", detail: "", green: true, gate: "", score: "", warnings: [], options: [], recommended: "", command: "", directory: "", sha256: "", runnable: false, deniable: false, job: null, rule: null, dry_run: null, diff: null, pinned: false, until: 0, held: false, ts: now - 60};
const operator = {...base, kind: "operator", id: "operator/ship", title: "make ship", command: "make ship", directory: "/repo", detail: "release the build", runnable: true, deniable: true, green: false, sha256: "abc"};
const review = {...base, kind: "review", id: "0123456789abcdef", title: "feat: x", detail: "feature/x", gate: "pass", score: "🎯 95", directory: "/repo", diff: 4};
const ask = {...base, kind: "ask", id: "1123456789abcdef", title: "Bash: git commit -m x", command: "git commit -m x", directory: "/repo", deniable: true};
const decision = {...base, kind: "decision", id: "2123456789abcdef", title: "Merge?", options: [{label: "Now", description: ""}], recommended: "Now"};
const context = {
  console, Node, document, JSON, Math, Date, Intl, Promise, Set, Map, Number, String, Array, Object, RegExp, Boolean,
  window: {location: {hash: "", hostname: "localhost", port: "8737", pathname: "/"}, setTimeout: () => 0, clearTimeout: () => {}, setInterval: () => 0, clearInterval: () => {}, getSelection: () => null, innerWidth: 1366, innerHeight: 768, matchMedia: () => ({matches: false})},
  Nav: require(`${dir}/nav.js`), Diffs: require(`${dir}/diffs.js`), Faces: {of: () => ({parts: []}), SIZE: 64},
  state: {badges: {tasks: 3, agents: 0, artifacts: 1}, inbox: [operator, review, ask, decision], messages: [{id: "m1", text: "Feedback on review:0123456789abcdef a.py:1-2: \"x\" fix", created_ts: now}], people: {}, graph: {nodes: []}, silence: null, presence: {}, kinds: {operator: "Operator"}},
  ui: {screen: "inbox", views: {tasks: "list"}, selected: new Set(), cursor: 0, snoozed: false, busy: false, review: null, file: 0},
  KINDS: [["operator", "Operator"], ["review", "Review"]], speech: {current: null}, look: {hidden: new Set()}, settings: {}, known: {batches: new Set()},
  relative: new Intl.RelativeTimeFormat("en"), absolute: new Intl.DateTimeFormat("en"), calm: {matches: true}, drawn: {screen: "", sig: ""},
  proofFor: async (entries, label) => { calls.proofs.push({entries, label}); return {proof: {payload: "p", assertion: "a"}}; },
  sendJson: async (path, body) => { calls.posts.push({path, body}); return {ok: true, data: {id: "b1", due: now + 3}}; },
  radioSend: async (message) => { calls.radio.push(message); return true; },
  load: async () => {}, toast: () => {}, fail: () => [], undoToast: () => {},
  jobOpen: () => false, dismissJob: () => {}, consoleOf: () => null, settleConsoles: () => {}, repaintConsoles: () => {},
  withoutOutput: (item) => item, ruleRequestBody: () => null, acceptRule: () => null, reviewSheet: () => {}, openAgent: () => {}, confirmAct: () => {}, measure: () => {},
  openSheet: (title, body) => calls.sheets.push({title, body}), closeSheet: () => {}, emptyState: () => new El("div"), onLocalhost: () => true, localLink: () => null,
  focusSub: () => {}, openPalette: () => {}, closePalette: () => {}, skyLook: () => {}, popupDialog: () => ({open: false}), closePopup: () => {}, closeMenus: () => {}, helpSheet: () => {},
  space: {look: false}, stream: {events: [], entries: [], dom: null}, filter: {}, inboxDom: null, inboxSig: "", reviewDom: null, graphDom: null, tree: {}, taskView: {}, g3: {},
};
context.denySplit = () => {
  const button = new El("button");
  button.setAttribute("aria-label", "Deny");
  return button;
};
const source = names.map((name) => fs.readFileSync(`${dir}/${name}`, "utf8")).join("\n");
const probe = `
openSheet = (title, body) => calls.sheets.push({title, body});
const operatorCard = inboxItem(operator, 0);
const streamCard = eventRow({id: "e1", kind: "operator", waiting: true, ts: now, agent: "Skills", title: "make ship", text: "release the build", ref: {task: "operator/ship", directory: "/repo", status: "queued"}});
const plainCard = eventRow({id: "e2", kind: "operator", waiting: false, ts: now, agent: "Skills", title: "make other", text: "-", ref: {task: "operator/other", directory: "/repo", status: "done"}});
diffView.cache.set("review:0123456789abcdef", [
  {path: "src/app.py", status: "M", mode: "100644", additions: 2, deletions: 1, patch: "@@ -1,2 +1,3 @@\\n keep\\n-old\\n+new\\n+more", note: ""},
  {path: "logo.png", status: "B", mode: "100644", additions: 0, deletions: 0, patch: "", note: ""},
  {path: "big.txt", status: "M", mode: "100644 => 100755", additions: 300, deletions: 101, patch: "@@ -1 +1 @@\\n-a\\n+b", note: ""},
  {path: "late.txt", status: "A", mode: "100644", additions: 9, deletions: 0, patch: "", note: "content withheld"},
]);
const reviewCard = inboxItem(review, 1);
diffView.cache.set("ask:1123456789abcdef", [{path: "src/app.py", status: "M", mode: "100644", additions: 1, deletions: 0, patch: "@@ -1 +1,2 @@\\n keep\\n+new", note: ""}]);
const askCard = inboxItem({...ask, diff: 1}, 2);
const sections = all(reviewCard).filter((el) => classes(el).includes("diff-file"));
const read = (section) => {
  const details = all(section).find((el) => el.tag === "details") || null;
  const rows = all(section).filter((el) => el.tag === "tr");
  return {path: section.dataset.path, status: section.dataset.status, open: details ? details.getAttribute("open") !== null : null, table: rows.length > 0,
    rows: rows.map((row) => [classes(row).join(" "), row.dataset.line || null]),
    note: all(section).filter((el) => classes(el).includes("note")).map((el) => el.textContent), mode: all(section).filter((el) => classes(el).includes("mode")).map((el) => el.textContent),
    stat: all(section).filter((el) => classes(el).includes("add") || classes(el).includes("del")).filter((el) => el.tag === "span").map((el) => el.textContent)};
};
drawStatus();
const tasksBadge = navButtons.get("tasks").badge;
const badgeState = {keys: [...navButtons.keys()], text: tasksBadge.textContent, hidden: tasksBadge.hidden, urgent: tasksBadge.className, title: document.title};
state.badges = {tasks: 0, agents: 0, artifacts: 1};
drawStatus();
badgeState.zero = [tasksBadge.hidden, document.title];
const results = {
  operator: {classes: classes(operatorCard), checkbox: all(operatorCard).filter((el) => el.tag === "input" && el.attrs.type === "checkbox").length, ref: operatorCard.dataset.ref, to: operatorCard.dataset.to,
    command: all(operatorCard).filter((el) => classes(el).includes("command")).map((el) => [el.dataset.path, all(el).find((inner) => inner.tag === "code").textContent]),
    text: operatorCard.textContent, buttons: labels(operatorCard)},
  stream: {buttons: labels(streamCard), actions: all(streamCard).filter((el) => classes(el).includes("line-actions")).length, ref: streamCard.dataset.ref || null, plain: [labels(plainCard), plainCard.dataset.ref || null]},
  review: {ref: reviewCard.dataset.ref, files: sections.map(read), feedback: all(reviewCard).filter((el) => classes(el).includes("feedback-list")).map((el) => el.textContent)},
  status: badgeState,
  ask: {ref: askCard.dataset.ref, to: askCard.dataset.to, files: all(askCard).filter((el) => classes(el).includes("diff-file")).map((el) => [el.dataset.path, all(el).filter((inner) => inner.tag === "tr").length]),
    regions: all(askCard).filter((el) => el.dataset.path !== undefined).map((el) => el.dataset.path)},
};
bulk([operator, review, ask, decision], "Grant selection", false);
const sheet = calls.sheets.pop();
const confirm = all({children: sheet.body}).filter((el) => el.tag === "button").pop();
results.bulk = {label: confirm.textContent, shown: all({children: sheet.body}).filter((el) => el.tag === "li").length};
confirm.click();
feedbackSheet({ref: "review:0123456789abcdef", to: "Skills", path: "src/app.py", from: 2, until: 4, quote: "-old\\n+new"});
const form = calls.sheets.pop();
const area = all({children: form.body}).find((el) => el.tag === "textarea");
area.value = "  call the helper instead  ";
const send = all({children: form.body}).filter((el) => el.tag === "button").pop();
results.feedback = {title: form.title, send: [send.getAttribute("aria-label"), send.getAttribute("title")]};
send.click();
let prevented = false;
feedbackKey = () => true;
keyboard({key: "f", target: document.body, altKey: false, ctrlKey: false, metaKey: false, isComposing: false, preventDefault: () => { prevented = true; }});
results.key = prevented;
setTimeout(() => {
  results.proofs = calls.proofs.map((call) => call.entries.map((entry) => [entry.kind, entry.verb, entry.label]));
  results.posts = calls.posts.map((call) => [call.path, call.body.items.length, call.body.proof !== null]);
  results.radio = calls.radio;
  console.log(JSON.stringify(results));
}, 20);
`;
vm.runInNewContext(`${source}\n${probe}`, {...context, setTimeout, Element: El, HTMLElement: El, now, operator, review, ask, decision, calls, all, classes, labels});
"""


def git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, env={**os.environ, **GIT_ENV}, check=True, capture_output=True, text=True)
    return done.stdout


def scratch_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "app.py").write_text("keep = 1\nold = 2\n", encoding="utf-8")
    (repo / "gone.txt").write_text("bye\n", encoding="utf-8")
    (repo / "logo.png").write_bytes(b"\x89PNG\x00\x01")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    (repo / "app.py").write_text(f"keep = 1\nnew = 3\n{SECRET}\nprint(1)\n", encoding="utf-8")
    (repo / "added.txt").write_text("fresh\n", encoding="utf-8")
    (repo / "logo.png").write_bytes(b"\x89PNG\x00\x02")
    (repo / "gone.txt").unlink()
    git(repo, "add", "-A")
    return repo


def bytes_read() -> int:
    counters = dict(line.split(": ") for line in Path("/proc/self/io").read_text(encoding="ascii").splitlines())
    return int(counters["rchar"])


def deny(entries: object) -> dict:
    return {"sandbox": {"filesystem": {"denyRead": entries}}}


def write_settings(file: Path, content: object) -> None:
    file.parent.mkdir(parents=True, exist_ok=True)
    file.unlink(missing_ok=True)
    if content is not None:
        file.write_bytes(content if isinstance(content, bytes) else json.dumps(content).encode())


def rules_dir(root: Path) -> Path:
    folder = root / "rules" / "secrets"
    folder.mkdir(parents=True)
    (folder / "test.yaml").write_text(RULES, encoding="utf-8")
    return root / "rules"


def client_calls(tree: ast.AST) -> list[ast.Call]:
    return [node for node in ast.walk(tree) if isinstance(node, ast.Call) and "client_module" in (getattr(node.func, "id", ""), getattr(node.func, "attr", ""))]


class TestDiffsModule(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        done = subprocess.run(["node", "-e", DIFFS_PROBE, str(DIFFS)], capture_output=True, text=True, timeout=60, check=True)
        cls.data = json.loads(done.stdout)

    def test_a_patch_parses_into_unified_rows_with_both_line_numbers(self):
        self.assertEqual(self.data["rows"], [
            ["hunk", 1, "", "", "@@ -3,3 +3,4 @@"],
            ["ctx", 2, 3, 3, "keep"],
            ["del", 3, 4, "", "old"],
            ["add", 4, "", 4, "new"],
            ["add", 5, "", 5, "more"],
            ["ctx", 6, 5, 6, "tail"],
        ])

    def test_a_file_over_400_changed_lines_is_collapsed(self):
        self.assertEqual(self.data["collapsed"], [False, True, True])

    def test_selected_rows_and_command_quotes_give_a_line_range(self):
        self.assertEqual(self.data["span"], [[3, 7], None, [2, 2]])
        self.assertEqual(self.data["lineSpan"], [[2, 3], [1, 1], [1, 2]])

    def test_the_feedback_text_follows_the_contract(self):
        self.assertEqual(self.data["feedback"], 'Feedback on review:0123456789abcdef src/app.py:4-5: "-old\n+new" use the helper')
        self.assertEqual(self.data["quoted"], [2001, 2000])
        self.assertEqual(self.data["picked"], 1)


class TestOperatorPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        done = subprocess.run(["node", "-e", PAGE_PROBE, str(TEMPLATES), json.dumps(PAGE_MODULES)], capture_output=True, text=True, timeout=60, check=False)
        if done.returncode != 0:
            raise AssertionError(done.stderr[-4000:])
        cls.data = json.loads(done.stdout)

    def test_the_tasks_entry_carries_the_waiting_count_hidden_at_zero_and_no_inbox_entry_exists(self):
        status = self.data["status"]
        self.assertEqual(status["keys"], ["home", "stream", "rules", "agents", "artifacts", "tasks", "resources"])
        self.assertEqual((status["text"], status["hidden"], status["urgent"], status["title"]), ("3", False, "badge urgent", "(3) Agent Orchestrator"))
        self.assertEqual(status["zero"], [True, "Agent Orchestrator"])

    def test_an_operator_task_is_a_stream_card_with_a_checkbox_and_every_action(self):
        card = self.data["operator"]
        self.assertTrue({"item", "entry", "k-operator", "waiting"} <= set(card["classes"]), card["classes"])
        self.assertEqual((card["checkbox"], card["ref"], card["to"]), (1, "operator:operator/ship", "Skills"))
        self.assertEqual(card["command"], [["/repo", "make ship"]])
        for text in ("in /repo", "release the build"):
            with self.subTest(text=text):
                self.assertIn(text, card["text"])
        for label in ("Run", "Deny", "Copy", "1 h", "tomorrow", "pin"):
            with self.subTest(label=label):
                self.assertIn(label, card["buttons"])

    def test_the_stream_keeps_its_operator_card_with_its_actions(self):
        stream = self.data["stream"]
        self.assertEqual((stream["actions"], stream["ref"]), (1, "operator:operator/ship"))
        self.assertIn("Run", stream["buttons"])
        self.assertIn("Deny", stream["buttons"])
        self.assertEqual(stream["plain"], [["Skills", "Copy"], None])

    def test_a_review_card_shows_one_unified_block_per_file_expanded_collapsed_past_400_lines_and_binary_named_only(self):
        files = self.data["review"]["files"]
        self.assertEqual([(entry["path"], entry["status"], entry["open"], entry["table"]) for entry in files], [
            ("src/app.py", "M", True, True), ("logo.png", "B", None, False), ("big.txt", "M", False, True), ("late.txt", "A", None, False),
        ])
        self.assertEqual(files[0]["rows"], [["hunk", None], ["ctx", "1"], ["del", "2"], ["add", "2"], ["add", "3"]])
        self.assertEqual((files[0]["note"], files[0]["mode"], files[0]["stat"]), ([], [], ["+2", "-1"]))
        self.assertEqual((files[2]["mode"], files[3]["note"], files[3]["stat"]), (["100644 => 100755"], [WITHHELD], ["+9", "-0"]))

    def test_a_commit_ask_shows_its_diff_like_a_review_and_its_command_and_files_take_feedback(self):
        ask = self.data["ask"]
        self.assertEqual((ask["ref"], ask["to"], ask["files"]), ("ask:1123456789abcdef", "Skills", [["src/app.py", 3]]))
        self.assertEqual(ask["regions"], ["/repo", "src/app.py"])

    def test_sent_feedback_shows_under_its_card(self):
        self.assertEqual(len(self.data["review"]["feedback"]), 1)
        self.assertIn('a.py:1-2: "x" fix', self.data["review"]["feedback"][0])

    def test_the_bulk_bar_counts_and_grants_asks_reviews_operator_commands_and_choices_with_one_signature(self):
        self.assertEqual(self.data["bulk"], {"label": "Grant 4", "shown": 4})
        self.assertEqual(self.data["proofs"], [[["operator", "approve", ""], ["review", "approve", ""], ["ask", "approve", ""], ["decision", "approve", "Now"]]])
        self.assertEqual(self.data["posts"], [["/api/inbox/approve", 4, True]])

    def test_feedback_is_one_signed_post_to_the_requesting_agent_in_the_contract_format_and_the_key_f_opens_it(self):
        self.assertEqual(self.data["feedback"]["title"], "Feedback")
        self.assertEqual(self.data["feedback"]["send"], ["Send feedback", "Send feedback: a post to Skills"])
        self.assertEqual(self.data["radio"], [{"to": "Skills", "text": 'Feedback on review:0123456789abcdef src/app.py:2-4: "-old\n+new" call the helper instead', "upload": "", "cls": "post", "voice": ""}])
        self.assertTrue(self.data["key"])


class TestStagedDiff(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(os.path.realpath(tmp.name))
        self.repo = scratch_repo(self.root)
        self.rules = rules_dir(self.root)
        for patch in (
            mock.patch.object(staged_diff, "CACHE", self.root / "cache" / "secret-rules.json"),
            mock.patch.object(sandbox_paths, "MANAGED", self.root / "managed"),
            mock.patch.dict(os.environ, {"HOME": str(self.root), "CLAUDE_CONFIG_DIR": str(self.root / ".claude"), "CLAUDE_PROJECT_DIR": str(self.root / "project")}),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def test_the_staged_diff_lists_each_file_once_and_a_file_matching_a_secret_rule_ships_only_its_counts_and_the_note(self):
        found = {entry["path"]: entry for entry in staged_diff.review_diff(self.repo, False, self.rules)}
        self.assertEqual(sorted(found), ["added.txt", "app.py", "gone.txt", "logo.png"])
        self.assertEqual({path: (entry["status"], entry["mode"], entry["additions"], entry["deletions"], entry["note"]) for path, entry in found.items()}, {
            "added.txt": ("A", "100644", 1, 0, ""), "app.py": ("M", "100644", 3, 1, WITHHELD), "gone.txt": ("D", "100644", 0, 1, ""), "logo.png": ("B", "100644", 0, 0, ""),
        })
        self.assertEqual([found[path]["patch"] for path in ("added.txt", "app.py", "gone.txt", "logo.png")], ["@@ -0,0 +1 @@\n+fresh", "", "@@ -1 +0,0 @@\n-bye", ""])
        self.assertNotIn("plain-example", json.dumps(list(found.values())))
        self.assertFalse(hasattr(staged_diff, "masked"))
        self.assertEqual(diffs.valid_diff(list(found.values())), [found[path] for path in sorted(found)])

    def test_an_armour_line_in_the_old_or_the_new_blob_withholds_the_whole_file(self):
        (self.repo / "key.txt").write_text(ARMOURED, encoding="utf-8")
        (self.repo / "plain.txt").write_text("plain\n", encoding="utf-8")
        git(self.repo, "add", "key.txt", "plain.txt")
        git(self.repo, "commit", "-q", "-m", "armour")
        (self.repo / "key.txt").write_text("before\nafter\n", encoding="utf-8")
        (self.repo / "plain.txt").write_text("plain\n-----BEGIN lowercase is no armour-----\n", encoding="utf-8")
        (self.repo / "fresh.txt").write_text(ARMOURED, encoding="utf-8")
        git(self.repo, "add", "key.txt", "plain.txt", "fresh.txt")
        found = {entry["path"]: entry for entry in staged_diff.review_diff(self.repo, False, self.rules)}
        self.assertEqual([(found[path]["patch"], found[path]["note"], found[path]["deletions"]) for path in ("key.txt", "fresh.txt")], [("", WITHHELD, 3), ("", WITHHELD, 0)])
        self.assertEqual((found["plain.txt"]["note"], found["plain.txt"]["additions"]), ("", 1))
        self.assertNotIn("plain words only", json.dumps(list(found.values())))

    def test_past_the_cap_the_rest_is_listed_by_stat_only(self):
        with mock.patch.object(staged_diff, "DIFF_LIMIT", 40):
            found = staged_diff.review_diff(self.repo, False, self.rules)
        self.assertEqual([(entry["path"], bool(entry["patch"]), entry["note"]) for entry in found], [("added.txt", True, ""), ("app.py", False, WITHHELD), ("gone.txt", False, ""), ("logo.png", False, "")])
        self.assertEqual([(entry["additions"], entry["deletions"]) for entry in found], [(1, 0), (3, 1), (0, 1), (0, 0)])

    def test_without_secret_rules_or_with_a_broken_rule_file_every_text_file_is_withheld(self):
        broken = self.root / "broken-rules"
        broken.mkdir()
        (broken / "bad.yaml").write_text("cwe: CWE-798\nrules: [unclosed\n", encoding="utf-8")
        for rules in (None, self.root / "missing", broken):
            with self.subTest(rules=str(rules)):
                found = staged_diff.review_diff(self.repo, False, rules)
                self.assertEqual([(entry["patch"], entry["note"]) for entry in found], [("", WITHHELD)] * 3 + [("", "")])
        self.assertIsNone(staged_diff.secret_rules(broken))

    def test_the_diff_fails_past_the_file_cap_or_the_path_limit_instead_of_the_hub_refusing_it(self):
        for name, value in (("FILE_CAP", 3), ("PATH_LIMIT", 8)):
            with self.subTest(limit=name), mock.patch.object(staged_diff, name, value), self.assertRaises(staged_diff.DiffError):
                staged_diff.review_diff(self.repo, False, self.rules)
        self.assertEqual((staged_diff.FILE_CAP, staged_diff.PATH_LIMIT, diffs.FILE_CAP, diffs.PATH_LIMIT), (hub_limits.FILE_CAP, hub_limits.PATH_LIMIT) * 2)

    def test_commit_all_shows_the_executable_bit_on_disk(self):
        (self.repo / "added.txt").chmod(0o755)
        everything = {entry["path"]: entry for entry in staged_diff.review_diff(self.repo, True, self.rules)}
        self.assertEqual((everything["added.txt"]["mode"], everything["app.py"]["mode"]), ("100755", "100644"))
        git(self.repo, "commit", "-q", "-m", "next")
        found = {entry["path"]: entry for entry in staged_diff.review_diff(self.repo, True, self.rules)}
        self.assertEqual((found["added.txt"]["status"], found["added.txt"]["mode"], found["added.txt"]["additions"]), ("M", "100644 => 100755", 0))
        self.assertEqual(staged_diff.review_diff(self.repo, False, self.rules), [])

    def test_commit_all_diffs_the_tracked_working_tree_against_head_without_untracked_files(self):
        (self.repo / "added.txt").write_text("fresh\nlater\n", encoding="utf-8")
        (self.repo / "untracked.txt").write_text("not mine\n", encoding="utf-8")
        staged = {entry["path"]: entry["additions"] for entry in staged_diff.review_diff(self.repo, False, self.rules)}
        everything = {entry["path"]: entry["additions"] for entry in staged_diff.review_diff(self.repo, True, self.rules)}
        self.assertEqual((staged["added.txt"], everything["added.txt"]), (1, 2))
        self.assertNotIn("untracked.txt", everything)

    def test_a_planted_fsmonitor_or_clean_filter_starts_no_program(self):
        marker = self.root / "ran"
        git(self.repo, "config", "core.fsmonitor", f"touch {marker}")
        git(self.repo, "config", "filter.evil.clean", f"touch {marker}; cat")
        (self.repo / ".gitattributes").write_text("* filter=evil\n", encoding="utf-8")
        for everything in (False, True):
            staged_diff.review_diff(self.repo, everything, self.rules)
        self.assertFalse(marker.exists())

    def test_a_planted_promisor_remote_fetches_no_missing_object_and_starts_no_program(self):
        marker = self.root / "fetched"
        oid = git(self.repo, "rev-parse", "HEAD:app.py").strip()
        (self.repo / ".git" / "objects" / oid[:2] / oid[2:]).unlink()
        promisor = {
            "core.repositoryformatversion": "1", "extensions.partialClone": "origin", "remote.origin.url": str(self.root),
            "remote.origin.promisor": "true", "remote.origin.uploadpack": f"touch {shlex.quote(str(marker))} && false",
        }
        for key, value in promisor.items():
            git(self.repo, "config", key, value)
        for everything in (False, True):
            with self.subTest(everything=everything), self.assertRaises(staged_diff.DiffError):
                staged_diff.review_diff(self.repo, everything, self.rules)
        self.assertFalse(marker.exists())

    def test_commit_all_reads_no_file_behind_a_symlinked_parent_directory(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "key").write_text("stolen = 1\n", encoding="utf-8")
        for folder in ("k", "d"):
            (self.repo / folder).mkdir()
            (self.repo / folder / "key").write_text("mine = 1\n", encoding="utf-8")
        (self.repo / "d" / "link").symlink_to("key")
        git(self.repo, "add", "k", "d")
        (self.repo / "k" / "key").unlink()
        (self.repo / "k").rmdir()
        (self.repo / "k").symlink_to(outside)
        found = {entry["path"]: entry for entry in staged_diff.review_diff(self.repo, True, self.rules)}
        self.assertEqual([found[path]["patch"] for path in ("d/key", "d/link")], ["@@ -0,0 +1 @@\n+mine = 1", "@@ -0,0 +1 @@\n+key"])
        self.assertNotIn("k/key", found)
        self.assertNotIn("stolen", json.dumps(list(found.values())))

    def test_an_index_path_leaving_the_working_tree_is_refused(self):
        (self.root / "outside.txt").write_text("stolen = 1\n", encoding="utf-8")
        for path in ("../outside.txt", "d/../../outside.txt", str(self.root / "outside.txt")):
            with self.subTest(path=path), self.assertRaises(staged_diff.DiffError):
                staged_diff.worktree(self.repo, path, "100644", "sha1", [])

    def test_a_fifo_in_the_working_tree_is_skipped_without_blocking(self):
        os.mkfifo(self.repo / "pipe")
        found = []
        reader = threading.Thread(target=lambda: found.append(staged_diff.worktree(self.repo, "pipe", "100644", "sha1", [])), daemon=True)
        reader.start()
        reader.join(10)
        self.assertEqual(found, [None])

    def test_a_working_tree_file_over_the_blob_limit_is_not_read(self):
        with (self.repo / "big.bin").open("wb") as handle:
            handle.truncate(4 * staged_diff.BLOB_LIMIT)
        before = bytes_read()
        found = staged_diff.worktree(self.repo, "big.bin", "100644", "sha1", [])
        self.assertLess(bytes_read() - before, staged_diff.BLOB_LIMIT)
        self.assertEqual((found[0], found[2]), ("100644", None))

    def test_commit_all_reads_no_file_under_a_deny_read_path_and_still_reads_its_sibling(self):
        (self.repo / "vault").mkdir()
        (self.repo / "vault" / "key").write_text("stolen = 1\n", encoding="utf-8")
        (self.repo / "open.txt").write_text("seen = 1\n", encoding="utf-8")
        git(self.repo, "add", "vault", "open.txt")
        write_settings(self.repo / ".claude" / "settings.local.json", deny(["~/repo/vault"]))
        found = {entry["path"]: entry for entry in staged_diff.review_diff(self.repo, True, self.rules)}
        self.assertEqual([found[path]["patch"] for path in ("vault/key", "open.txt")], ["", "@@ -0,0 +1 @@\n+seen = 1"])
        self.assertNotIn("stolen", json.dumps(list(found.values())))

    def test_commit_all_without_any_settings_file_diffs_normal_files(self):
        self.assertEqual([file for file, _ in sandbox_paths.settings_files(self.repo) if file.exists()], [])
        found = {entry["path"]: entry for entry in staged_diff.review_diff(self.repo, True, self.rules)}
        self.assertEqual((found["added.txt"]["patch"], found["app.py"]["additions"]), ("@@ -0,0 +1 @@\n+fresh", 3))

    def test_a_planted_empty_deny_read_list_still_leaves_the_floor_unread(self):
        (self.repo / ".ssh").mkdir()
        (self.repo / ".ssh" / "id_ed25519").write_text("stolen = 1\n", encoding="utf-8")
        (self.repo / "notes.txt").write_text("seen = 1\n", encoding="utf-8")
        git(self.repo, "add", ".ssh", "notes.txt")
        write_settings(self.repo / ".claude" / "settings.json", deny([]))
        with mock.patch.dict(os.environ, {"HOME": str(self.repo)}):
            found = {entry["path"]: entry for entry in staged_diff.review_diff(self.repo, True, self.rules)}
        self.assertEqual([found[path]["patch"] for path in (".ssh/id_ed25519", "notes.txt")], ["", "@@ -0,0 +1 @@\n+seen = 1"])
        self.assertNotIn("stolen", json.dumps(list(found.values())))

    def test_commit_all_fails_closed_on_an_unreadable_deny_read_setting_or_in_a_denied_working_tree(self):
        cases = {"unparsable": b"{", "no utf-8": b"\xff", "no paths": deny("~/x"), "denied top": deny(["~"])}
        for case, content in cases.items():
            with self.subTest(case=case):
                write_settings(self.root / ".claude" / "settings.json", content)
                for everything in (True, False):
                    with self.assertRaises(staged_diff.DiffError):
                        staged_diff.review_diff(self.repo, everything, self.rules)

    def test_the_staged_diff_ships_no_content_under_a_denied_path(self):
        (self.repo / "vault").mkdir()
        (self.repo / "vault" / "key").write_text("stolen = 1\n", encoding="utf-8")
        git(self.repo, "add", "vault")
        write_settings(self.repo / ".claude" / "settings.json", deny(["vault"]))
        found = {entry["path"]: entry for entry in staged_diff.review_diff(self.repo, False, self.rules)}
        self.assertEqual((found["vault/key"]["status"], found["vault/key"]["patch"], found["added.txt"]["patch"]), ("A", "", "@@ -0,0 +1 @@\n+fresh"))

    def test_the_session_project_settings_and_read_rules_add_denies(self):
        (self.repo / "vault").mkdir()
        for name in ("vault/key", "notes.txt", "deep.pem", "open.txt"):
            (self.repo / name).write_text("stolen = 1\n" if name != "open.txt" else "seen = 1\n", encoding="utf-8")
        git(self.repo, "add", "vault", "notes.txt", "deep.pem", "open.txt")
        write_settings(self.root / "project" / ".claude" / "settings.local.json", deny(["~/repo/vault"]))
        write_settings(self.repo / ".claude" / "settings.json", {"permissions": {"deny": ["Read(/notes.txt)", "Bash(rm:*)"]}})
        write_settings(self.root / ".claude" / "settings.json", {"permissions": {"deny": ["Read(*.pem)"]}})
        found = {entry["path"]: entry["patch"] for entry in staged_diff.review_diff(self.repo, True, self.rules)}
        self.assertEqual([found[path] for path in ("vault/key", "notes.txt", "deep.pem", "open.txt")], ["", "", "", "@@ -0,0 +1 @@\n+seen = 1"])

    def test_each_settings_scope_resolves_relative_entries_from_its_own_folder_and_read_rules_like_claude_code(self):
        managed = self.root / "managed"
        write_settings(managed / "managed-settings.json", deny(["held"]))
        write_settings(self.root / ".claude" / "settings.json", {**deny(["mine"]), "permissions": {"deny": ["Read(//abs/x)", "Read(~/h)", "Read(/s)", "Read(./r/q)", "Read"]}})
        write_settings(self.repo / ".claude" / "settings.json", deny(["vault"]))
        roots = set(sandbox_paths.denied_roots(self.repo))
        expected = {managed / "held", self.root / ".claude" / "mine", self.repo / "vault", Path("/abs/x"), self.root / "h", self.root / ".claude" / "s", self.repo / "r" / "q", Path("/")}
        self.assertLessEqual({str(path) for path in expected}, roots)
        (managed / "managed-settings.d").write_text("no folder", encoding="utf-8")
        with self.assertRaises(sandbox_paths.Unreadable):
            sandbox_paths.denied_roots(self.repo)

    def test_a_double_star_read_rule_also_matches_no_folder_at_all(self):
        write_settings(self.repo / ".claude" / "settings.json", {"permissions": {"deny": ["Read(**/.env)", "Read(conf/**/secret/**/key)"]}})
        roots = sandbox_paths.denied_roots(self.repo)
        for path in (".env", "deep/er/.env", "conf/secret/key", "conf/a/secret/key", "conf/secret/b/key", "conf/a/secret/b/key"):
            with self.subTest(path=path):
                self.assertTrue(sandbox_paths.denied(str(self.repo / path), roots))
        self.assertFalse(sandbox_paths.denied(str(self.repo / "env.txt"), roots))
        (self.repo / ".env").write_text("hidden = 1\n", encoding="utf-8")
        git(self.repo, "add", ".env")
        found = {entry["path"]: entry for entry in staged_diff.review_diff(self.repo, True, self.rules)}
        self.assertEqual((found[".env"]["patch"], found["added.txt"]["patch"]), ("", "@@ -0,0 +1 @@\n+fresh"))

    def test_an_allow_turns_into_a_deny_when_the_staged_tree_changed_since_the_preview_even_in_a_file_it_withholds(self):
        ask = {**ASK, "tool": "Bash", "command": "git commit -m x", "cwd": str(self.repo)}
        changed = {"behavior": "deny", "message": "staged tree changed since the preview"}
        edits = {
            "withheld content": lambda: (self.repo / "app.py").write_text(f"{SECRET}\nslipped in\n", encoding="utf-8"),
            "mode only": lambda: (self.repo / "added.txt").chmod(0o755),
            "binary": lambda: (self.repo / "logo.png").write_bytes(b"\x89PNG\x00\x03"),
        }
        for case, edit in edits.items():
            with self.subTest(case=case):
                git(self.repo, "add", "-A")
                pinned, shown = permission_hook.commit_diff(ask, self.rules)
                self.assertEqual((pinned, len(shown["diff"])), (git(self.repo, "write-tree").strip(), len(shown["diff"])))
                self.assertEqual(permission_hook.bound(ALLOW, ask, pinned), ALLOW)
                edit()
                self.assertEqual(permission_hook.bound(ALLOW, ask, pinned), ALLOW)
                git(self.repo, "add", "-A")
                self.assertEqual(permission_hook.bound(ALLOW, ask, pinned), changed)
                self.assertEqual(permission_hook.bound({"behavior": "deny", "message": "no"}, ask, pinned), {"behavior": "deny", "message": "no"})

    def test_an_allow_of_commit_all_is_bound_to_the_working_tree_too(self):
        ask = {**ASK, "tool": "Bash", "command": "git commit -am x", "cwd": str(self.repo)}
        pinned, shown = permission_hook.commit_diff(ask, self.rules)
        self.assertEqual([entry["path"] for entry in shown["diff"]], ["added.txt", "app.py", "gone.txt", "logo.png"])
        self.assertEqual(permission_hook.bound(ALLOW, ask, pinned), ALLOW)
        (self.repo / "app.py").write_text("unstaged edit\n", encoding="utf-8")
        self.assertEqual(permission_hook.bound(ALLOW, ask, pinned)["behavior"], "deny")

    def test_an_allow_fails_closed_with_a_reason_when_the_tree_cannot_be_read(self):
        ask = {**ASK, "tool": "Bash", "command": "git commit -m x", "cwd": str(self.repo)}
        pinned, _ = permission_hook.commit_diff(ask, self.rules)
        self.assertEqual(permission_hook.bound(ALLOW, ask, None), {"behavior": "deny", "message": permission_hook.UNBOUND})
        for error in (staged_diff.DiffError("git write-tree failed: broken\x07index"), OSError("gone"), ValueError("no ascii")):
            with self.subTest(error=type(error).__name__), mock.patch.object(staged_diff, "binding", side_effect=error):
                chosen = permission_hook.bound(ALLOW, ask, pinned)
                self.assertEqual(chosen["behavior"], "deny")
                self.assertTrue(chosen["message"].startswith(f"{permission_hook.UNBOUND}: "), chosen)
                self.assertNotIn("\x07", chosen["message"])
        with mock.patch.object(staged_diff, "binding", side_effect=staged_diff.DiffError("unmerged")):
            self.assertEqual(permission_hook.commit_diff(ask, self.rules), (None, {}))
        self.assertEqual(permission_hook.bound(ALLOW, {**ASK, "command": "make deploy"}, None), ALLOW)

    def test_the_tree_diff_shows_the_written_tree_not_the_live_index(self):
        tree = git(self.repo, "write-tree").strip()
        before = staged_diff.tree_diff(self.repo, tree, self.rules)
        (self.repo / "added.txt").write_text("fresh\nslipped in\n", encoding="utf-8")
        git(self.repo, "add", "added.txt")
        self.assertEqual(staged_diff.tree_diff(self.repo, tree, self.rules), before)
        self.assertNotEqual(staged_diff.review_diff(self.repo, False, self.rules), before)

    def test_without_a_secret_pattern_no_patch_ships(self):
        empty = self.root / "empty-rules"
        empty.mkdir()
        (empty / "none.yaml").write_text("rules: []\n", encoding="utf-8")
        self.assertEqual({(entry["patch"], entry["note"]) for entry in staged_diff.review_diff(self.repo, False, empty)}, {("", WITHHELD), ("", "")})

    def test_a_file_name_that_is_no_utf8_ships_as_backslash_escapes(self):
        (self.repo / os.fsdecode(b"caf\xe9.txt")).write_text("x\n", encoding="utf-8")
        git(self.repo, "add", "-A")
        found = staged_diff.review_diff(self.repo, False, self.rules)
        self.assertIn("caf\\xe9.txt", [entry["path"] for entry in found])
        json.dumps(found, ensure_ascii=False).encode("utf-8")

    def test_only_an_unborn_head_counts_as_empty_and_lines_split_on_newlines_only(self):
        tree = git(self.repo, "rev-parse", "HEAD^{tree}").strip()
        (self.repo / "added.txt").write_text("one\x0ctwo\n", encoding="utf-8")
        git(self.repo, "add", "added.txt")
        self.assertEqual(next(entry for entry in staged_diff.review_diff(self.repo, False, self.rules) if entry["path"] == "added.txt")["additions"], 1)
        (self.repo / ".git" / "objects" / tree[:2] / tree[2:]).unlink()
        with self.assertRaises(staged_diff.DiffError):
            staged_diff.review_diff(self.repo, False, self.rules)

    def test_a_head_naming_a_missing_commit_or_a_broken_ref_fails_and_only_an_unborn_one_is_empty(self):
        fresh = self.root / "fresh"
        fresh.mkdir()
        git(fresh, "init", "-q", "-b", "main")
        (fresh / "one.txt").write_text("one\n", encoding="utf-8")
        git(fresh, "add", "one.txt")
        self.assertEqual([(entry["path"], entry["status"]) for entry in staged_diff.review_diff(fresh, False, self.rules)], [("one.txt", "A")])
        commit = git(self.repo, "rev-parse", "HEAD").strip()
        (self.repo / ".git" / "objects" / commit[:2] / commit[2:]).unlink()
        with self.assertRaises(staged_diff.DiffError):
            staged_diff.review_diff(self.repo, False, self.rules)
        (self.repo / ".git" / "refs" / "heads" / "main").write_text("not a ref\n", encoding="utf-8")
        with self.assertRaises(staged_diff.DiffError):
            staged_diff.review_diff(self.repo, False, self.rules)

    def test_the_rules_are_cached_until_a_rule_file_changes(self):
        first = staged_diff.secret_rules(self.rules)
        with mock.patch.object(staged_diff, "parsed_rules", side_effect=AssertionError("parsed again")):
            self.assertEqual([[globs, [p.pattern for p in found]] for globs, found in staged_diff.secret_rules(self.rules)], [[globs, [p.pattern for p in found]] for globs, found in first])
        self.assertEqual([globs for globs, _ in first], [("*.py",)])

    def test_a_changed_rule_file_or_a_broken_cache_parses_the_rules_again(self):
        staged_diff.secret_rules(self.rules)
        rule_file = self.rules / "secrets" / "test.yaml"
        rule_file.write_text(RULES.replace("'*.py'", "'*.txt'"), encoding="utf-8")
        self.assertEqual([globs for globs, _ in staged_diff.secret_rules(self.rules)], [("*.txt",)])
        for broken in ('{"signature": "x", "rules": 1}', "[]", "{", json.dumps({"signature": json.loads(staged_diff.CACHE.read_text(encoding="utf-8"))["signature"], "rules": 1})):
            with self.subTest(cache=broken):
                staged_diff.CACHE.write_text(broken, encoding="utf-8")
                self.assertEqual([globs for globs, _ in staged_diff.secret_rules(self.rules)], [("*.txt",)])

    def test_only_a_single_git_commit_names_its_directory_and_all_mode(self):
        cases = {
            "git commit -m 'feat: x'": ("/w", False),
            "git commit -am 'feat: x'": ("/w", True),
            "git commit -m all -a": ("/w", True),
            "git commit --all --no-verify -m x": ("/w", True),
            "git commit -ma": ("/w", False),
            "git -C sub commit -m x": ("/w/sub", False),
            "GIT_EDITOR=true git commit": ("/w", False),
            "env -C sub git commit -m x": ("/w/sub", False),
            "env --chdir=sub GIT_EDITOR=true git -C deeper commit -am x": ("/w/sub/deeper", True),
            "git commit -m x -- -a": None,
            "git commit -m x file.txt": None,
            "git commit -a -m x file.txt": None,
            "git commit -o -m x": None,
            "git commit --only -m x": None,
            "git commit -i -m x": None,
            "git commit --include -m x": None,
            "git commit -p": None,
            "git commit --pathspec-from-file=list": None,
            "git commit --pathspec-from=list": None,
            "git commit --pathspec-f=list": None,
            "git commit --inc -m x": None,
            "git commit --on -m x": None,
            "git commit --inter -m x": None,
            "git commit -a --no-all -m x": None,
            "git commit --al -m x": None,
            "git commit --frobnicate -m x": None,
            "git commit --mess 'feat: x' --no-veri": ("/w", False),
            "git commit --all-m": None,
            "git commit -U 3 -m x": ("/w", False),
            "git commit --unified 3 -am x": ("/w", True),
            "GIT_INDEX_FILE=/tmp/other git commit -m x": None,
            "GIT_DIR=/tmp/other git commit -m x": None,
            "env GIT_WORK_TREE=/tmp/other git commit -m x": None,
            "env -i git commit -m x": None,
            "git -c core.worktree=/tmp/other commit -m x": None,
            "git status": None,
            "cd x && git commit -a": None,
            "git commit -m 'x' ; rm -rf /": None,
            "echo git commit": None,
            "git commit -m 'unterminated": None,
        }
        for command, expected in cases.items():
            with self.subTest(command=command):
                found = staged_diff.commit_of(command, "/w")
                self.assertEqual(None if found is None else (str(found[0]), found[1]), expected)


class TestHubOperatorTasks(HubCase):
    def scratch(self) -> tuple[Path, Path, dict]:
        root = self.outside / "w1"
        root.mkdir()
        home = root / "home"
        home.mkdir()
        claude = {"HOME": str(home), "CLAUDE_CONFIG_DIR": str(home / ".claude"), "CLAUDE_PROJECT_DIR": str(root)}
        return scratch_repo(root), rules_dir(root), {**os.environ, **GIT_ENV, **claude, "XDG_CACHE_HOME": str(home / ".cache")}

    def test_approval_request_ships_the_masked_staged_diff_with_the_review_and_the_card_reads_it(self):
        repo, rules, env = self.scratch()
        notes = self.outside / "table.txt"
        notes.write_text("🎯 95 💥 3", encoding="utf-8")
        page = self.page("w1.html", PAGE)
        command = [sys.executable, str(APPROVAL), "request", "--port", str(self.port), "--title", "feat: w1", "--page", page, "--notes", str(notes), "--gate", "pass", "--score", "🎯 95 💥 3", "--agent", "Skills", "--rules", str(rules)]
        done = subprocess.run(command, cwd=repo, env=env, capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        answer = json.loads(done.stdout)
        self.assertEqual((answer["status"], answer["url"]), ("pending", f"{self.origin}/"))
        item = next(item for item in self.snapshot()["inbox"] if item["id"] == answer["id"])
        self.assertEqual((item["kind"], item["diff"], item["agent"], item["to"]), ("review", 4, "Skills", "Skills"))
        status, _, body = self.get(f"/api/diffs/review/{answer['id']}")
        self.assertEqual(status, 200, body)
        shipped = json.loads(body)["diff"]
        self.assertEqual([(entry["path"], entry["status"], entry["note"]) for entry in shipped], [("added.txt", "A", ""), ("app.py", "M", WITHHELD), ("gone.txt", "D", ""), ("logo.png", "B", "")])
        self.assertNotIn(b"plain-example", body)
        self.assertEqual(self.tool("review_status", {"id": answer["id"]})["structuredContent"]["tree"], git(repo, "write-tree").strip())
        for path in ("/api/diffs/review/0123456789abcdef", f"/api/diffs/ask/{answer['id']}", f"/api/diffs/decision/{answer['id']}"):
            with self.subTest(path=path):
                self.assertEqual(self.get(path)[0], 404)

    def test_a_review_request_takes_a_diff_past_the_old_body_limit_and_refuses_a_broken_one(self):
        big = [{"path": f"f{index}.txt", "status": "A", "mode": "100644", "additions": 1, "deletions": 0, "patch": "@@ -0,0 +1 @@\n+" + "x" * 300_000, "note": ""} for index in range(5)]
        arguments = {**self.arguments("feat: big", "", self.page("big.html", PAGE)), "agent": "Skills", "diff": big}
        result = self.tool("review_request", arguments)
        self.assertFalse(result["isError"], result)
        self.assertEqual(len(json.loads(self.get(f"/api/diffs/review/{result['structuredContent']['id']}")[2])["diff"]), 5)
        good = {"path": "a", "status": "M", "mode": "100644 => 100755", "additions": 1, "deletions": 0, "patch": "@@ -1 +1 @@\n+x", "note": ""}
        self.assertFalse(self.tool("review_request", {**arguments, "diff": [good, {**good, "path": "b", "patch": "", "note": WITHHELD}]})["isError"])
        for broken in ([{**good, "status": "X"}], [{**good, "status": "B"}], [{**good, "mode": "755"}], [{**good, "note": "masked"}], [{**good, "note": WITHHELD}], [{**good, "masked": []}],
                       [{**good, "extra": 1}], [{**good, "additions": -1}], {"a": 1}, [{**good, "path": "p" * (hub_limits.PATH_LIMIT + 1)}], [good] * (hub_limits.FILE_CAP + 1),
                       [{**good, "patch": "x" * (diffs.DIFF_LIMIT + 1)}]):
            with self.subTest(broken=str(broken)[:60]):
                self.assertTrue(self.tool("review_request", {**arguments, "diff": broken})["isError"])

    def test_approval_request_refuses_notes_past_the_hub_limit_instead_of_cutting_them(self):
        repo, rules, env = self.scratch()
        notes = self.outside / "long.txt"
        notes.write_text("x" * (hub_limits.NOTES_LIMIT + 1), encoding="utf-8")
        command = [sys.executable, str(APPROVAL), "request", "--port", str(self.port), "--title", "feat: w1", "--page", self.page("long.html", PAGE), "--notes", str(notes), "--gate", "pass", "--score", "🎯 95 💥 3", "--agent", "Skills", "--rules", str(rules)]
        done = subprocess.run(command, cwd=repo, env=env, capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual((done.returncode, done.stdout), (1, ""))
        self.assertIn(f"at most {hub_limits.NOTES_LIMIT}", done.stderr)

    def test_the_hook_attaches_the_staged_diff_to_a_git_commit_ask_and_nothing_to_other_commands(self):
        repo, rules, env = self.scratch()
        with mock.patch.object(staged_diff, "CACHE", self.outside / "cache.json"), mock.patch.dict(os.environ, {key: env[key] for key in ("HOME", "CLAUDE_CONFIG_DIR", "CLAUDE_PROJECT_DIR")}):
            commit = {**ASK, "command": "git commit -m 'feat: w1'", "cwd": str(repo)}
            pinned, attached = permission_hook.commit_diff(commit, rules)
            self.assertEqual(([entry["path"] for entry in attached["diff"]], pinned), (["added.txt", "app.py", "gone.txt", "logo.png"], git(repo, "write-tree").strip()))
            self.assertEqual(permission_hook.commit_diff({**commit, "command": "make deploy"}, rules), (None, {}))
            self.assertEqual(permission_hook.commit_diff({**commit, "tool": "Write"}, rules), (None, {}))
            self.assertEqual(permission_hook.commit_diff({**commit, "cwd": str(self.outside / "nowhere")}, rules), (None, {}))
            ask = {key: commit[key] for key in ("tool", "command", "cwd", "session", "agent")}
            ask_id = permission_hook.create(f"http://{self.host}", ask, 60, permission_hook.commit_diff(ask, rules)[1])
        item = next(item for item in self.snapshot()["inbox"] if item["id"] == ask_id)
        self.assertEqual((item["kind"], item["diff"]), ("ask", 4))
        status, _, body = self.get(f"/api/diffs/ask/{ask_id}")
        self.assertEqual((status, [entry["status"] for entry in json.loads(body)["diff"]]), (200, ["A", "M", "D", "B"]))
        plain = self.create_ask(ASK)
        self.assertIsNone(next(item for item in self.snapshot()["inbox"] if item["id"] == plain)["diff"])
        self.assertEqual(self.post_json("/api/asks", {**ASK, "diff": [{"path": "a"}]}, self.local())[0], 400)

    def test_an_ask_whose_encoded_body_passes_the_hub_limit_goes_without_its_diff_instead_of_a_413(self):
        wide = "\U0001f600" * (hub_limits.DIFF_LIMIT // 4 - 16)
        diff = [{"path": "wide.txt", "status": "A", "mode": "100644", "additions": 1, "deletions": 0, "patch": f"@@ -0,0 +1 @@\n+{wide}", "note": ""}]
        self.assertEqual(diffs.valid_diff(diff), diff)
        ask = {key: ASK[key] for key in ("tool", "command", "cwd", "session", "agent")}
        self.assertGreater(len(permission_hook.encoded({**ask, "timeout": 60, "diff": diff})), hub_limits.DIFF_BODY_LIMIT)
        ask_id = permission_hook.create(f"http://{self.host}", ask, 60, {"diff": diff})
        self.assertIsNone(next(item for item in self.snapshot()["inbox"] if item["id"] == ask_id)["diff"])
        small = permission_hook.create(f"http://{self.host}", ask, 60, {"diff": [{**diff[0], "patch": "@@ -0,0 +1 @@\n+\U0001f600"}]})
        self.assertEqual(next(item for item in self.snapshot()["inbox"] if item["id"] == small)["diff"], 1)

    def test_approval_request_with_a_broken_rule_file_withholds_every_text_file_and_exits_0(self):
        repo, rules, env = self.scratch()
        (rules / "secrets" / "test.yaml").write_text("cwe: CWE-798\nrules: [unclosed\n", encoding="utf-8")
        notes = self.outside / "broken.txt"
        notes.write_text("notes", encoding="utf-8")
        command = [sys.executable, str(APPROVAL), "request", "--port", str(self.port), "--title", "feat: w1", "--page", self.page("broken.html", PAGE), "--notes", str(notes), "--gate", "pass", "--score", "🎯 95 💥 3", "--agent", "Skills", "--rules", str(rules)]
        done = subprocess.run(command, cwd=repo, env=env, capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertNotIn("Traceback", done.stderr)
        shipped = json.loads(self.get(f"/api/diffs/review/{json.loads(done.stdout)['id']}")[2])["diff"]
        self.assertEqual([(entry["patch"], entry["note"]) for entry in shipped], [("", WITHHELD)] * 3 + [("", "")])


class TestSharedLimits(unittest.TestCase):
    def test_the_client_and_the_hub_take_each_limit_from_hub_limits(self):
        self.assertEqual(Path(signed.limits.__file__).resolve(), (HUB / "client" / "hub_limits.py").resolve())
        self.assertEqual((staged_diff.DIFF_LIMIT, diffs.DIFF_LIMIT, reviewing.NOTES_LIMIT), (hub_limits.DIFF_LIMIT, hub_limits.DIFF_LIMIT, hub_limits.NOTES_LIMIT))
        self.assertEqual((diffs.DIFF_BODY_LIMIT, diffs.FILE_CAP, diffs.PATH_LIMIT, fields.PATH_LIMIT, permission_hook.PATH_LIMIT), (hub_limits.DIFF_BODY_LIMIT, hub_limits.FILE_CAP, *[hub_limits.PATH_LIMIT] * 3))
        self.assertEqual((staged_diff.WITHHELD, diffs.NOTES), (WITHHELD, ("", WITHHELD)))
        self.assertTrue(fields.PATH.fullmatch("/" + "p" * (hub_limits.PATH_LIMIT - 1)))
        self.assertFalse(fields.PATH.fullmatch("/" + "p" * hub_limits.PATH_LIMIT))

    def test_the_encoded_worst_case_body_without_a_diff_fits_the_hub_body_limit_non_ascii_included(self):
        chars = ("x", "\x01", "é", " ", "\U0001f600")
        widest = {ascii_only: max(chars, key=lambda char: len(json.dumps(char, ensure_ascii=ascii_only).encode("utf-8"))) for ascii_only in (True, False)}
        self.assertEqual((widest[True], widest[False]), ("\U0001f600", "\x01"))
        ask = {name: widest[True] * limit for name, limit in permission_hook.LIMITS.items()}
        self.assertLessEqual(len(permission_hook.encoded({**ask, "timeout": float(1 << 60)})), hub_limits.DIFF_BODY_LIMIT)
        wide, path = widest[False], "/" + widest[False] * (hub_limits.PATH_LIMIT - 1)
        arguments = {"repo": path, "worktree": path, "branch": "b" * 255, "tree": "0" * 64, "title": wide * 200, "page": path, "notes": wide * hub_limits.NOTES_LIMIT,
                     "gate": "pass", "score": wide * reviewing.SCORE_LIMIT, "agent": wide * 200}
        self.assertLessEqual(len(approval.review_body(arguments)), hub_limits.DIFF_BODY_LIMIT)
        patch = "+" + widest[True] * (hub_limits.DIFF_LIMIT // 4 - 2)
        self.assertLessEqual(len(json.dumps(patch, ensure_ascii=False).encode("utf-8")), hub_limits.DIFF_LIMIT)
        self.assertGreater(len(permission_hook.encoded({"diff": [{"patch": patch}]})), hub_limits.DIFF_BODY_LIMIT)

    def test_client_module_calls_are_found_bare_and_as_attributes(self):
        found = client_calls(ast.parse('signed.client_module("a", {})\nclient_module("b", {})\nother("c")\nx.other("d")'))
        self.assertEqual([node.args[0].value for node in found], ["a", "b"])

    def test_the_hub_image_copies_every_client_module_the_hub_loads(self):
        trees = [ast.parse(path.read_text(encoding="utf-8")) for path in sorted((HUB / "kvb_orchestrator").glob("*.py"))]
        calls = [node for tree in trees for node in client_calls(tree)]
        self.assertTrue(all(node.args and isinstance(node.args[0], ast.Constant) for node in calls))
        loaded = {f"{node.args[0].value}.py" for node in calls}
        copies = [line.split()[1:] for line in (HUB / "Dockerfile").read_text(encoding="utf-8").splitlines() if line.startswith("COPY ")]
        copied = {Path(source).name for words in copies if words[-1] == "/app/client/" for source in words[:-1]}
        self.assertLessEqual({"hub_limits.py", "queue_live.py"}, loaded)
        self.assertLessEqual(loaded, copied)


if __name__ == "__main__":
    unittest.main()
