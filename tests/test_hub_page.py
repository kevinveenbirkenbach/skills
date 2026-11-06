from __future__ import annotations

import errno
import json
import re
import subprocess
import time
import unittest
from pathlib import Path
from unittest import mock

from hub_case import HubCase
from hub_support import AMBIENCE, NAV, SPACE, VOICE
from kvb_orchestrator import exchange


class TestHubPage(HubCase):
    def test_review_page_is_sandboxed_and_the_index_allows_only_its_own_inline_code(self):
        review_id = self.request("feat: csp", "")
        status, headers, _ = self.get(f"/reviews/{review_id}/page")
        self.assertEqual(status, 200)
        self.assertEqual(headers["content-security-policy"], "sandbox allow-scripts")
        self.assertEqual(headers["x-content-type-options"], "nosniff")
        status, headers, body = self.get("/")
        csp = headers["content-security-policy"]
        nonce = re.search(r"script-src 'nonce-([^']+)'", csp).group(1)
        self.assertIn(f"style-src 'nonce-{nonce}'", csp)
        self.assertNotIn("unsafe", csp)
        self.assertIn("default-src 'none'", csp)
        html = body.decode("utf-8")
        tags = re.findall(r"<(script|style)\b([^>]*)>", html)
        self.assertEqual(sorted({tag for tag, _ in tags}), ["script", "style"])
        self.assertGreaterEqual(len(tags), 3)
        for tag, attributes in tags:
            with self.subTest(tag=tag, attributes=attributes):
                self.assertIn(f'nonce="{nonce}"', attributes)
        self.assertNotIn(nonce, self.get("/")[1]["content-security-policy"])
        status, headers, _ = self.get(f"/reviews/{review_id}/files")
        self.assertEqual((status, headers["content-type"]), (200, "application/json"))
        self.assertEqual(headers["content-security-policy"], exchange.PLAIN_CSP)

    def test_a_stored_file_that_cannot_be_read_answers_500(self):
        review_id = self.request("feat: io", "")
        for name in ("page", "files"):
            with self.subTest(name=name), mock.patch.object(Path, "read_bytes", side_effect=OSError(errno.EIO, "Input/output error")):
                status, _, body = self.get(f"/reviews/{review_id}/{name}")
                self.assertEqual((status, body), (500, b"storage failed: Input/output error\n"))

    def test_markup_from_agents_is_escaped(self):
        self.request("<script>alert(1)</script>", "</pre><script>alert(2)</script>")
        register = {"work/x": {"title": "<script>alert(3)</script>", "status": "running", "roles": {"<b>One</b>": "RA"}}}
        news = {"ts": time.time(), "from": "<img src=x>", "to": [], "text": "<script>alert(4)</script>"}
        self.write_council({"rasci.json": register, "news.jsonl": self.jsonl([news])})
        html = self.index()
        for n in range(1, 5):
            with self.subTest(n=n):
                self.assertNotIn(f"<script>alert({n})", html)
        self.assertNotIn("<img src=x>", html)
        self.assertNotIn("<b>One</b>", html)
        embedded = re.search(r'<script nonce="[^"]+" id="state" type="application/json">(.*?)</script>', html, re.DOTALL).group(1)
        state = json.loads(embedded)
        self.assertEqual((state["reviews"][0]["title"], state["reviews"][0]["notes"]), ("<script>alert(1)</script>", "</pre><script>alert(2)</script>"))
        self.assertEqual((state["register"][0]["title"], state["radio"][0]["from"]), ("<script>alert(3)</script>", "<img src=x>"))

    def test_the_index_scripts_parse_and_embed_the_ambience_voice_nav_and_space_modules(self):
        html = self.index()
        for module in (AMBIENCE, VOICE, NAV, SPACE):
            with self.subTest(module=module.name):
                self.assertIn(module.read_text(encoding="utf-8").strip(), html)
        scripts = re.findall(r'<script nonce="[^"]+">(.*?)</script>', html, re.DOTALL)
        self.assertEqual(len(scripts), 4)
        page = self.state / "page.js"
        page.write_text("\n;\n".join(scripts), encoding="utf-8")
        done = subprocess.run(["node", "--check", str(page)], capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        for module in (AMBIENCE, VOICE, NAV, SPACE):
            with self.subTest(module=module.name):
                done = subprocess.run(["node", "--check", str(module)], capture_output=True, text=True, timeout=60, check=False)
                self.assertEqual(done.returncode, 0, done.stderr)


if __name__ == "__main__":
    unittest.main()
