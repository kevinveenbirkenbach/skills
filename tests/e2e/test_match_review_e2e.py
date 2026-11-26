from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

import hub_e2e_kit as base
from hub_case import HubCase
from hub_support import iso

OUT = Path(os.environ.get("E2E_OUT", "/tmp/hub-012-shots"))
FILES = (("src/app.py", 60), ("src/view.js", 30), ("docs/notes.md", 12))
PATTERNS = ("dots", "stripes", "waves", "grid", "rings")
CARD = """
  const card = () => document.querySelector("#main .match-card.front");
  const body = () => card() && card().querySelector(".match-body");
  const opened = () => all(".match-file", card()).filter((file) => file.open).map((file) => file.dataset.path);
  const pick = async (id) => {
    const tab = await until(() => document.querySelector(`#main .match-peek[data-card="${id}"]`), 8000);
    if (tab) {
      tab.click();
    }
    return until(() => card() && card().dataset.card === id && card(), 8000);
  };
  const head = () => ({
    card: card().dataset.card, kind: card().dataset.kind, stale: card().dataset.stale, face: Boolean(card().querySelector(".match-who .avatar svg")),
    opens: Boolean(card().querySelector(".match-who .avatar").closest("button.agent-link")),
    name: text(card().querySelector(".match-name")), age: text(card().querySelector(".match-age")),
    metrics: all(".match-metric", card()).map((chip) => [chip.dataset.metric, text(chip.querySelector("strong"))]),
    under: Boolean(card().querySelector(".match-metrics")) && card().querySelector(".match-metrics").getBoundingClientRect().top >= card().querySelector(".match-name").getBoundingClientRect().bottom - 1,
    place: all(".match-place .match-where", card()).map((chip) => [chip.dataset.place, text(chip), chip.title]),
    paint: [card().dataset.pattern, card().style.getPropertyValue("--card-hue"), card().style.getPropertyValue("--card-hue-2"), getComputedStyle(card().querySelector(".match-head")).backgroundImage.includes("radial-gradient")],
    files: all(".match-file", card()).map((file) => file.dataset.path), accept: card().closest(".match-stack").querySelector(".match-accept").disabled,
    reason: text(card().querySelector(".match-stale")), peeks: all("#main .match-peek").map((tab) => tab.dataset.card),
    wide: document.documentElement.scrollWidth > window.innerWidth + 1,
  });
"""
STACK = """(async () => {@HELPERS@@CARD@
  await screenShown(8000);
  await until(card, 8000);
  await sleep(400);
  return head();
})()"""
SCROLL = """(async () => {@HELPERS@@CARD@
  await until(card, 8000);
  const steps = [opened()];
  for (let step = 0; step < 6; step += 1) {
    body().scrollTop = body().scrollHeight;
    body().dispatchEvent(new Event("scroll"));
    await sleep(350);
    steps.push(opened());
  }
  const numbered = all(".match-file[open]", card()).map((file) => [file.dataset.path, all("tr[data-line] td.num", file).filter((cell) => text(cell)).length > 0]);
  body().scrollTop = 0;
  return {steps, numbered};
})()"""
MARK = """(async () => {@HELPERS@@CARD@
  await until(card, 8000);
  const row = (path, line) => card().querySelector(`.match-file[data-path="${path}"] tr[data-line="${line}"]`);
  const save = async (words) => {
    const field = await until(() => card().querySelector(".match-comment textarea"), 3000);
    if (!field) {
      return false;
    }
    field.value = words;
    card().querySelector(".match-comment .match-save").click();
    await sleep(200);
    return true;
  };
  const first = row("@FIRST@", 3);
  first.scrollIntoView({block: "center"});
  const box = first.getBoundingClientRect();
  first.dispatchEvent(new MouseEvent("contextmenu", {bubbles: true, cancelable: true, clientX: box.left + 40, clientY: box.top + 4, button: 2}));
  const clicked = await save("use the helper here");
  const second = row("@FIRST@", 6);
  second.dispatchEvent(new PointerEvent("pointerdown", {bubbles: true, cancelable: true, pointerId: 7, pointerType: "touch", isPrimary: true, clientX: box.left + 40, clientY: box.top + 4}));
  await sleep(800);
  second.dispatchEvent(new PointerEvent("pointerup", {bubbles: true, cancelable: true, pointerId: 7, pointerType: "touch", isPrimary: true}));
  const pressed = await save("long press note");
  const marks = all("tr.match-mark", card()).map((mark) => [mark.dataset.line, text(mark.querySelector(".match-mark-text"))]);
  const marked = all("tr.marked", card()).map((mark) => mark.dataset.line);
  const third = row("@FIRST@", 9);
  third.dispatchEvent(new MouseEvent("contextmenu", {bubbles: true, cancelable: true, clientX: box.left + 40, clientY: box.top + 4, button: 2}));
  const field = await until(() => card().querySelector(".match-comment textarea"), 3000);
  const presets = all(".match-comment .reason-chips .chip", card()).map(text);
  card().querySelector(".match-comment .reason-chips .chip:last-child").click();
  const preset = [field.value, document.activeElement === field];
  card().querySelector(".match-comment .btn.ghost").click();
  return {clicked, pressed, marks, marked, presets, preset, count: text(card().querySelector('.match-file[data-path="@FIRST@"] .match-marks'))};
})()"""
PICK = """(async () => {@HELPERS@@CARD@
  const found = await pick("@ID@");
  if (!found) {
    return {missing: "@ID@"};
  }
  await sleep(400);
  const command = card().querySelector(".match-command");
  const payload = all(".match-file", card()).map((file) => [file.dataset.path.split("/").pop(), file.dataset.state || "", all("tr[data-line]", file).length]);
  return {...head(), command: command ? text(command.querySelector("code")) : null, where: text(card().querySelector(".match-directory")), why: text(card().querySelector(".match-reason")), payload};
})()"""


def probe(template: str, **values: str) -> str:
    found = template.replace("@HELPERS@", base.HELPERS).replace("@CARD@", CARD)
    for name, value in values.items():
        found = found.replace(f"@{name}@", value)
    return found


def patch(lines: int) -> str:
    rows = [f"@@ -1,{lines} +1,{lines + 1} @@"] + [f" line {number}" for number in range(1, lines + 1)]
    rows.insert(4, "+added line")
    return "\n".join(rows)


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestMatchReview(HubCase):
    drive = base.OrchestratorE2ECase.drive

    def setUp(self):
        super().setUp()
        self.cards()

    def cards(self) -> None:
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.work = Path(work.name)
        now = time.time()
        self.write_council({
            "work/s1/claim.json": {"office": "work/s1", "session": "s1", "runtime": "claude", "name": "Skills", "since": iso(now - 3 * 86400 - 60), "beat": now, "work": "match"},
            "work/s2/claim.json": {"office": "work/s2", "session": "s2", "runtime": "claude", "name": "Stage", "since": iso(now - 9 * 86400 - 60), "beat": now, "work": "i18n"},
        })
        diff = [{"path": path, "status": "M", "mode": "100644", "additions": 1, "deletions": 0, "patch": patch(lines), "note": ""} for path, lines in FILES]
        self.commit = self.review("feat: match review", "/repo/.worktrees/feature/match", "feature/match", "Skills", diff)
        stale_diff = [{"path": "README.md", "status": "M", "mode": "100644", "additions": 1, "deletions": 0, "patch": patch(8), "note": ""}]
        self.stale = self.review("docs: stale stage", "/repo/.worktrees/feature/old", "feature/old", "Stage", stale_diff)
        status, _, body = self.post_json("/api/match/stale", {"id": self.stale, "tree": "f" * 40}, self.local())
        self.assertEqual(status, 200, body)
        self.payload()
        self.base = f"http://{self.host}/"

    def review(self, title: str, worktree: str, branch: str, agent: str, diff: list[dict]) -> str:
        arguments = {**self.arguments(title, "", self.page(f"{branch.replace('/', '-')}.html", "<!doctype html><title>p</title>")), "worktree": worktree, "branch": branch, "agent": agent, "diff": diff}
        result = self.tool("review_request", arguments)
        self.assertFalse(result["isError"], result)
        return result["structuredContent"]["id"]

    def payload(self) -> None:
        body = self.work / "body.md"
        body.write_text("".join(f"Release note line {number}\n" for number in range(1, 15)), encoding="utf-8")
        (self.work / "link.md").symlink_to(body)
        folder = self.state / "firewall"
        folder.mkdir(parents=True, exist_ok=True)
        files = [{"path": "/home/op/.claude/settings.json", "exists": True, "sha256": "", "settings": {"sandbox": {"filesystem": {"denyRead": []}}}}]
        (folder / "view.json").write_text(json.dumps({"written": "2026-11-14T12:00:00+00:00", "files": files}), encoding="utf-8")
        self.command = f"gh issue create --body-file {body} --list link.md"
        self.write_council({"rasci.json": {"operator/issue": {"title": self.command, "workdir": str(self.work), "description": "file the release issue", "check": "done", "roles": {"Skills": "A", "Operator": "R"}}}})

    def steps(self, browser: str, widths: tuple[tuple[int, int], ...]) -> list[dict]:
        OUT.mkdir(parents=True, exist_ok=True)
        steps = []
        for width, height in widths:
            shot = str(OUT / f"{browser}-{width}")
            steps += [
                {"width": width, "height": height, "url": f"{self.base}?{width}#tasks/match", "wait": 1500, "probe": probe(STACK), "shot": f"{shot}-stack.png"},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(SCROLL), "shot": None},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(MARK, FIRST=FILES[0][0]), "shot": f"{shot}-marked.png"},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(PICK, ID="operator:operator/issue"), "shot": f"{shot}-command.png"},
                {"width": width, "height": height, "url": None, "wait": 0, "probe": probe(PICK, ID=f"review:{self.stale}"), "shot": f"{shot}-stale.png"},
            ]
        return steps

    def check(self, data: dict, widths: tuple[tuple[int, int], ...]) -> None:
        results = iter(data["results"])
        order = [path for path, _ in FILES]
        paints = set()
        for width, _ in widths:
            stack, scroll, mark, command, stale = (next(results) for _ in range(5))
            with self.subTest(width=width):
                self.assertEqual((stack["card"], stack["kind"], stack["stale"], stack["face"], stack["opens"]), (f"review:{self.commit}", "commit", "false", True, True), stack)
                self.assertEqual((stack["name"], stack["age"]), ("Skills", "3 days"), stack)
                self.assertEqual((stack["metrics"], stack["under"]), ([["fix", "95"], ["break", "3"]], True), stack)
                place = [["branch", "feature/match", "Branch: feature/match (click copies)"], ["repo", "repo", "Repository: /repo (click copies)"],
                         ["worktree", ".worktrees/feature/match", "Worktree: /repo/.worktrees/feature/match (click copies)"]]
                self.assertEqual(stack["place"], place, stack)
                self.assertIn(stack["paint"][0], PATTERNS, stack)
                self.assertTrue(stack["paint"][1] and stack["paint"][2] and stack["paint"][3], stack)
                paints.add(tuple(stack["paint"]))
                self.assertEqual(stack["files"], order)
                self.assertEqual(stack["peeks"], ["operator:operator/issue", f"review:{self.stale}"], stack)
                self.assertFalse(stack["accept"], stack)
                self.assertFalse(stack["wide"], stack)
                self.assertEqual(scroll["steps"][0], order[:1], scroll)
                self.assertEqual(scroll["steps"][-1], order, scroll)
                for step in scroll["steps"]:
                    self.assertEqual(step, order[: len(step)], scroll)
                self.assertGreater(len({len(step) for step in scroll["steps"]}), 2, scroll)
                self.assertEqual(scroll["numbered"], [[path, True] for path in order], scroll)
                self.assertEqual((mark["clicked"], mark["pressed"]), (True, True), mark)
                self.assertEqual(mark["marks"], [["3", "use the helper here"], ["6", "long press note"]], mark)
                self.assertEqual(mark["marked"], ["3", "6"], mark)
                self.assertEqual((mark["presets"], mark["preset"]), (["long press note", "use the helper here"], ["use the helper here", True]), mark)
                self.assertEqual(mark["count"], "2", mark)
                self.assertEqual((command["kind"], command["stale"], command["command"], command["why"]), ("command", "false", self.command, "file the release issue"), command)
                self.assertEqual(command["where"], str(self.work), command)
                self.assertEqual(command["payload"], [["body.md", "read", 14], ["link.md", "refused", 0]], command)
                self.assertEqual((command["name"], command["age"]), ("Skills", "3 days"), command)
                self.assertEqual((stale["kind"], stale["stale"], stale["accept"], stale["name"], stale["age"]), ("commit", "true", True, "Stage", "9 days"), stale)
                self.assertIn("changed", stale["reason"])
        self.assertEqual(len(paints), 1, paints)

    def test_chromium_shows_face_place_files_on_scroll_and_marks_at_three_widths(self):
        data = self.drive(self.steps("chromium", base.WIDTHS), None)
        (OUT / "chromium-match.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        self.check(data, base.WIDTHS)

    @unittest.skipUnless(shutil.which(os.environ.get("FIREFOX", "firefox")), "no Firefox")
    def test_firefox_shows_face_place_files_on_scroll_and_marks_at_three_widths(self):
        data = self.drive(self.steps("firefox", base.WIDTHS), None, "bidi.mjs", os.environ.get("FIREFOX", "firefox"))
        (OUT / "firefox-match.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual([error for error in data["errors"] if "/favicon.ico" not in error], [])
        self.check(data, base.WIDTHS)


if __name__ == "__main__":
    unittest.main()
