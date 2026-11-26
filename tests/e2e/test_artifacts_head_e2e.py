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
from hub_case import HubCase

OUT = Path(os.environ.get("E2E_OUT", "/tmp/hub-045-shots"))
WIDTHS = ((1920, 1080), (1366, 768), (390, 844))
HEAD = """(async () => {@HELPERS@
  const head = await until(() => {
    const found = document.querySelector("#main .art-head");
    return found && found.querySelector(".art-count").textContent && found.querySelector(".delete-blocked") ? found : null;
  }, 10000);
  if (!head) {
    return {error: text(document.getElementById("main")).slice(0, 300)};
  }
  await sleep(300);
  const items = (node) => (getComputedStyle(node).display === "contents" ? [...node.children].flatMap(items) : [node]);
  const shown = [...head.children].flatMap(items).filter((child) => child.getClientRects().length);
  const boxes = shown.map((child) => child.getBoundingClientRect()).sort((a, b) => a.top - b.top);
  let [lines, bottom] = [0, -Infinity];
  for (const box of boxes) {
    if (box.top >= bottom - 1) {
      lines += 1;
      bottom = box.bottom;
    } else {
      bottom = Math.max(bottom, box.bottom);
    }
  }
  const look = getComputedStyle(head);
  const inner = head.clientHeight - parseFloat(look.paddingTop) - parseFloat(look.paddingBottom);
  const row = Math.max(...shown.map((child) => child.getBoundingClientRect().height));
  const count = head.querySelector(".art-count");
  const chip = head.querySelector(".delete-blocked");
  const every = head.querySelector('button[aria-label="Delete all merged"]');
  return {
    lines, inner: Math.round(inner), row: Math.round(row), overflow: head.scrollWidth > head.clientWidth + 1,
    count: {text: text(count), title: count.title, ellipsis: getComputedStyle(count).textOverflow, nowrap: getComputedStyle(count).whiteSpace},
    chip: {title: chip.title, beside: chip.parentElement === every.closest(".why-off").parentElement},
    every: {disabled: every.disabled, wrapper: every.closest(".why-off").title},
    wide: document.documentElement.scrollWidth > innerWidth + 1,
  };
})()"""


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestArtifactsHead(HubCase):
    drive = base.OrchestratorE2ECase.drive

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        self.write_fixture("branch-tree-tokenless.json")
        data = json.loads(self.tree_file.read_text(encoding="utf-8"))
        data["repos"] = [repo for repo in data["repos"] if repo["forge"] != "none"]
        self.tree_file.write_text(json.dumps(data), encoding="utf-8")

    def test_chromium_keeps_the_artifacts_head_on_one_line_from_1024_px_and_moves_delete_blocked_into_a_chip(self):
        steps = [{"width": width, "height": height, "url": f"http://localhost:{self.port}/?{width}#artifacts/tree", "wait": 1500, "probe": HEAD.replace("@HELPERS@", base.HELPERS), "shot": str(OUT / f"chromium-{width}-artifacts-head.png")} for width, height in WIDTHS]
        data = self.drive(steps, None)
        (OUT / "chromium-artifacts-head.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        reason = "no GitHub token in the Secret Service"
        for (width, _), found in zip(WIDTHS, data["results"], strict=True):
            with self.subTest(width=width):
                self.assertNotIn("error", found, found)
                self.assertEqual((found["overflow"], found["wide"]), (False, False), found)
                self.assertLessEqual(found["lines"], 1 if width >= 1024 else 2, found)
                if width >= 1024:
                    self.assertLessEqual(abs(found["inner"] - found["row"]), 2, found)
                self.assertRegex(found["count"]["text"], r"^\d+ repositories · as of \d\d:\d\d$")
                self.assertEqual((found["count"]["title"], found["count"]["ellipsis"], found["count"]["nowrap"]), (found["count"]["text"], "ellipsis", "nowrap"), found)
                self.assertEqual(found["chip"], {"title": f"Delete blocked: {reason}", "beside": True}, found)
                self.assertEqual(found["every"], {"disabled": True, "wrapper": f"Delete all merged blocked: {reason}"}, found)


if __name__ == "__main__":
    unittest.main()
