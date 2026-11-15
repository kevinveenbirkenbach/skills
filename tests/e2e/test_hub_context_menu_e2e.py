from __future__ import annotations

import json
import os
import shutil
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

import hub_e2e_kit as base

OUT = Path(os.environ.get("E2E_OUT", "/tmp/hub-context-menu-shots"))
GAP = 8
TASK = ["element", "Task work/feature", ["Open task", "Copy task id", "Pin to Home"]]
TASKS_TAB = ["tasks", "Tasks", ["Tasks: List", "Tasks: Board", "Tasks: RASCI", "Tasks: Gantt", "Tasks: Burndown and burnup", "Tasks: 3D"]]
GENERAL_HEAD = [f"View: {tab}" for tab in base.TABS] + ["Radio …", "Cancel mayday", "Drain", "Suspend", "Resume", "Settings …"]
GENERAL_TAIL = ["Look at the sky", "Toggle control room", "Enable notifications", "Keyboard shortcuts"]
MOVES = ["Copy task id", "Pin to Home", "Copy task id", "Keyboard shortcuts", "Open task", "Keyboard shortcuts"]
MENU = base.UNLABELLED + """
  const shownMenu = () => document.querySelector(".ctx-menu:not([hidden])");
  const itemLabel = (node) => (node && node.closest('[role="menuitem"]') ? text(node.closest('[role="menuitem"]').querySelector(".ctx-label")) : null);
  const key = (word, extra) => (document.activeElement || document.body).dispatchEvent(new KeyboardEvent("keydown", {key: word, bubbles: true, cancelable: true, ...extra}));
  const menuState = () => {
    const menu = shownMenu();
    if (!menu) {
      return {open: false};
    }
    const box = menu.getBoundingClientRect();
    return {
      open: true, role: menu.getAttribute("role"), roles: [...new Set(all("button", menu).map((node) => node.getAttribute("role")))],
      groups: all('[role="group"]', menu).map((group) => [group.dataset.scope, group.getAttribute("aria-label"), all('[role="menuitem"]', group).map(itemLabel)]),
      box: [box.left, box.top, box.right, box.bottom].map(Math.round), focused: itemLabel(document.activeElement),
      wide: document.documentElement.scrollWidth > innerWidth + 1, unlabelled: unlabelled(menu),
    };
  };
  const rowOf = () => document.querySelector('#main li.task-row[data-task="work/feature"]');
  const cardOf = () => document.querySelector('#main .kanban-card[data-task="work/feature"]');
"""
MOUSE = """(async () => {@HELPERS@@MENU@
  await screenShown(8000);
  const row = await until(rowOf, 10000);
  if (!row) {
    return {error: text(document.getElementById("main"))};
  }
  row.scrollIntoView({block: "center"});
  await sleep(300);
  const spot = row.querySelector("code.task-id");
  const box = spot.getBoundingClientRect();
  const at = {clientX: Math.round(box.left + box.width / 2), clientY: Math.round(box.top + box.height / 2)};
  const prevented = !spot.dispatchEvent(new MouseEvent("contextmenu", {bubbles: true, cancelable: true, button: 2, ...at}));
  await sleep(200);
  return {prevented, at: [at.clientX, at.clientY], ...menuState()};
})()"""
STEER = """(async () => {@HELPERS@@MENU@
  const moves = [];
  for (const word of ["ArrowDown", "ArrowDown", "ArrowUp", "End", "Home", "ArrowUp"]) {
    key(word);
    moves.push(itemLabel(document.activeElement));
  }
  key("Escape");
  await sleep(100);
  const closed = !shownMenu();
  const spot = rowOf().querySelector("code.task-id");
  const box = spot.getBoundingClientRect();
  const passed = spot.dispatchEvent(new MouseEvent("contextmenu", {bubbles: true, cancelable: true, button: 2, shiftKey: true, clientX: box.left + 2, clientY: box.top + 2}));
  await sleep(100);
  const shift = {passed, open: Boolean(shownMenu())};
  key("k", {ctrlKey: true});
  await sleep(200);
  const palette = all("#palette:not([hidden]) .palette-list li").map((li) => text(li.querySelector("span")));
  key("Escape");
  await sleep(100);
  return {moves, closed, shift, palette, paletteClosed: document.getElementById("palette").hidden};
})()"""
KEYED = """(async () => {@HELPERS@@MENU@
  await screenShown(8000);
  const card = await until(cardOf, 10000);
  if (!card) {
    return {error: text(document.getElementById("main"))};
  }
  card.scrollIntoView({block: "center"});
  await sleep(300);
  card.focus();
  const anchor = card.getBoundingClientRect();
  const prevented = !key("ContextMenu");
  await sleep(200);
  return {prevented, at: [Math.round(anchor.left), Math.round(anchor.bottom)], ...menuState()};
})()"""
RUN = """(async () => {@HELPERS@@MENU@
  const first = itemLabel(document.activeElement);
  key("Enter");
  const sheet = await until(() => all('#sheet:not([hidden]) [role="dialog"]').find((node) => node.getAttribute("aria-label") === "work/feature"), 4000);
  await sleep(200);
  return {first, closed: !shownMenu(), sheet: Boolean(sheet)};
})()"""
SHIFT_F10 = """(async () => {@HELPERS@@MENU@
  document.querySelector('#sheet:not([hidden]) .sheet-head button[aria-label="Close"]').click();
  await sleep(150);
  const card = cardOf();
  card.focus();
  const prevented = !key("F10", {shiftKey: true});
  await sleep(150);
  const opened = menuState();
  key("?");
  await sleep(100);
  const help = Boolean(document.querySelector("#sheet:not([hidden])"));
  return {prevented, element: opened.groups ? opened.groups[0] : null, closed: !shownMenu(), back: document.activeElement === cardOf(), help};
})()"""


def probe(template: str) -> str:
    return template.replace("@HELPERS@", base.HELPERS).replace("@MENU@", MENU)


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestHubContextMenu(base.OrchestratorE2ECase):
    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)

    def steps(self, browser: str) -> list[dict]:
        local = f"http://localhost:{self.port}/"
        steps = []
        for width, height in base.WIDTHS:
            shot = str(OUT / f"{browser}-{width}-context")
            steps += [
                {"width": width, "height": height, "url": f"{local}?{width}-mouse#tasks/list", "wait": 1500, "probe": probe(MOUSE), "shot": f"{shot}-mouse.png"},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(STEER), "shot": None},
                {"width": width, "height": height, "url": f"{local}?{width}-keyed#tasks/board", "wait": 1500, "probe": probe(KEYED), "shot": f"{shot}-key.png"},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(RUN), "shot": f"{shot}-task-sheet.png"},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(SHIFT_F10), "shot": None},
            ]
        return steps

    def placed(self, menu: dict, at: list[int], size: tuple[int, int]) -> None:
        """Args:
            menu: the menuState of an open menu.
            at: the viewport point the menu was opened at.
            size: the viewport width and height.
        """
        left, top, right, bottom = menu["box"]
        width, height = size
        self.assertTrue(0 <= left and right <= width and 0 <= top and bottom <= height, menu["box"])
        if at[0] + right - left <= width - GAP:
            self.assertLessEqual(abs(left - at[0]), 1, (menu["box"], at))
        else:
            self.assertGreaterEqual(right, width - GAP - 1, (menu["box"], at))
        if at[1] + bottom - top <= height - GAP:
            self.assertLessEqual(abs(top - at[1]), 1, (menu["box"], at))
        else:
            self.assertTrue(bottom <= at[1] + 1 or top <= GAP + 1, (menu["box"], at))

    def grouped(self, menu: dict) -> None:
        self.assertEqual((menu["open"], menu["role"], menu["roles"], menu["unlabelled"], menu["wide"]), (True, "menu", ["menuitem"], [], False), menu)
        self.assertEqual(menu["groups"][:2], [TASK, TASKS_TAB])
        scope, title, general = menu["groups"][2]
        self.assertEqual((scope, title, len(menu["groups"])), ("general", "General", 3))
        self.assertEqual(general[: len(GENERAL_HEAD)], GENERAL_HEAD)
        self.assertEqual(general[-len(GENERAL_TAIL) :], GENERAL_TAIL)
        self.assertIn(general[len(GENERAL_HEAD)], ("Music on", "Music off"))
        self.assertEqual(menu["focused"], "Open task")

    def check(self, data: dict) -> None:
        per = 5
        for index, (width, height) in enumerate(base.WIDTHS):
            mouse, steer, keyed, ran, shifted = data["results"][per * index : per * (index + 1)]
            with self.subTest(width=width):
                for result in (mouse, steer, keyed, ran, shifted):
                    self.assertNotIn("error", result, result)
                self.assertTrue(mouse["prevented"], mouse)
                self.grouped(mouse)
                self.placed(mouse, mouse["at"], (width, height))
                self.assertEqual((steer["moves"], steer["closed"]), (MOVES, True), steer)
                self.assertEqual(steer["shift"], {"passed": True, "open": False})
                self.assertLessEqual({"View: Home", "Tasks: List", "Stage", "Priority …", "Keyboard shortcuts"}, set(steer["palette"]), steer["palette"])
                self.assertTrue(steer["paletteClosed"])
                self.assertTrue(keyed["prevented"], keyed)
                self.grouped(keyed)
                self.placed(keyed, keyed["at"], (width, height))
                self.assertEqual(ran, {"first": "Open task", "closed": True, "sheet": True})
                self.assertEqual(shifted, {"prevented": True, "element": TASK, "closed": True, "back": True, "help": False})

    def run_browser(self, browser: str, driver: str, binary: str) -> None:
        data = self.drive(self.steps(browser), None, driver, binary)
        (OUT / f"{browser}-context-menu.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        self.check(data)

    def test_chromium_right_click_and_menu_key_open_the_grouped_context_menu_and_run_an_item_at_three_widths(self):
        self.run_browser("chromium", "cdp.mjs", os.environ.get("CHROMIUM", "chromium"))

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_right_click_and_menu_key_open_the_grouped_context_menu_and_run_an_item_at_three_widths(self):
        self.run_browser("firefox", "bidi.mjs", os.environ.get("FIREFOX", "firefox"))


if __name__ == "__main__":
    unittest.main()
