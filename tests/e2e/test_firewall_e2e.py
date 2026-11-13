from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

import test_orchestrator_e2e as base
from hub_case import HubCase
from hub_support import verifier
from test_settings_writer import ORIGINAL
from test_settings_writer import host as writer_host

OUT = Path(os.environ.get("E2E_OUT", "/tmp/firewall-shots"))
SECRET = ORIGINAL["env"]["EXAMPLE_FLAG"]
SHOW = """(async () => {@HELPERS@
  await screenShown(8000);
  const ready = await until(() => document.querySelector("#main [data-file] .fw-group"), 10000);
  if (!ready) {
    return {error: text(document.getElementById("main"))};
  }
  const owned = (svg) => svg.closest("button, a, [title]");
  return {
    title: text(document.querySelector("#main h2.title")),
    subs: all("#tabs .subtabs button").map(name),
    files: all("#main [data-file]").map((node) => node.dataset.file),
    groups: all("#main [data-file] details.fw-group[data-tool]").map((node) => [node.dataset.tool, node.dataset.prefix, all("li", node).length]),
    lists: all("#main [data-file] li[data-list]").map((node) => [node.dataset.list, node.dataset.entry]),
    sandbox: all("#main [data-file] [data-key]").map((node) => node.dataset.key),
    patterns: all('#main [aria-label="Never granted"] li').length,
    targets: all('#main .rule-form select[aria-label="Applies to"] option').map(text),
    unlabelled: all("#main svg.bi").map(owned).filter((owner) => !owner || (!text(owner) && !(owner.getAttribute("title") && owner.getAttribute("aria-label")))).length,
    secret: document.documentElement.innerHTML.includes("@SECRET@"),
    wide: document.documentElement.scrollWidth > innerWidth + 1,
  };
})()"""
SIGN = """(async () => {@HELPERS@
  const entryNode = (entry) => all("#main li[data-entry]").find((node) => node.dataset.entry === entry);
  if (@REMOVE@) {
    entryNode("Bash(git status:*)").querySelector('button[aria-label="Remove"]').click();
    await sleep(100);
  }
  const form = document.querySelector('#main form[aria-label="Stage a settings change"]');
  form.querySelector('select[aria-label="Settings file"]').value = "@FILE@";
  form.querySelector('select[aria-label="List"]').value = "permissions.allow";
  form.querySelector('input[aria-label="Entry"]').value = "@ENTRY@";
  form.requestSubmit();
  await sleep(100);
  const staged = all('#main [aria-label="Staged changes"] li').map((node) => node.dataset.staged);
  document.querySelector('#main button[aria-label="Review and sign"]').click();
  const diff = await until(() => document.querySelector('.sheet-box [aria-label="Diff"] pre.fw-diff'), 8000);
  if (!diff) {
    return {error: "no diff", toasts: all("#toasts .toast").map(text)};
  }
  const lines = (cls) => all(`span.${cls}`, diff).map((node) => node.textContent.trim());
  const shown = {added: lines("add"), removed: lines("del"), staged, labelled: all(".sheet-box button").every((button) => text(button) || (button.title && button.getAttribute("aria-label")))};
  document.querySelector('.sheet-box button[aria-label="Sign and apply"]').click();
  const done = await until(() => document.querySelector(".sheet-box [data-result]"), 30000);
  shown.result = done ? done.dataset.result : null;
  shown.text = text(done);
  shown.toasts = all("#toasts .toast").map(text);
  shown.wide = document.documentElement.scrollWidth > innerWidth + 1;
  return shown;
})()"""
GROUP_RULE = """(async () => {@HELPERS@
  const prompts = [];
  new MutationObserver((records) => records.forEach((record) => record.addedNodes.forEach((node) => {
    if (node.id === "passkey-prompt") {
      prompts.push(text(node));
    }
  }))).observe(document.body, {childList: true});
  const choose = (select, value) => {
    select.value = value;
    select.dispatchEvent(new Event("change"));
  };
  const groupValue = (select) => [...select.options].map((option) => option.value).find((value) => value.startsWith("group:"));
  const setRow = () => document.querySelector('#main [data-set="ci"]');
  const setTarget = () => setRow().querySelector("select");
  const setTake = () => setRow().querySelector('button[aria-label="Take over"]');
  const setState = () => ({label: text(setTarget().selectedOptions[0]), value: setTarget().value.split(":")[0], blocked: setTake().disabled, valid: setTarget().checkValidity()});
  const stage = async (entry) => {
    const form = document.querySelector('#main form[aria-label="Stage a settings change"]');
    form.querySelector('input[aria-label="Entry"]').value = entry;
    form.requestSubmit();
    return until(() => all('#main [aria-label="Staged changes"] li').find((node) => node.dataset.staged === `add ${entry}`), 8000);
  };
  await screenShown(8000);
  await until(() => document.querySelector('#main form[aria-label="New agent group"]'), 10000);
  const group = document.querySelector('#main form[aria-label="New agent group"]');
  group.querySelector('input[aria-label="Group name"]').value = "builders";
  for (const option of group.querySelector('select[aria-label="Members"]').options) {
    option.selected = true;
  }
  group.requestSubmit();
  const row = await until(() => document.querySelector('#main [data-group="builders"]'), 8000);
  const rules = document.querySelector("#main .rule-form");
  const target = rules.querySelector('select[aria-label="Applies to"]');
  const choice = await until(() => [...target.options].find((option) => option.value.startsWith("group:")), 8000);
  if (!row || !choice) {
    return {error: "no group", toasts: all("#toasts .toast").map(text)};
  }
  target.value = choice.value;
  rules.querySelector('input[placeholder="make test*"]').value = "make e2e";
  rules.requestSubmit();
  const pill = await until(() => all("#main .rule-row [data-agents]").find((node) => text(node) === "group builders"), 15000);
  const found = {group: text(row.querySelector("strong")), members: text(row.querySelector(".muted")), pills: all("#main .rule-row [data-agents]").map(text), found: Boolean(pill), toasts: all("#toasts .toast").map(text)};
  const sets = document.querySelector('#main form[aria-label="New rule set"]');
  sets.querySelector('input[aria-label="Set name"]').value = "ci";
  for (const option of sets.querySelector('select[aria-label="Rules"]').options) {
    option.selected = option.textContent.includes("make e2e");
  }
  sets.requestSubmit();
  if (!await until(setRow, 8000)) {
    return {...found, error: "no rule set", toasts: all("#toasts .toast").map(text)};
  }
  found.fresh = setState();
  choose(setTarget(), groupValue(setTarget()));
  await stage("Bash(make e2e:*)");
  found.kept = setState();
  setTake().click();
  found.taken = await until(() => all("#toasts .toast").map(text).find((line) => line.startsWith("ci:")), 15000);
  found.reloaded = await until(() => setRow() && setTarget().value.startsWith("group:") && document.querySelector("#main .rule-form") && setState(), 8000);
  const form = document.querySelector("#main .rule-form");
  const picker = form.querySelector('select[aria-label="Applies to"]');
  const sign = form.querySelector("[data-sign]");
  choose(picker, groupValue(picker));
  found.picked = {value: picker.value.split(":")[0], blocked: sign.disabled};
  const sent = [];
  const fetched = window.fetch;
  window.fetch = (url, options) => {
    sent.push(String(url));
    return fetched(url, options);
  };
  document.querySelector('#main [data-group="builders"] button[aria-label="Delete group"]').click();
  await until(() => picker.value === "gone" || !picker.isConnected, 8000);
  found.gone = {connected: picker.isConnected, value: picker.value, label: text(picker.selectedOptions[0]), valid: picker.checkValidity(), blocked: sign.disabled, groups: [...picker.options].filter((option) => option.value.startsWith("group:")).length};
  await stage("Bash(make e2e-again:*)");
  found.setGone = setState();
  setTake().click();
  await sleep(500);
  found.sent = sent.filter((url) => url.startsWith("/api/rules"));
  choose(picker, "all");
  found.again = {value: picker.value, valid: picker.checkValidity(), blocked: sign.disabled, options: [...picker.options].map((option) => option.value).includes("gone")};
  const ruleRow = () => all("#main .rule-row").find((node) => node.querySelector("[data-agents]") && all("code", node).some((code) => text(code) === "make e2e"));
  const toggle = (label) => ruleRow() && [...ruleRow().querySelectorAll("button")].find((button) => text(button) === label);
  toggle("Turn off").click();
  found.off = Boolean(await until(() => toggle("Turn on"), 8000));
  toggle("Turn on").click();
  found.on = Boolean(await until(() => toggle("Turn off"), 15000));
  found.prompts = prompts;
  return found;
})()"""


def signed_lines(rule: dict) -> list[str]:
    """Returns:
        The lines the passkey prompt shows for a stored make e2e rule before
        its target, its lifetime in days as N.
    """
    return ["ask Bash: make e2e", "in *", f"until {time.strftime('%Y-%m-%d %H:%M', time.gmtime(rule['expires']))} UTC, in N days"]


def probe(template: str, values: dict[str, str]) -> str:
    text = template.replace("@HELPERS@", base.HELPERS)
    for name, value in values.items():
        text = text.replace(f"@{name}@", value)
    return text


@unittest.skipUnless(shutil.which(os.environ.get("CHROMIUM", "chromium")), "no Chromium")
class TestFirewallE2E(HubCase):
    drive = base.TestOrchestratorE2E.drive
    beside = base.TestOrchestratorE2E.beside
    authenticator = base.TestOrchestratorE2E.authenticator

    def setUp(self):
        super().setUp()
        OUT.mkdir(parents=True, exist_ok=True)
        self.claim("s1", "Skills")
        self.claim("s2", "Stage")
        self.snapshot()
        home = self.outside / "home"
        self.settings = home / ".claude" / "settings.json"
        self.settings.parent.mkdir(parents=True)
        self.settings.write_text(json.dumps(ORIGINAL, indent=2) + "\n", encoding="utf-8")
        self.settings.chmod(0o640)
        tree = self.outside / "writer-tree.json"
        tree.write_text(json.dumps({"repos": [{"path": str(self.outside / "demo"), "known": True, "default": "main"}]}), encoding="utf-8")
        trust = verifier.Trust(approvers=self.approvers, replay=self.replay / "firewall.json", origin=self.origin)
        self.writer = writer_host.Writer(trust, home, tree)
        self.spool = self.state / "firewall"
        verifier.write_private(self.spool / "view.json", self.writer.view())
        self.local = f"http://localhost:{self.port}/"

    def host_unit(self) -> None:
        if any((self.spool / "jobs").iterdir()):
            writer_host.cycle(self.spool / "jobs", self.spool / "results", self.writer)
            verifier.write_private(self.spool / "view.json", self.writer.view())

    def test_chromium_shows_the_settings_and_signs_a_settings_diff_at_three_widths(self):
        authenticator = self.authenticator()
        self.beside(self.host_unit)
        steps = []
        for index, (width, height) in enumerate(base.WIDTHS):
            values = {"SECRET": SECRET, "FILE": str(self.settings), "ENTRY": f"Bash(make lint-{width}:*)", "REMOVE": "true" if index == 0 else "false"}
            steps.append({"width": width, "height": height, "url": f"{self.local}?{width}#stream/rules", "wait": 1500, "probe": probe(SHOW, values), "shot": str(OUT / f"chromium-{width}-firewall.png")})
            steps.append({"width": width, "height": height, "url": None, "wait": 0, "probe": probe(SIGN, values), "shot": str(OUT / f"chromium-{width}-firewall-signed.png")})
        data = self.drive(steps, authenticator)
        (OUT / "chromium-firewall.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        for index, (width, _) in enumerate(base.WIDTHS):
            shown, signed = data["results"][2 * index : 2 * index + 2]
            with self.subTest(width=width):
                self.assertNotIn("error", shown, shown)
                self.assertEqual((shown["title"], shown["subs"]), ("Firewall", base.SUBS))
                self.assertEqual(shown["files"], [str(self.settings), str(self.outside / "demo" / ".claude" / "settings.json")])
                self.assertIn(["Bash", "make", 1 + index], shown["groups"])
                self.assertIn(["Read", "~/.ssh/**", 1], shown["groups"])
                self.assertIn(["sandbox.filesystem.allowWrite", "/tmp"], shown["lists"])
                self.assertIn("sandbox.enabled", shown["sandbox"])
                self.assertGreater(shown["patterns"], 5)
                self.assertEqual(shown["targets"], ["All agents", "Agent Skills", "Agent Stage"])
                self.assertEqual((shown["unlabelled"], shown["secret"], shown["wide"]), (0, False, False))
                self.assertNotIn("error", signed, signed)
                self.assertTrue(any(line.startswith("+") and f'"Bash(make lint-{width}:*)"' in line for line in signed["added"]), signed["added"])
                self.assertEqual(any("git status" in line for line in signed["removed"]), index == 0)
                self.assertEqual((signed["result"], signed["labelled"], signed["wide"]), ("done", True, False), signed)
                self.assertIn("Settings: written", " ".join(signed["toasts"]))
        written = json.loads(self.settings.read_text(encoding="utf-8"))
        self.assertEqual(written["permissions"]["allow"], ["Bash(make test:*)", *(f"Bash(make lint-{width}:*)" for width, _ in base.WIDTHS)])
        self.assertEqual({key: written[key] for key in ("model", "env", "hooks", "sandbox")}, {key: ORIGINAL[key] for key in ("model", "env", "hooks", "sandbox")})
        backups = sorted(self.settings.parent.glob("settings.json.before-firewall-*"))
        self.assertEqual((len(backups), self.settings.stat().st_mode & 0o777), (3, 0o640))

    def test_chromium_names_a_group_and_signs_a_rule_for_it(self):
        authenticator = self.authenticator()
        steps = [{"width": 1366, "height": 768, "url": f"{self.local}#stream/rules", "wait": 1500, "probe": probe(GROUP_RULE, {}), "shot": str(OUT / "chromium-1366-firewall-group-rule.png")}]
        data = self.drive(steps, authenticator)
        (OUT / "chromium-firewall-group.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.assertEqual(data["errors"], [])
        found = data["results"][0]
        self.assertNotIn("error", found, found)
        self.assertEqual((found["group"], found["members"], found["found"]), ("builders", "Skills, Stage", True), found)
        stored = [rule for rule in self.httpd.hub.rules.listed() if rule["pattern"] == "make e2e"]
        self.assertEqual([(rule["agents"], rule["proof"]["payload"]["agents"]) for rule in stored], [(["s1", "s2"], ["s1", "s2"])] * 2)
        for rule in stored:
            self.assertLess(abs(rule["expires"] - (time.time() + 7 * 86400)), 2 * 86400)
        self.assertEqual(found["fresh"], {"label": "Pick a target", "value": "", "blocked": True, "valid": False}, found)
        self.assertEqual(found["kept"], {"label": "Group builders", "value": "group", "blocked": False, "valid": True}, found)
        self.assertEqual(found["taken"], "ci: 1 of 1 rules signed for group builders")
        self.assertEqual(found["reloaded"], found["kept"])
        self.assertEqual(found["setGone"], {"label": "Target gone: pick again", "value": "gone", "blocked": True, "valid": False}, found)
        self.assertEqual(found["sent"], [])
        members = "Skills (s1), Stage (s2)"
        shown = [re.sub(r"in \d+\.\d days$", "in N days", prompt.removeprefix("Passkey signs"), flags=re.MULTILINE).split("\n") for prompt in found["prompts"]]
        made = sorted(stored, key=lambda rule: rule["created_ts"])
        self.assertEqual(shown[:2], [["Rule", *signed_lines(made[0]), f"for group builders: {members}"], ["Rule set ci", *signed_lines(made[1]), f"for group builders: {members}"]], found)
        self.assertIn(shown[2:], [[["Turn on rule", *signed_lines(rule), f"for agents {members}"]] for rule in made], found)
        self.assertTrue(found["prompts"][1].split("\n")[3].endswith("in 7.0 days"), found["prompts"])
        self.assertEqual((found["off"], found["on"], [rule["enabled"] for rule in self.httpd.hub.rules.listed() if rule["pattern"] == "make e2e"]), (True, True, [True, True]))
        self.assertEqual(found["picked"], {"value": "group", "blocked": False})
        self.assertEqual(found["gone"], {"connected": True, "value": "gone", "label": "Target gone: pick again", "valid": False, "blocked": True, "groups": 0}, found)
        self.assertEqual(found["again"], {"value": "all", "valid": True, "blocked": False, "options": False}, found)
        self.assertEqual(self.httpd.hub.groups.listed(), [])


if __name__ == "__main__":
    unittest.main()
