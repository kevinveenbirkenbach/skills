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
import test_home_bookmarks_e2e as bm
from hub_case import HubCase

OUT = Path(os.environ.get("E2E_OUT", "/tmp/hub-059-shots"))
INIT = """() => {
  window.e2eViolations = [];
  document.addEventListener("securitypolicyviolation", (event) => window.e2eViolations.push(`${event.violatedDirective} ${event.blockedURI}`));
  window.e2eHidden = false;
  Object.defineProperty(Document.prototype, "hidden", {configurable: true, get: () => window.e2eHidden});
  window.e2eAudio = {starts: 0, stops: 0};
  const start = OscillatorNode.prototype.start;
  const stop = OscillatorNode.prototype.stop;
  OscillatorNode.prototype.start = function (...args) { window.e2eAudio.starts += 1; return start.apply(this, args); };
  OscillatorNode.prototype.stop = function (...args) { window.e2eAudio.stops += 1; return stop.apply(this, args); };
}"""
POLLS = """(async () => {@HELPERS@
  await streamShowsAll();
  const list = await until(() => document.querySelector('#main [data-panel="stream"]') && document.querySelector('#main [data-panel="stream"] li.entry') ? document.querySelector('#main [data-panel="stream"]') : null, 10000);
  if (!list) {
    return {error: text(document.getElementById("main"))};
  }
  await sleep(1500);
  const first = list.querySelector("li.entry");
  let replaced = 0;
  new MutationObserver((records) => { replaced += records.length; }).observe(list, {childList: true});
  await sleep(11500);
  const kept = {connected: first.isConnected, replaced, rows: list.querySelectorAll("li.entry").length};
  const note = document.getElementById("sky-note");
  let sky = 0;
  new MutationObserver((records) => { sky += records.length; }).observe(note, {childList: true, characterData: true, subtree: true});
  window.e2eHidden = true;
  document.dispatchEvent(new Event("visibilitychange"));
  await sleep(11500);
  const hidden = sky;
  window.e2eHidden = false;
  document.dispatchEvent(new Event("visibilitychange"));
  await sleep(3000);
  return {kept, hidden, shown: sky - hidden, violations: window.e2eViolations};
})()"""
MUSIC = """(async () => {@HELPERS@
  const audio = () => ({...window.e2eAudio});
  const save = async (on, volume) => {
    document.getElementById("settings-open").click();
    const form = await until(() => document.querySelector("#sheet form.settings"), 5000);
    if (!form) {
      return false;
    }
    const box = [...form.querySelectorAll("label.check")].find((label) => label.textContent.includes("Music on")).querySelector("input");
    box.checked = on;
    form.querySelector('input[aria-label="Overall volume"]').value = String(volume);
    form.requestSubmit();
    return Boolean(await until(() => !document.querySelector("#sheet form.settings"), 8000));
  };
  const before = audio();
  const on = await save(true, 0.5);
  const started = await until(() => window.e2eAudio.starts >= before.starts + 4, 8000);
  const loud = audio();
  const quiet = await save(true, 0);
  await sleep(3500);
  const stopped = audio();
  await sleep(6000);
  const later = audio();
  const rose = await save(true, 0.5);
  const restarted = await until(() => window.e2eAudio.starts >= later.starts + 4, 8000);
  const off = await save(false, 0.5);
  return {saved: [on, quiet, rose, off], started: Boolean(started), restarted: Boolean(restarted), before, loud, stopped, later, violations: window.e2eViolations};
})()"""


def probe(template: str) -> str:
    return template.replace("@HELPERS@", base.HELPERS)


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestPollCost(HubCase):
    drive = base.OrchestratorE2ECase.drive

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        now = time.time()
        self.write_council({"news.jsonl": self.jsonl([{"ts": now - 60 * n, "from": "One", "to": [], "text": f"row {n}"} for n in range(1, 6)])})
        self.page_url = f"http://localhost:{self.port}/"

    def test_chromium_keeps_stream_rows_across_polls_stops_the_sky_hidden_and_the_music_at_level_zero_at_three_widths(self):
        steps = []
        for width, height in base.WIDTHS:
            at = {"width": width, "height": height}
            shot = OUT / f"chromium-{width}"
            steps += [
                {**at, "url": f"{self.page_url}?{width}-clear#stream", "wait": 600, "probe": bm.CLEAR, "shot": None},
                {**at, "url": f"{self.page_url}?{width}#stream", "wait": 1500, "probe": probe(POLLS), "shot": f"{shot}-stream.png"},
                {**at, "url": None, "wait": 0, "probe": probe(MUSIC), "shot": None},
            ]
        data = self.drive(steps, None, init=INIT)
        (OUT / "chromium-poll-cost.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        results = iter(data["results"])
        for width, _ in base.WIDTHS:
            _, polls, music = next(results), next(results), next(results)
            with self.subTest(width=width):
                self.assertNotIn("error", polls, polls)
                self.assertEqual((polls["kept"]["connected"], polls["kept"]["replaced"]), (True, 0), polls)
                self.assertGreaterEqual(polls["kept"]["rows"], 5, polls)
                self.assertEqual(polls["hidden"], 0, polls)
                self.assertGreaterEqual(polls["shown"], 1, polls)
                self.assertEqual(polls["violations"], [])
                self.assertEqual(music["saved"], [True, True, True, True], music)
                self.assertTrue(music["started"], music)
                self.assertGreaterEqual(music["stopped"]["stops"] - music["loud"]["stops"], 4, music)
                self.assertEqual(music["later"]["starts"], music["stopped"]["starts"], music)
                self.assertTrue(music["restarted"], music)
                self.assertEqual(music["violations"], [])


if __name__ == "__main__":
    unittest.main()
