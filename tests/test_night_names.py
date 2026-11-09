"""Pin decision 29: the six night skills renamed to drain, suspend and resume leave their old names nowhere but in a rename record."""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RENAMED = {
    "kvb-org-evening": "kvb-org-drain",
    "kvb-org-sunset": "kvb-org-suspend",
    "kvb-org-sunrise": "kvb-org-resume",
    "kvb-agent-relax": "kvb-agent-drain",
    "kvb-agent-sleep": "kvb-agent-suspend",
    "kvb-agent-wakeup": "kvb-agent-resume",
}
OLD = re.compile(r"(?<![\w-])(?:" + "|".join(map(re.escape, RENAMED)) + r")(?![\w-])")
RECORD = re.compile(r"`(?:" + "|".join(map(re.escape, RENAMED)) + r")` →")
SELF = Path(__file__).resolve().relative_to(REPO_ROOT).as_posix()


def old_name_lines() -> list[str]:
    """Returns:
        Every `path:line` of a tracked or new, not ignored text file that names
        an old night skill outside a rename record (`old` → `new`, as decision
        29 of docs/requirements/001-agent-orchestrator.md writes it).
    """
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout
    hits = []
    for name in sorted(set(listed.split("\0")) - {"", SELF}):
        try:
            text = (REPO_ROOT / name).read_text(encoding="utf-8")
        except (UnicodeDecodeError, IsADirectoryError, FileNotFoundError):
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if OLD.search(RECORD.sub("", line)):
                hits.append(f"{name}:{number}")
    return hits


class TestNightNames(unittest.TestCase):
    def test_the_six_new_skills_exist_and_the_old_ones_do_not(self):
        for old, new in RENAMED.items():
            with self.subTest(skill=new):
                self.assertTrue((REPO_ROOT / "skills" / new / "SKILL.md").is_file())
                self.assertFalse((REPO_ROOT / "skills" / old).exists())

    def test_old_names_live_only_in_rename_records(self):
        self.assertEqual(old_name_lines(), [], "write a rename as `old` → `new`; any other mention goes")

    def test_a_rename_record_is_the_only_exemption(self):
        self.assertIsNone(OLD.search(RECORD.sub("", "`kvb-org-sunset` → `kvb-org-suspend`")))
        for line in ("run kvb-agent-sleep now", "`kvb-org-sunset`", "kvb-org-sunset → kvb-org-suspend", "skills/kvb-org-sunrise/SKILL.md"):
            with self.subTest(line=line):
                self.assertIsNotNone(OLD.search(RECORD.sub("", line)))
        self.assertIsNone(OLD.search("kvb-org-sunsets kvb-agent-sleeper my-kvb-org-evening"))


if __name__ == "__main__":
    print("\n".join(old_name_lines()))
