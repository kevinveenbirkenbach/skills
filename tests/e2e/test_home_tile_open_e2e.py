from __future__ import annotations

import json
import os
import shutil
import sys
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

import test_home_bookmarks_e2e as bm
import test_home_dashboard_e2e as dash
import test_orchestrator_e2e as base
import test_resources_view_e2e as res
import test_workbench_w4_e2e as w4
from hub_case import HubCase

OUT = Path(os.environ.get("E2E_OUT", "/tmp/hub-home-tile-open-shots"))
GONE = "task:work/none-such"
PANELS = ["agents/orbit", "tasks/3d", "tasks/operator", "agents/order", "radio-log", "stream", "artifacts/tree"]
LANDINGS = {
    "panel:agents/orbit": ("#agents/orbit", "tab-agents"),
    "panel:tasks/3d": ("#tasks/3d", "tab-tasks"),
    "panel:tasks/operator": ("#tasks/operator", "tab-inbox"),
    "panel:agents/order": ("#agents/hierarchy", "tab-agents"),
    "panel:radio-log": ("#stream", "tab-stream"),
    "panel:stream": ("#stream", "tab-stream"),
    "panel:artifacts/tree": ("#artifacts/tree", "tab-artifacts"),
    "task": ("#tasks/list", "tab-tasks"),
    "message": ("#stream", "tab-stream"),
    "artifact": ("#artifacts/orbit", "tab-artifacts"),
    "agent": ("#agents/orbit", "tab-agents"),
    "ancestry": ("#artifacts/tree", "tab-artifacts"),
    "metric": ("#resources", "tab-resources"),
}
KIT = """
  const lineIds = (root) => (root ? [...new Set(all("path.res-line", root).map((path) => path.dataset.id))] : []);
  const itemOf = (selector, value) => all(selector).find((node) => node.dataset.item === value) || null;
  const closeAll = async () => {
    const popup = document.getElementById("popup");
    if (popup.open) {
      popup.querySelector('.popup-head button[aria-label="Close"]').click();
    }
    const sheet = document.querySelector('#sheet:not([hidden]) .sheet-head button[aria-label="Close"]');
    if (sheet) {
      sheet.click();
    }
    if (!document.getElementById("radio-spot").hidden) {
      document.getElementById("radio-open").click();
    }
    await sleep(100);
  };
  const landed = async (key) => {
    const cut = key.indexOf(":");
    const kind = key.slice(0, cut);
    const id = key.slice(cut + 1);
    const raw = Panels.raw(id);
    await screenShown(8000);
    let found = null;
    if (kind === "panel") {
      found = await until(() => (id === "radio-log" ? document.querySelector('#radio-spot:not([hidden]) [data-panel="radio-log"]') : document.querySelector(`#main [data-panel="${id}"]`)), 8000);
    } else if (kind === "task") {
      found = await until(() => all('#sheet:not([hidden]) [role="dialog"]').find((node) => node.getAttribute("aria-label") === raw), 8000);
    } else if (kind === "ancestry") {
      found = await until(() => itemOf("#main details[open] [data-item]", `ancestry:${raw}`), 8000);
    } else if (kind === "metric") {
      found = await until(() => lineIds(document.querySelector('#main [data-panel="resources-hardware"]')).join() === "@CPU@", 15000);
    } else {
      found = await until(() => itemOf("#popup[open] [data-item]", `${kind}:${raw}`), 10000);
    }
    await sleep(150);
    const box = found instanceof Element ? found.getBoundingClientRect() : null;
    return {
      key, found: Boolean(found), hash: location.hash, screen: document.getElementById("main").getAttribute("aria-labelledby"),
      inView: box ? box.bottom > 0 && box.top < innerHeight : null, focused: document.activeElement ? document.activeElement.id || null : null,
      chips: kind === "metric" ? all('#main [data-panel="resources-hardware"] .legend-chip[aria-pressed="true"]').map((chip) => chip.dataset.chip) : null,
      picked: kind === "artifact" ? all("#main .picked[data-pick]").map((node) => node.dataset.pick) : null,
    };
  };
"""
SEED = """(async () => {@HELPERS@@HOME@@KIT@
  await go("agents/orbit");
  const agent = await until(() => document.querySelector("#main svg .node.k-session[data-pick]"), 8000);
  await go("stream");
  const message = await until(() => document.querySelector('#main [data-item^="message:"]'), 8000);
  await go("artifacts/tree");
  const branch = await until(() => document.querySelector('#main .branch-row[data-item^="artifact:"]'), 8000);
  const ancestry = document.querySelector('#main [data-item^="ancestry:"]');
  const token = (node, attr) => Panels.token(node.getAttribute(attr).slice(node.getAttribute(attr).indexOf(":") + 1));
  const narrow = innerWidth > 640 ? 1 : 4;
  const pins = [
    ...@PANELS@.map((id) => ({kind: "panel", id, w: 4, h: 3})),
    {kind: "task", id: "work/feature", w: 4, h: 3},
    {kind: "message", id: token(message, "data-item"), w: 4, h: 3},
    {kind: "artifact", id: token(branch, "data-item"), w: narrow, h: 3},
    {kind: "agent", id: Panels.token(agent.dataset.pick), w: 4, h: 3},
    {kind: "ancestry", id: token(ancestry, "data-item"), w: 4, h: 3},
    {kind: "metric", id: `hardware/${Panels.digest("@CPU@")}`, w: 4, h: 3, view: {chart: "hardware", tokens: "interval", shown: ["@CPU@"]}},
    {kind: "task", id: "@GONE@".slice(5), w: 4, h: 3},
  ];
  await ViewStore.update("home.pins", () => pins);
  return {keys: pins.map((pin) => `${pin.kind}:${pin.id}`)};
})()"""
HEADERS = """(async () => {@HELPERS@@HOME@@KIT@
  await go("home");
  await until(() => !all("#main .home-tile .empty h2").some((title) => text(title).endsWith("…")), 8000);
  await sleep(600);
  const rect = (node) => {
    const box = node.getBoundingClientRect();
    return [Math.round(box.width), Math.round(box.height)];
  };
  const heads = all("#main .home-tile").map((node) => {
    const head = node.querySelector(".home-head");
    const box = head.getBoundingClientRect();
    const shown = [...head.children].filter((child) => child.getClientRects().length);
    const title = head.querySelector(".home-title");
    const open = head.querySelector(".home-open");
    open.focus();
    const focused = document.activeElement === open;
    return {
      key: node.dataset.pin, w: Number(node.dataset.w), gone: node.classList.contains("gone"), overflow: head.scrollWidth > head.clientWidth + 1,
      outside: shown.filter((child) => child.getBoundingClientRect().left < box.left - 0.5 || child.getBoundingClientRect().right > box.right + 0.5).map((child) => child.className),
      order: shown.map((child) => [...child.classList].find((name) => name.startsWith("home-"))),
      ellipsis: [getComputedStyle(title).textOverflow, getComputedStyle(title).whiteSpace, title.scrollWidth > title.clientWidth],
      open: open.hidden ? null : {href: open.getAttribute("href"), title: open.getAttribute("title"), label: open.getAttribute("aria-label"), tag: open.tagName, focused, tabIndex: open.tabIndex, size: rect(open), unpin: rect(head.querySelector(".home-unpin")), glyph: open.querySelector("use").getAttribute("href")},
    };
  });
  document.activeElement.blur();
  window.scrollTo(0, 0);
  const first = document.querySelector("#main .home-tile .home-open:not([hidden])");
  first.focus();
  await sleep(200);
  return {heads};
})()"""
NARROW = """(async () => {@HELPERS@@HOME@
  const found = all("#main .home-tile").find((node) => node.dataset.pin.startsWith("artifact:"));
  found.scrollIntoView({block: "center"});
  found.querySelector(".home-open").focus();
  await sleep(300);
  return {key: found.dataset.pin};
})()"""
CLICKS = """(async () => {@HELPERS@@HOME@@KIT@
  const results = [];
  for (const key of @KEYS@) {
    await ViewStore.update("resources.hidden", () => []);
    await go("home");
    const open = await until(() => tile(key) && tile(key).querySelector(".home-open:not([hidden])"), 8000);
    if (!open) {
      results.push({key, found: false, missing: true});
      continue;
    }
    open.scrollIntoView({block: "center"});
    open.click();
    results.push(await landed(key));
    await closeAll();
  }
  await ViewStore.update("resources.hidden", () => []);
  return {results};
})()"""
LANDED = """(async () => {@HELPERS@@HOME@@KIT@
  return landed("@KEY@");
})()"""


def probe(template: str, **names: str) -> str:
    fills = {"@HELPERS@": base.HELPERS, "@HOME@": dash.HOME, "@KIT@": KIT, "@CPU@": res.CPU, "@GONE@": GONE, "@PANELS@": json.dumps(PANELS)}
    fills.update({f"@{key.upper()}@": value for key, value in names.items()})
    for key, value in fills.items():
        template = template.replace(key, value)
    return template


def landing(key: str) -> tuple[str, str]:
    return LANDINGS[key] if key in LANDINGS else LANDINGS[key.split(":", 1)[0]]


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestHomeTileOpen(HubCase):
    seed = base.TestOrchestratorE2E.seed
    subagents = base.TestOrchestratorE2E.subagents
    drive = base.TestOrchestratorE2E.drive
    sample = w4.TestWorkbenchResources.sample

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        self.seed()
        now = int(time.time())
        self.start = now - now % 60 - w4.ROWS * 60
        folder = self.kept / "resources"
        folder.mkdir()
        (folder / "samples.jsonl").write_text(self.jsonl([self.sample(index) for index in range(w4.ROWS)]), encoding="utf-8")

    def pinned(self, browser: str) -> list[dict]:
        steps = []
        for width, height in base.WIDTHS:
            page = f"{self.base}?{width}"
            shot = str(OUT / f"{browser}-{width}")
            steps += [
                {"width": width, "height": height, "url": f"{page}-clear#stream", "wait": 600, "probe": bm.CLEAR, "shot": None},
                {"width": width, "height": height, "url": f"{page}-seed#stream", "wait": 1200, "probe": probe(SEED), "shot": None},
                {"width": width, "height": height, "url": f"{page}-home#home", "wait": 1500, "probe": probe(HEADERS), "shot": f"{shot}-home-headers.png"},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(NARROW), "shot": f"{shot}-home-narrow.png"},
            ]
        return steps

    def clicks(self, keys: list[str]) -> list[dict]:
        steps = []
        for width, height in base.WIDTHS:
            steps.append({"width": width, "height": height, "url": f"{self.base}?{width}-clicks#home", "wait": 1500, "probe": probe(CLICKS, keys=json.dumps(keys)), "shot": None})
        return steps

    def tabs(self, links: dict[int, dict[str, str]]) -> list[dict]:
        steps = []
        for width, height in base.WIDTHS:
            for index, (key, href) in enumerate(sorted(links[width].items())):
                steps.append({"width": width, "height": height, "url": f"{self.base}?{width}-tab-{index}{href}", "wait": 1500, "probe": probe(LANDED, key=key), "shot": None})
        return steps

    def check_heads(self, heads: list[dict], width: int) -> dict[str, str]:
        links = {}
        for head in heads:
            with self.subTest(width=width, key=head["key"]):
                self.assertFalse(head["overflow"], head)
                self.assertEqual(head["outside"], [], head)
                self.assertEqual(head["ellipsis"][:2], ["ellipsis", "nowrap"], head)
                if head["key"] == GONE:
                    self.assertTrue(head["gone"], head)
                    self.assertIsNone(head["open"], head)
                    self.assertEqual(head["order"], ["home-grip", "home-title", "home-unpin"], head)
                    continue
                self.assertFalse(head["gone"], head)
                self.assertEqual(head["order"], ["home-grip", "home-title", "home-open", "home-unpin"], head)
                found = head["open"]
                self.assertEqual((found["tag"], found["label"], found["focused"], found["tabIndex"], found["glyph"]), ("A", "Open", True, 0, "#bi-arrows-angle-expand"), found)
                self.assertTrue(found["title"].startswith("Open: show ") and found["title"].endswith(" in full view"), found)
                self.assertEqual(found["size"], found["unpin"], found)
                hash_, _ = landing(head["key"])
                if head["key"].startswith("panel:"):
                    self.assertEqual(found["href"], {"panel:agents/order": "#agents/hierarchy?open=panel:agents/order", "panel:radio-log": "#stream/radio"}.get(head["key"], f"#{head['key'][6:]}"), found)
                else:
                    self.assertEqual(found["href"], f"{hash_}?open={head['key']}", found)
                links[head["key"]] = found["href"]
        narrow = [head for head in heads if head["key"].startswith("artifact:")]
        self.assertEqual(len(narrow), 1, heads)
        if width != 390:
            self.assertEqual(narrow[0]["w"], 1, narrow)
            self.assertTrue(narrow[0]["ellipsis"][2], narrow)
        return links

    def check_landed(self, found: dict, where: str) -> None:
        with self.subTest(where=where, key=found["key"]):
            hash_, screen = landing(found["key"])
            self.assertEqual((found["found"], found["hash"], found["screen"]), (True, hash_, screen), found)
            kind = found["key"].split(":", 1)[0]
            if kind == "ancestry":
                self.assertTrue(found["inView"], found)
            if found["key"] == "panel:agents/order":
                self.assertEqual(found["focused"], "agent-order-title", found)
            if kind == "metric":
                self.assertEqual(found["chips"], [res.CPU], found)
            if kind == "artifact":
                self.assertEqual(len(found["picked"]), 1, found)

    def run_browser(self, browser: str, driver: str, binary: str) -> None:
        first = self.drive(self.pinned(browser), None, driver, binary, init=w4.GUARD)
        (OUT / f"{browser}-pinned.json").write_text(json.dumps(first, indent=1), encoding="utf-8")
        self.assertEqual([error for error in first["errors"] if "/favicon.ico" not in error], [])
        results = iter(first["results"])
        links = {}
        keys = []
        for width, _ in base.WIDTHS:
            next(results)
            keys = next(results)["keys"]
            self.assertEqual(len(keys), len(PANELS) + 7, keys)
            links[width] = self.check_heads(next(results)["heads"], width)
            self.assertEqual(sorted(links[width]), sorted(key for key in keys if key != GONE))
            self.assertTrue(next(results)["key"].startswith("artifact:"))
        clicked = self.drive(self.clicks([key for key in keys if key != GONE]), None, driver, binary, init=w4.GUARD)
        (OUT / f"{browser}-clicks.json").write_text(json.dumps(clicked, indent=1), encoding="utf-8")
        self.assertEqual([error for error in clicked["errors"] if "/favicon.ico" not in error], [])
        for (width, _), result in zip(base.WIDTHS, clicked["results"], strict=True):
            for found in result["results"]:
                self.check_landed(found, f"{browser} click {width}")
        tabs = self.drive(self.tabs(links), None, driver, binary, init=w4.GUARD)
        (OUT / f"{browser}-tabs.json").write_text(json.dumps(tabs, indent=1), encoding="utf-8")
        self.assertEqual([error for error in tabs["errors"] if "/favicon.ico" not in error], [])
        for found in tabs["results"]:
            self.check_landed(found, f"{browser} new tab")

    def test_chromium_opens_every_tile_kind_in_its_full_view_by_click_and_by_link_at_three_widths(self):
        self.run_browser("chromium", "cdp.mjs", os.environ.get("CHROMIUM", "chromium"))

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_opens_every_tile_kind_in_its_full_view_by_click_and_by_link_at_three_widths(self):
        self.run_browser("firefox", "bidi.mjs", os.environ.get("FIREFOX", "firefox"))


if __name__ == "__main__":
    unittest.main()
