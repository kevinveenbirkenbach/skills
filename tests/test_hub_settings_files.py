from __future__ import annotations

import json
import subprocess
import unittest

import hub_support

MODULE = hub_support.HUB / "templates" / "settings-files.js"
LISTED = r"""
const S = require(process.argv[1]);
const files = JSON.parse(process.argv[2]);
const paths = (result) => ({shown: result.shown.map((file) => file.path), missing: result.missing});
console.log(JSON.stringify({folded: paths(S.listed(files, false)), open: paths(S.listed(files, true))}));
"""


def files() -> list[dict]:
    present = [{"path": f"/p/{index:02d}/.claude/settings.json", "folder": True, "error": ""} for index in range(10)]
    present[7]["error"] = "unreadable: ValueError"
    present[3]["error"] = "a link or no directory on the path: Not a directory"
    absent = [{"path": f"/a/{index:02d}/.claude/settings.json", "folder": False, "error": "no directory: create it first"} for index in range(30)]
    older = {"path": "/o/.claude/settings.json", "error": ""}
    return [*absent[15:], present[5], *present[:5], *absent[:15], older, *present[6:]]


class TestSettingsFiles(unittest.TestCase):
    def test_files_without_their_folder_fold_away_and_error_rows_lead_then_paths_in_order(self):
        done = subprocess.run(["node", "-e", LISTED, str(MODULE), json.dumps(files())], capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        found = json.loads(done.stdout)
        errors = ["/p/03/.claude/settings.json", "/p/07/.claude/settings.json"]
        rest = [f"/p/{index:02d}/.claude/settings.json" for index in range(10) if index not in (3, 7)]
        self.assertEqual(found["folded"], {"shown": [*errors, "/o/.claude/settings.json", *rest], "missing": 30})
        self.assertEqual(found["open"]["shown"], [*errors, "/o/.claude/settings.json", *rest, *[f"/a/{index:02d}/.claude/settings.json" for index in range(30)]])
        self.assertEqual(found["open"]["missing"], 30)


if __name__ == "__main__":
    unittest.main()
