"""Exercise issues.py: closing keywords, mentions, commits, branch number and linked issues."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "skills" / "kvb-git-close-issues" / "scripts" / "issues.py"
PR = {
    "body": "Fixes #12 and touches #13.\nCloses: other/repo#7\nSee https://github.com/a/b/issues/9",
    "headRefName": "fix/sys-ctl-hlth-runtime/vulnerability-engines/1324",
    "commits": [
        {"oid": "abcdef1234567", "messageHeadline": "fix: guard", "messageBody": "Resolved #13"},
        {"oid": "1111111111111", "messageHeadline": "chore: tidy", "messageBody": ""},
    ],
    "closingIssuesReferences": [
        {"number": 21, "url": "https://github.com/owner/repo/issues/21"}
    ],
}


def _run(payload: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--json"],
        input=payload,
        check=False,
        capture_output=True,
        text=True,
    )


class TestIssues(unittest.TestCase):
    def test_every_reference_is_found_with_its_kind_and_source(self):
        result = _run(json.dumps(PR))
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = {(r["repo"], r["issue"]): r for r in json.loads(result.stdout)}
        self.assertEqual(
            {key: (row["closing"], row["sources"]) for key, row in rows.items()},
            {
                ("", 12): (True, ["body"]),
                ("", 13): (True, ["body", "commit abcdef1234"]),
                ("other/repo", 7): (True, ["body"]),
                ("a/b", 9): (False, ["body"]),
                ("", 1324): (False, ["branch"]),
                ("owner/repo", 21): (True, ["linked"]),
            },
        )

    def test_invalid_input_exits_2(self):
        self.assertEqual(_run("not json").returncode, 2)
        self.assertEqual(_run("[]").returncode, 2)


if __name__ == "__main__":
    unittest.main()
