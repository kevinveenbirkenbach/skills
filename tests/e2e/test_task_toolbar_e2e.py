"""Exercise requirement 089 in Chromium: the Tasks toolbar in one row with a Filter and an Actions menu, every control of the old two rows within two clicks, the filter chip and its reset, at three widths."""

from __future__ import annotations

import datetime
import json
import os
import shutil
import sys
import unittest
from pathlib import Path
from typing import NamedTuple

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

import hub_e2e_kit as base

OUT = Path(os.environ.get("E2E_OUT", "/tmp/task-toolbar-shots"))
SCREENS = ("list", "rasci", "gantt", "burn", "board", "operator")
TASKS = SCREENS[:-1]
FILTER = ("task-filter",)
ACTIONS = ("task-actions",)
CHOICES = ("task-actions", "choice-request")


class Control(NamedTuple):
    """Args:
        control: the control's name.
        today: where the two-row toolbar held it.
        place: where the one-row toolbar holds it.
        screens: the Tasks screens that show it.
        path: the menus to open, one click each, before it shows.
        selector: finds it in the page.
        condition: "" when it always shows, "points" when it shows under
            Story points only, "optional" when only some state shows it.
    """

    control: str
    today: str
    place: str
    screens: tuple[str, ...]
    path: tuple[str, ...]
    selector: str
    condition: str = ""


VIEWS = ["List", "Board", "RASCI", "Gantt", "Burndown and burnup", "3D", "Match"]
CHANNELS = {"post": "Post", "call": "Call", "newsletter": "Newsletter", "broadcast": "Broadcast", "pan-pan": "Pan-Pan", "security": "Sécurité", "mayday": "Mayday"}
STATUS_TABS = {"all": "All", "open": "Open", "work": "Open work", "operator": "Waits on Operator", "grant": "Waiting for a grant", "ended": "Ended"}
INVENTORY = (
    *(Control(f"View switcher: {view}", "row 1", "toolbar row", SCREENS, (), f'#main .task-bar [aria-label="View"] button[aria-label="{view}"]') for view in VIEWS),
    Control("Filter search", "row 1", "toolbar row", TASKS, (), '#main .task-bar input[aria-label="Filter tasks"]'),
    Control("Search mic", "row 1", "toolbar row, inside the search frame", TASKS, (), "#main .task-bar .mic-line > button.mic"),
    Control("Task count", "row 1", "toolbar row, last", SCREENS, (), "#main .task-bar > .task-count"),
    Control("Estimation: No estimate (info button)", "row 1", "Filter > View", TASKS, FILTER, '#main [aria-label="Estimation"] button[data-estimation="none"]'),
    Control("Estimation: Story points (diamond button)", "row 1", "Filter > View", TASKS, FILTER, '#main [aria-label="Estimation"] button[data-estimation="points"]'),
    Control("Request estimates", "row 1, under Story points", "Actions > Plan", TASKS, ACTIONS, "#request-estimates", "points"),
    Control("Sort", "row 1, list", "Filter > View", ("list",), FILTER, '#main select[aria-label="Sort"]'),
    Control("Sort direction", "row 1, list", "Filter > View", ("list",), FILTER, "#main button[data-direction]"),
    Control("Business value of the selection", "row 1, list", "Actions > Plan", ("list",), ACTIONS, '#main select[aria-label="Business value of the selection"]'),
    Control("Set business value", "row 1, list", "Actions > Plan", ("list",), ACTIONS, "#bulk-value"),
    Control("Forecast", "row 1, gantt", "Filter > View", ("gantt",), FILTER, '#main select[aria-label="Forecast"]'),
    Control("Scope", "row 1, burn", "Filter > View", ("burn",), FILTER, '#main select[aria-label="Scope"]'),
    Control("Trend", "row 1, burn", "Filter > View", ("burn",), FILTER, '#main select[aria-label="Trend"]'),
    Control("Request choices", "row 1", "Actions > Request choices", SCREENS, ACTIONS, "#choice-request > summary"),
    Control("Request choices: agents", "row 1, Request choices", "Actions > Request choices", SCREENS, CHOICES, "#choice-request .choice-agents"),
    *(Control(f"Request choices: {label}", "row 1, Request choices", "Actions > Request choices", SCREENS, CHOICES, f'#choice-request button[data-channel="{channel}"]') for channel, label in CHANNELS.items()),
    Control("Apply staged moves (green done counter)", "row 2, board", "Actions > Board", ("board",), ACTIONS, "#kanban-apply"),
    Control("Discard staged moves (cancel)", "row 2, board", "Actions > Board", ("board",), ACTIONS, "#kanban-discard"),
    Control("Older Done (hidden counter)", "row 2, board", "Filter > Board", ("board",), FILTER, "#kanban-old"),
    Control("Running", "row 2, board", "Filter > Board", ("board",), FILTER, "#kanban-running"),
    Control("Stale filter", "new", "Filter > Board", ("board",), FILTER, "#kanban-stale-only"),
    Control("Stale count (hourglass counter)", "row 2, board", "toolbar row, compact chip while a card is stale", ("board",), (), "#main .task-bar #kanban-stale"),
    Control("Prune stale", "row 2, board", "Actions > Board", ("board",), ACTIONS, "#kanban-prune-open"),
    Control("Prune countdown", "row 2, board, while a signed prune waits", "toolbar row chip, and the readout inside Prune stale", ("board",), (), "#main .task-bar #kanban-prune", "optional"),
    Control("Queue line", "row 2, board", "Filter > Board", ("board",), FILTER, '#main .legend-chip[data-path="kanban.hidden"][data-chip="line"]'),
    Control("Queue jobs", "row 2, board", "Filter > Board", ("board",), FILTER, '#main .legend-chip[data-path="kanban.hidden"][data-chip="jobs"]'),
    Control("Queue order only", "row 2, board, while queue.py lists no JSON", "Filter > Board", ("board",), FILTER, "#kanban-queue-order", "optional"),
    *(Control(f"Status: {label}", "status tabs", "Filter > Status, one radio group with counts", SCREENS, FILTER, f'#main [aria-label="Task filters"] [data-filter="{tab}"] input[type="radio"]') for tab, label in STATUS_TABS.items()),
    Control("Filter chip reset", "new", "toolbar row, next to Filter", ("operator",), (), "#main .task-bar #task-filter-chip button.x"),
    Control("Undo", "undo toast", "Actions > Undo, one entry per running undo window", SCREENS, ACTIONS, "#main .task-undo"),
)
CLOSE = """
  const closeAll = async () => {
    document.body.dispatchEvent(new KeyboardEvent("keydown", {key: "Escape", bubbles: true}));
    await sleep(150);
  };
"""
REACH = """(async () => {@HELPERS@@CLOSE@
  const entries = @ENTRIES@;
  const ready = () => document.getElementById("task-actions") && document.querySelector("#main .tasks-body > *, #main .inbox-list");
  if (!(await screenShown(8000)) || !(await until(ready, 8000))) {
    return {error: text(document.getElementById("main")).slice(0, 300)};
  }
  await sleep(500);
  const estimate = async (mode) => {
    await openTaskMenu("task-filter");
    const button = () => document.querySelector(`#main [aria-label="Estimation"] button[data-estimation="${mode}"]`);
    if (button().getAttribute("aria-pressed") !== "true") {
      button().click();
      await until(() => button().getAttribute("aria-pressed") === "true", 8000);
    }
    await closeAll();
  };
  const reach = async ([control, , , , path, selector, condition]) => {
    await closeAll();
    let clicks = 0;
    for (const id of path) {
      const menu = document.getElementById(id);
      if (!menu) {
        return [control, [clicks, `no menu ${id}`]];
      }
      menu.querySelector(":scope > summary").click();
      clicks += 1;
      await sleep(150);
    }
    const node = document.querySelector(selector);
    if (!node) {
      return [control, [clicks, condition === "optional" ? "absent" : "missing"]];
    }
    const box = node.getBoundingClientRect();
    const seen = node.checkVisibility() && box.width > 0 && box.height > 0 && box.left >= -1 && box.right <= innerWidth + 1;
    return [control, [clicks, seen ? "reachable" : "hidden"]];
  };
  await closeAll();
  const rows = toolbarRows();
  const wide = document.documentElement.scrollWidth > innerWidth + 1;
  const reached = [];
  for (const entry of entries.filter((item) => item[6] !== "points")) {
    reached.push(await reach(entry));
  }
  const points = entries.filter((item) => item[6] === "points");
  if (points.length) {
    await estimate("points");
    for (const entry of points) {
      reached.push(await reach(entry));
    }
    await estimate("none");
  }
  await closeAll();
  return {rows, wide, layout: taskLayout(), reached: Object.fromEntries(reached)};
})()"""
SECTIONS = """
  const sections = (menu) => all(":scope > .menu-box > .task-menu-section", menu).filter((node) => node.checkVisibility()).map((node) => text(node.querySelector("h3")));
  const inside = (menu) => {
    const box = menu.querySelector(":scope > .menu-box").getBoundingClientRect();
    return box.left >= -1 && box.right <= innerWidth + 1;
  };
"""
FILTER_OPEN = """(async () => {@HELPERS@@SECTIONS@
  if (!(await screenShown(8000)) || !(await until(() => document.getElementById("kanban-running"), 8000))) {
    return {error: text(document.getElementById("main")).slice(0, 300)};
  }
  await sleep(400);
  const menu = await openTaskMenu("task-filter");
  await sleep(200);
  return {
    open: menu.open, sections: sections(menu), inside: inside(menu), rows: toolbarRows(),
    radios: all('[aria-label="Task filters"] input[type="radio"]', menu).map((input) => [input.value, input.checked, text(input.closest("label").querySelector(".count"))]),
    wide: document.documentElement.scrollWidth > innerWidth + 1,
  };
})()"""
ACTIONS_OPEN = """(async () => {@HELPERS@@SECTIONS@
  const menu = await openTaskMenu("task-actions");
  const choices = document.getElementById("choice-request");
  choices.querySelector(":scope > summary").click();
  await sleep(250);
  return {
    open: [menu.open, choices.open, document.getElementById("task-filter").open], sections: sections(menu), inside: inside(menu),
    channels: all("button[data-channel]", choices).filter((button) => button.checkVisibility()).map((button) => button.dataset.channel),
    undo: text(menu.querySelector(".task-undo")), wide: document.documentElement.scrollWidth > innerWidth + 1,
  };
})()"""
CHIP = """(async () => {@HELPERS@@CLOSE@
  const chip = () => document.getElementById("task-filter-chip");
  const radio = (id) => document.querySelector(`#main [aria-label="Task filters"] [data-filter="${id}"] input`);
  const cards = () => all("#main .kanban-card").length;
  await closeAll();
  const before = {chip: Boolean(chip()), all: radio("all").checked, cards: cards()};
  await openTaskMenu("task-filter");
  radio("open").click();
  if (!(await until(() => chip() && text(chip()).includes("Open"), 4000))) {
    return {error: "no chip after Open", before};
  }
  const kept = document.getElementById("task-filter").open;
  document.getElementById("kanban-running").click();
  if (!(await until(() => chip() && text(chip()).includes("Running"), 4000))) {
    return {error: "no Running in the chip", before};
  }
  await closeAll();
  await sleep(300);
  const host = chip().parentElement;
  const shown = {
    words: text(chip().querySelector(".task-chip-word")), label: chip().getAttribute("aria-label"), reset: name(chip().querySelector("button.x")),
    beside: host.previousElementSibling ? host.previousElementSibling.id : null, rows: toolbarRows(), kept, wide: document.documentElement.scrollWidth > innerWidth + 1,
  };
  chip().querySelector("button.x").click();
  await until(() => !chip() && radio("all").checked, 4000);
  await sleep(400);
  const after = {chip: Boolean(chip()), all: radio("all").checked, running: document.getElementById("kanban-running").getAttribute("aria-pressed"), cards: cards()};
  await openTaskMenu("task-filter");
  radio("open").click();
  await until(() => chip(), 4000);
  await closeAll();
  await sleep(300);
  return {before, shown, after, again: [text(chip().querySelector(".task-chip-word")), toolbarRows()]};
})()"""
KEYS = """(async () => {@HELPERS@
  const menu = await openTaskMenu("task-actions");
  const opened = menu.open;
  document.body.dispatchEvent(new KeyboardEvent("keydown", {key: "Escape", bubbles: true}));
  await sleep(150);
  const closed = !document.getElementById("task-actions").open;
  await pressKey(String(Nav.TABS.findIndex(([id]) => id === "stream") + 1));
  const moved = Boolean(await until(() => location.hash.startsWith("#stream"), 4000));
  return {opened, closed, moved};
})()"""
UNDO = """(async () => {@HELPERS@@LABELS@
  if (!(await screenShown(8000))) {
    return {error: "no screen"};
  }
  const row = await until(() => askOf("make deploy"), 8000);
  if (!row) {
    return {error: text(document.getElementById("main")).slice(0, 300)};
  }
  press(row, "Grant");
  const waiting = await until(() => all("#toasts .toast.wait").find((box) => box.textContent.includes("Grant")), 15000);
  await openTaskMenu("task-actions");
  const item = await until(() => document.querySelector('#main .task-undo button[data-key^="undo:"]'), 4000);
  if (!waiting || !item) {
    return {error: "no undo entry", toast: Boolean(waiting), undo: text(document.querySelector("#main .task-undo"))};
  }
  const first = text(item.querySelector(".undo-left"));
  await sleep(1300);
  const second = item.isConnected ? text(item.querySelector(".undo-left")) : null;
  return {visible: item.checkVisibility(), label: name(item), first, second, open: document.getElementById("task-actions").open};
})()"""


def stamp(days: float) -> str:
    """Args:
        days: how long ago.

    Returns:
        That moment as an ISO 8601 UTC stamp.
    """
    return (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=days)).isoformat(timespec="seconds")


def probe(template: str, **fills: str) -> str:
    """Args:
        template: a probe with @NAME@ placeholders.
        fills: extra placeholders by lower-case name.

    Returns:
        The probe with the kit's helpers and every fill put in.
    """
    for key, value in {"@HELPERS@": base.HELPERS, "@LABELS@": base.LABELS, "@CLOSE@": CLOSE, "@SECTIONS@": SECTIONS, **{f"@{key.upper()}@": value for key, value in fills.items()}}.items():
        template = template.replace(key, value)
    return template


def shown_on(screen: str) -> list[Control]:
    """Args:
        screen: one of SCREENS.

    Returns:
        The inventory the screen shows.
    """
    return [entry for entry in INVENTORY if screen in entry.screens]


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestTaskToolbar(base.OrchestratorE2ECase):
    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        path = self.council / "rasci.json"
        tasks = json.loads(path.read_text(encoding="utf-8"))
        tasks.update({
            "work/stale-a": {"title": "Stale A", "status": "queued", "worker": "Docs", "roles": {"Docs": "RA"}, "updated": stamp(12)},
            "work/stale-b": {"title": "Stale B", "status": "blocked", "worker": "Docs", "roles": {"Docs": "RA"}, "updated": stamp(6)},
        })
        path.write_text(json.dumps(tasks), encoding="utf-8")
        payload = {**self.snapshot()["settings"], "undo": 20, "proof": None}
        self.assertEqual(self.post_json("/api/settings", payload, self.guard(self.host))[0], 200)
        self.local = f"http://localhost:{self.port}/"

    def steps(self) -> list[dict]:
        steps = []
        for width, height in base.WIDTHS:
            at = {"width": width, "height": height}
            entries = {screen: json.dumps([list(entry) for entry in shown_on(screen)], ensure_ascii=False) for screen in SCREENS}
            steps += [{**at, "url": f"{self.local}?{width}-{screen}#tasks/{screen}", "wait": 1500, "probe": probe(REACH, entries=entries[screen]), "shot": str(OUT / f"chromium-{width}-{screen}.png")} for screen in SCREENS]
            steps += [
                {**at, "url": f"{self.local}?{width}-menus#tasks/board", "wait": 1500, "probe": probe(FILTER_OPEN), "shot": str(OUT / f"chromium-{width}-board-filter-menu.png")},
                {**at, "url": None, "wait": 0, "probe": probe(ACTIONS_OPEN), "shot": str(OUT / f"chromium-{width}-board-actions-menu.png")},
                {**at, "url": None, "wait": 0, "probe": probe(CHIP), "shot": str(OUT / f"chromium-{width}-board-filter-chip.png")},
                {**at, "url": None, "wait": 0, "probe": probe(KEYS), "shot": None},
            ]
        steps.append({"width": 1366, "height": 768, "url": f"{self.local}?undo#tasks/operator", "wait": 1500, "probe": probe(UNDO), "shot": str(OUT / "chromium-1366-operator-undo.png")})
        return steps

    def check_rows(self, rows: int, width: int, found: dict) -> None:
        self.assertIn(rows, (1, 2) if width == 390 else (1,), found)

    def check_reach(self, found: dict, screen: str, width: int) -> None:
        self.assertNotIn("error", found, found)
        self.assertEqual((found["wide"], found["layout"]), (False, ["toolbar", "body"]), found)
        self.check_rows(found["rows"], width, found)
        entries = shown_on(screen)
        self.assertEqual(sorted(found["reached"]), sorted(entry.control for entry in entries), found)
        for entry in entries:
            with self.subTest(control=entry.control):
                clicks, state = found["reached"][entry.control]
                self.assertLessEqual(clicks, 2)
                self.assertEqual(clicks, len(entry.path), (entry, found["reached"][entry.control]))
                self.assertIn(state, ("reachable", "absent") if entry.condition == "optional" else ("reachable",), (entry, state))

    def check_menus(self, filtered: dict, actions: dict, width: int) -> None:
        self.assertNotIn("error", filtered, filtered)
        self.assertEqual((filtered["open"], filtered["sections"], filtered["inside"], filtered["wide"]), (True, ["Status", "Board", "View"], True, False), filtered)
        self.assertEqual([[value, checked] for value, checked, _ in filtered["radios"]], [[tab, tab == "all"] for tab in STATUS_TABS])
        self.assertTrue(all(count.isdigit() for _, _, count in filtered["radios"]), filtered)
        self.check_rows(filtered["rows"], width, filtered)
        self.assertEqual((actions["open"], actions["sections"], actions["inside"], actions["wide"]), ([True, True, False], ["Board", "Undo"], True, False), actions)
        self.assertEqual((actions["channels"], actions["undo"]), (list(CHANNELS), "Nothing to undo"), actions)

    def check_chip(self, chip: dict, keys: dict, width: int) -> None:
        self.assertNotIn("error", chip, chip)
        self.assertEqual(chip["before"]["chip"], False, chip)
        self.assertTrue(chip["before"]["all"], chip)
        shown = chip["shown"]
        self.assertEqual((shown["words"], shown["label"], shown["reset"], shown["beside"], shown["kept"], shown["wide"]), ("Open · Running", "Filter: Open · Running", "Reset filter", "task-filter", True, False), shown)
        self.check_rows(shown["rows"], width, shown)
        self.assertEqual(chip["after"], {"chip": False, "all": True, "running": "false", "cards": chip["before"]["cards"]}, chip)
        self.assertEqual(chip["again"][0], "Open", chip)
        self.check_rows(chip["again"][1], width, chip)
        self.assertEqual(keys, {"opened": True, "closed": True, "moved": True}, keys)

    def test_chromium_reaches_every_control_of_the_old_two_rows_from_one_row_at_three_widths(self):
        data = self.drive(self.steps(), self.authenticator())
        (OUT / "chromium-task-toolbar.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error and "(style-src-elem)" not in error], [])
        results = iter(data["results"])
        for width, _ in base.WIDTHS:
            reached = {screen: next(results) for screen in SCREENS}
            filtered, actions, chip, keys = next(results), next(results), next(results), next(results)
            for screen, found in reached.items():
                with self.subTest(width=width, screen=screen):
                    self.check_reach(found, screen, width)
            with self.subTest(width=width, step="menus"):
                self.check_menus(filtered, actions, width)
            with self.subTest(width=width, step="chip"):
                self.check_chip(chip, keys, width)
        undo = next(results)
        self.assertNotIn("error", undo, undo)
        self.assertEqual((undo["visible"], undo["open"]), (True, True), undo)
        self.assertTrue(undo["label"].startswith("Undo: Grant"), undo)
        self.assertRegex(undo["first"], r"^\d+ s$")
        self.assertRegex(undo["second"], r"^\d+ s$")
        self.assertLess(int(undo["second"].split()[0]), int(undo["first"].split()[0]), undo)


if __name__ == "__main__":
    unittest.main()
