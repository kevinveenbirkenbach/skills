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
from hub_case import HubCase
from hub_support import ASK

OUT = Path(os.environ.get("E2E_OUT", "/tmp/hub-reason-chips-shots"))
SAID = ("make the gate green first", "rebase on main", "", "rebase on main", "split the bundle")
SHOWN = ["split the bundle", "rebase on main", "make the gate green first"]
COMMON = """
  const row = (ref) => document.querySelector(`#main .inbox-list > li[data-ref="${ref}"]`);
  const sheet = () => document.querySelector("#sheet:not([hidden]) .sheet-box");
  const chips = () => all(".reason-chips .chip", sheet());
  const wide = () => document.documentElement.scrollWidth > innerWidth + 1;
  const key = (value) => document.body.dispatchEvent(new KeyboardEvent("keydown", {key: value, bubbles: true}));
  const pick = async (index, field) => {
    const shown = chips().map(text);
    chips()[index].click();
    const filled = field.value;
    const focused = document.activeElement === field;
    field.value += " now";
    const result = {shown, filled, focused, edited: field.value, inside: chips().every((chip) => chip.getBoundingClientRect().right <= sheet().getBoundingClientRect().right + 1), wide: wide()};
    key("Escape");
    await until(() => !sheet(), 4000);
    return result;
  };
"""
INBOX = """(async () => {@HELPERS@@COMMON@
  if (!(await until(() => row("@ASK@"), 8000))) {
    return {error: text(document.getElementById("main"))};
  }
  row("@ASK@").querySelector('.deny-split button[aria-haspopup="dialog"]').click();
  if (!(await until(() => sheet() && chips().length, 4000))) {
    return {error: text(document.getElementById("sheet"))};
  }
  const single = await pick(1, sheet().querySelector(".deny-reason textarea"));
  const menu = () => document.querySelector("#grant-bar details.grant-menu");
  const checkbox = row("@ASK@").querySelector('input[type="checkbox"]');
  if (checkbox && !checkbox.checked) {
    checkbox.click();
  }
  if (!(await until(() => menu(), 3000))) {
    return {single, error: "no selection menu"};
  }
  menu().querySelector("summary").click();
  await until(() => menu().open, 2000);
  const deny = all("#grant-bar .menu-item.danger").find((button) => text(button).startsWith("Deny"));
  deny.click();
  if (!(await until(() => sheet() && chips().length, 4000))) {
    return {single, error: text(document.getElementById("sheet"))};
  }
  const bulk = await pick(0, sheet().querySelector(".deny-reason textarea"));
  return {single, bulk};
})()"""
MATCH = """(async () => {@HELPERS@@COMMON@
  const card = () => document.querySelector("#main .match-card.front");
  if (!(await until(card, 8000))) {
    return {error: text(document.getElementById("main"))};
  }
  key("ArrowLeft");
  if (!(await until(() => sheet() && sheet().querySelector(".match-feedback") && chips().length, 4000))) {
    return {error: text(document.getElementById("sheet"))};
  }
  return {reject: await pick(2, sheet().querySelector(".match-feedback"))};
})()"""


def probe(template: str, ask: str) -> str:
    return template.replace("@HELPERS@", base.HELPERS).replace("@COMMON@", COMMON).replace("@ASK@", ask)


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestReasonChips(HubCase):
    drive = base.OrchestratorE2ECase.drive
    authenticator = base.OrchestratorE2ECase.authenticator

    def setUp(self):
        super().setUp()
        self.claim("s1", "Skills session")
        self.ask = self.create_ask({**ASK, "timeout": 3600})
        now = time.time()
        for age, reason in enumerate(SAID):
            denial = {"channel": "post", "kind": "ask", "reason": reason, "subject": {}, "to": "Skills"}
            fields = {"to": "Skills", "address": "Skills session", "text": "Denied by the operator.", "upload": None, "voice": None, "voice_sha256": "", "class": "post"}
            self.httpd.hub.messages.add({**fields, "denial": denial, "proof": None, "created_ts": now - 60 + age})

    def steps(self) -> list[dict]:
        OUT.mkdir(parents=True, exist_ok=True)
        local = f"http://localhost:{self.port}/"
        ref = f"ask:{self.ask}"
        steps = []
        for width, height in base.WIDTHS:
            steps.append({"width": width, "height": height, "url": f"{local}?{width}#stream/inbox", "wait": 1200, "probe": probe(INBOX, ref), "shot": str(OUT / f"chromium-{width}-inbox.png")})
            steps.append({"width": width, "height": height, "url": f"{local}?{width}-match#tasks/match", "wait": 1200, "probe": probe(MATCH, ref), "shot": str(OUT / f"chromium-{width}-match.png")})
        return steps

    def test_chromium_offers_the_last_reasons_in_every_deny_sheet_at_three_widths(self):
        data = self.drive(self.steps(), self.authenticator(), "cdp.mjs", os.environ.get("CHROMIUM", "chromium"))
        (OUT / "chromium-reason-chips.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "(style-src-elem)" not in error and "/favicon.ico" not in error], [])
        results = iter(data["results"])
        for width, _ in base.WIDTHS:
            inbox, match = next(results), next(results)
            with self.subTest(width=width):
                self.assertNotIn("error", inbox, inbox)
                self.assertNotIn("error", match, match)
                for found, index in ((inbox["single"], 1), (inbox["bulk"], 0), (match["reject"], 2)):
                    self.assertEqual(found["shown"], SHOWN, found)
                    self.assertEqual((found["filled"], found["focused"], found["edited"]), (SHOWN[index], True, f"{SHOWN[index]} now"), found)
                    self.assertEqual((found["inside"], found["wide"]), (True, False), found)


if __name__ == "__main__":
    unittest.main()
