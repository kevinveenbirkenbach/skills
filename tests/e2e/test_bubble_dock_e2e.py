from __future__ import annotations

import json
import os
import shutil
import sys
import time
import unittest
from collections.abc import Callable
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

import hub_e2e_kit as base
from hub_case import HubCase
from hub_support import iso

OUT = Path(os.environ.get("E2E_OUT", "/tmp/hub-bubble-dock-shots"))
WIDTH, HEIGHT = 1366, 768
CUE = "e2e-dock"
SPEAKERS = ("Stage", "Docs")
SAID = " ".join(["the build host is almost full so rotate the logs and retry the gate before the next push"] * 4)
SILENT = """() => {
  try {
    localStorage.setItem("kvb-orchestrator.radio", JSON.stringify({mode: "silence", classes: ["mayday", "security"], muted: []}));
  } catch (error) {
    return;
  }
}"""
PROBE = """(async () => {@HELPERS@
  const layer = document.getElementById("bubbles");
  const toggle = document.getElementById("bubbles-toggle");
  const live = () => all(".speech-bubble:not(.leaving):not([data-vanishing])", layer);
  const of = (who) => live().find((node) => node.dataset.who === who) || null;
  const where = (node) => (node.parentElement.classList.contains("bubble-bar") ? "bar" : "layer");
  const seen = (node) => Boolean(node) && node.getClientRects().length > 0;
  const parts = (node) => {
    const face = node.querySelector(".bubble-head .avatar[data-face]");
    const who = node.querySelector(".bubble-who");
    const skip = node.querySelector("button.bubble-skip");
    return {
      where: where(node), face: seen(face) ? face.dataset.face : null, skip: seen(skip), faceLeft: seen(face) && seen(who) ? face.getBoundingClientRect().right <= who.getBoundingClientRect().left + 1 : null,
      label: skip ? skip.getAttribute("aria-label") : null, title: skip ? skip.getAttribute("title") : null, type: skip ? skip.getAttribute("type") : null, tab: skip ? skip.tabIndex : null,
    };
  };
  const pin = (key) => {
    const node = document.createElement("span");
    node.dataset.e2ePin = key;
    node.dataset.face = key;
    Object.assign(node.style, {position: "fixed", left: `${Math.round(innerWidth / 2)}px`, top: `${Math.round(innerHeight / 2)}px`, width: "26px", height: "26px", borderRadius: "50%", background: "#9aa4b1"});
    document.body.prepend(node);
  };
  const poll = () => window.dispatchEvent(new Event("focus"));
  if (toggle.getAttribute("aria-pressed") !== "true") {
    toggle.click();
  }
  if (!(await until(() => toggle.getAttribute("aria-pressed") === "true" && !layer.hidden, 8000))) {
    return {error: "bubbles stay off"};
  }
  await sleep(1500);
  poll();
  await sleep(1500);
  await fetch("/api/tts", {method: "POST", headers: {"X-Kvb-Orchestrator": "1", "Content-Type": "application/json"}, body: JSON.stringify({text: "@CUE@", voice: ""}), cache: "no-store"});
  poll();
  if (!(await until(() => live().length >= 2, 20000))) {
    return {error: "no bubbles", shown: live().map((node) => [node.dataset.who, node.dataset.state])};
  }
  const docked = live().find((node) => where(node) === "bar");
  if (!docked) {
    return {error: "no docked bubble", shown: live().map((node) => [node.dataset.who, where(node)])};
  }
  const [dockedWho, anchoredWho] = [docked.dataset.who, live().find((node) => node !== docked).dataset.who];
  pin(anchoredWho);
  await until(() => of(anchoredWho) && where(of(anchoredWho)) === "layer", 4000);
  await sleep(800);
  const anchored = parts(of(anchoredWho));
  const dock = parts(of(dockedWho));
  const states = live().map((node) => [node.dataset.who, node.dataset.state]);
  const skip = of(dockedWho).querySelector("button.bubble-skip");
  const box = skip.getBoundingClientRect();
  const hit = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
  const takesPointer = Boolean(hit && hit.closest("button.bubble-skip") === skip);
  skip.focus();
  const focused = document.activeElement === skip;
  (hit && hit.closest("button.bubble-skip") ? hit : skip).dispatchEvent(new MouseEvent("click", {bubbles: true, cancelable: true, view: window}));
  const gone = Boolean(await until(() => !layer.querySelector(`.speech-bubble[data-who="${CSS.escape(dockedWho)}"]`), 3000));
  const kept = Boolean(of(anchoredWho));
  poll();
  await sleep(2500);
  poll();
  await sleep(1500);
  const back = Boolean(of(dockedWho));
  all("[data-e2e-pin]").forEach((node) => node.remove());
  return {dockedWho, anchoredWho, anchored, dock, states, takesPointer, focused, gone, back, kept};
})()"""


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestDockedBubble(HubCase):
    drive = base.OrchestratorE2ECase.drive

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        now = time.time()
        self.claim("s1", "Skills session")
        self.write_council({
            "work/s2/claim.json": {"office": "work/s2", "session": "s2", "runtime": "claude", "name": "Stage", "since": iso(now - 7200), "beat": now - 60, "work": "x"},
            "work/s3/claim.json": {"office": "work/s3", "session": "s3", "runtime": "claude", "name": "Docs", "since": iso(now - 7200), "beat": now - 60, "work": "x"},
        })
        hub = self.httpd.hub
        hub.settings.put({**hub.settings.get(), "bubbles": True}, hub.settings.get())

        def synthesize(body: bytes, admit: Callable[[str], None]) -> bytes:
            if json.loads(body)["text"] == CUE:
                stamp = time.time()
                rows = [{"ts": stamp - index / 1000, "from": name, "to": [], "text": f"{name}: {SAID}", "class": "broadcast", "v": 2} for index, name in enumerate(SPEAKERS)]
                with (self.council / "news.jsonl").open("a", encoding="utf-8") as handle:
                    handle.write(self.jsonl(rows))
            return base.tone(1, 8000)

        patch = mock.patch.object(hub.speech, "synthesize", synthesize)
        patch.start()
        self.addCleanup(patch.stop)
        self.base = f"http://{self.host}/"

    def steps(self) -> list[dict]:
        probe = PROBE.replace("@HELPERS@", base.HELPERS).replace("@CUE@", CUE)
        return [{"width": WIDTH, "height": HEIGHT, "url": f"{self.base}?dock#stream", "wait": 1200, "probe": probe, "shot": str(OUT / f"chromium-{WIDTH}-bubble-dock.png")}]

    def check(self, found: dict) -> None:
        self.assertNotIn("error", found, found)
        self.assertNotEqual(found["dockedWho"], found["anchoredWho"], found)
        self.assertEqual({state for _, state in found["states"]}, {"quiet"}, found)
        dock, anchored = found["dock"], found["anchored"]
        self.assertEqual((dock["where"], dock["face"], dock["skip"], dock["faceLeft"]), ("bar", found["dockedWho"], True, True), found)
        self.assertEqual((dock["type"], dock["tab"]), ("button", 0), found)
        self.assertTrue(dock["label"] and dock["title"], found)
        self.assertEqual((anchored["where"], anchored["face"], anchored["skip"]), ("layer", None, False), found)
        self.assertEqual((found["takesPointer"], found["focused"]), (True, True), found)
        self.assertEqual((found["gone"], found["back"], found["kept"]), (True, False, True), found)

    def test_chromium_docks_a_bubble_with_face_and_close_and_the_close_skips_the_silent_bubble(self):
        data = self.drive(self.steps(), None, init=SILENT)
        (OUT / "chromium-bubble-dock.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        self.assertEqual(len(data["results"]), 1, data)
        self.check(data["results"][0])


if __name__ == "__main__":
    unittest.main()
