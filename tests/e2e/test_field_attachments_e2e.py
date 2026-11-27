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
import test_match_rejects_e2e as rejects
import test_match_review_e2e as matched
from hub_case import HubCase
from hub_support import HOST_STATE

OUT = Path(os.environ.get("E2E_OUT", "/tmp/hub-082-shots"))
MARK = "📎 "
INIT = """() => {
  window.e2eUploads = 0;
  const real = window.fetch.bind(window);
  window.fetch = (input, options) => {
    if (String(input && input.url ? input.url : input).startsWith("/api/uploads")) {
      window.e2eUploads += 1;
    }
    return real(input, options);
  };
}"""
FIELD = """
  const LIMIT = 50 * 1024 * 1024;
  const wide = () => document.documentElement.scrollWidth > innerWidth + 1;
  const pngFile = async (name) => {
    const canvas = document.createElement("canvas");
    Object.assign(canvas, {width: 24, height: 16});
    const paint = canvas.getContext("2d");
    paint.fillStyle = "#c33";
    paint.fillRect(0, 0, 24, 16);
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
    return new File([blob], name, {type: "image/png"});
  };
  const carry = (files, words) => {
    const transfer = new DataTransfer();
    files.forEach((file) => transfer.items.add(file));
    if (words) {
      transfer.setData("text/plain", words);
    }
    return transfer;
  };
  const lineOf = (field, pattern) => field.value.split("\\n").find((line) => pattern.test(line)) || null;
  const choose = (picker, file) => {
    picker.files = carry([file]).files;
    picker.dispatchEvent(new Event("change", {bubbles: true}));
  };
  const exercise = async (field) => {
    const frame = await until(() => field.closest(".mic-frame"), 4000);
    if (!frame) {
      return {error: "field not framed"};
    }
    field.focus();
    const before = window.e2eUploads;
    const plainValue = field.value;
    const plain = new ClipboardEvent("paste", {clipboardData: carry([], "plain words"), bubbles: true, cancelable: true});
    field.dispatchEvent(plain);
    await sleep(300);
    const textPaste = {prevented: plain.defaultPrevented, uploads: window.e2eUploads - before, same: field.value === plainValue};
    field.dispatchEvent(new ClipboardEvent("paste", {clipboardData: carry([await pngFile("image.png")]), bubbles: true, cancelable: true}));
    const placeholder = lineOf(field, /^📎 uploading paste-\\d{8}-\\d{6}\\.png…$/);
    const pasted = await until(() => lineOf(field, /^📎 \\/.*\\/paste-\\d{8}-\\d{6}\\.png$/), 8000);
    const drop = new DragEvent("drop", {dataTransfer: carry([new File(["dropped notes\\n"], "notes.txt", {type: "text/plain"})]), bubbles: true, cancelable: true});
    field.dispatchEvent(drop);
    const dropped = await until(() => lineOf(field, /^📎 \\/.*\\/notes\\.txt$/), 8000);
    const picker = frame.querySelector(".mic-attach-file");
    const button = frame.querySelector(".mic-foot > .mic-attach");
    choose(picker, new File(["# picked\\n"], "picked.md", {type: "text/markdown"}));
    const picked = await until(() => lineOf(field, /^📎 \\/.*\\/picked\\.md$/), 8000);
    await until(() => frame.querySelectorAll(".mic-chip").length === 3, 4000);
    const thumb = frame.querySelector(".mic-chip img.mic-chip-thumb");
    await until(() => thumb && thumb.complete && thumb.naturalWidth > 0, 4000);
    const chips = all(".mic-chip", frame).map((chip) => ({path: chip.dataset.path, thumb: Boolean(chip.querySelector("img.mic-chip-thumb")), icon: Boolean(chip.querySelector(":scope > svg.bi"))}));
    const row = frame.querySelector(":scope > .mic-chips");
    const layout = {aboveFoot: Boolean(row) && row.nextElementSibling === frame.querySelector(":scope > .mic-foot"), beforeMic: Boolean(button) && button.nextElementSibling && button.nextElementSibling.matches("button.mic"), icon: Boolean(button && button.querySelector('use[href="#bi-paperclip"]'))};
    const overBefore = window.e2eUploads;
    choose(picker, new File([new Uint8Array(LIMIT + 1)], "big.bin"));
    const over = await until(() => lineOf(field, /^⚠️ big\\.bin: /), 4000);
    const overUploads = window.e2eUploads - overBefore;
    const overPath = lineOf(field, /^📎 \\/.*big\\.bin$/);
    const gone = all(".mic-chip", frame).find((chip) => chip.dataset.path.endsWith("/notes.txt"));
    gone.querySelector(".mic-chip-drop").click();
    await sleep(150);
    const lines = field.value.split("\\n");
    return {
      textPaste, placeholder, pasted, dropped, picked, chips, layout, thumbLoaded: Boolean(thumb && thumb.naturalWidth > 0),
      over, overUploads, overPath,
      removed: {line: lines.includes(dropped), chips: frame.querySelectorAll(".mic-chip").length, kept: [pasted, picked].every((line) => lines.includes(line))},
      wide: wide(),
    };
  };
"""
REJECT = """(async () => {@HELPERS@@CARD@@STEPS@@FIELD@
  await screenShown(8000);
  if (!(await until(card, 8000))) {
    return {error: text(document.getElementById("main")).slice(0, 300)};
  }
  await sleep(300);
  await actionable();
  key("ArrowLeft");
  const field = await until(() => document.querySelector(".match-feedback"), 4000);
  if (!field) {
    return {error: "no reject feedback field"};
  }
  return exercise(field);
})()"""
COMPOSER = """(async () => {@HELPERS@@FIELD@
  const field = await until(() => document.querySelector("#radio-spot form.composer textarea"), 15000);
  if (!field) {
    return {error: "no composer"};
  }
  return exercise(field);
})()"""


def probe(template: str) -> str:
    return template.replace("@HELPERS@", base.HELPERS).replace("@CARD@", matched.CARD).replace("@STEPS@", rejects.STEPS).replace("@FIELD@", FIELD)


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestFieldAttachments(HubCase):
    drive = base.OrchestratorE2ECase.drive
    cards = matched.TestMatchReview.cards
    review = matched.TestMatchReview.review
    payload = matched.TestMatchReview.payload

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        self.cards()
        self.base = f"http://localhost:{self.port}/"

    def stored(self, line: str) -> Path:
        self.assertTrue(line and line.startswith(MARK), line)
        return self.state / Path(line[len(MARK):]).relative_to(HOST_STATE)

    def check(self, found: dict) -> None:
        self.assertNotIn("error", found, found)
        self.assertEqual(found["textPaste"], {"prevented": False, "uploads": 0, "same": True}, found)
        self.assertIsNotNone(found["placeholder"], found)
        for key in ("pasted", "dropped", "picked"):
            with self.subTest(line=key):
                self.assertTrue(self.stored(found[key]).is_file(), found[key])
        self.assertEqual(self.stored(found["pasted"]).read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(self.stored(found["dropped"]).read_text(encoding="utf-8"), "dropped notes\n")
        self.assertEqual([(chip["thumb"], chip["icon"]) for chip in found["chips"]], [(True, False), (False, True), (False, True)], found["chips"])
        self.assertTrue(found["thumbLoaded"], found)
        self.assertEqual(found["layout"], {"aboveFoot": True, "beforeMic": True, "icon": True}, found)
        self.assertEqual((found["over"], found["overUploads"], found["overPath"]), ("⚠️ big.bin: too large, at most 50 MiB", 0, None), found)
        self.assertEqual(found["removed"], {"line": False, "chips": 2, "kept": True}, found)
        self.assertFalse(found["wide"], found)

    def test_chromium_attaches_by_paste_drop_and_picker_in_the_reject_feedback_and_the_composer_at_three_widths(self):
        steps = []
        for width, height in base.WIDTHS:
            shot = OUT / f"chromium-{width}"
            steps += [
                {"width": width, "height": height, "url": f"{self.base}?{width}-reject#tasks/match", "wait": 1500, "probe": probe(REJECT), "shot": f"{shot}-reject.png"},
                {"width": width, "height": height, "url": f"{self.base}?{width}-radio#stream/radio", "wait": 1200, "probe": probe(COMPOSER), "shot": f"{shot}-composer.png"},
            ]
        data = self.drive(steps, None, init=INIT)
        (OUT / "chromium-field-attachments.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        results = iter(data["results"])
        for width, _ in base.WIDTHS:
            for view in ("reject", "composer"):
                with self.subTest(width=width, view=view):
                    self.check(next(results))


if __name__ == "__main__":
    unittest.main()
