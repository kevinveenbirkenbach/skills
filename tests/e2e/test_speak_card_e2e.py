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
from kvb_orchestrator import skill_scripts

OUT = Path(os.environ.get("E2E_OUT", "/tmp/speak-card-shots"))
HINTS = ("Post arrives at the end of the turn.", "Your passkey signs every message.")
CARD = """
  const card = () => document.querySelector("#radio-spot .radio-speak");
  const form = () => card().querySelector("form.composer");
  const toggle = () => form().querySelector(".mayday-toggle");
  const answer = async (yes) => {
    toggle().click();
    const box = await until(() => form().querySelector(".mayday-confirm"), 4000);
    if (!box) {
      return null;
    }
    const question = text(box.querySelector("p"));
    all("button", box).find((node) => text(node) === (yes ? yes : "Cancel")).click();
    return question;
  };
  const posted = [];
  const send = window.fetch.bind(window);
  window.fetch = (path, init) => {
    if (/^\\/api\\/(board|messages)/.test(String(path))) {
      posted.push(String(path));
    }
    return send(path, init);
  };
"""
RAISE = """(async () => {@HELPERS@@CARD@
  if (!(await screenShown(8000)) || !(await until(card, 8000))) {
    return {error: text(document.getElementById("main"))};
  }
  await sleep(400);
  const foot = toggle().parentElement;
  const radius = (node) => getComputedStyle(node).borderTopLeftRadius;
  const layout = {
    hints: @HINTS@.filter((line) => text(card()).includes(line)),
    channels: all("select option", form()).slice(0, 6).map((option) => [option.value, Boolean(option.title)]),
    mayday: all("select option", form()).some((option) => option.value === "mayday"),
    next: Boolean(toggle().previousElementSibling && toggle().previousElementSibling.matches(".ptt-split")),
    face: [text(toggle()), toggle().getAttribute("aria-pressed")],
    cards: all(".card", card()).length,
    radius: [radius(card()), radius(form().querySelector(".composer-grid")), radius(form().querySelector("textarea").closest(".mic-frame"))],
    fits: foot.scrollWidth <= foot.clientWidth + 1 && foot.getBoundingClientRect().right <= card().getBoundingClientRect().right + 1,
    wide: document.documentElement.scrollWidth > innerWidth + 1,
  };
  const field = form().querySelector("textarea");
  field.value = "disk full @WIDTH@";
  field.dispatchEvent(new Event("input", {bubbles: true}));
  const shown = new Set(all("#toasts .toast"));
  const declined = await answer(false);
  await sleep(600);
  const quiet = posted.slice();
  const asked = await answer("Send mayday");
  const toast = await until(() => all("#toasts .toast").filter((node) => !shown.has(node)).map(text).find((line) => line.includes(" to all")), 15000);
  return {layout, declined, quiet, asked, toast, left: field.value, violations: window.e2eViolations || null};
})()"""
CANCEL = """(async () => {@HELPERS@@CARD@
  if (!(await screenShown(8000)) || !(await until(() => card() && toggle().getAttribute("aria-pressed") === "true", 8000))) {
    return {error: text(document.getElementById("main"))};
  }
  const face = [text(toggle()), toggle().getAttribute("aria-pressed"), toggle().title];
  const shown = new Set(all("#toasts .toast"));
  const asked = await answer("Cancel mayday");
  const toast = await until(() => all("#toasts .toast").filter((node) => !shown.has(node)).map(text).find((line) => line.startsWith("Cancel mayday")), 15000);
  return {face, asked, toast, posted};
})()"""
IDLE = """(async () => {@HELPERS@@CARD@
  await screenShown(8000);
  await until(card, 8000);
  return {face: [text(toggle()), toggle().getAttribute("aria-pressed")]};
})()"""


def probe(template: str, **names: str) -> str:
    fills = {"@HELPERS@": base.HELPERS, "@CARD@": CARD, "@HINTS@": json.dumps(HINTS)}
    fills.update({f"@{key.upper()}@": value for key, value in names.items()})
    for key, value in fills.items():
        template = template.replace(key, value)
    return template


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestSpeakCard(base.OrchestratorE2ECase):
    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        (self.council / "radio-silence.json").unlink()
        self.local = f"http://localhost:{self.port}/"

    def steps(self, template: str, name: str) -> list[dict]:
        return [{"width": width, "height": height, "url": f"{self.local}?{width}-{name}#stream/radio", "wait": 1200, "probe": probe(template, width=str(width)), "shot": self.shot(f"{width}-speak-{name}")} for width, height in base.WIDTHS]

    def test_chromium_raises_and_cancels_a_mayday_from_the_toggle_beside_ptt(self):
        raised = self.drive(self.steps(RAISE, "raise"), self.authenticator(), init=w4.GUARD)
        (OUT / "chromium-raise.json").write_text(json.dumps(raised, indent=1), encoding="utf-8")
        self.assertEqual(raised["errors"], [])
        ask = "Send a mayday to all? All agents pause writing steps until you cancel it."
        for result, (width, _) in zip(raised["results"], base.WIDTHS, strict=True):
            with self.subTest(step="raise", width=width):
                self.assertNotIn("error", result, result)
                layout = result["layout"]
                self.assertEqual((layout["hints"], layout["mayday"], layout["next"], layout["face"], layout["cards"]), ([], False, True, ["MAYDAY", "false"], 0), layout)
                self.assertEqual([value for value, _ in layout["channels"]], ["post", "call", "newsletter", "broadcast", "pan-pan", "security"], layout)
                self.assertTrue(all(titled for _, titled in layout["channels"]), layout)
                self.assertEqual(layout["radius"], ["14px", "10px", "10px"], layout)
                self.assertEqual((layout["fits"], layout["wide"]), (True, False), layout)
                self.assertEqual((result["declined"], result["quiet"], result["asked"]), (ask, [], ask), result)
                self.assertTrue((result["toast"] or "").startswith("Mayday to all: sent$ radio.py send mayday"), result)
                self.assertEqual((result["left"], w4.quiet(result["violations"])), ("", []), result)
        sent = [args for script, args in self.scripts.calls if script == skill_scripts.RADIO]
        self.assertEqual([args[:2] for args in sent], [["send", "mayday"]] * len(base.WIDTHS))
        for args, (width, _) in zip(sent, base.WIDTHS, strict=True):
            self.assertTrue(args[-1].endswith(f"disk full {width}"), args)
        self.scripts.calls.clear()
        (self.council / "radio-silence.json").write_text(json.dumps({"since": time.time() - 30, "until": time.time() + 3600, "by": "Operator", "text": "disk full"}), encoding="utf-8")
        cancelled = self.drive(self.steps(CANCEL, "cancel"), {**self.authenticator(), "signCount": len(base.WIDTHS)}, init=w4.GUARD)
        (OUT / "chromium-cancel.json").write_text(json.dumps(cancelled, indent=1), encoding="utf-8")
        self.assertEqual(cancelled["errors"], [])
        for result, (width, _) in zip(cancelled["results"], base.WIDTHS, strict=True):
            with self.subTest(step="cancel", width=width):
                self.assertNotIn("error", result, result)
                self.assertEqual(result["face"][:2], ["Cancel mayday", "true"], result)
                self.assertEqual((result["asked"], result["posted"]), ("Lift the radio silence of the active mayday?", ["/api/board/sign", "/api/board/clear-mayday"]), result)
                self.assertTrue((result["toast"] or "").startswith("Cancel mayday: done"), result)
        self.assertEqual(self.scripts.calls, [(skill_scripts.RADIO, ["clear", "--force", "--session", "Operator"])] * len(base.WIDTHS))
        (self.council / "radio-silence.json").unlink()
        idle = self.drive(self.steps(IDLE, "idle"), None, init=w4.GUARD)
        self.assertEqual([result["face"] for result in idle["results"]], [["MAYDAY", "false"]] * len(base.WIDTHS))


if __name__ == "__main__":
    unittest.main()
