from __future__ import annotations

import json
import subprocess
import unittest

from hub_support import HUB

TEMPLATES = HUB / "templates"
MODULES = ["page-constants.js", "page-reveal.js", "page-dom.js", "page-dialog.js", "page-api.js", "page-passkey.js", "page-diff.js", "page-deny.js", "page-inbox.js", "page-grant.js", "page-console.js", "page-rule-request.js", "page-load.js"]
GONE = "operator/gui-agentbox-merge-push"
NOTICE = "already done or removed elsewhere"
PROBE = r"""
const fs = require("fs");
const vm = require("vm");
const [dir, names, GONE] = [process.argv[1], JSON.parse(process.argv[2]), process.argv[3]];
class El {
  constructor() { Object.assign(this, {children: [], attrs: {}, dataset: {}, style: {}, textContent: ""}); }
  setAttribute(key, value) { this.attrs[key] = String(value); }
  append(...nodes) { this.children.push(...nodes); }
  addEventListener() {}
  remove() {}
}
const document = {
  currentScript: null, body: new El(), hidden: false,
  getElementById: (id) => Object.assign(new El(), {textContent: id === "emoji-bases" ? "[]" : ""}),
  createElement: () => new El(), createElementNS: () => new El(),
};
const now = 1_800_000_000;
const base = {agent: "Store", to: "Store", detail: "", green: false, gate: "", score: "", warnings: [], options: [], recommended: "", command: "", directory: "/repo", sha256: "s", runnable: true, deniable: true, job: null, rule: null, dry_run: null, diff: null, pinned: false, until: 0, held: false, ts: now, reviews: []};
const row = (id, command, extra) => ({...base, kind: "operator", id, title: command, command, ...extra});
const items = {
  gone: row(GONE, "git merge --no-ff --no-verify -F msg"),
  kept: row("operator/kept", "echo kept"),
  later: row("operator/later", "echo later"),
  closed: row("operator/closed", "echo closed", {runnable: false, deniable: false, job: {id: "0123456789abcdef", status: "done", code: 0, output: "", created_ts: now, started: now, finished: now}}),
  rule: {...base, kind: "rule", id: "1123456789abcdef", title: "Rule ask Bash make deploy", runnable: false},
};
const context = {
  console, document, JSON, Math, Date, Intl, Promise, Set, Map, Number, String, Array, Object, RegExp, Boolean, Error, AbortController, setTimeout, setImmediate,
  window: {location: {hash: "", hostname: "localhost", port: "8737", pathname: "/"}, setTimeout: () => 0, clearTimeout: () => {}, setInterval: () => 0, clearInterval: () => {}, getSelection: () => "", matchMedia: () => ({matches: false})},
  ResizeObserver: class { observe() {} unobserve() {} },
  state: {inbox: [], radio: [], settings: {}, now}, inboxDom: null,
  ui: {screen: "inbox", busy: false, selected: new Set(), cursor: 0, snoozed: false, asOf: null, playing: false, offline: false},
  known: {batches: new Set()}, motion: {current: new Map([["x", {}]]), asOf: null}, settingsSig: "{}",
  windowQuery: () => "", adoptSettings: () => {}, tuneMusic: () => {}, drawSky: () => {}, announce: () => {}, drawTime: () => {}, drawAgent: () => {}, relayout: () => {}, pulses: () => {}, tick: () => {}, forgetRevealed: () => {},
  GONE, items, now,
};
const source = names.map((name) => fs.readFileSync(`${dir}/${name}`, "utf8")).join("\n");
const probe = `
const fresh = load;
const toasts = [];
const posts = [];
let renders = [];
let atLoad = null;
let loads = 0;
let reloaded = null;
let replies = {};
toast = (title, lines, good) => { toasts.push([title, lines, good]); return {remove() {}}; };
render = (force) => { renders.push(force); };
drawStream = () => {};
load = async () => {
  loads += 1;
  atLoad = atLoad || state.inbox.map((item) => item.id);
  if (reloaded) {
    state.inbox = reloaded.map((key) => ({...items[key]}));
  }
};
fetch = async (path) => {
  posts.push(path);
  const answer = replies[path] || [500, "unexpected " + path];
  if (answer === "offline") {
    throw new TypeError("Failed to fetch");
  }
  const [status, text] = answer;
  return {ok: status >= 200 && status < 300, status, text: async () => text, json: async () => JSON.parse(text)};
};
const reply = (status, text) => [status, text];
const missing = reply(404, "not found\\n");
const results = {};
async function scenario(name, shown, given, act, after) {
  state.inbox = shown.map((key) => ({...items[key]}));
  ui.busy = false;
  toasts.length = 0;
  posts.length = 0;
  renders = [];
  atLoad = null;
  loads = 0;
  reloaded = after || null;
  replies = given;
  await act();
  results[name] = {inbox: state.inbox.map((item) => item.id), atLoad, loads, renders: renders.length, toasts: [...toasts], posts: [...posts], busy: ui.busy};
}
const grantBoth = () => submit(state.inbox.map((item) => entryOf(item, "approve", "")), "Grant selection: 2 entries");
(async () => {
  await scenario("run_sign_404", ["gone", "kept"], {"/api/sign": missing}, () => approveOne(state.inbox[0]));
  await scenario("run_approve_404", ["gone", "kept"], {"/api/sign": reply(200, '{"payload": null}'), "/api/inbox/approve": missing}, () => approveOne(state.inbox[0]));
  await scenario("deny_404", ["gone", "kept"], {"/api/sign": missing}, () => submit([denialOf(state.inbox[0], "")], "Denial: " + short(state.inbox[0].title)));
  await scenario("dismiss_404", ["closed", "kept"], {"/api/inbox/dismiss": missing}, () => dismissJob(state.inbox[0].job));
  await scenario("rule_404", ["rule", "kept"], {["/api/rule-requests/" + items.rule.id + "/sign"]: missing}, () => acceptRule(state.inbox[0]));
  await scenario("run_409", ["gone", "kept"], {"/api/sign": reply(409, '{"id": "operator/kept", "status": "changed"}')}, () => approveOne(state.inbox[1]));
  await scenario("run_offline", ["gone", "kept"], {"/api/sign": "offline"}, () => approveOne(state.inbox[1]));
  await scenario("bulk_404", ["gone", "kept"], {"/api/sign": missing}, grantBoth, ["kept"]);
  await scenario("bulk_approve_404", ["gone", "kept"], {"/api/sign": reply(200, '{"payload": null}'), "/api/inbox/approve": missing}, grantBoth, ["kept"]);
  await scenario("bulk_404_none_gone", ["gone", "kept"], {"/api/sign": missing}, grantBoth, ["gone", "kept"]);
  await scenario("bulk_409", ["gone", "kept"], {"/api/sign": reply(409, '{"status": "held"}')}, grantBoth, ["kept"]);
  state.inbox = [items.gone, items.kept, items.later].map((item) => ({...item}));
  renders = [];
  replies = {"/api/state?": reply(200, JSON.stringify({inbox: [items.kept], radio: [], settings: {}, now: now + 10}))};
  await fresh();
  results.refresh = {inbox: state.inbox.map((item) => item.id), renders, offline: ui.offline};
  console.log(JSON.stringify(results));
})().catch((error) => { console.error(error && error.stack || error); process.exit(1); });
`;
vm.runInNewContext(`${source}\n${probe}`, {...context, process});
"""


class TestInboxGoneRows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        done = subprocess.run(["node", "-e", PROBE, str(TEMPLATES), json.dumps(MODULES), GONE], capture_output=True, text=True, timeout=60, check=False)
        if done.returncode != 0:
            raise AssertionError(done.stderr[-4000:])
        cls.data = json.loads(done.stdout)

    def assert_closed(self, name: str, kept: list[str], label: str) -> None:
        """Args:
            name: the scenario whose card the hub answered 404 for.
            kept: the ids the inbox still holds after the action.
            label: the start of the notice the page shows instead of an error.
        """
        found = self.data[name]
        self.assertEqual(found["inbox"], kept, found)
        self.assertEqual(found["atLoad"], kept, "the card must go before the page reloads its state")
        self.assertGreaterEqual(found["renders"], 1, found)
        self.assertEqual(found["toasts"], [[f"{label}: {NOTICE}", [], True]], found)
        self.assertFalse(found["busy"], found)

    def test_a_run_the_hub_answers_404_at_signing_closes_the_card_with_a_notice(self):
        self.assert_closed("run_sign_404", ["operator/kept"], "Run: git merge --no-ff --no-verify -F msg")

    def test_a_run_the_hub_answers_404_at_the_grant_closes_the_card_with_a_notice(self):
        self.assert_closed("run_approve_404", ["operator/kept"], "Run: git merge --no-ff --no-verify -F msg")
        self.assertEqual(self.data["run_approve_404"]["posts"], ["/api/sign", "/api/inbox/approve"])

    def test_a_denial_of_a_removed_row_closes_its_card(self):
        self.assert_closed("deny_404", ["operator/kept"], "Denial: git merge --no-ff --no-verify -F msg")

    def test_closing_the_console_of_a_removed_job_closes_its_card(self):
        self.assert_closed("dismiss_404", ["operator/kept"], "Close")

    def test_accepting_a_removed_rule_request_closes_its_card(self):
        self.assert_closed("rule_404", ["operator/kept"], "Rule: Rule ask Bash make deploy")

    def test_a_present_row_whose_run_fails_otherwise_stays_with_its_error(self):
        for name, line in (("run_409", '409 {"id": "operator/kept", "status": "changed"}'), ("run_offline", "0 TypeError: Failed to fetch")):
            with self.subTest(name=name):
                found = self.data[name]
                self.assertEqual(found["inbox"], [GONE, "operator/kept"], found)
                self.assertEqual(found["toasts"], [["Run: echo kept: not possible", [line], False]], found)

    def test_a_404_for_a_selection_reloads_once_and_closes_the_cards_that_are_gone_with_the_notice(self):
        for name in ("bulk_404", "bulk_approve_404"):
            with self.subTest(name=name):
                found = self.data[name]
                self.assertEqual((found["inbox"], found["loads"]), (["operator/kept"], 1), found)
                self.assertEqual(found["toasts"], [[f"Grant selection: 2 entries: {NOTICE}", [], True]], found)

    def test_a_404_for_a_selection_whose_reload_still_lists_every_card_keeps_the_error(self):
        found = self.data["bulk_404_none_gone"]
        self.assertEqual((found["inbox"], found["loads"]), ([GONE, "operator/kept"], 1), found)
        self.assertEqual(found["toasts"], [["Grant selection: 2 entries: not possible", ["404 not found"], False]], found)

    def test_a_selection_refused_for_another_reason_keeps_its_error_and_no_notice(self):
        found = self.data["bulk_409"]
        self.assertEqual(found["toasts"], [["Grant selection: 2 entries: not possible", ['409 {"status": "held"}'], False]], found)

    def test_the_next_refresh_drops_every_row_the_hub_no_longer_returns_without_a_reload(self):
        found = self.data["refresh"]
        self.assertEqual(found["inbox"], ["operator/kept"], found)
        self.assertEqual((found["renders"], found["offline"]), ([False], False), found)


if __name__ == "__main__":
    unittest.main()
