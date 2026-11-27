from __future__ import annotations

import json
import re
import subprocess
import unittest

from hub_support import HUB

DOM = HUB / "templates" / "page-dom.js"
PROBE = r"""
const vm = require("vm");
const sandbox = {};
vm.runInNewContext(process.argv[1], sandbox);
console.log(JSON.stringify(vm.runInNewContext(`({
  absolute: vscodeHref("/home/op/repo"),
  folder: vscodeHref("/home/op/repo/"),
  encoded: vscodeHref("/home/op/my repo/a#b/100%.md"),
  unicode: vscodeHref("/home/op/Übung?x=1"),
  relative: vscodeHref("repo/src/app.py"),
  dotted: vscodeHref("./src/app.py"),
  empty: vscodeHref(""),
  missing: vscodeHref(undefined),
  under: vscodeHref(pathUnder("/repo/.worktrees/feature/match/", "src/my app.py")),
  rootless: vscodeHref(pathUnder("", "src/app.py")),
  relativeRoot: vscodeHref(pathUnder("repo", "src/app.py")),
  fileless: pathUnder("/repo", ""),
})`, sandbox)));
"""


def extracted() -> str:
    source = DOM.read_text(encoding="utf-8")
    function = re.search(r"^  function vscodeHref\(.*?^  }$", source, re.MULTILINE | re.DOTALL)
    under = re.search(r"^  const pathUnder = .*;$", source, re.MULTILINE)
    if function is None or under is None:
        raise AssertionError(f"vscodeHref or pathUnder not found in {DOM}")
    return function.group(0) + "\n" + under.group(0).replace("const ", "var ", 1)


class TestPathLinks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        done = subprocess.run(["node", "-e", PROBE, extracted()], capture_output=True, text=True, timeout=60, check=False)
        if done.returncode != 0:
            raise AssertionError(done.stderr[-4000:])
        cls.data = json.loads(done.stdout)

    def test_an_absolute_path_becomes_a_vscode_file_link(self):
        self.assertEqual(self.data["absolute"], "vscode://file/home/op/repo")
        self.assertEqual(self.data["folder"], "vscode://file/home/op/repo/")

    def test_every_segment_is_uri_encoded_and_the_slashes_are_kept(self):
        self.assertEqual(self.data["encoded"], "vscode://file/home/op/my%20repo/a%23b/100%25.md")
        self.assertEqual(self.data["unicode"], "vscode://file/home/op/%C3%9Cbung%3Fx%3D1")

    def test_a_relative_or_empty_path_gets_no_link(self):
        self.assertEqual([self.data[key] for key in ("relative", "dotted", "empty", "missing")], ["", "", "", ""])

    def test_a_diff_file_links_below_its_worktree_only_when_the_worktree_is_absolute(self):
        self.assertEqual(self.data["under"], "vscode://file/repo/.worktrees/feature/match/src/my%20app.py")
        self.assertEqual((self.data["rootless"], self.data["relativeRoot"], self.data["fileless"]), ("", "", ""))


if __name__ == "__main__":
    unittest.main()
