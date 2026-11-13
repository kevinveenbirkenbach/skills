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

import test_orchestrator_e2e as base
from hub_case import HubCase
from hub_support import ASK, iso
from kvb_orchestrator import skill_scripts

OUT = Path(os.environ.get("E2E_OUT", "/tmp/orchestrator-001-gaps-shots"))
BANNER = "MAYDAY · Docs: disk full"
LOCKED = "kept for the audit"
INIT = """() => {
  window.consoleErrors = [];
  const original = console.error.bind(console);
  console.error = (...args) => {
    window.consoleErrors.push(args.map(String).join(" "));
    original(...args);
  };
  window.addEventListener("error", (event) => window.consoleErrors.push(String(event.message || event.type)));
  window.addEventListener("unhandledrejection", (event) => window.consoleErrors.push(String(event.reason)));
}"""
SWEEP = """(async () => {@HELPERS@
  await screenShown(8000);
  await until(() => !(text(document.querySelector("#main .space-note")) || "").startsWith("Loading") && !all("#main .empty h2").some((title) => text(title).endsWith("…")), 8000);
  await sleep(300);
  const main = document.getElementById("main");
  const page = document.scrollingElement;
  const styles = new Map();
  const css = (node) => styles.get(node) || styles.set(node, getComputedStyle(node)).get(node);
  const scrolls = (node) => /(auto|scroll)/.test(css(node).overflowX + css(node).overflowY);
  const clips = (node) => css(node).overflowX !== "visible" || css(node).overflowY !== "visible";
  const shown = (node) => {
    const box = node.getBoundingClientRect();
    return node.getClientRects().length > 0 && css(node).visibility !== "hidden" && box.width > 1 && box.height > 1 && !node.closest("details:not([open]) > :not(summary)");
  };
  const path = (node) => {
    const parts = [];
    for (let cur = node; cur && cur !== main && parts.length < 4; cur = cur.parentElement) {
      parts.unshift(cur.tagName.toLowerCase() + (cur.id ? `#${cur.id}` : "") + [...cur.classList].slice(0, 2).map((cls) => `.${cls}`).join(""));
    }
    return parts.join(" > ");
  };
  const clipped = (node) => {
    let {top, bottom, left, right} = node.getBoundingClientRect();
    let [cur, statics] = [node, false];
    for (let up = node.parentElement; up && cur !== main; cur = up, up = up.parentElement) {
      if (css(cur).position === "fixed") {
        break;
      }
      statics = css(cur).position === "absolute" || (statics && css(cur).position === "static");
      if (statics && css(up).position === "static" && up !== main) {
        continue;
      }
      if (!clips(up)) {
        continue;
      }
      const own = up.getBoundingClientRect();
      if (scrolls(up)) {
        if (top - own.top + up.scrollTop < -1 || left - own.left + up.scrollLeft < -1) {
          return `before the scroll start of ${path(up)}`;
        }
        ({top, bottom, left, right} = own);
        continue;
      }
      if (css(up).textOverflow === "ellipsis" || css(up).webkitLineClamp !== "none") {
        return null;
      }
      if (top < own.top - 1 || bottom > own.bottom + 1 || left < own.left - 1 || right > own.right + 1) {
        return `cut by ${path(up)}`;
      }
    }
    return top < -1 || bottom > innerHeight + 1 || left < -1 || right > innerWidth + 1 ? "outside the window" : null;
  };
  const nodes = all("#main *").filter((node) => !node.ownerSVGElement && !node.closest("canvas") && shown(node));
  const cut = nodes.map((node) => [path(node), clipped(node)]).filter(([, why]) => why);
  const owner = (node) => {
    for (let up = node.parentElement; up && up !== main; up = up.parentElement) {
      if (scrolls(up)) {
        return up;
      }
    }
    return main;
  };
  const lasts = new Map();
  for (const node of nodes) {
    const box = owner(node);
    const at = node.getBoundingClientRect().bottom - box.getBoundingClientRect().top + box.scrollTop;
    if (!lasts.has(box) || at > lasts.get(box)[1]) {
      lasts.set(box, [node, at]);
    }
  }
  const seen = (node) => {
    const {bottom} = node.getBoundingClientRect();
    for (let up = node.parentElement; up && up !== document.body; up = up.parentElement) {
      if (clips(up) && bottom > up.getBoundingClientRect().bottom + 1) {
        return `below the end of ${path(up)}`;
      }
    }
    return bottom <= innerHeight + 1 ? null : "below the window";
  };
  const kept = [main, ...nodes].filter(scrolls).map((node) => [node, node.scrollTop, node.scrollLeft]);
  const unreached = [];
  for (const [box, [node]] of lasts) {
    node.scrollIntoView({block: "end", inline: "nearest"});
    await sleep(100);
    const why = seen(node);
    if (why) {
      unreached.push(`${path(box) || "main"} last ${path(node)}: ${why}`);
    }
  }
  const moved = page.scrollTop !== 0 || page.scrollLeft !== 0;
  kept.forEach(([node, top, left]) => node.scrollTo(left, top));
  page.scrollTo(0, 0);
  const banner = document.getElementById("mayday");
  const expected = [
    ...Nav.TABS.filter(([id]) => !["agents", "artifacts", "tasks"].includes(id)).map(([id]) => Nav.hashOf(id, null)),
    ...Object.values(Nav.SUBS).flat().map(([sub]) => Nav.hashOf(sub, null)),
    ...Object.keys(Nav.PANES).map((pane) => Nav.hashOf(pane, null)),
    ...["agents", "artifacts", "tasks"].flatMap((screen) => Nav.viewsOf(screen).map(([id]) => Nav.hashOf(screen, id))),
  ];
  return {
    hash: location.hash, banner: banner.hidden ? null : text(banner),
    layout: ["pane", "fit"].filter((cls) => document.body.classList.contains(cls)),
    tall: page.scrollHeight > innerHeight, wide: page.scrollWidth > innerWidth + 1,
    scrollers: lasts.size, unreached, moved,
    cut: [...new Set(cut.map(([where, why]) => `${where}: ${why}`))].slice(0, 12), count: cut.length,
    errors: window.consoleErrors || ["no console recorder"],
    expected, nav: all("#tabs button[id^='tab-']").map((button) => Nav.hashOf(button.id.slice(4), null)),
    views: all('#main [aria-label="View"] button').map(name),
    viewNames: [...new Set(["agents", "artifacts", "tasks"].flatMap((screen) => Nav.viewsOf(screen).map(([, label]) => label)))],
  };
})()"""
FILTER = """(async () => {@HELPERS@
  await screenShown(8000);
  const menu = await until(() => all("#main details.menu").find((details) => name(details.querySelector("summary")) === "Filter"), 8000);
  if (!menu) {
    return {error: text(document.getElementById("main"))};
  }
  const box = menu.querySelector(".menu-box");
  const groups = () => Object.fromEntries(all(".chips[aria-label]", box).map((group) => [group.getAttribute("aria-label"), all("button, .chip, .muted", group).filter((node) => node.parentElement === group).map(name)]));
  const outside = ["Kinds", "Transcript parts", "Saved views"].filter((label) => all(`#main [aria-label="${label}"]`).some((node) => !menu.contains(node)));
  menu.querySelector("summary").click();
  await sleep(200);
  const opened = menu.open;
  const before = groups();
  document.querySelector('#main [aria-label="Categories"] button[aria-label="Transcripts"]').click();
  await until(() => all('.chips[aria-label="Transcript parts"] button', box).length, 4000);
  return {
    opened, headings: all("h3", box).map(text), before, after: groups(), outside,
    range: all('input[type="datetime-local"]', box).map((input) => input.getAttribute("aria-label")),
    tall: document.documentElement.scrollHeight > window.innerHeight, wide: document.documentElement.scrollWidth > window.innerWidth + 1,
  };
})()"""
TREE_ICONS = """(async () => {@HELPERS@
  await screenShown(8000);
  const card = await until(() => all("#main details.repo").find((details) => details.textContent.includes("elsewhere")), 8000);
  if (!card) {
    return {error: text(document.getElementById("main"))};
  }
  const chips = Object.fromEntries(all("#main span.state").map((chip) => [name(chip), [(chip.querySelector("use") || {getAttribute: () => null}).getAttribute("href"), chip.title === chip.getAttribute("aria-label"), chip.getAttribute("role"), text(chip)]]));
  const row = all("#main .branch-row", card).find((entry) => text(entry.querySelector(".branch-name strong")) === "old/stale");
  return {chips, stale: row ? all(".branch-name span.state", row).map(name) : null, worktree: row ? all(".wt-head span.state", row).map(name) : null};
})()"""
MAYDAY = """(async () => {@HELPERS@
  await screenShown(8000);
  window.confirm = () => true;
  if (!@SIGNS@) {
    navigator.credentials.get = () => Promise.reject(new DOMException("The operator canceled.", "NotAllowedError"));
  }
  const banner = document.getElementById("mayday");
  const cancel = await until(() => !banner.hidden && banner.querySelector("button"), 8000);
  if (!cancel) {
    return {error: "no mayday banner", hidden: banner.hidden};
  }
  const tint = document.createElement("i");
  tint.style.color = "var(--alarm)";
  document.body.append(tint);
  const red = getComputedStyle(tint).color;
  tint.remove();
  const seen = {text: text(banner.querySelector(".text")), role: banner.getAttribute("role"), red: getComputedStyle(banner).backgroundColor === red,
    cancel: [cancel.getAttribute("aria-label"), cancel.title, text(cancel), Boolean(cancel.querySelector('use[href="#bi-x-octagon"]'))]};
  const shown = new Set(all("#toasts .toast"));
  cancel.click();
  const done = @SIGNS@ ? await until(() => all("#toasts .toast").filter((node) => !shown.has(node)).map(text).find((line) => line.startsWith("Cancel mayday")), 15000) : (await sleep(1500), null);
  const hidden = @SIGNS@ ? Boolean(await until(() => banner.hidden, 15000)) : banner.hidden;
  return {seen, done, hidden, children: banner.children.length};
})()"""
GONE = """(async () => {@HELPERS@
  await screenShown(8000);
  await sleep(600);
  const banner = document.getElementById("mayday");
  return {hidden: banner.hidden, display: getComputedStyle(banner).display, children: banner.children.length, alerts: all('[role="alert"]').filter((node) => node.getClientRects().length).length};
})()"""


def probe(template: str, signs: bool = False) -> str:
    return template.replace("@HELPERS@", base.HELPERS).replace("@SIGNS@", "true" if signs else "false")


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestOrchestratorGaps(HubCase):
    drive = base.TestOrchestratorE2E.drive
    authenticator = base.TestOrchestratorE2E.authenticator
    subagents = base.TestOrchestratorE2E.subagents
    beside = base.TestOrchestratorE2E.beside

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        now = time.time()
        root = self.write_tree()
        data = json.loads(self.tree_file.read_text(encoding="utf-8"))
        elsewhere = data["repos"][1]
        lone = next(item for item in elsewhere["items"] if item["branch"] == "lone")
        stale = {**lone, "branch": "old/stale", "worktree": f"{root}/worktrees/x/y/stale", "locked": LOCKED, "state": "stale", "reason": "stale: no commit for 90 days"}
        elsewhere["items"].append(stale)
        self.tree_file.write_text(json.dumps(data), encoding="utf-8")
        feature = f"{root}/worktrees/github.com/me/demo/feature"
        self.claim("s1", "Skills session")
        self.write_council({
            "work/s2/claim.json": {"office": "work/s2", "session": "s2", "runtime": "claude", "name": "Stage", "since": iso(now - 7200), "beat": now - 2000, "work": "x"},
            "chair/claim.json": {"office": "chair", "session": "s1", "runtime": "claude", "name": "Skills session", "since": iso(now - 7200), "beat": now, "work": "allocate"},
            "rasci.json": {
                "work/feature": {"title": "Show the merge flow in the hub", "status": "running", "worker": "Skills session", "workdir": feature, "prio": 1, "roles": {"Skills session": "RA", "Operator": "C"}},
                "work/docs": {"title": "Update the README", "status": "blocked", "worker": "Docs", "branch": "main", "roles": {"Docs": "R", "Maintainer": "A"}},
                "operator/push": {"title": "git push", "workdir": "/repo", "status": "done", "roles": {"Operator": "R"}},
            },
            "queue.json": {"seq": 3, "entries": [{"id": "gate-3", "kind": "gate", "task": "work/feature", "workdir": feature, "session": "s1", "name": "Skills", "status": "waiting", "enqueued": now - 120, "cmd": "make test"}]},
            "radio-silence.json": {"since": now - 60, "until": now + 3600, "by": "Docs", "text": "disk full"},
            "news.jsonl": self.jsonl([
                {"ts": now - 600, "from": "Skills", "to": ["Stage"], "text": "rebase please", "class": "post", "v": 2},
                {"ts": now - 500, "from": "Stage", "to": ["Skills"], "text": "gate red", "class": "call", "v": 2},
                {"ts": now - 400, "from": "Maintainer", "to": [], "text": "main is green", "class": "newsletter", "v": 2},
                {"ts": now - 60, "from": "Docs", "to": [], "text": "MAYDAY disk full", "class": "mayday", "v": 2},
            ]),
        })
        self.subagents(now)
        self.request("feat: orchestrator", "")
        self.create_ask({**ASK, "timeout": 3600})
        self.base = f"http://localhost:{self.port}/"

    def steps(self, browser: str, signs: bool) -> list[dict]:
        steps = [
            {"width": width, "height": height, "url": f"{self.base}?sweep-{width}-{screen.replace('/', '-')}#{screen}", "wait": 900, "probe": probe(SWEEP), "shot": str(OUT / f"{browser}-{width}-sweep-{screen.replace('/', '-')}.png")}
            for width, height in base.WIDTHS
            for screen in base.SCREENS
        ]
        for width, height in base.WIDTHS:
            steps.append({"width": width, "height": height, "url": f"{self.base}?{width}-filter#stream", "wait": 900, "probe": probe(FILTER), "shot": str(OUT / f"{browser}-{width}-filter.png")})
            steps.append({"width": width, "height": height, "url": f"{self.base}?{width}-icons#artifacts/tree", "wait": 900, "probe": probe(TREE_ICONS), "shot": str(OUT / f"{browser}-{width}-tree-icons.png")})
        (width, height), *rest = base.WIDTHS
        steps.append({"width": width, "height": height, "url": f"{self.base}?{width}-mayday#stream", "wait": 900, "probe": probe(MAYDAY, signs), "shot": str(OUT / f"{browser}-{width}-mayday.png")})
        if signs:
            steps += [{"width": width, "height": height, "url": f"{self.base}?{width}-gone#{screen}", "wait": 900, "probe": probe(GONE), "shot": str(OUT / f"{browser}-{width}-no-mayday.png")} for (width, height), screen in zip(rest, ("agents/orbit", "artifacts/tree"), strict=True)]
        return steps

    def check(self, data: dict, signs: bool) -> None:
        walked = len(base.WIDTHS) * len(base.SCREENS)
        screens = [screen for _ in base.WIDTHS for screen in base.SCREENS]
        widths = [width for width, _ in base.WIDTHS for _ in base.SCREENS]
        sweep = data["results"][:walked]
        with self.subTest(part="every screen and view"):
            self.assertNotIn("error", sweep[0], sweep[0])
            self.assertEqual(sorted(sweep[0]["expected"]), sorted(f"#{screen}" for screen in base.SCREENS))
            self.assertEqual([target for target in sweep[0]["nav"] if not any(f"#{screen}" == target or f"#{screen}".startswith(f"{target}/") for screen in base.SCREENS)], [])
            self.assertEqual(sorted({view for found in sweep for view in found["views"]}), sorted(sweep[0]["viewNames"]))
        for found, screen, width in zip(sweep, screens, widths, strict=True):
            with self.subTest(screen=screen, width=width):
                self.assertNotIn("error", found, found)
                self.assertEqual((found["hash"], found["banner"]), (f"#{screen}", BANNER))
                self.assertEqual(len(found["layout"]), 1, found["layout"])
                self.assertEqual((found["tall"], found["wide"], found["moved"]), (False, False, False), "the page scrolls")
                self.assertEqual(found["unreached"], [], "a scroller cannot show its last child")
                self.assertEqual((found["count"], found["cut"]), (0, []), "an element sits outside every scroller")
                self.assertEqual(found["errors"], [], "console error")
        extra = iter(data["results"][walked:])
        for width, _ in base.WIDTHS:
            menu, icons = next(extra), next(extra)
            with self.subTest(width=width, part="filter"):
                self.assertNotIn("error", menu, menu)
                self.assertEqual((menu["opened"], menu["headings"], menu["outside"], menu["range"]), (True, ["Kinds", "Transcript parts", "Saved views", "Custom time range"], [], ["From", "To"]))
                kinds = ["only waiting", *self.snapshot()["kinds"].values()]
                self.assertEqual(menu["before"], {"Kinds": kinds, "Transcript parts": ["Only with the kind Transcripts."], "Saved views": ["Save view"]})
                self.assertEqual(menu["after"]["Transcript parts"], ["User", "Assistant", "Tool call", "Tool result", "System"])
                self.assertEqual((menu["tall"], menu["wide"]), (False, False))
            with self.subTest(width=width, part="tree icons"):
                self.assertNotIn("error", icons, icons)
                chips = icons["chips"]
                expected = {
                    "merged by #12 into main": "#bi-sign-merge-left", "clean": "#bi-check-circle", "not committed: 0 staged, 0 changed, 1 new": "#bi-pencil-square", "1 commits unpushed": "#bi-cloud-upload",
                    "upstream gone": "#bi-cloud-slash", f"locked: {LOCKED}": "#bi-lock-fill", "stale": "#bi-hourglass-bottom", "protected": "#bi-shield-lock",
                }
                for label, href in expected.items():
                    with self.subTest(label=label):
                        self.assertIn(label, chips, sorted(chips))
                        self.assertEqual(chips[label][:3], [href, True, "img"])
                self.assertEqual((chips["1 commits unpushed"][3], chips["not committed: 0 staged, 0 changed, 1 new"][3]), ("1", "1"))
                self.assertIn("stale", icons["stale"])
                self.assertEqual(icons["worktree"], ["clean", f"locked: {LOCKED}"])
        mayday, gone = next(extra), list(extra)
        clear = (skill_scripts.RADIO, ["clear", "--force", "--session", "Operator"])
        with self.subTest(part="mayday"):
            self.assertNotIn("error", mayday, mayday)
            self.assertEqual(mayday["seen"], {"text": BANNER, "role": "alert", "red": True, "cancel": ["cancel", "cancel: end the mayday (radio.py clear)", "", True]})
            if signs:
                self.assertTrue((mayday["done"] or "").startswith("Cancel mayday: done"), mayday)
                self.assertEqual((mayday["hidden"], mayday["children"]), (True, 0))
                self.assertEqual(self.scripts.calls.count(clear), 1)
            else:
                self.assertEqual((mayday["hidden"], mayday["children"]), (False, 2))
                self.assertNotIn(clear, self.scripts.calls)
        with self.subTest(part="no mayday"):
            self.assertEqual(gone, [{"hidden": True, "display": "none", "children": 0, "alerts": 0}] * (len(base.WIDTHS) - 1 if signs else 0))

    def lift(self) -> None:
        handled = []

        def answer() -> None:
            for script, args in self.scripts.calls[len(handled) :]:
                handled.append(script)
                if script == skill_scripts.RADIO and args[:1] == ["clear"]:
                    (self.council / "radio-silence.json").unlink(missing_ok=True)

        self.beside(answer)

    def test_chromium_fits_every_screen_fills_the_filter_menu_marks_locked_and_stale_and_shows_the_mayday_banner_only_until_its_cancel_clears_it(self):
        self.lift()
        data = self.drive(self.steps("chromium", True), self.authenticator(), init=INIT)
        (OUT / "chromium-gaps.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        self.check(data, True)

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_fits_every_screen_fills_the_filter_menu_marks_locked_and_stale_and_keeps_the_mayday_without_a_signature(self):
        data = self.drive(self.steps("firefox", False), None, "bidi.mjs", os.environ.get("FIREFOX", "firefox"), INIT)
        (OUT / "firefox-gaps.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        blocked = [error for error in data["errors"] if error.startswith("Content-Security-Policy")]
        self.assertEqual([error for error in data["errors"] if error not in blocked and "/favicon.ico" not in error], [])
        self.assertEqual([error for error in blocked if "(style-src-elem)" not in error and "/favicon.ico" not in error], [])
        self.check(data, False)


if __name__ == "__main__":
    unittest.main()
