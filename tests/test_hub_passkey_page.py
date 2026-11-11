from __future__ import annotations

import json
import subprocess
import unittest

from hub_support import HUB

PASSKEY = HUB / "templates" / "page-passkey.js"
PROBE = """
const source = require("fs").readFileSync(process.argv[1], "utf8");
const toasts = [];
const gates = [];
let asked = 0;
let served = 0;
const window = {location: {hostname: "localhost", port: "8737", pathname: "/", hash: ""}};
const navigator = {credentials: {get: () => {
  asked += 1;
  return new Promise((resolve, reject) => gates.push({resolve, reject}));
}}};
const sendJson = async () => {
  served += 1;
  return {ok: true, data: {payload: {nonce: served}, challenge: "AAAA", credentials: ["AAAA"]}};
};
const toast = (title) => toasts.push(title);
const bytes = new Uint8Array([1]).buffer;
const credential = {rawId: bytes, response: {clientDataJSON: bytes, authenticatorData: bytes, signature: bytes}};
const P = new Function("window", "navigator", "sendJson", "toast", "fail", "h", `${source}\\nreturn {signedProof};`)(window, navigator, sendJson, toast, () => [], () => null);
const tick = () => new Promise((resolve) => setImmediate(resolve));
const nonce = (signed) => (signed ? signed.proof.payload.nonce : null);
(async () => {
  const first = P.signedProof("/api/board/sign", {action: "resume"}, "Resume");
  const second = P.signedProof("/api/board/sign", {action: "resume"}, "Resume");
  await tick();
  const open = {asked, served, toasts: [...toasts]};
  gates.splice(0).forEach((gate) => gate.resolve(credential));
  const both = [nonce(await first), nonce(await second)];
  const canceled = P.signedProof("/api/board/sign", {action: "drain"}, "Drain");
  await tick();
  gates.splice(0).forEach((gate) => gate.reject(new Error("canceled")));
  const dropped = nonce(await canceled);
  const after = P.signedProof("/api/board/sign", {action: "suspend"}, "Suspend");
  await tick();
  gates.splice(0).forEach((gate) => gate.resolve(credential));
  console.log(JSON.stringify({open, both, canceled: dropped, after: nonce(await after), asked, toasts}));
})();
"""


class TestPasskeyPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        done = subprocess.run(["node", "-e", PROBE, str(PASSKEY)], capture_output=True, text=True, timeout=60, check=True)
        cls.data = json.loads(done.stdout)

    def test_a_second_signature_while_one_is_open_asks_no_passkey_and_sends_nothing(self):
        self.assertEqual(self.data["open"], {"asked": 1, "served": 1, "toasts": ["Resume: not signed"]})
        self.assertEqual(self.data["both"], [1, None])

    def test_a_canceled_signature_frees_the_next_one(self):
        self.assertIsNone(self.data["canceled"])
        self.assertEqual((self.data["after"], self.data["asked"]), (3, 3))
        self.assertEqual(self.data["toasts"], ["Resume: not signed", "Drain: not signed"])


if __name__ == "__main__":
    unittest.main()
