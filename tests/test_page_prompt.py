from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parent.parent / "orchestrator" / "templates"
FIREWALL = TEMPLATES / "page-firewall.js"
REVEAL = TEMPLATES / "page-reveal.js"
NOW = 1_800_000_000
DAY = 86400
NAMES = {"s1": "Skills", "s2": "Stage", "s3": "Evil"}
HARNESS = """const fs = require("fs");
const [source, given] = [fs.readFileSync(process.argv[2], "utf8"), JSON.parse(fs.readFileSync(process.argv[3], "utf8"))];
const revealed = new Function("document", `${fs.readFileSync(process.argv[4], "utf8")}\\nreturn revealed;`)({getElementById: () => ({textContent: "[]"})});
const make = new Function("HUMAN", "people", "labelOf", "h", "state", "nowSeconds", "DAY", "revealed", `${source}\\nreturn {scopeLabel, promptText: typeof promptText === "function" ? promptText : () => "no promptText", firewall};`);
const page = make("human", () => given.names, (key) => given.names[key] || key, () => ({}), {rules: []}, () => given.now, given.day, revealed);
page.firewall.data = {groups: given.groups, files: [], sets: []};
console.log(JSON.stringify({scope: given.scopes.map((agents) => page.scopeLabel(agents)), prompts: given.prompts.map(([label, prepared]) => page.promptText(label, prepared))}));
"""


def rule(agents: list[str] | None, days: int) -> dict:
    """Returns:
        A signed rule payload for asks of any command under /home/op, lasting
        days from NOW, for agents or, with None, untargeted.
    """
    payload = {"v": 1, "kind": "rule", "id": "0123456789abcdef", "kinds": ["ask"], "tool": "Bash", "pattern": "*", "scope": "/home/op/*", "expires": NOW + days * DAY}
    return payload if agents is None else {**payload, "agents": agents}


def shown(source: Path, groups: list[dict], scopes: list[list[str]], prompts: list[list[object]], names: dict[str, str]) -> dict:
    """Args:
        source: the page script.
        groups: the firewall groups the page knows.
        scopes: the agents of each scope to name.
        prompts: each [label, offer] to show in the passkey prompt.
        names: the label of each session, as council claims give it.

    Returns:
        {"scope", "prompts"}: what the page script names for each scope and
        shows in the passkey prompt for each [label, offer].
    """
    with tempfile.TemporaryDirectory() as scratch:
        harness, given = Path(scratch) / "harness.js", Path(scratch) / "given.json"
        harness.write_text(HARNESS, encoding="utf-8")
        given.write_text(json.dumps({"names": names, "now": NOW, "day": DAY, "groups": groups, "scopes": scopes, "prompts": prompts}), encoding="utf-8")
        done = subprocess.run(["node", str(harness), str(source), str(given), str(REVEAL)], capture_output=True, text=True, timeout=60, check=False)
    if done.returncode != 0:
        raise AssertionError(done.stderr.strip()[:500])
    return json.loads(done.stdout)


@unittest.skipUnless(shutil.which("node"), "no node")
class TestPagePrompt(unittest.TestCase):
    def test_a_group_redefined_after_it_was_picked_shows_every_signed_session(self):
        redefined = [{"id": "ffffffffffffffff", "name": "builders", "members": ["s1", "s2", "s3"]}]
        found = shown(FIREWALL, redefined, [["s1", "s2", "s3"], ["s1", "s2"], ["s3"], ["*"]], [], NAMES)
        self.assertEqual(found["scope"], ["for group builders: Skills (s1), Stage (s2), Evil (s3)", "for agents Skills (s1), Stage (s2)", "for agent Evil (s3)", "for all agents"])

    def test_the_prompt_shows_the_pattern_directory_and_lifetime_of_every_signed_rule(self):
        end = time.strftime("%Y-%m-%d %H:%M", time.gmtime(NOW + 366 * DAY))
        approval = {"v": 1, "kind": "approve", "items": ["ab" * 32], "nonce": "cd" * 16, "expires": NOW + 900}
        found = shown(FIREWALL, [], [], [
            ["Rule set ci", {"payload": rule(["s1"], 366)}],
            ["Rule", {"payload": rule(None, 1)}],
            ["Turn on rule", {"payload": approval, "enables": rule(["s1", "s3"], 366)}],
            ["Settings", {"payload": approval}],
        ], NAMES)
        lines = ["ask Bash: *", "in /home/op/*", f"until {end} UTC, in 366.0 days"]
        self.assertEqual([prompt.split("\n") for prompt in found["prompts"]], [
            ["Rule set ci", *lines, "for agent Skills (s1)"],
            ["Rule", "ask Bash: *", "in /home/op/*", f"until {time.strftime('%Y-%m-%d %H:%M', time.gmtime(NOW + DAY))} UTC, in 1.0 days", "for all agents"],
            ["Turn on rule", *lines, "for agents Skills (s1), Evil (s3)"],
            ["Settings"],
        ])

    def test_a_hidden_character_of_a_group_set_claim_legacy_rule_or_pattern_shows_as_a_marker_in_the_prompt(self):
        rlo, separator, nel = chr(0x202E), chr(0x2028), chr(0x85)
        approval = {"v": 1, "kind": "approve", "items": ["ab" * 32], "nonce": "cd" * 16, "expires": NOW + 900}
        groups = [{"id": "ffffffffffffffff", "name": f"ci{rlo}", "members": ["s1", "s3"]}]
        legacy = {**rule(None, 1), "pattern": f"make test{rlo}*"}
        separated = {**rule(["s2"], 1), "pattern": f"make test{separator}in /safe", "scope": f"/repo{nel}*"}
        found = shown(FIREWALL, groups, [], [
            [f"Rule set ci{rlo}", {"payload": rule(["s1", "s3"], 1)}],
            ["Turn on rule", {"payload": approval, "enables": legacy}],
            ["Rule", {"payload": separated}],
        ], {**NAMES, "s2": f"Main{rlo}"})
        until = f"until {time.strftime('%Y-%m-%d %H:%M', time.gmtime(NOW + DAY))} UTC, in 1.0 days"
        self.assertEqual([prompt.split("\n") for prompt in found["prompts"]], [
            [f"Rule set ci{marker(0x202E)}", "ask Bash: *", "in /home/op/*", until, f"for group ci{marker(0x202E)}: Skills (s1), Evil (s3)"],
            ["Turn on rule", f"ask Bash: make test{marker(0x202E)}*", "in /home/op/*", until, "for all agents"],
            ["Rule", f"ask Bash: make test{marker(0x2028)}in /safe", f"in /repo{marker(0x85)}*", until, f"for agent Main{marker(0x202E)} (s2)"],
        ])


def marker(code: int) -> str:
    return f"⟨U+{code:04X}⟩"


if __name__ == "__main__":
    unittest.main()
