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
import test_field_attachments_e2e as attached
from kvb_orchestrator import skill_scripts

OUT = Path(os.environ.get("E2E_OUT", "/tmp/hub-095-shots"))
SIZES = ((1366, 768), (390, 844))
TOUCH = 640
CELLS = ["switch", "spacer", "attach", "mic", "send"]
SEND = ["Send", "Send: your passkey signs the message, verifiable with operator_message"]
HINTS = [["post", "Post", "Post arrives at the end of the turn."], ["call", "Call", "Call arrives at once, with a read receipt."]]
HEADS = {"post": ["post", "--to"], "call": ["send", "call", "--to"]}
KIT = """
  const shown = (node) => Boolean(node) && node.getClientRects().length > 0;
  const box = () => document.querySelector("#popup form.popup-form");
  const addressee = (form) => form.querySelector("textarea").getAttribute("aria-label").replace(/^Message to /, "");
  const cell = (node) => (node.matches(".to-one") ? "switch" : node.matches(".spacer") ? "spacer" : node.matches(".mic-attach") ? "attach" : node.matches("button.mic") ? "mic" : node.matches(".agent-send") ? "send" : node.className || node.tagName);
  const openAgentBox = async () => {
    location.hash = "#stream";
    await streamShowsAll();
    const links = await until(() => {
      const found = all("#main button.agent-link").filter(shown);
      return found.length ? found : null;
    }, 10000);
    if (!links) {
      return null;
    }
    (links.find((node) => text(node) === "Stage") || links[0]).click();
    return until(() => document.getElementById("popup").open && box(), 4000);
  };
"""
LAYOUT = """(async () => {@HELPERS@@FIELD@@KIT@
  await screenShown(8000);
  const form = await openAgentBox();
  if (!form) {
    return {error: text(document.getElementById("main")).slice(0, 300)};
  }
  await sleep(300);
  const frame = form.querySelector(":scope > .mic-frame");
  const foot = frame ? frame.querySelector(":scope > .mic-foot") : null;
  if (!foot) {
    return {error: "no framed footer", form: form.outerHTML.slice(0, 300)};
  }
  const rect = (node) => node.getBoundingClientRect();
  const send = foot.querySelector(":scope > .agent-send");
  const controls = [...all(".to-one > label", foot), foot.querySelector(":scope > .mic-attach"), foot.querySelector(":scope > button.mic"), send];
  if (controls.some((node) => !node)) {
    return {error: "footer control missing", foot: foot.outerHTML.slice(0, 400)};
  }
  const [outer, strip, boxes] = [rect(frame), rect(foot), controls.map(rect)];
  const within = (b, edge) => b.left >= edge.left - 0.5 && b.right <= edge.right + 0.5 && b.top >= edge.top - 0.5 && b.bottom <= edge.bottom + 0.5;
  return {
    to: addressee(form),
    files: all("input[type=file]", form).map((input) => [input.className, input.hidden, shown(input)]),
    paragraphs: all("p", form).length,
    children: [...form.children].map((node) => node.className),
    cells: [...foot.children].filter(shown).map(cell),
    inside: boxes.every((b) => within(b, outer)),
    footed: boxes.every((b) => within(b, strip)),
    row: Math.max(...boxes.map((b) => b.top)) < Math.min(...boxes.map((b) => b.bottom)),
    sizes: boxes.map((b) => [Math.round(b.width), Math.round(b.height)]),
    send: [name(send), send.title],
    classes: all(".to-one > label", foot).map((label) => [label.querySelector("input").value, text(label), label.title]),
    wide: wide(),
  };
})()"""
DELIVER = """(async () => {@HELPERS@@FIELD@@KIT@
  const form = box();
  if (!form) {
    return {error: "agent box closed"};
  }
  const field = form.querySelector("textarea");
  const send = form.querySelector(".agent-send");
  const runs = [];
  for (const cls of ["post", "call"]) {
    form.querySelector(`.to-one input[value="${cls}"]`).closest("label").click();
    field.value = `agent box @WIDTH@ ${cls}`;
    field.focus();
    field.setSelectionRange(field.value.length, field.value.length);
    field.dispatchEvent(new Event("input", {bubbles: true}));
    let path = null;
    if (cls === "post") {
      field.dispatchEvent(new ClipboardEvent("paste", {clipboardData: carry([await pngFile("image.png")]), bubbles: true, cancelable: true}));
      path = await until(() => lineOf(field, /^📎 \\/.*\\/paste-\\d{8}-\\d{6}\\.png$/), 8000);
    }
    const chips = form.querySelectorAll(".mic-chip").length;
    const checked = form.querySelector(".to-one input:checked").value;
    const before = new Set(all("#toasts .toast"));
    send.click();
    const toast = await until(() => all("#toasts .toast").filter((node) => !before.has(node)).map(text).find((entry) => entry.includes(" to ")), 20000);
    await until(() => !send.disabled, 20000);
    runs.push({cls, checked, path, chips, toast, left: field.value});
  }
  document.getElementById("toasts").replaceChildren();
  return {to: addressee(form), runs};
})()"""


def probe(template: str, width: int) -> str:
    return template.replace("@HELPERS@", base.HELPERS).replace("@FIELD@", attached.FIELD).replace("@KIT@", KIT).replace("@WIDTH@", str(width))


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestAgentMessageBox(base.OrchestratorE2ECase):
    stored = attached.TestFieldAttachments.stored

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)

    def check_layout(self, width: int, layout: dict) -> None:
        self.assertNotIn("error", layout, layout)
        self.assertEqual(layout["files"], [["mic-attach-file", True, False]], layout)
        self.assertEqual((layout["paragraphs"], layout["children"]), (0, ["mic-frame mic-area"]), layout)
        self.assertEqual(layout["cells"], CELLS, layout)
        self.assertEqual((layout["inside"], layout["footed"], layout["row"]), (True, True, True), layout)
        self.assertEqual((layout["send"], layout["classes"]), (SEND, HINTS), layout)
        self.assertFalse(layout["wide"], layout)
        if width < TOUCH:
            self.assertTrue(all(side >= 44 for size in layout["sizes"] for side in size), layout["sizes"])

    def check_delivery(self, delivered: dict) -> None:
        self.assertNotIn("error", delivered, delivered)
        post, call = delivered["runs"]
        self.assertEqual([(run["cls"], run["checked"], run["left"]) for run in delivered["runs"]], [("post", "post", ""), ("call", "call", "")], delivered)
        self.assertEqual(self.stored(post["path"]).read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual((post["chips"], call["path"], call["chips"]), (1, None, 0), delivered)
        for run, label in ((post, "Post"), (call, "Call")):
            self.assertTrue((run["toast"] or "").startswith(f"{label} to {delivered['to']}: sent"), run)

    def test_chromium_sends_post_with_a_pasted_screenshot_and_call_from_one_framed_field_at_two_widths(self):
        local = f"http://localhost:{self.port}/"
        steps = []
        for width, height in SIZES:
            shot = OUT / f"chromium-{width}"
            steps += [
                {"width": width, "height": height, "url": f"{local}?{width}-agent#stream", "wait": 1200, "probe": probe(LAYOUT, width), "shot": f"{shot}-agent-box.png"},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(DELIVER, width), "shot": f"{shot}-agent-box-sent.png"},
            ]
        data = self.drive(steps, self.authenticator())
        (OUT / "chromium-agent-box.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        results = iter(data["results"])
        sends = []
        for width, _ in SIZES:
            layout, delivered = next(results), next(results)
            with self.subTest(width=width, part="layout"):
                self.check_layout(width, layout)
            with self.subTest(width=width, part="delivery"):
                self.check_delivery(delivered)
            sends += [(width, delivered["to"], run["cls"], run["path"]) for run in delivered["runs"]]
        radio = [args for script, args in self.scripts.calls if script == skill_scripts.RADIO]
        self.assertEqual([args[:-1] for args in radio], [[*HEADS[cls], to, "--session", "Operator"] for _, to, cls, _ in sends])
        for args, (width, _, cls, path) in zip(radio, sends, strict=True):
            with self.subTest(width=width, cls=cls):
                self.assertIn(f"agent box {width} {cls}", args[-1])
                if path:
                    self.assertIn(path, args[-1])


if __name__ == "__main__":
    unittest.main()
