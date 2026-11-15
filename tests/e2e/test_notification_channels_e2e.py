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
from hub_case import HubCase
from hub_support import ASK
from kvb_orchestrator import settings

OUT = Path(os.environ.get("E2E_OUT", "/tmp/notification-channels-shots"))
TITLED = r"^\(\d+\) Agent Orchestrator$"
PLAIN = "Agent Orchestrator"
LABELS = [
    ("channel-browser", "Desktop notifications when the browser allows them"),
    ("channel-sounds", "Sound tones"),
    ("channel-aloud", "Read radio aloud"),
    ("channel-title", "Waiting count in the tab title"),
]
ON = {"browser": True, "sounds": True, "aloud": True, "title": True}
KIT = """
  const boxes = (group) => all("input[type=checkbox]", group).map((box) => [box.name, box.checked, words(box.closest("label"))]);
  const sheet = async () => {
    document.getElementById("settings-open").click();
    const form = await until(() => document.querySelector(".sheet-box form.settings"), 8000);
    const group = form ? form.querySelector("fieldset.channels") : null;
    if (group) {
      group.scrollIntoView({block: "center"});
      await sleep(300);
    }
    return {form, group};
  };
  const look = (form, group) => {
    const box = group.getBoundingClientRect();
    return {
      legend: text(group.querySelector("legend")), boxes: boxes(group), sections: all("section > h3", form).map(text), clashes: clashes(form),
      inside: box.left >= -1 && box.right <= innerWidth + 1, wide: document.documentElement.scrollWidth > innerWidth + 1,
    };
  };
  const save = async (group, on) => {
    for (const box of all("input[type=checkbox]", group)) {
      if (box.checked !== on) {
        box.click();
      }
    }
    const shown = boxes(group);
    group.closest("form").querySelector('button[type="submit"]').click();
    const closed = Boolean(await until(() => !document.querySelector(".sheet-box form.settings"), 8000));
    const titled = Boolean(await until(() => (on ? /@TITLED@/.test(document.title) : document.title === "@PLAIN@"), 8000));
    const stored = (await (await fetch("/api/state", {cache: "no-store"})).json()).settings.channels;
    return {shown, closed, titled, title: document.title, stored};
  };
"""
OPENED = """(async () => {@HELPERS@@OVERLAP@@KIT@
  await screenShown(8000);
  await until(() => /@TITLED@/.test(document.title), 8000);
  const title = document.title;
  const {form, group} = await sheet();
  return group ? {title, ...look(form, group)} : {error: text(document.querySelector(".sheet-box")), title};
})()"""
SWITCHED = """(async () => {@HELPERS@@OVERLAP@@KIT@
  const group = document.querySelector(".sheet-box fieldset.channels");
  return group ? save(group, @ON@) : {error: "no channel group"};
})()"""
SAVED_ON = """(async () => {@HELPERS@@OVERLAP@@KIT@
  const group = document.querySelector(".sheet-box fieldset.channels");
  if (!group) {
    return {error: "no channel group"};
  }
  const saved = await save(group, true);
  const again = await sheet();
  return {...saved, reopened: again.group ? boxes(again.group) : null};
})()"""


def fill(probe: str) -> str:
    return probe.replace("@HELPERS@", base.HELPERS).replace("@OVERLAP@", base.OVERLAP).replace("@KIT@", KIT).replace("@TITLED@", TITLED).replace("@PLAIN@", PLAIN)


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestNotificationChannels(HubCase):
    drive = base.OrchestratorE2ECase.drive
    authenticator = base.OrchestratorE2ECase.authenticator

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        self.claim("s1", "Skills session")
        self.create_ask({**ASK, "timeout": 3600})

    def legacy(self) -> None:
        file = self.state / "settings.json"
        older = {key: value for key, value in settings.SETTINGS.items() if key != "channels"}
        file.write_text(json.dumps({**older, "notify": False}), encoding="utf-8")
        held = self.httpd.hub.settings
        with held.lock:
            held.current = settings.Settings(file).get()

    def steps(self, width: int, height: int) -> list[dict]:
        page = f"http://{self.host}/?{width}"
        return [
            {"width": width, "height": height, "url": f"{page}#stream", "wait": 1200, "probe": fill(OPENED), "shot": str(OUT / f"chromium-{width}-channels-legacy.png")},
            {"width": width, "height": height, "url": None, "wait": 0, "probe": fill(SWITCHED).replace("@ON@", "false"), "shot": None},
            {"width": width, "height": height, "url": f"{page}-reloaded#stream", "wait": 1200, "probe": fill(OPENED.replace("await until(() => /@TITLED@/.test(document.title), 8000);", "await sleep(600);")), "shot": str(OUT / f"chromium-{width}-channels-off-reloaded.png")},
            {"width": width, "height": height, "url": None, "wait": 0, "probe": fill(SAVED_ON), "shot": str(OUT / f"chromium-{width}-channels-on.png")},
        ]

    def check(self, data: dict) -> None:
        opened, off, reloaded, back = data["results"]
        for found in (opened, off, reloaded, back):
            self.assertNotIn("error", found, found)
        self.assertEqual(data["errors"], [])
        self.assertRegex(opened["title"], TITLED)
        self.assertEqual((opened["legend"], opened["boxes"]), ("Notification channels", [[name, name != "channel-browser", label] for name, label in LABELS]))
        self.assertEqual(opened["sections"], ["Ambience", "Location", "Appearance", "Music", "Notifications", "Passkey"])
        self.assertEqual((opened["clashes"], opened["inside"], opened["wide"]), ({"found": [], "outside": []}, True, False), opened)
        self.assertEqual((off["shown"], off["closed"], off["titled"], off["title"], off["stored"]), ([[name, False, label] for name, label in LABELS], True, True, PLAIN, dict.fromkeys(ON, False)), off)
        self.assertEqual((reloaded["title"], reloaded["boxes"], reloaded["clashes"]), (PLAIN, [[name, False, label] for name, label in LABELS], {"found": [], "outside": []}), reloaded)
        self.assertEqual((back["closed"], back["titled"], back["stored"], back["reopened"]), (True, True, ON, [[name, True, label] for name, label in LABELS]), back)
        self.assertRegex(back["title"], TITLED)
        written = json.loads((self.state / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual((written["channels"], "notify" in written), (ON, False))

    def test_chromium_migrates_the_old_notify_flag_and_switches_every_channel_off_and_on_through_a_reload_at_three_widths(self):
        authenticator = self.authenticator()
        for width, height in base.WIDTHS:
            with self.subTest(width=width):
                self.legacy()
                data = self.drive(self.steps(width, height), authenticator)
                (OUT / f"chromium-{width}-channels.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
                self.check(data)


if __name__ == "__main__":
    unittest.main()
