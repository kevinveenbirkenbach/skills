from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import unittest
from collections import defaultdict
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parent.parent / "orchestrator" / "templates"
INCLUDE = re.compile(r'\{% include "([^"]+\.js)" %\}')
DECLARED = re.compile(r"^  (?:async\s+)?(?:function\s*\*?\s*([A-Za-z_$][\w$]*)|(?:const|let|var|class)\s+([A-Za-z_$][\w$]*))", re.MULTILINE)
OPENING = '(() => {\n  "use strict";'
CLOSING = "})();"


def page_block(templates: Path) -> str:
    """Returns:
        The shared page script of index.html.j2, from its opening arrow to
        its closing call, with the include tags still in place.
    """
    page = (templates / "index.html.j2").read_text(encoding="utf-8")
    start = page.index(OPENING)
    return page[start : page.index(CLOSING, start) + len(CLOSING)]


def clashes(templates: Path) -> dict[str, list[str]]:
    """Returns:
        Every top-level name the shared page script declares in more than one
        included file, with those files in include order.
    """
    owners: dict[str, list[str]] = defaultdict(list)
    for name in INCLUDE.findall(page_block(templates)):
        for match in DECLARED.finditer((templates / name).read_text(encoding="utf-8")):
            owners[match.group(1) or match.group(2)].append(name)
    return {name: files for name, files in owners.items() if len(files) > 1}


def assembled(templates: Path) -> str:
    return INCLUDE.sub(lambda match: (templates / match.group(1)).read_text(encoding="utf-8"), page_block(templates))


def parse_error(script: str) -> str:
    """Returns:
        What node --check reports for the script, "" when it parses.
    """
    with tempfile.TemporaryDirectory() as scratch:
        path = Path(scratch) / "page.js"
        path.write_text(script, encoding="utf-8")
        done = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True, timeout=60, check=False)
    return "" if done.returncode == 0 else done.stderr.strip()[:500]


class TestPageScope(unittest.TestCase):
    def test_no_top_level_name_is_declared_in_two_page_files(self):
        self.assertEqual(clashes(TEMPLATES), {})

    @unittest.skipUnless(shutil.which("node"), "no node")
    def test_the_assembled_page_script_parses(self):
        self.assertEqual(parse_error(assembled(TEMPLATES)), "")

    def test_a_clash_between_two_page_files_is_caught(self):
        with tempfile.TemporaryDirectory() as scratch:
            copy = Path(scratch)
            shutil.copytree(TEMPLATES, copy, dirs_exist_ok=True)
            firewall = copy / "page-firewall.js"
            firewall.write_text(firewall.read_text(encoding="utf-8") + "\n  const pickOf = (key) => key;\n", encoding="utf-8")
            self.assertEqual(clashes(copy), {"pickOf": ["page-firewall.js", "page-popup.js"]})
            if shutil.which("node"):
                self.assertIn("'pickOf' has already been declared", parse_error(assembled(copy)))


if __name__ == "__main__":
    unittest.main()
