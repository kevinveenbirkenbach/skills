"""Exercise meditation.py and keep it in step with the keys and choices of meditation.html."""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL = REPO_ROOT / "skills" / "kvb-coach-meditation"
SCRIPT = SKILL / "scripts" / "meditation.py"
PAGE = SKILL / "assets" / "meditation.html"
FULL = [
    "minutes=5",
    "beat=10",
    "base=196",
    "volume=0.4",
    "mode=isochronic",
    "palette=aurora",
    "breathing=box",
]


class TestMeditation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name) / "state" / "meditation.json"

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--state", str(self.state), *args],
            check=False,
            capture_output=True,
            text=True,
        )

    def _session(self) -> subprocess.CompletedProcess:
        out = Path(self.tmp.name) / "session.html"
        return self._run("session", "--page", str(PAGE), "--out", str(out))

    def test_session_page_embeds_every_setting(self):
        self.assertEqual(self._run("set", *FULL).returncode, 0)
        result = self._session()
        self.assertEqual(result.returncode, 0, result.stderr)
        page = Path(result.stdout.strip()).read_text(encoding="utf-8")
        self.assertNotIn("const SETTINGS = null;", page)
        embedded = json.loads(re.search(r"const SETTINGS = (\{.*?\});", page).group(1))
        self.assertEqual(embedded["beat"], 10.0)
        self.assertEqual(embedded["minutes"], 5)
        self.assertEqual(set(embedded), {pair.split("=")[0] for pair in FULL})

    def test_session_refuses_missing_settings(self):
        self._run("set", "minutes=5")
        self.assertEqual(self._session().returncode, 2)
        self.assertFalse((Path(self.tmp.name) / "session.html").exists())

    def test_invalid_values_exit_2_and_keep_the_state(self):
        self._run("set", *FULL)
        before = json.loads(self.state.read_text(encoding="utf-8"))
        for pair in ("beat=20", "mode=loud", "minutes=five", "tempo=3", "volume"):
            with self.subTest(pair=pair):
                self.assertEqual(self._run("set", "minutes=7", pair).returncode, 2)
        self.assertEqual(json.loads(self.state.read_text(encoding="utf-8")), before)


class TestPageMatchesScript(unittest.TestCase):
    def test_keys_and_choices_agree(self):
        spec = importlib.util.spec_from_file_location("meditation", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        page = PAGE.read_text(encoding="utf-8")
        self.assertEqual(page.count(module.PLACEHOLDER), 1)
        keys = re.search(r"const KEYS = \[(.*?)\];", page).group(1)
        self.assertEqual(re.findall(r'"(\w+)"', keys), list(module.KEYS))
        for name, choices in (("PALETTES", "palette"), ("PATTERNS", "breathing")):
            block = re.search(rf"const {name} = \{{(.*?)\n\}};", page, re.DOTALL).group(1)
            found = re.findall(r'^\s*"?(\w+)"?:', block, re.MULTILINE)
            self.assertEqual(sorted(found), sorted(module.CHOICES[choices]))

    def test_buttons_show_vendored_icons_with_their_former_text(self):
        page = PAGE.read_text(encoding="utf-8")
        sprite = (REPO_ROOT / "orchestrator" / "vendor" / "bootstrap-icons" / "bootstrap-icons.svg").read_text(encoding="utf-8")
        vendored = dict(re.findall(r'<symbol class="bi bi-[a-z0-9-]+" viewBox="0 0 16 16" id="([a-z0-9-]+)">(.*?)</symbol>', sprite, re.DOTALL))
        embedded = dict(re.findall(r'<symbol id="bi-([a-z0-9-]+)" viewBox="0 0 16 16">(.*?)</symbol>', page, re.DOTALL))
        used = re.findall(r'<use href="#bi-([a-z0-9-]+)">', page)
        self.assertTrue(used)
        self.assertEqual(sorted(embedded), sorted(set(used)))
        for name in used:
            with self.subTest(icon=name):
                self.assertEqual(embedded[name], vendored[name])
        buttons = re.findall(r"<button\b([^>]*)>(.*?)</button>", page, re.DOTALL)
        self.assertEqual([re.sub(r"<[^>]+>", "", inner).strip() for _, inner in buttons], [""])
        for attributes, inner in buttons:
            self.assertIn('<use href="#bi-play-fill">', inner)
            self.assertIn('title="Start"', attributes)
            self.assertIn('aria-label="Start"', attributes)
        self.assertNotIn("☀", page)
        self.assertIsNone(re.search(r'(?:src|href)="(?:https?:)?//', page))


if __name__ == "__main__":
    unittest.main()
