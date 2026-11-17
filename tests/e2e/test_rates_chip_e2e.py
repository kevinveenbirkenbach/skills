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

import hub_e2e_kit as base
import test_workbench_w4_e2e as w4
from hub_case import HubCase
from hub_support import iso

OUT = Path(os.environ.get("E2E_OUT", "/tmp/hub-header-rates-shots"))
HOUR = 3600
DAY = 86400
GIB = 1 << 30
METRICS = ["tasks", "commits", "krs", "tokens", "cpu", "ram", "vram", "swap", "disk"]
HEAD = ["Metric", "Chip", "min", "h", "d", "wk", "mo", "yr", "all"]
PARTS = {"presets": ["1 h", "6 h", "24 h", "7 d", "all"], "thumbs": 2, "replay": True, "live": True, "range": ["From", "To"], "units": ["min", "h", "d", "wk", "mo", "yr", "all"], "head": HEAD}
READ = """
  const chip = () => document.querySelector("#rates summary.rates-chip");
  const menu = () => document.querySelector("#rates details.rates-menu");
  const box = () => document.querySelector("#rates .rates-box");
  const thumb = (end) => document.querySelector(`#rates .span-slider .span-${end}`);
  const unit = (short) => all("#rates .rates-units button").find((button) => text(button) === short);
  const preset = (name) => all('#rates [aria-label="Time range"] button').find((button) => text(button) === name);
  const pick = (id) => document.querySelector(`#rates tr[data-metric="${id}"] input[type="checkbox"]`);
  const shown = () => all("#rates summary .rate").filter((node) => !node.hidden).map((node) => node.dataset.metric);
  const value = (id) => text(document.querySelector(`#rates summary .rate[data-metric="${id}"] .rate-value`));
  const cell = (id, period) => text(document.querySelector(`#rates tr[data-metric="${id}"] td[data-period="${period}"]`));
  const windowText = () => text(document.querySelector("#rates .rate-window"));
  const loaded = () => Boolean(chip() && shown().length && !text(chip()).includes("…"));
  const stored = async () => (await (await fetch("/api/state", {cache: "no-store"})).json()).settings.rates;
  const storedUntil = async (test, ms) => {
    const end = Date.now() + ms;
    while (Date.now() < end) {
      const found = await stored();
      if (test(found)) {
        return found;
      }
      await sleep(200);
    }
    return null;
  };
  if (!window.e2eAsked) {
    window.e2eAsked = [];
    const send = window.fetch.bind(window);
    window.fetch = (path, init) => {
      window.e2eAsked.push(String(path));
      return send(path, init);
    };
  }
  const asked = (path) => {
    const hits = window.e2eAsked.map((entry) => new URL(entry, location.href)).filter((url) => url.pathname === path);
    const last = hits[hits.length - 1];
    return last ? {from: Number(last.searchParams.get("from")), to: last.searchParams.has("to") ? Number(last.searchParams.get("to")) : null} : null;
  };
  const inside = (node) => {
    const rect = node.getBoundingClientRect();
    return rect.width > 0 && rect.left >= -1 && rect.right <= innerWidth + 1;
  };
  const fits = () => {
    const bar = document.querySelector(".navbar");
    const spill = menu().open && box().getClientRects().length ? box().scrollWidth > box().clientWidth + 1 : false;
    return {wide: document.documentElement.scrollWidth > innerWidth + 1, bar: bar.scrollWidth > bar.clientWidth + 1, chip: inside(chip()), spill};
  };
  const opened = async () => {
    if (!menu().open) {
      chip().click();
    }
    return Boolean(await until(() => menu().open && box().getClientRects().length, 4000));
  };
"""
PANEL = """(async () => {@HELPERS@@READ@
  if (!(await until(loaded, 15000))) {
    return {error: text(document.getElementById("rates"))};
  }
  const header = {time: Boolean(document.getElementById("time")), select: all(".navbar select").length, window: windowText()};
  const open = await opened();
  const parts = {
    presets: all('#rates [aria-label="Time range"] button').map(text), thumbs: all("#rates .span-slider input[type=range]").length,
    replay: Boolean(document.querySelector('#rates .replay button[aria-label="Replay"]')), live: Boolean(all("#rates .replay button").find((button) => text(button) === "Live")),
    range: all('#rates .custom input[type="datetime-local"]').map((input) => input.getAttribute("aria-label")), units: all("#rates .rates-units button").map(text),
    head: all("#rates .rates-table thead th").map(text),
  };
  unit("d").click();
  const saved = await storedUntil((found) => found.period === "day", 8000);
  preset("7 d").click();
  const week = Boolean(await until(() => windowText() === "7 d · /d" && loaded() && value("tokens").endsWith("/d"), 8000));
  await sleep(600);
  const tokens = {chip: value("tokens"), cell: cell("tokens", "day"), current: all('#rates td[aria-current="true"]').map((node) => node.dataset.period)};
  const rates = asked("/api/rates");
  thumb("from").focus();
  return {header, open, parts, saved, week, tokens, rates, now: Date.now() / 1000, from: Number(thumb("from").value), focused: document.activeElement === thumb("from"), fits: fits(), violations: window.e2eViolations || null};
})()"""
STEPPED = """(async () => {@HELPERS@@READ@
  await sleep(800);
  const stepped = {from: Number(thumb("from").value), to: Number(thumb("to").value)};
  thumb("from").value = String(Number(thumb("to").value) - 1);
  thumb("from").dispatchEvent(new Event("input", {bubbles: true}));
  await sleep(800);
  thumb("from").focus();
  return {stepped, near: {from: Number(thumb("from").value), to: Number(thumb("to").value)}, focused: document.activeElement === thumb("from")};
})()"""
BLOCKED = """(async () => {@HELPERS@@READ@
  await sleep(800);
  const blocked = {from: Number(thumb("from").value), to: Number(thumb("to").value)};
  thumb("from").value = "100";
  thumb("from").dispatchEvent(new Event("input", {bubbles: true}));
  thumb("to").value = "800";
  thumb("to").dispatchEvent(new Event("input", {bubbles: true}));
  const past = Boolean(await until(() => windowText() === "7 d · past · /d" && loaded(), 8000));
  await sleep(800);
  const label = text(document.querySelector("#rates .window-label"));
  return {blocked, past, label, rates: asked("/api/rates"), state: asked("/api/state"), now: Date.now() / 1000, fits: fits(), violations: window.e2eViolations || null};
})()"""
REPLAY = """(async () => {@HELPERS@@READ@
  const play = () => document.querySelector("#rates .replay button.icon-only");
  const liveButton = () => all("#rates .replay button").find((button) => text(button) === "Live");
  play().click();
  await sleep(1500);
  play().click();
  await sleep(800);
  const paused = text(document.querySelector("#rates .window-label"));
  await sleep(1500);
  const held = text(document.querySelector("#rates .window-label")) === paused && !liveButton().disabled;
  play().click();
  const ended = Boolean(await until(() => liveButton().disabled && text(document.querySelector("#rates .window-label")).endsWith("· live"), 45000));
  return {paused: !paused.endsWith("· live"), held, ended, window: windowText(), playing: play().getAttribute("aria-label"), violations: window.e2eViolations || null};
})()"""
NINE = """(async () => {@HELPERS@@READ@
  for (const id of @METRICS@) {
    if (!pick(id).checked) {
      pick(id).click();
      await storedUntil((found) => found.metrics.includes(id), 8000);
      await until(() => pick(id) && pick(id).checked, 4000);
    }
  }
  menu().open = false;
  await until(() => !menu().open, 2000);
  window.dispatchEvent(new Event("resize"));
  await sleep(400);
  const more = document.querySelector("#rates summary .rate-more");
  return {stored: (await stored()).metrics.length, shown: shown().length, more: more.hidden ? null : text(more), fits: fits(), violations: window.e2eViolations || null};
})()"""
KEPT = """(async () => {@HELPERS@@READ@
  if (!(await until(loaded, 15000))) {
    return {error: text(document.getElementById("rates"))};
  }
  const kept = {window: windowText(), metrics: (await stored()).metrics.length, unit: all('#rates .rates-units button[aria-pressed="true"]').map(text)};
  await opened();
  document.body.dispatchEvent(new KeyboardEvent("keydown", {key: "Escape", bubbles: true}));
  const escaped = Boolean(await until(() => !menu().open, 3000));
  chip().click();
  const reopened = Boolean(await until(() => menu().open, 3000));
  document.getElementById("main").click();
  const outside = Boolean(await until(() => !menu().open, 3000));
  return {kept, escaped, reopened, outside, fits: fits(), violations: window.e2eViolations || null};
})()"""


def probe(template: str) -> str:
    names = {"@HELPERS@": base.HELPERS, "@READ@": READ, "@METRICS@": json.dumps(METRICS)}
    for key, value in names.items():
        template = template.replace(key, value)
    return template


def sample(t: int) -> dict:
    gpus = [{"name": "0000:01:00.0", "util": 30.0, "vram_used": 2 * GIB, "vram_total": 8 * GIB}]
    return {"t": t, "disks": [{"mount": "/", "used": 400 << 30, "total": 1000 << 30}], "cpu": 25.0, "ram": 40.0, "swap": 5.0, "load": 1.0, "gpus": gpus, "queue": {"waiting": 0, "active": 0}}


def token(t: int, amount: int) -> dict:
    return {"t": t, "agent": "Skills", "model": "claude-opus-5-5", "input": amount - 400_000, "output": 0, "cache_read": 400_000, "cache_write": 0}


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestRatesChip(HubCase):
    drive = base.OrchestratorE2ECase.drive

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        now = int(time.time())
        hour = now - now % HOUR
        folder = self.kept / "resources"
        folder.mkdir()
        (folder / "samples.jsonl").write_text(self.jsonl([sample(now - 2 * HOUR + step * 60) for step in range(140)]), encoding="utf-8")
        tokens = [token(hour - 9 * DAY, 500_000), *(token(hour - day * DAY, 1_000_000) for day in range(7))]
        (folder / "tokens.jsonl").write_text(self.jsonl(tokens), encoding="utf-8")
        self.write_council({
            "rasci.json": {
                "work/first": {"title": "First", "status": "done", "worker": "Skills", "start": iso(now - 5 * HOUR), "end": iso(now - 3 * HOUR), "roles": {"Skills": "RA"}},
                "work/second": {"title": "Second", "status": "done", "worker": "Skills", "start": iso(now - 2 * HOUR), "end": iso(now - 1200), "roles": {"Skills": "RA"}, "key_results": [{"text": "shipped", "met": True, "met_at": iso(now - 1300)}]},
            },
            "news.jsonl": self.jsonl([{"ts": now - 10 * DAY, "from": "Skills", "to": [], "text": "the oldest record", "class": "post", "v": 2}]),
        })
        (self.council / "scores.jsonl").write_text(json.dumps({"time": now - 2 * HOUR, "remote": "example.org/skills", "path": "/repo", "branch": "main", "sha": "d" * 40, "values": {"score": 90}, "digest": "0" * 64}) + "\n", encoding="utf-8")
        self.base = f"http://{self.host}/"

    def steps(self, browser: str) -> list[dict]:
        steps = []
        for width, height in base.WIDTHS:
            shot = OUT / f"{browser}-{width}"
            steps += [
                {"width": width, "height": height, "url": f"{self.base}?{width}#home", "wait": 1200, "probe": probe(PANEL), "shot": f"{shot}-panel.png"},
                {"width": width, "height": height, "url": None, "wait": 0, "keys": ["ArrowRight"], "probe": probe(STEPPED), "shot": None},
                {"width": width, "height": height, "url": None, "wait": 0, "keys": ["ArrowRight"], "probe": probe(BLOCKED), "shot": f"{shot}-past.png"},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(REPLAY), "shot": None},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(NINE), "shot": f"{shot}-nine.png"},
                {"width": width, "height": height, "url": f"{self.base}?{width}-reloaded#home", "wait": 1200, "probe": probe(KEPT), "shot": None},
            ]
        return steps

    def check(self, data: dict, browser: str) -> None:
        results = iter(data["results"])
        fitting = {"wide": False, "bar": False, "chip": True, "spill": False}
        for width, _ in base.WIDTHS:
            panel, stepped, blocked, replay, nine, kept = (next(results) for _ in range(6))
            with self.subTest(browser=browser, width=width):
                self.assertNotIn("error", panel, panel)
                self.assertEqual(panel["header"]["time"], False)
                self.assertEqual(panel["header"]["select"], 0)
                self.assertTrue(panel["open"], panel)
                self.assertEqual(panel["parts"], PARTS)
                self.assertEqual(panel["saved"]["period"], "day", panel)
                self.assertTrue(panel["week"], panel)
                self.assertEqual(panel["tokens"], {"chip": "1.0M/d", "cell": "1.0M/d", "current": ["day"] * len(METRICS)}, panel)
                self.assertLess(abs(panel["rates"]["from"] - (panel["now"] - 7 * DAY)), 120, panel["rates"])
                self.assertEqual((panel["focused"], panel["fits"], w4.quiet(panel["violations"])), (True, fitting, []))
                self.assertEqual(stepped["stepped"], {"from": panel["from"] + 1, "to": 1000}, stepped)
                self.assertEqual((stepped["near"], stepped["focused"]), ({"from": 999, "to": 1000}, True), stepped)
                self.assertEqual(blocked["blocked"], {"from": 999, "to": 1000}, blocked)
                self.assertTrue(blocked["past"], blocked)
                self.assertIn(" – ", blocked["label"])
                self.assertFalse(blocked["label"].endswith("· live"), blocked)
                self.assertEqual(panel["from"], 300, panel)
                for asked in (blocked["rates"], blocked["state"]):
                    self.assertLess(abs(asked["from"] - (blocked["now"] - 9 * DAY)), 0.01 * 10 * DAY, asked)
                    self.assertLess(abs(asked["to"] - (blocked["now"] - 2 * DAY)), 0.01 * 10 * DAY, asked)
                self.assertEqual((blocked["fits"], w4.quiet(blocked["violations"])), (fitting, []))
                self.assertEqual({key: replay[key] for key in ("paused", "held", "ended", "playing")}, {"paused": True, "held": True, "ended": True, "playing": "Replay"}, replay)
                self.assertEqual(w4.quiet(replay["violations"]), [])
                self.assertEqual(nine["stored"], 9)
                if width == 1920:
                    self.assertEqual((nine["shown"], nine["more"]), (9, None), nine)
                if width == 390:
                    self.assertLess(nine["shown"], 9, nine)
                    self.assertEqual(nine["more"], f"+{9 - nine['shown']}", nine)
                self.assertEqual((nine["fits"], w4.quiet(nine["violations"])), (fitting, []))
                self.assertNotIn("error", kept, kept)
                self.assertEqual(kept["kept"], {"window": "24 h · /d", "metrics": 9, "unit": ["d"]})
                self.assertEqual({key: kept[key] for key in ("escaped", "reopened", "outside")}, dict.fromkeys(("escaped", "reopened", "outside"), True))
                self.assertEqual((kept["fits"], w4.quiet(kept["violations"])), (fitting, []))
        self.assertEqual(self.httpd.hub.settings.get()["rates"], {"period": "day", "metrics": ["tasks", "tokens", "cpu", "commits", "krs", "ram", "vram", "swap", "disk"]})

    def test_chromium_moves_the_time_range_and_the_rate_unit_into_the_rates_panel_at_three_widths(self):
        data = self.drive(self.steps("chromium"), None, init=w4.GUARD)
        (OUT / "chromium-rates.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        self.check(data, "chromium")

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_moves_the_time_range_and_the_rate_unit_into_the_rates_panel_at_three_widths(self):
        data = self.drive(self.steps("firefox"), None, "bidi.mjs", os.environ.get("FIREFOX", "firefox"), init=w4.GUARD)
        (OUT / "firefox-rates.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        self.check(data, "firefox")


if __name__ == "__main__":
    unittest.main()
