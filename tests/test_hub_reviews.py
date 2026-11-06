from __future__ import annotations

import json
import os
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from hub_case import HubCase
from hub_support import PAGE, TREE, key
from kvb_hub import ledger, review_page, reviewing

REVIEW_PAGE = """<!DOCTYPE html><html><head><script>const x = "<details class='file'>";</script></head><body>
<section class="group" id="staged" data-files="2">
<h2>Staged <span class="muted">2 files</span><span class="stat"><span class="add">+2</span><span class="del">&minus;1</span></span></h2>
<details class="file" id="f1" data-path="hub/server.py" open>
<summary>
<span class="badge modified" title="modified">M</span>
<span class="path">hub/server.py</span>
<span class="stat"><span class="add">+2</span><span class="del">&minus;1</span></span>
<a class="open" href="vscode://file/x" title="Open in VS Code">Open &#8599;</a>
</summary>
<table class="diff">
<tbody>
<tr class="hunk"><td class="num" colspan="2"></td><td class="code" colspan="2">@@ -1,2 +1,3 @@</td></tr>
<tr class="ctx"><td class="num">1</td><td class="num"><a href="vscode://file/x:1">1</a></td><td class="sign"></td><td class="code">import os</td></tr>
<tr class="del"><td class="num">2</td><td class="num"></td><td class="sign">-</td><td class="code">if a &lt; b:</td></tr>
<tr class="add"><td class="num"></td><td class="num">2</td><td class="sign">+</td><td class="code">if a &lt;= b:</td></tr>
<tr class="add"><td class="num"></td><td class="num">3</td><td class="sign">+</td><td class="code">    return &quot;&lt;b&gt;&quot;</td></tr>
</tbody>
<tbody><tr class="more"><td colspan="4">&hellip; 5 more lines not shown</td></tr></tbody>
</table>
</details>
<details class="file" id="f2" data-path="docs/new.md">
<summary>
<span class="badge renamed" title="renamed">R</span>
<span class="path"><span class="old">docs/old.md</span><span class="arrow"> &rarr; </span>docs/new.md</span>
<span class="tag">binary</span>
<span class="stat"><span class="add">+0</span><span class="del">&minus;0</span></span>
</summary>
<p class="placeholder">No content changes.</p>
</details>
</section>
<section class="group" id="commits">
<details class="commit" id="c1" open><summary><code class="sha">abc1234</code></summary>
<div class="commit-files">
<details class="file" id="f3" data-path="skip.py"><summary><span class="badge added" title="added">A</span><span class="path">skip.py</span></summary></details>
</div>
</details>
</section>
</body></html>
"""


class TestHubReviews(HubCase):
    def decide(self, review_id: str, action: str, headers: dict[str, str], body: bytes) -> int:
        status, _, _ = self.call("POST", f"/reviews/{review_id}/{action}", body, headers)
        return status

    def test_review_request_copies_the_page(self):
        source = self.page("bundle.html", PAGE)
        result = self.tool("review_request", self.arguments("feat: copy", "", source))
        review_id = result["structuredContent"]["id"]
        self.assertEqual(result["structuredContent"]["url"], f"http://localhost:{self.port}/")
        Path(source).write_text("<p>changed after the request</p>", encoding="utf-8")
        status, _, body = self.get(f"/reviews/{review_id}/page")
        self.assertEqual((status, body.decode("utf-8")), (200, PAGE))
        self.assertEqual((self.state / "pages" / f"{review_id}.html").read_text(encoding="utf-8"), PAGE)

    def test_review_request_rejects_pages_outside_the_pages_dir(self):
        evil = self.outside / "evil.html"
        evil.write_text("<p>evil</p>", encoding="utf-8")
        (self.pages / "notes.txt").write_text("plain", encoding="utf-8")
        (self.pages / "link.html").symlink_to(evil)
        (self.pages / "dir.html").mkdir()
        os.mkfifo(self.pages / "fifo.html")
        for page in (
            str(evil),
            f"{self.pages}/../outside/evil.html",
            str(self.pages / "notes.txt"),
            str(self.pages / "link.html"),
            str(self.pages / "dir.html"),
            str(self.pages / "fifo.html"),
            str(self.pages / "missing.html"),
            "bundle.html",
            "",
        ):
            with self.subTest(page=page):
                result = self.tool("review_request", self.arguments("feat: x", "", page))
                self.assertTrue(result["isError"], result)
        self.assertEqual(self.tool("review_list", {})["structuredContent"]["reviews"], [])
        self.assertEqual(list((self.state / "pages").iterdir()), [])

    def test_approve_flips_the_status_and_review_wait_returns_it(self):
        review_id = self.request("feat: approve me", "")
        results = []
        waiter = threading.Thread(target=lambda: results.append(self.tool("review_wait", {"id": review_id, "timeout_seconds": 30})))
        waiter.start()
        time.sleep(0.3)
        self.assertTrue(waiter.is_alive())
        signer = key(-7, "main")
        for body in (b"", b'{"proof": null}', b'{"proof": {"payload": {}, "assertion": {}}}', b'{"proof": 1, "extra": 1}'):
            with self.subTest(body=body):
                self.assertEqual(self.decide(review_id, "approve", self.guard(self.host), body), 400)
        self.assertTrue(waiter.is_alive())
        started = time.monotonic()
        proven = self.proven([self.entry("review", review_id, "", "")], signer)
        self.assertEqual(self.decide(review_id, "approve", self.guard(self.host), proven), 200)
        waiter.join(10)
        self.assertLess(time.monotonic() - started, 10)
        decided = results[0]["structuredContent"]
        self.assertEqual((decided["status"], decided["tree"]), ("approved", TREE))
        self.assertIsNotNone(decided["decided"])
        self.assertEqual(self.status(review_id), "approved")
        status, _, body = self.get(f"/api/reviews/{review_id}")
        self.assertEqual((status, json.loads(body)["proof"]), (200, json.loads(proven)["proof"]))
        self.assertEqual(self.decide(review_id, "reject", self.guard(self.host), b""), 409)
        self.assertEqual(self.status(review_id), "approved")
        other = self.request("feat: reject me", "")
        self.assertEqual(self.decide(other, "reject", self.guard(f"localhost:{self.port}"), b""), 200)
        self.assertEqual(self.tool("review_wait", {"id": other, "timeout_seconds": 0})["structuredContent"]["status"], "rejected")
        self.assertIsNone(json.loads(self.get(f"/api/reviews/{other}")[2])["proof"])
        self.assertEqual(self.tool("review_list", {})["structuredContent"]["reviews"], [])
        self.assertEqual(self.decide("0123456789abcdef", "approve", self.guard(self.host), proven), 404)
        self.assertEqual(self.get("/api/reviews/0123456789abcdef")[0], 404)
        self.assertEqual(ledger.Reviews(self.state).get(review_id)["status"], "approved")

    def test_review_wait_times_out_at_the_cap(self):
        review_id = self.request("feat: slow", "")
        started = time.monotonic()
        with mock.patch.object(reviewing, "WAIT_CAP", 0.2):
            result = self.tool("review_wait", {"id": review_id, "timeout_seconds": 10**6})
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(result["structuredContent"]["status"], "pending")

    def test_cross_site_decisions_are_forbidden(self):
        review_id = self.request("feat: guarded", "")
        good = self.guard(self.host)
        for headers in (
            {k: v for k, v in good.items() if k != "X-Kvb-Hub"},
            {**good, "X-Kvb-Hub": "0"},
            {k: v for k, v in good.items() if k != "Origin"},
            {**good, "Origin": "http://evil.example"},
            {**good, "Origin": "null"},
            {**good, "Origin": f"http://localhost:{self.port}"},
            {**good, "Host": f"evil.example:{self.port}", "Origin": f"http://evil.example:{self.port}"},
            {**good, "Host": "127.0.0.1:1", "Origin": "http://127.0.0.1:1"},
        ):
            for action in ("approve", "reject"):
                with self.subTest(headers=headers, action=action):
                    self.assertEqual(self.decide(review_id, action, headers, b""), 403)
        self.assertEqual(self.status(review_id), "pending")

    def test_review_files_come_from_the_page(self):
        files = review_page.review_files(REVIEW_PAGE.encode("utf-8"))
        self.assertEqual([(f["section"], f["path"], f["old"], f["status"], f["added"], f["removed"]) for f in files], [
            ("staged", "hub/server.py", "", "modified", 2, 1),
            ("staged", "docs/new.md", "docs/old.md", "renamed", 0, 0),
        ])
        lines = [(line["kind"], line["old"], line["new"], line["text"]) for line in files[0]["lines"]]
        self.assertEqual(lines, [
            ("hunk", "", "", "@@ -1,2 +1,3 @@"),
            ("ctx", "1", "1", "import os"),
            ("del", "2", "", "if a < b:"),
            ("add", "", "2", "if a <= b:"),
            ("add", "", "3", '    return "<b>"'),
            ("more", "", "", "… 5 more lines not shown"),
        ])
        self.assertEqual((files[1]["tags"], files[1]["detail"], files[1]["lines"]), (["binary"], "No content changes.", []))
        review_id = self.tool("review_request", self.arguments("feat: tree", "", self.page("tree.html", REVIEW_PAGE)))["structuredContent"]["id"]
        status, _, body = self.get(f"/reviews/{review_id}/files")
        self.assertEqual((status, json.loads(body)), (200, {"files": files}))
        self.assertEqual([(r["id"], r["files"]) for r in self.snapshot()["reviews"]], [(review_id, 2)])
        self.assertEqual(self.get(f"/reviews/{review_id}/page")[2].decode("utf-8"), REVIEW_PAGE)


if __name__ == "__main__":
    unittest.main()
