from __future__ import annotations

import json
import subprocess
import unittest

from hub_support import AMBIENCE
from kvb_orchestrator.settings import stream_origin

DLF = "https://st01.sslstream.dlf.de/dlf/01/high/aac/stream.aac?aggregator=web"
OTHER = "https://radio.example/morgen"
URLS = [DLF, "https://Radio.Example:443/zweiter?x=1", "http://10.0.0.5:8000/nacht", "https://other.example:8443/", "http://radio.example:80/x"]
PROBE = """
const A = require(process.argv[1]);
const [DLF, OTHER] = JSON.parse(process.argv[2]);
const toasts = (events) => {
  let told = null;
  const shown = [];
  for (const [url, kind, cause] of events) {
    const fresh = A.retold(told, url, kind, cause);
    if (fresh) {
      told = fresh;
      shown.push(`${kind}:${cause}`);
    }
  }
  return shown;
};
const attempt = [[DLF, "error", "csp"], [DLF, "error", "media"], [DLF, "error", "refused"]];
console.log(JSON.stringify({
  attempt: toasts(attempt),
  reversed: toasts([...attempt].reverse()),
  clicks: toasts([1, 2, 3, 4].flatMap(() => attempt)),
  autoplay: toasts([[DLF, "blocked", "refused"], [DLF, "blocked", "refused"], ...attempt]),
  stations: toasts([...attempt, [OTHER, "error", "media"], [OTHER, "error", "csp"]]),
  origins: JSON.parse(process.argv[3]).map((url) => A.stationOrigins({url, via: []})[0]),
  redirected: A.stationOrigins({url: DLF, via: ["https://*.rndfnk.com"]}),
}));
"""


class TestRadioTrouble(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        command = ["node", "-e", PROBE, str(AMBIENCE), json.dumps([DLF, OTHER]), json.dumps(URLS)]
        done = subprocess.run(command, capture_output=True, text=True, timeout=60, check=True)
        cls.data = json.loads(done.stdout)

    def test_a_blocked_redirect_and_its_media_error_toast_once(self):
        self.assertEqual(self.data["attempt"], ["error:csp"])

    def test_a_later_cause_replaces_a_lesser_one_but_never_the_other_way(self):
        self.assertEqual(self.data["reversed"], ["error:refused", "error:media", "error:csp"])

    def test_retries_through_clicks_stack_no_toast(self):
        self.assertEqual(self.data["clicks"], ["error:csp"])

    def test_each_failure_and_station_toasts_on_its_own(self):
        self.assertEqual(self.data["autoplay"], ["blocked:refused", "error:csp"])
        self.assertEqual(self.data["stations"], ["error:csp", "error:media", "error:csp"])

    def test_the_page_computes_the_origins_the_server_puts_into_media_src(self):
        self.assertEqual(self.data["origins"], [stream_origin(url) for url in URLS])
        self.assertEqual(self.data["redirected"], ["https://st01.sslstream.dlf.de", "https://*.rndfnk.com"])


if __name__ == "__main__":
    unittest.main()
