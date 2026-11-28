"""Exercise requirement 086: nothing in the hub leaves the page abruptly, working things beat, confetti lands and fades."""

from __future__ import annotations

import re
import shutil
import tempfile
import unittest
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parent.parent / "orchestrator" / "templates"
REMOVAL = re.compile(r"\.remove\(\)|\.replaceChildren\(\)")
HELPERS = re.compile(r"^  function (vanish|fadeShut|fadeSwap|fadeTransition)\(")
HELPER_HOMES = {"vanish": "page-dom.js", "fadeShut": "page-dom.js", "fadeSwap": "page-dom.js", "fadeTransition": "page-screens.js"}
ALLOWED = (
    ("page-composer.js", 'foot.querySelector(":scope > .spacer").remove();', "detached: the composer frame is still being built and not in the page yet"),
    ("page-match.js", 'host.querySelector(".task-toolbar").remove();', "detached: homeMatch() strips the toolbar of a host matchScreen() just built"),
    ("page-bubbles.js", "window.setTimeout(() => view.node.remove(), BUBBLE_FADE);", "the bubble already fades out through its own leaving class for BUBBLE_FADE ms"),
    ("page-bubbles.js", "node.remove();", "hidden: clearBubbles() runs after syncBubbles() hid the bubble layer"),
    ("page-pulses.js", "}, () => ring.remove());", "SVG redraw inside a chart: the pulse ring leaves at the end of its own fade to opacity 0"),
    ("page-pulses.js", "}, () => dot.remove());", "SVG redraw inside a chart: the pulse dot leaves once its flight across the orbit ends"),
    ("page-resources.js", "entry.plot.replaceChildren();", "hidden: the panel of this chart is hidden"),
    ("page-resources.js", "entry.legend.replaceChildren();", "hidden: the panel of this legend is hidden"),
    ("page-radiolog.js", "node.remove();", "keepLine() morphs a kept radio line in place: its old parts give way to the fresh twin's in the same row"),
    ("page-home.js", "old.remove();", "a tile head slot gives way to its successor in the same spot, so a fade would show both"),
    ("page-mic.js", "frame.remove();", "an orphaned mic frame whose field already moved into a fresh frame; a fade would show the field twice"),
    ("page-slash.js", "slash.box.remove();", "the slash list closes and reopens with each keystroke; a fading copy would stack under the next list"),
    ("page-tree.js", "tree.dom.removeAll.replaceChildren();", "the delete-all slot empties in the frame the list turns into the unreadable notice, so no button outlives its tree"),
)
LISTS = (
    ("page-match.js", "dom.stack"),
    ("page-inbox.js", "inboxDom"),
    ("page-tasks.js", "dom.body"),
    ("page-queue.js", "dom.jobs"),
    ("page-stream.js", "stream.dom.list"),
    ("page-spawn.js", "spawn.dom.list"),
)


def helper_lines(lines: list[str]) -> set[int]:
    """Args:
        lines: the lines of one template.

    Returns:
        The indexes of every line inside vanish(), fadeShut(), fadeSwap()
        or fadeTransition(), from its head to its closing brace.
    """
    inside: set[int] = set()
    start = None
    for index, line in enumerate(lines):
        if HELPERS.match(line):
            start = index
        elif start is not None and line == "  }":
            inside.update(range(start, index + 1))
            start = None
    return inside


def bare(templates: Path) -> list[str]:
    """Args:
        templates: the folder holding the hub's templates.

    Returns:
        Every `.remove()` or empty `.replaceChildren()` of a template outside
        the motion helpers and ALLOWED, as "file:line: code".
    """
    allowed = {(name, code) for name, code, _ in ALLOWED}
    found = []
    for path in sorted(templates.glob("*.js")):
        lines = path.read_text(encoding="utf-8").splitlines()
        inside = helper_lines(lines)
        for index, line in enumerate(lines):
            if REMOVAL.search(line) and index not in inside and (path.name, line.strip()) not in allowed:
                found.append(f"{path.name}:{index + 1}: {line.strip()}")
    return found


class TestPageMotion(unittest.TestCase):
    def test_no_template_removes_a_visible_element_outside_the_motion_helpers(self):
        self.assertEqual(bare(TEMPLATES), [])

    def test_every_allowed_removal_names_its_reason_and_still_exists(self):
        for name, code, reason in ALLOWED:
            with self.subTest(file=name, code=code):
                self.assertTrue(reason.strip())
                self.assertIn(code, [line.strip() for line in (TEMPLATES / name).read_text(encoding="utf-8").splitlines()])

    def test_a_bare_removal_of_a_visible_element_is_caught(self):
        with tempfile.TemporaryDirectory() as scratch:
            copy = Path(scratch)
            shutil.copytree(TEMPLATES, copy, dirs_exist_ok=True)
            settings = copy / "page-settings.js"
            settings.write_text(settings.read_text(encoding="utf-8") + "\n  const dropRow = (row) => row.remove();\n", encoding="utf-8")
            toasts = copy / "page-inbox.js"
            toasts.write_text(toasts.read_text(encoding="utf-8") + "\n  const dropToasts = () => document.getElementById(\"toasts\").replaceChildren();\n", encoding="utf-8")
            caught = bare(copy)
        self.assertEqual([line.split(":", 2)[0::2] for line in caught], [
            ["page-inbox.js", ' const dropToasts = () => document.getElementById("toasts").replaceChildren();'],
            ["page-settings.js", " const dropRow = (row) => row.remove();"],
        ])

    def test_each_motion_helper_lives_in_one_template(self):
        for name, home in HELPER_HOMES.items():
            with self.subTest(helper=name):
                owners = [path.name for path in sorted(TEMPLATES.glob("*.js")) if re.search(rf"^  function {name}\(", path.read_text(encoding="utf-8"), re.MULTILINE)]
                self.assertEqual(owners, [home])

    def test_re_rendered_lists_swap_through_the_view_transition(self):
        for name, box in LISTS:
            with self.subTest(file=name, box=box):
                source = (TEMPLATES / name).read_text(encoding="utf-8")
                self.assertNotIn(f"{box}.replaceChildren(", source)
                self.assertIn(f"fadeSwap({box}, ", source)

    def test_vanish_fades_for_a_while_and_leaves_at_once_under_reduced_motion(self):
        source = (TEMPLATES / "page-dom.js").read_text(encoding="utf-8")
        self.assertEqual(int(re.search(r"const VANISH_MS = (\d+);", source).group(1)), 180)
        vanish = re.search(r"^  function vanish\(.*?^  }$", source, re.MULTILINE | re.DOTALL).group(0)
        self.assertIn("calm.matches", vanish)
        self.assertLess(vanish.index("calm.matches"), vanish.index("el.animate("))

    def test_the_heartbeat_beats_scale_and_glow_and_keeps_only_the_glow_under_reduced_motion(self):
        css = (TEMPLATES / "style-ui.css").read_text(encoding="utf-8")
        beat = re.search(r"@keyframes lub-dub \{(.*?)\n\}", css, re.DOTALL).group(1)
        glow = re.search(r"@keyframes lub-dub-glow \{(.*?)\n\}", css, re.DOTALL).group(1)
        self.assertIn(".is-working { --beat: var(--ok); animation: lub-dub 1.2s ease-in-out infinite; }", css)
        self.assertEqual(("transform" in beat, "box-shadow" in beat), (True, True))
        self.assertEqual(("transform" in glow, "box-shadow" in glow), (False, True))
        self.assertIn("@media (prefers-reduced-motion: reduce) { .is-working { animation-name: lub-dub-glow; animation-duration: 1.2s !important; } }", css)


if __name__ == "__main__":
    unittest.main()
