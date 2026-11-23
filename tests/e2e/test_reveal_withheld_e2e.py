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
from hub_e2e_kit import WIDTHS
from hub_support import PAGE

OUT = Path(os.environ.get("E2E_OUT", "/tmp/reveal-shots"))
MASK = "••••"
APP_CLEAR = '@@ -1 +1 @@\n-old\n+api_key = "plain-example-words"'
CONF_CLEAR = '@@ -0,0 +1 @@\n+token = "plain-other-words"'
DIFF = [
    {"path": "app.py", "status": "M", "mode": "100644", "additions": 1, "deletions": 1, "patch": f"@@ -1 +1 @@\n-old\n+{MASK}", "note": "masked"},
    {"path": "conf.py", "status": "A", "mode": "100644", "additions": 1, "deletions": 0, "patch": "", "note": "content withheld"},
    {"path": "open.txt", "status": "A", "mode": "100644", "additions": 1, "deletions": 0, "patch": "@@ -0,0 +1 @@\n+seen", "note": ""},
]
SEALED = {"app.py": APP_CLEAR, "conf.py": CONF_CLEAR}
WORDS = ("plain-example", "plain-other")
COMMON = """
  const words = @WORDS@;
  const row = (ref) => document.querySelector(`#main .inbox-list > li[data-ref="${ref}"]`);
  const files = (ref) => all(".diff-file", row(ref));
  const look = (ref) => ({
    hidden: files(ref).map((file) => file.dataset.hidden || null),
    buttons: all("button.reveal", row(ref)).map(name),
    masked: text(row(ref)).includes("@MASK@"),
    clear: words.filter((word) => text(row(ref)).includes(word)),
  });
  const wide = () => document.documentElement.scrollWidth > innerWidth + 1;
"""
SHOW = """(async () => {@HELPERS@@COMMON@
  if (!(await until(() => row("@ONE@") && row("@ALL@") && files("@ONE@").length === 3 && files("@ALL@").length === 3, 8000))) {
    return {error: text(document.getElementById("main"))};
  }
  return {one: look("@ONE@"), all: look("@ALL@"), leaked: words.filter((word) => document.body.textContent.includes(word)), wide: wide()};
})()"""
REVEAL = """(async () => {@HELPERS@@COMMON@
  navigator.credentials.get = @SIGNS@ ? navigator.credentials.get.bind(navigator.credentials) : () => Promise.reject(new DOMException("The operator canceled.", "NotAllowedError"));
  const posted = [];
  const send = window.fetch.bind(window);
  window.fetch = (path, init) => {
    if (String(path).includes("/reveal")) {
      posted.push([String(path).replace(/^.*[/]api[/]diffs[/]/, ""), JSON.parse(init.body).paths]);
    }
    return send(path, init);
  };
  if (!(await until(() => row("@REF@") && files("@REF@").length === 3, 8000))) {
    return {error: text(document.getElementById("main"))};
  }
  all("button.reveal", row("@REF@")).find((button) => name(button) === "@BUTTON@").click();
  if (@SIGNS@) {
    await until(() => files("@REF@").filter((file) => file.dataset.hidden === "revealed").length === @COUNT@, 15000);
  } else {
    await sleep(1500);
  }
  const view = await (await send("/api/view", {cache: "no-store"})).text();
  let stored = "";
  try {
    stored = JSON.stringify({...localStorage});
  } catch {
    stored = "";
  }
  return {after: look("@REF@"), posted, kept: words.filter((word) => view.includes(word) || stored.includes(word)), wide: wide()};
})()"""


def probe(template: str, **values: str) -> str:
    found = template.replace("@HELPERS@", base.HELPERS).replace("@COMMON@", COMMON).replace("@WORDS@", json.dumps(WORDS)).replace("@MASK@", MASK)
    for name, value in values.items():
        found = found.replace(f"@{name}@", value)
    return found


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestRevealWithheld(base.OrchestratorE2ECase):
    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        page = self.page("sealed.html", PAGE)
        self.sets = {width: {"ONE": self.review(f"feat: one {width}", page), "ALL": self.review(f"feat: all {width}", page)} for width, _ in WIDTHS}

    def review(self, title: str, page: str) -> str:
        branch = "feature/" + title.removeprefix("feat: ").replace(" ", "-")
        result = self.tool("review_request", {**self.arguments(title, "", page), **self.branched(branch), "agent": "Skills", "diff": DIFF, "sealed": SEALED})
        self.assertFalse(result["isError"], result)
        return f"review:{result['structuredContent']['id']}"

    def steps(self, browser: str, signs: bool) -> list[dict]:
        local = f"http://localhost:{self.port}/"
        flag = "true" if signs else "false"
        steps = []
        for width, height in WIDTHS:
            ids = self.sets[width]
            shot = str(OUT / f"{browser}-{width}")
            steps += [
                {"width": width, "height": height, "url": f"{local}?{width}#stream/inbox", "wait": 1200, "probe": probe(SHOW, **ids), "shot": f"{shot}-masked.png"},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(REVEAL, REF=ids["ONE"], BUTTON="Reveal", COUNT="1", SIGNS=flag), "shot": f"{shot}-revealed-file.png"},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(REVEAL, REF=ids["ALL"], BUTTON="Reveal all 2", COUNT="2", SIGNS=flag), "shot": f"{shot}-revealed-all.png"},
            ]
        return steps

    def check(self, data: dict, browser: str, signs: bool) -> None:
        self.assertEqual([error for error in data["errors"] if "(style-src-elem)" not in error and "/favicon.ico" not in error], [])
        hidden = {"hidden": ["masked", "content withheld", None], "buttons": ["Reveal all 2", "Reveal", "Reveal"], "masked": True, "clear": []}
        results = iter(data["results"])
        for width, _ in WIDTHS:
            ids = self.sets[width]
            show, one, every = (next(results) for _ in range(3))
            with self.subTest(browser=browser, width=width):
                self.assertNotIn("error", show, show)
                self.assertEqual(show["one"], hidden, show)
                self.assertEqual(show["all"], hidden, show)
                self.assertEqual(show["leaked"], [], show)
                one_id, all_id = (ids[name].split(":", 1)[1] for name in ("ONE", "ALL"))
                self.assertEqual(one["posted"], [[f"review/{one_id}/reveal/sign", ["app.py"]], *([[f"review/{one_id}/reveal", ["app.py"]]] if signs else [])], one)
                self.assertEqual(every["posted"], [[f"review/{all_id}/reveal/sign", ["app.py", "conf.py"]], *([[f"review/{all_id}/reveal", ["app.py", "conf.py"]]] if signs else [])], every)
                if signs:
                    self.assertEqual(one["after"], {"hidden": ["revealed", "content withheld", None], "buttons": ["Reveal"], "masked": False, "clear": ["plain-example"]}, one)
                    self.assertEqual(every["after"], {"hidden": ["revealed", "revealed", None], "buttons": [], "masked": False, "clear": list(WORDS)}, every)
                else:
                    self.assertEqual((one["after"], every["after"]), (hidden, hidden))
                self.assertEqual((one["kept"], every["kept"]), ([], []))
                self.assertFalse(any(found["wide"] for found in (show, one, every)), width)

    def test_chromium_masked_files_reveal_per_file_and_per_item_with_the_passkey_at_three_widths(self):
        data = self.drive(self.steps("chromium", True), self.authenticator())
        (OUT / "chromium-reveal.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.check(data, "chromium", True)
        rows = [row for row in self.events("kinds=approval")["events"] if row["title"].startswith("Reveal ")]
        self.assertEqual(len(rows), 2 * len(WIDTHS))
        self.assertFalse(any(word in json.dumps(rows) for word in WORDS))

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_masked_files_stay_masked_without_a_signature_at_three_widths(self):
        data = self.drive(self.steps("firefox", False), None, "bidi.mjs", os.environ.get("FIREFOX", "firefox"))
        (OUT / "firefox-reveal.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.check(data, "firefox", False)


if __name__ == "__main__":
    unittest.main()
