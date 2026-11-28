"""Exercise requirement 090: one map from task state to card colour, total over the register's states, one colour per entry."""

from __future__ import annotations

import json
import re
import subprocess
import unittest

from hub_support import AMBIENCE, HUB, PLAN, RASCI

KANBAN_PAGE = HUB / "templates" / "page-kanban.js"
TASKS = HUB / "kvb_orchestrator" / "tasks.py"
NAMES = ("KANBAN_STATES", "queueFailed", "cardOwner", "cardState")
DERIVED = ("operator", "stale", "failed")
PROBE = r"""
const vm = require("vm");
const Ambience = require(process.argv[2]);
const sandbox = {Plan: {STALE_DAYS: 3}, STATES: JSON.parse(process.argv[3]), out: {}};
vm.runInNewContext(process.argv[1], sandbox);
vm.runInNewContext(`
  const row = (status, fields) => ({task: "work/x", kind: "task", status, ended: status === "done" || status === "stopped", worker: "-", roles: {}, queue: null, ...fields});
  const calm = {operator: false, stale: false, working: false};
  const key = (entry, found) => cardState(entry, {...calm, ...found}).key;
  out.entries = KANBAN_STATES.map((entry) => [entry.key, entry.tone, entry.line, entry.states]);
  out.labels = KANBAN_STATES.map((entry) => entry.label);
  out.listed = Object.fromEntries(STATES.map((state) => [state, KANBAN_STATES.filter((entry) => entry.states.includes(state)).map((entry) => entry.key)]));
  out.status = Object.fromEntries(STATES.filter((state) => !["operator", "stale", "failed"].includes(state)).map((state) => [state, key(row(state), {})]));
  out.derived = {
    operator: [key(row("queued"), {operator: true}), key(row("blocked"), {operator: true}), key(row("running"), {operator: true, stale: true}), key(row("done"), {operator: true})],
    stale: [key(row("running"), {stale: true}), key(row("queued"), {stale: true}), key(row("running"), {stale: true, working: true}), key(row("blocked"), {stale: true}), key(row("stopped"), {stale: true})],
    failed: [key(row("stopped", {kind: "queue", queue: {exit: 2}}), {}), key(row("done", {kind: "queue", queue: {exit: 0}}), {}), key(row("stopped", {kind: "queue", queue: {exit: null}}), {}), key(row("stopped", {queue: {exit: 2}}), {})],
    unknown: key(row("parked"), {}),
  };
  out.owners = [
    cardOwner(row("queued", {worker: "Main", roles: {Docs: "R"}})),
    cardOwner(row("queued", {roles: {Docs: "C", Skills: "RA"}})),
    cardOwner(row("queued", {roles: {Docs: "I"}})),
    cardOwner({task: "queue/q-1", worker: "-"}),
  ];
`, sandbox);
sandbox.out.themes = Object.fromEntries(Object.entries(Ambience.THEMES).map(([mode, tokens]) => [mode, sandbox.out.entries.map(([, tone]) => tokens[tone] || null)]));
console.log(JSON.stringify(sandbox.out));
"""


def extracted() -> str:
    source = KANBAN_PAGE.read_text(encoding="utf-8")
    parts = []
    for name in NAMES:
        found = re.search(rf"^  (?:function {name}\(.*?^  }}$|const {name} = \[.*?^  \];$|const {name} = .*?;$)", source, re.MULTILINE | re.DOTALL)
        if found is None:
            raise AssertionError(f"{name} not found in {KANBAN_PAGE}")
        parts.append(found.group(0).replace(f"const {name} = ", f"var {name} = "))
    return "\n".join(parts)


def register_states() -> list[str]:
    """Returns:
        Every status the board can meet: rasci.py's STATUSES, the statuses
        the hub gives a queue row, Plan's STATUS_ORDER and the states the
        board derives, each once in that order.
    """
    rasci = re.search(r"^STATUSES = \(([^)]*)\)", RASCI.read_text(encoding="utf-8"), re.MULTILINE)
    queue = re.search(r"^def queue_status\(.*?(?=^\S)", TASKS.read_text(encoding="utf-8"), re.MULTILINE | re.DOTALL)
    order = re.search(r"const STATUS_ORDER = \[([^\]]*)\]", PLAN.read_text(encoding="utf-8"))
    if rasci is None or queue is None or order is None:
        raise AssertionError("a status list moved: rasci.py STATUSES, tasks.py queue_status or plan.js STATUS_ORDER")
    found = [*re.findall(r'"(\w+)"', rasci.group(1)), *re.findall(r'return "(\w+)" if .* else "(\w+)"', queue.group(0)), *re.findall(r'"(\w+)"', order.group(1)), *DERIVED]
    flat = [state for entry in found for state in (entry if isinstance(entry, tuple) else (entry,))]
    return list(dict.fromkeys(flat))


class TestCardIdentity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.states = register_states()
        done = subprocess.run(["node", "-e", PROBE, extracted(), str(AMBIENCE), json.dumps(cls.states)], capture_output=True, text=True, timeout=60, check=False)
        if done.returncode != 0:
            raise AssertionError(done.stderr[-4000:])
        cls.data = json.loads(done.stdout)

    def test_the_register_states_are_the_ones_the_map_was_written_for(self):
        self.assertEqual(self.states, ["queued", "running", "blocked", "done", "stopped", "awaiting", "claimed", "stale", "operator", "failed"])

    def test_the_map_is_total_every_state_in_exactly_one_entry(self):
        self.assertEqual({state: len(keys) for state, keys in self.data["listed"].items()}, dict.fromkeys(self.states, 1))
        listed = [state for *_, states in self.data["entries"] for state in states]
        self.assertEqual(sorted(listed), sorted(self.states))

    def test_the_entries_are_the_six_operator_meanings_in_their_tokens(self):
        self.assertEqual(self.data["entries"], [
            ["running", "ok", "solid", ["running", "claimed"]],
            ["operator", "warn", "solid", ["operator"]],
            ["queued", "info", "solid", ["queued", "awaiting"]],
            ["blocked", "bad", "solid", ["blocked", "failed"]],
            ["stale", "faint", "dashed", ["stale"]],
            ["ended", "line-strong", "solid", ["done", "stopped"]],
        ])
        self.assertIn("3 days", self.data["labels"][4])
        self.assertEqual(len(set(self.data["labels"])), len(self.data["labels"]))

    def test_no_two_entries_share_a_colour_in_either_theme_and_running_never_looks_stale(self):
        tones = [tone for _, tone, _, _ in self.data["entries"]]
        self.assertEqual(len(set(tones)), len(tones))
        self.assertEqual(sorted(self.data["themes"]), ["dark", "light"])
        for mode, colours in self.data["themes"].items():
            with self.subTest(theme=mode):
                self.assertNotIn(None, colours)
                self.assertEqual(len({colour.lower() for colour in colours}), len(colours), colours)
        running, stale = self.data["entries"][0], self.data["entries"][4]
        self.assertNotEqual((running[1], running[2]), (stale[1], stale[2]))
        self.assertEqual([line for _, _, line, _ in self.data["entries"]].count("dashed"), 1)

    def test_each_status_reads_as_its_own_entry_and_an_unknown_one_as_queued(self):
        self.assertEqual(self.data["status"], {
            "queued": "queued", "running": "running", "blocked": "blocked", "done": "ended", "stopped": "ended", "awaiting": "queued", "claimed": "running",
        })
        self.assertEqual(self.data["derived"]["unknown"], "queued")

    def test_waits_on_the_operator_outranks_every_open_state_and_never_an_ended_one(self):
        self.assertEqual(self.data["derived"]["operator"], ["operator", "operator", "operator", "ended"])

    def test_a_stale_card_is_grey_unless_it_works_is_blocked_or_ended(self):
        self.assertEqual(self.data["derived"]["stale"], ["stale", "stale", "running", "blocked", "ended"])

    def test_only_a_queue_job_that_ended_with_a_non_zero_exit_reads_failed(self):
        self.assertEqual(self.data["derived"]["failed"], ["blocked", "ended", "ended", "ended"])

    def test_the_owner_is_the_worker_else_the_first_r_holder_else_nobody(self):
        self.assertEqual(self.data["owners"], ["Main", "Skills", "", ""])

    def test_every_card_and_the_legend_take_their_colour_from_the_map(self):
        source = KANBAN_PAGE.read_text(encoding="utf-8")
        card = re.search(r"^  function kanbanCard\(.*?^  }$", source, re.MULTILINE | re.DOTALL).group(0)
        legend = re.search(r"^  function stateLegend\(.*?^  }$", source, re.MULTILINE | re.DOTALL).group(0)
        self.assertIn("const look = cardState(row, ", card)
        self.assertIn('return stateTint(h("li", {', card)
        self.assertIn("ownerFace(row, owner)", card)
        self.assertIn("KANBAN_STATES.map((entry) =>", legend)
        self.assertIn('"data-legend-slot": ""', legend)
        self.assertIn("stateLegend(), box)", source)
        self.assertNotRegex(source, r"style:|setAttribute\(\"style\"")
        css = (HUB / "templates" / "style-kanban.css").read_text(encoding="utf-8")
        self.assertNotIn("--mark", css)
        self.assertIn("border: 2px var(--card-line, solid) var(--card-state, var(--line-strong))", css)
        self.assertIn("--beat: var(--card-state, var(--ok))", (HUB / "templates" / "style-ui.css").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
