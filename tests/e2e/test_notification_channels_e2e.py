from __future__ import annotations

import datetime
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
SOURCES = [("resources", "Resource warnings"), ("mayday", "MAYDAY calls"), ("dream", "Dream reminder")]
ON = {"browser": True, "sounds": True, "aloud": True, "title": True}
SECTIONS = ["Ambience", "Location", "Appearance", "Music", "Undo window", "Claude dialogs", "Passkey"]
KIT = """
  const boxes = (group) => all("input[type=checkbox]", group).map((box) => [box.name, box.checked, words(box.closest("label"))]);
  const rows = (fold) => all(".notify-source", fold).map((row) => [row.dataset.source, row.dataset.state, words(row.querySelector("label")), text(row.querySelector(".notify-state")), all("button", row).map(text)]);
  const stored = async () => (await (await fetch("/api/state", {cache: "no-store"})).json()).settings;
  const fold = async () => {
    location.hash = "#stream/radio";
    const notify = await until(() => document.querySelector("#radio-spot details.radio-notify"), 8000);
    if (notify && !notify.open) {
      notify.querySelector("summary").click();
      await sleep(400);
    }
    const group = notify ? await until(() => notify.querySelector("fieldset.channels"), 8000) : null;
    return {notify, group};
  };
  const sheet = async () => {
    document.getElementById("settings-open").click();
    const form = await until(() => document.querySelector(".sheet-box form.settings"), 8000);
    const found = form ? {sections: all("section > h3", form).map(text), channels: all("fieldset.channels, .notify-source", form).length} : null;
    if (form) {
      all("button", form).find((button) => text(button) === "Cancel").click();
      await until(() => !document.querySelector(".sheet-box form.settings"), 8000);
    }
    return found;
  };
  const look = (notify, group) => {
    const layer = notify.querySelector(".station-body").getBoundingClientRect();
    return {
      legend: text(group.querySelector("legend")), boxes: boxes(group), sources: rows(notify), clashes: clashes(notify.querySelector(".station-body")),
      inDevice: Boolean(notify.closest(".radio-device > .radio-settings")), stations: Boolean(notify.closest(".radio-settings").querySelector("details.radio-station")),
      inside: layer.left >= -1 && layer.right <= innerWidth + 1, wide: document.documentElement.scrollWidth > innerWidth + 1,
    };
  };
  const save = async (on) => {
    for (const name of @NAMES@) {
      const {group} = await fold();
      const box = group.querySelector(`input[name="${name}"]`);
      if (box.checked !== on) {
        box.click();
      }
      const key = name.replace("channel-", "");
      const end = Date.now() + 8000;
      while (Date.now() < end && (await stored()).channels[key] !== on) {
        await sleep(200);
      }
    }
    const {group} = await fold();
    const titled = Boolean(await until(() => (on ? /@TITLED@/.test(document.title) : document.title === "@PLAIN@"), 8000));
    return {shown: boxes(group), titled, title: document.title, stored: (await stored()).channels};
  };
"""
OPENED = """(async () => {@HELPERS@@OVERLAP@@KIT@
  await screenShown(8000);
  await until(() => /@TITLED@/.test(document.title), 8000);
  const title = document.title;
  const general = await sheet();
  const {notify, group} = await fold();
  return group ? {title, general, ...look(notify, group)} : {error: "no channel group in the Device card", title};
})()"""
SWITCHED = """(async () => {@HELPERS@@OVERLAP@@KIT@
  return save(@ON@);
})()"""
SAVED_ON = """(async () => {@HELPERS@@OVERLAP@@KIT@
  const saved = await save(true);
  document.querySelector("#radio-spot details.radio-notify").open = false;
  await sleep(300);
  const again = await fold();
  return {...saved, reopened: again.group ? boxes(again.group) : null};
})()"""
SNOOZED = """(async () => {@HELPERS@@OVERLAP@@KIT@
  await screenShown(8000);
  const {notify} = await fold();
  const row = (id) => notify.querySelector(`.notify-source[data-source="${id}"]`);
  const button = (id, label) => all("button", row(id)).find((item) => text(item) === label);
  const wait = async (id, state) => Boolean(await until(() => row(id) && row(id).dataset.state === state, 8000));
  const before = rows(notify);
  const titles = all(".notify-source button", notify).map((item) => item.getAttribute("title"));
  button("resources", "1 h").click();
  const hour = await wait("resources", "snoozed");
  const snoozed = rows(notify);
  row("mayday").querySelector('input[type="checkbox"]').click();
  const off = await wait("mayday", "off");
  button("dream", "8:00").click();
  const morning = await wait("dream", "snoozed");
  const after = rows(notify);
  const dream = (await stored()).popups.dream;
  button("dream", "Resume").click();
  const resumed = await wait("dream", "on");
  return {before, titles, hour, snoozed, off, morning, after, dream, resumed, last: rows(notify), popups: (await stored()).popups, toasts: all("#toasts .toast").map(text)};
})()"""


def fill(probe: str) -> str:
    names = json.dumps([name for name, _ in LABELS])
    return probe.replace("@HELPERS@", base.HELPERS).replace("@OVERLAP@", base.OVERLAP).replace("@KIT@", KIT).replace("@NAMES@", names).replace("@TITLED@", TITLED).replace("@PLAIN@", PLAIN)


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
        older = {key: value for key, value in settings.SETTINGS.items() if key not in ("channels", "popups")}
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
        self.assertEqual(opened["general"], {"sections": SECTIONS, "channels": 0})
        self.assertEqual((opened["legend"], opened["boxes"]), ("Notification channels", [[name, name != "channel-browser", label] for name, label in LABELS]))
        self.assertEqual([row[:3] for row in opened["sources"]], [[source, "on", label] for source, label in SOURCES])
        self.assertEqual((opened["inDevice"], opened["stations"], opened["clashes"], opened["inside"], opened["wide"]), (True, True, {"found": [], "outside": []}, True, False), opened)
        self.assertEqual((off["shown"], off["titled"], off["title"], off["stored"]), ([[name, False, label] for name, label in LABELS], True, PLAIN, dict.fromkeys(ON, False)), off)
        self.assertEqual((reloaded["title"], reloaded["boxes"], reloaded["clashes"]), (PLAIN, [[name, False, label] for name, label in LABELS], {"found": [], "outside": []}), reloaded)
        self.assertEqual((back["titled"], back["stored"], back["reopened"]), (True, ON, [[name, True, label] for name, label in LABELS]), back)
        self.assertRegex(back["title"], TITLED)
        written = json.loads((self.state / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual((written["channels"], "notify" in written), (ON, False))

    def test_chromium_migrates_the_old_notify_flag_and_switches_every_channel_off_and_on_in_the_device_card_through_a_reload_at_three_widths(self):
        authenticator = self.authenticator()
        for width, height in base.WIDTHS:
            with self.subTest(width=width):
                self.legacy()
                data = self.drive(self.steps(width, height), authenticator)
                (OUT / f"chromium-{width}-channels.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
                self.check(data)

    def test_chromium_snoozes_mutes_and_resumes_each_gnome_popup_source_and_writes_notify_json(self):
        page = f"http://localhost:{self.port}/?popups"
        started = time.time()
        data = self.drive([{"width": 1366, "height": 900, "url": f"{page}#stream", "wait": 1200, "probe": fill(SNOOZED), "shot": str(OUT / "chromium-popups.png")}], self.authenticator())
        (OUT / "chromium-popups.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        found = data["results"][0]
        self.assertNotIn("error", found, found)
        self.assertEqual([row[:3] for row in found["before"]], [[source, "on", label] for source, label in SOURCES])
        self.assertEqual([row[4] for row in found["before"]], [["1 h", "8:00"]] * 3)
        self.assertTrue(all(title.split(": ")[0] in dict(SOURCES).values() for title in found["titles"]), found["titles"])
        self.assertEqual((found["hour"], found["off"], found["morning"], found["resumed"]), (True, True, True, True), found)
        resources = found["snoozed"][0]
        self.assertEqual((resources[1], resources[4]), ("snoozed", ["Resume", "1 h", "8:00"]))
        self.assertRegex(resources[3], r"^snoozed until \d\d:\d\d$")
        self.assertEqual(found["after"][1][1:], ["off", "MAYDAY calls", "off", []])
        self.assertEqual(found["last"][2][1], "on")
        popups = found["popups"]
        self.assertEqual((popups["mayday"], popups["dream"]), ({"on": False, "until": 0}, {"on": True, "until": 0}))
        self.assertTrue(popups["resources"]["on"])
        self.assertLessEqual(abs(popups["resources"]["until"] - (started + 3600)), 120, popups)
        written = json.loads((self.council / settings.NOTIFY).read_text(encoding="utf-8"))
        self.assertEqual(written, popups)
        morning = datetime.datetime.fromtimestamp(found["dream"]["until"])
        self.assertEqual((found["dream"]["on"], morning.hour, morning.minute, morning.second), (True, 8, 0, 0), found["dream"])
        self.assertLess(started, found["dream"]["until"])
        self.assertLessEqual(found["dream"]["until"] - started, 33 * 3600)


if __name__ == "__main__":
    unittest.main()
