from __future__ import annotations

import json
import subprocess
import unittest

from hub_support import HUB

COMPOSER = HUB / "templates" / "page-composer.js"
PROBE = r"""
const fs = require("fs");
const vm = require("vm");
const code = fs.readFileSync(process.argv[1], "utf8");
const settle = async () => {
  for (let round = 0; round < 20; round += 1) {
    await new Promise((resolve) => setImmediate(resolve));
  }
};
function rig() {
  const timers = [];
  const log = [];
  const sandbox = {
    TO_ONE: [], TO_ALL: [], state: {speech: {seconds: 30}}, Event: class {},
    window: {setTimeout: (run) => timers.push(run) && timers.length, clearTimeout: (id) => {
      timers[id - 1] = null;
    }},
  };
  vm.runInNewContext(code, sandbox);
  sandbox.startRecording = (parts) => log.push(`start ${parts.ptt || "click"}`);
  sandbox.stopRecording = (parts) => log.push(`stop ${parts.ptt || "click"}`);
  const handlers = {};
  const record = {disabled: false, addEventListener: (kind, run) => {
    (handlers[kind] = handlers[kind] || []).push(run);
  }};
  const parts = {record, recorder: null, ptt: "", hold: 0, swallow: false};
  sandbox.holdToTalk(parts);
  const fire = (kind, event) => (handlers[kind] || []).forEach((run) => run(event || {button: 0}));
  const tick = () => timers.splice(0).forEach((run) => run && run());
  return {sandbox, parts, fire, tick, log};
}
async function kept(ptt, heard) {
  const {sandbox, parts} = rig();
  const looks = [];
  let submits = 0;
  Object.assign(sandbox, {
    context: () => ({}), wavOf: async () => "wav", attachVoice: () => null, toast: () => null, recLook: (button, look) => looks.push(look), h: () => ({}),
    send: async () => ({ok: true, data: {id: "n1"}}), heardNote: async () => heard,
  });
  Object.assign(parts, {ptt, status: {textContent: ""}, text: {value: "", dispatchEvent: () => true, focus: () => null, form: {requestSubmit: () => {
    submits += 1;
  }}}});
  await sandbox.keepRecording({size: 3}, parts);
  await settle();
  return {submits, ptt: parts.ptt, text: parts.text.value, looks};
}
(async () => {
  const quick = rig();
  quick.fire("pointerdown");
  quick.fire("pointerup");
  quick.tick();
  const tapped = {log: quick.log.splice(0), swallow: quick.parts.swallow};
  const held = rig();
  held.fire("pointerdown");
  held.tick();
  const holding = held.parts.ptt;
  held.fire("pointerleave");
  const released = {holding, log: held.log.splice(0), ptt: held.parts.ptt, swallow: held.parts.swallow};
  const right = rig();
  right.fire("pointerdown", {button: 2});
  right.tick();
  console.log(JSON.stringify({
    tapped, released, right: right.log,
    sent: await kept("released", {status: "done", text: "hello"}),
    clicked: await kept("", {status: "done", text: "hello"}),
    empty: await kept("released", {status: "done", text: ""}),
  }));
})().catch((error) => {
  console.error(error && error.stack || error);
  process.exit(1);
});
"""


class TestHoldToTalk(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        done = subprocess.run(["node", "-e", PROBE, str(COMPOSER)], capture_output=True, text=True, timeout=60, check=False)
        if done.returncode != 0:
            raise AssertionError(done.stderr[-4000:])
        cls.data = json.loads(done.stdout)

    def test_a_short_press_starts_nothing_and_leaves_the_click_to_toggle(self):
        self.assertEqual(self.data["tapped"], {"log": [], "swallow": False})

    def test_holding_records_and_releasing_stops_and_swallows_the_trailing_click(self):
        self.assertEqual(self.data["released"], {"holding": "holding", "log": ["start holding", "stop released"], "ptt": "released", "swallow": True})

    def test_only_the_primary_button_holds(self):
        self.assertEqual(self.data["right"], [])

    def test_a_held_recording_sends_its_transcript_and_a_clicked_one_waits_for_the_check(self):
        self.assertEqual(self.data["sent"], {"submits": 1, "ptt": "", "text": "hello", "looks": ["busy", "idle"]})
        self.assertEqual(self.data["clicked"], {"submits": 0, "ptt": "", "text": "hello", "looks": ["busy", "idle"]})
        self.assertEqual(self.data["empty"]["submits"], 0)


if __name__ == "__main__":
    unittest.main()
