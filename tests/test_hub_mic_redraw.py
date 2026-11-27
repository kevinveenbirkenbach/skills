from __future__ import annotations

import json
import subprocess
import unittest

from hub_support import HUB

MIC = HUB / "templates" / "page-mic.js"
PROBE = r"""
const fs = require("fs");
const vm = require("vm");
const code = fs.readFileSync(process.argv[1], "utf8");
const settle = async () => {
  for (let round = 0; round < 20; round += 1) {
    await new Promise((resolve) => setImmediate(resolve));
  }
};
function node(label) {
  const attributes = label ? {"aria-label": label} : {};
  const handlers = {};
  return {
    tagName: "INPUT", isConnected: true, value: "", selectionStart: 0, selectionEnd: 0, dataset: {}, children: [], disabled: false,
    setAttribute: (name, value) => { attributes[name] = value; }, getAttribute: (name) => attributes[name] ?? null,
    replaceChildren(...kids) { this.children = kids; },
    addEventListener: (kind, run) => { (handlers[kind] = handlers[kind] || []).push(run); },
    click: () => (handlers.click || []).forEach((run) => run()),
    focus: () => null, setSelectionRange: () => null, dispatchEvent: () => true,
  };
}
class Recorder {
  constructor() { this.state = "inactive"; this.handlers = {}; this.mimeType = "audio/webm"; }
  addEventListener(kind, run) { (this.handlers[kind] = this.handlers[kind] || []).push(run); }
  start() { this.state = "recording"; }
  stop() {
    this.state = "inactive";
    (this.handlers.dataavailable || []).forEach((run) => run({data: {size: 3}}));
    (this.handlers.stop || []).forEach((run) => run());
  }
}
function rig() {
  const live = node("");
  const sandbox = {
    Voice: {FIELDS: "input", spliced: (value, start, end, text) => ({value: value.slice(0, start) + text + value.slice(end), caret: start + text.length})},
    mic: {recorder: null, button: null, field: null, busy: false, cancel: false, timer: 0, started: 0},
    state: {speech: {input: 30}}, h: () => node(""), icon: (name) => name, micGap: () => "", toast: () => null, context: () => ({}),
    wavOf: async () => "wav", send: async () => ({ok: true, data: {text: "hallo"}}),
    document: {getElementById: () => live, body: {append: () => null}},
    navigator: {mediaDevices: {getUserMedia: async () => ({getTracks: () => []})}},
    MediaRecorder: Recorder, Blob: class { constructor() { this.size = 3; } }, Event: class {},
    window: {setInterval: () => 1, clearInterval: () => null, addEventListener: () => null},
    Date,
  };
  vm.runInNewContext(code, sandbox);
  return sandbox;
}
async function redrawn(label) {
  const sandbox = rig();
  const old = node(label);
  const oldButton = sandbox.micButton(old);
  oldButton.click();
  await settle();
  old.isConnected = false;
  oldButton.isConnected = false;
  const fresh = node(label);
  const freshButton = sandbox.micButton(fresh);
  const during = freshButton.dataset.rec;
  freshButton.click();
  await settle();
  return {during, after: freshButton.dataset.rec, fresh: fresh.value, old: old.value, idle: sandbox.mic.button === null};
}
(async () => {
  console.log(JSON.stringify({labelled: await redrawn("Other answer to x"), unlabelled: await redrawn("")}));
})().catch((error) => {
  console.error(error && error.stack || error);
  process.exit(1);
});
"""


class TestMicSurvivesRedraw(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        done = subprocess.run(["node", "-e", PROBE, str(MIC)], capture_output=True, text=True, timeout=60, check=False)
        if done.returncode != 0:
            raise AssertionError(done.stderr[-4000:])
        cls.data = json.loads(done.stdout)

    def test_a_rebuilt_twin_takes_over_the_recording_and_gets_the_text(self):
        self.assertEqual(self.data["labelled"], {"during": "recording", "after": "idle", "fresh": "hallo", "old": "", "idle": True})

    def test_a_rebuilt_field_without_a_label_still_stops_on_its_new_mic(self):
        self.assertEqual(self.data["unlabelled"], {"during": "idle", "after": "idle", "fresh": "hallo", "old": "", "idle": True})


if __name__ == "__main__":
    unittest.main()
