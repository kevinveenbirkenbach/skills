from __future__ import annotations

import json
import os
import re
import shutil
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

import hub_e2e_kit as base
import hub_support
from hub_case import HubCase

OUT = Path(os.environ.get("E2E_OUT", "/tmp/hub-031-shots"))
TEMPLATES = hub_support.HUB / "templates"
SCAN = """
  const shown = (node) => Boolean(node && node.getClientRects().length);
  const scan = () => all("button.mic").filter(shown).map((button) => {
    const field = document.getElementById(button.getAttribute("aria-controls"));
    const frame = button.closest(".mic-frame");
    if (!field || !frame || field.parentElement !== frame) {
      return {id: button.getAttribute("aria-controls"), framed: false};
    }
    const line = frame.classList.contains("mic-line");
    const [outer, mic, text] = [frame.getBoundingClientRect(), button.getBoundingClientRect(), field.getBoundingClientRect()];
    const foot = line ? null : frame.querySelector(":scope > .mic-foot");
    const tail = line ? [...frame.children].slice([...frame.children].indexOf(button) + 1) : [];
    const end = line ? frame.lastElementChild.getBoundingClientRect() : null;
    const spans = (box) => Math.abs(box.top - outer.top - 1) <= 1 && Math.abs(outer.bottom - 1 - box.bottom) <= 1;
    return {
      id: field.id, label: field.getAttribute("aria-label") || "", framed: true, line,
      last: line ? field.nextElementSibling === button && tail.every((node) => node.matches("button[type=submit]")) : Boolean(foot) && button.parentElement === foot && [field.nextElementSibling, field.nextElementSibling && field.nextElementSibling.matches(".mic-chips") ? field.nextElementSibling.nextElementSibling : null].includes(foot) && [...foot.children].slice([...foot.children].indexOf(button) + 1).every((node) => node.matches(".ptt-split, .mayday-toggle")),
      fits: line ? spans(mic) && Math.abs(outer.right - 1 - end.right) <= 1 : mic.bottom <= outer.bottom && mic.top >= text.bottom - 1,
      divider: line ? getComputedStyle(button).borderLeftWidth : getComputedStyle(foot).borderTopWidth,
      clear: line ? text.right <= mic.left + 0.5 : true,
      send: tail.map((node) => ({fits: spans(node.getBoundingClientRect()), divider: getComputedStyle(node).borderLeftWidth, own: getComputedStyle(node).borderTopWidth})),
    };
  });
  const ring = (field) => {
    field.focus();
    const frame = field.closest(".mic-frame");
    return [getComputedStyle(frame).outlineStyle, getComputedStyle(field).outlineStyle];
  };
  const wide = () => document.documentElement.scrollWidth > innerWidth + 1;
"""
STREAM = """(async () => {@HELPERS@@SCAN@
  const field = await until(() => document.querySelector('#main input[type="search"]'), 15000);
  await until(() => field.closest(".mic-frame"), 4000);
  const other = await until(() => document.querySelector("#main .option.other .mic-frame"), 8000);
  const extra = document.body.appendChild(document.createElement("textarea"));
  await sleep(100);
  extra.remove();
  await sleep(100);
  const sends = other.closest("form").querySelectorAll("button[type=submit]").length;
  return {mics: scan(), sends, ring: ring(field), wide: wide()};
})()"""
RULES = """(async () => {@HELPERS@@SCAN@
  (await until(() => document.getElementById("controls-tab-rules"), 15000)).click();
  (await until(() => document.querySelector("#main [data-new-rule]"), 4000)).click();
  await until(() => document.querySelector("#sheet .rule-form .mic-frame"), 4000);
  return {mics: scan(), wide: wide()};
})()"""
RADIO = """(async () => {@HELPERS@@SCAN@
  const area = await until(() => document.querySelector("#radio-spot form.composer textarea"), 15000);
  await until(() => area.closest(".mic-frame"), 4000);
  const foot = area.closest(".mic-frame").querySelector(".mic-foot");
  const first = foot.firstElementChild;
  const mic = foot.querySelector(":scope > button.mic");
  const idle = getComputedStyle(mic).backgroundColor;
  mic.setAttribute("aria-pressed", "true");
  const recording = getComputedStyle(mic).backgroundColor;
  mic.setAttribute("aria-pressed", "false");
  area.style.height = "260px";
  await sleep(100);
  const after = scan().find((entry) => entry.id === area.id);
  return {mics: scan(), record: first.textContent.trim() || first.getAttribute("aria-label"), looks: idle !== recording, resized: after, ring: ring(area), wide: wide()};
})()"""


def probe(template: str) -> str:
    return template.replace("@HELPERS@", base.HELPERS).replace("@SCAN@", SCAN)


class TestMicSource(unittest.TestCase):
    def test_no_page_module_but_the_mic_helper_inserts_a_mic_button(self):
        callers = [path.name for path in TEMPLATES.glob("*.js") if path.name != "page-mic.js" and re.search(r"micButton\(", path.read_text(encoding="utf-8"))]
        self.assertEqual(callers, [])


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestMicFrames(HubCase):
    drive = base.OrchestratorE2ECase.drive

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        self.claim("s1", "Skills")
        decided = self.tool("decision_request", {"question": "Merge the mic frames?", "options": hub_support.OPTIONS, "agent": "Skills", "recommended": ""})
        self.assertFalse(decided["isError"], decided)
        self.snapshot()
        self.page_url = f"http://localhost:{self.port}/"

    def check_mics(self, mics: list[dict]) -> None:
        self.assertTrue(mics)
        for entry in mics:
            with self.subTest(field=entry["id"]):
                self.assertTrue(entry["framed"], entry)
                self.assertEqual((entry["last"], entry["fits"], entry["divider"], entry["clear"]), (True, True, "1px", True), entry)

    def test_chromium_joins_every_mic_into_its_field_frame_at_three_widths(self):
        steps = []
        for width, height in base.WIDTHS:
            shot = OUT / f"chromium-{width}"
            steps += [
                {"width": width, "height": height, "url": f"{self.page_url}?{width}#stream", "wait": 1200, "probe": probe(STREAM), "shot": f"{shot}-stream.png"},
                {"width": width, "height": height, "url": f"{self.page_url}?{width}-rules#stream/rules", "wait": 1200, "probe": probe(RULES), "shot": f"{shot}-rules.png"},
                {"width": width, "height": height, "url": f"{self.page_url}?{width}-radio#stream/radio", "wait": 1200, "probe": probe(RADIO), "shot": f"{shot}-radio.png"},
            ]
        data = self.drive(steps, None)
        (OUT / "chromium-mic-frames.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        results = iter(data["results"])
        for width, _ in base.WIDTHS:
            stream, rules, radio = next(results), next(results), next(results)
            with self.subTest(width=width):
                for found in (stream, rules, radio):
                    self.assertNotIn("error", found, found)
                    self.check_mics(found["mics"])
                    self.assertFalse(found["wide"])
                other = [entry for entry in stream["mics"] if entry["label"].startswith("Other answer to ")]
                self.assertEqual([entry["send"] for entry in other], [[{"fits": True, "divider": "1px", "own": "0px"}]], other)
                self.assertEqual(stream["sends"], 1)
                self.assertEqual(stream["ring"], ["solid", "none"])
                self.assertEqual(radio["ring"], ["solid", "none"])
                self.assertEqual(radio["record"], "Record")
                self.assertTrue(radio["looks"])
                self.assertEqual((radio["resized"]["last"], radio["resized"]["fits"]), (True, True), radio["resized"])


if __name__ == "__main__":
    unittest.main()
