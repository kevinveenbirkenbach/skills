"""Run orchestrator.sh install twice in a scratch HOME with stub docker, claude and systemctl."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "orchestrator.sh"
HOST_SCRIPTS = ("kvb-org-organize/scripts/council.py", "kvb-org-organize/scripts/nofollow.py", "kvb-org-rasci/scripts/rasci.py")
OLD = "kvb-hub"
NEW = "kvb-orchestrator"
STUB = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path

tool, args = Path(sys.argv[0]).name, sys.argv[1:]
file = Path(os.environ["STUB_STATE"])
state = json.loads(file.read_text())
state["calls"].append([tool, *args])
code = 0
if tool == "docker" and args[:2] == ["image", "inspect"]:
    code = 0 if args[2] in state["images"] else 1
elif tool == "docker" and args[:2] == ["image", "rm"]:
    code = 0 if args[2] in state["images"] else 1
    state["images"] = [image for image in state["images"] if image != args[2]]
elif tool == "docker" and args[0] == "compose" and "up" in args:
    state["images"] = sorted({*state["images"], "kvb-orchestrator:local"})
elif tool == "claude" and args[:2] == ["mcp", "get"]:
    code = 0 if args[2] in state["mcp"] else 1
elif tool == "claude" and args[:2] == ["mcp", "remove"]:
    code = 0 if args[-1] in state["mcp"] else 1
    state["mcp"].pop(args[-1], None)
elif tool == "claude" and args[:2] == ["mcp", "add"]:
    state["mcp"][args[-2]] = args[-1]
elif tool == "systemctl":
    verb, unit = args[1], args[-1]
    if verb == "is-enabled":
        print("enabled" if unit in state["enabled"] else "disabled")
        code = 0 if unit in state["enabled"] else 1
    elif verb == "disable":
        state["enabled"] = [name for name in state["enabled"] if name != unit]
    elif verb == "enable":
        state["enabled"] = sorted({*state["enabled"], unit})
    elif verb == "is-active":
        print("active" if unit in state["enabled"] else "inactive")
        code = 0 if unit in state["enabled"] else 3
file.write_text(json.dumps(state))
sys.exit(code)
'''


def snapshot(root: Path) -> dict:
    found = {}
    for path in sorted(root.rglob("*")):
        key = str(path.relative_to(root))
        if path.is_symlink():
            found[key] = ("link", os.readlink(path))
        elif path.is_dir():
            found[key] = ("dir", path.stat().st_mode & 0o777)
        else:
            found[key] = ("file", path.stat().st_mode & 0o777, hashlib.sha256(path.read_bytes()).hexdigest())
    return found


@unittest.skipUnless(shutil.which("bash") and shutil.which("python3"), "bash or python3 missing")
class TestOrchestratorMigration(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.home = self.root / "home"
        stubs = self.root / "bin"
        stubs.mkdir()
        (stubs / "stub").write_text(STUB, encoding="utf-8")
        (stubs / "stub").chmod(0o755)
        for tool in ("docker", "claude", "systemctl"):
            (stubs / tool).symlink_to("stub")
        self.state = self.root / "stub.json"
        self.state.write_text(json.dumps({"calls": [], "images": [f"{OLD}:local"], "mcp": {OLD: "http://127.0.0.1:8737/mcp"}, "enabled": [f"{OLD}-runner.service"]}), encoding="utf-8")
        self.env = {**os.environ, "HOME": str(self.home), "PATH": f"{stubs}:{os.environ['PATH']}", "STUB_STATE": str(self.state), "AGENTS_COUNCIL_ROOT": str(self.root / "council"), "PKGMGR_REPO": str(self.root / "no-pkgmgr")}
        share, local, config = self.home / ".local" / "share", self.home / ".local" / "state", self.home / ".config"
        self.write(share / OLD / "compose.yml", f"name: {OLD}\n")
        self.write(share / OLD / ".env", "KVB_HUB_PORT=8737\n")
        self.write(local / OLD / "rules.json", '{"rule": 1}\n')
        self.write(local / f"{OLD}-approvals" / "runner.json", '{"used": {}}\n')
        self.write(config / OLD / "approvers.json", '{"credentials": []}\n', 0o600)
        (config / OLD).chmod(0o700)
        units = config / "systemd" / "user"
        self.write(units / f"{OLD}-runner.service", "[Unit]\n")
        (units / "default.target.wants").mkdir()
        (units / "default.target.wants" / f"{OLD}-runner.service").symlink_to(units / f"{OLD}-runner.service")
        self.other = {"matcher": "Bash", "hooks": [{"type": "command", "command": "other-hook"}]}
        legacy = {"matcher": "Bash", "hooks": [{"type": "command", "command": f"python3 {share}/{OLD}/client/permission_hook.py --port 8737"}]}
        self.write(self.home / ".claude" / "settings.json", json.dumps({"model": "x", "hooks": {"PermissionRequest": [self.other, legacy], "Stop": [self.other]}}), 0o640)
        for script in HOST_SCRIPTS:
            self.write(self.home / ".claude" / "skills" / script, (REPO_ROOT / "skills" / script).read_text(encoding="utf-8"))

    def write(self, path: Path, text: str, mode: int = 0o644) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        path.chmod(mode)

    def install(self) -> dict:
        done = subprocess.run(["bash", str(SCRIPT), "install"], env=self.env, capture_output=True, text=True, timeout=120, check=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(self.state.read_text(encoding="utf-8"))

    def test_install_migrates_every_trace_once(self):
        first = self.install()
        share, local, config = self.home / ".local" / "share", self.home / ".local" / "state", self.home / ".config"
        units = config / "systemd" / "user"
        for gone in (share / OLD, local / OLD, local / f"{OLD}-approvals", config / OLD, units / f"{OLD}-runner.service", units / "default.target.wants" / f"{OLD}-runner.service"):
            with self.subTest(gone=gone):
                self.assertFalse(gone.exists() or gone.is_symlink())
        self.assertEqual((local / NEW / "rules.json").read_text(encoding="utf-8"), '{"rule": 1}\n')
        self.assertEqual((local / f"{NEW}-approvals" / "runner.json").read_text(encoding="utf-8"), '{"used": {}}\n')
        self.assertEqual(((config / NEW).stat().st_mode & 0o777, (config / NEW / "approvers.json").stat().st_mode & 0o777), (0o700, 0o600))
        self.assertTrue((units / f"{NEW}-runner.service").is_file())
        self.assertTrue((units / f"{NEW}-sessions.timer").is_file())
        self.assertTrue((units / f"{NEW}-resources.timer").is_file())
        self.assertIn(f"KVB_ORCHESTRATOR_STATE={local / NEW}", (share / NEW / ".env").read_text(encoding="utf-8"))
        settings = self.home / ".claude" / "settings.json"
        data = json.loads(settings.read_text(encoding="utf-8"))
        hooks = data["hooks"]["PermissionRequest"]
        self.assertEqual((data["model"], data["hooks"]["Stop"], hooks[0], len(hooks)), ("x", [self.other], self.other, 2))
        self.assertIn(f"{share / NEW}/client/permission_hook.py", hooks[1]["hooks"][0]["command"])
        self.assertEqual(settings.stat().st_mode & 0o777, 0o640)
        self.assertIn(f"{OLD}/client", (self.home / ".claude" / f"settings.json.before-{NEW}-migration").read_text(encoding="utf-8"))
        self.assertEqual((first["images"], first["mcp"], first["enabled"]), ([f"{NEW}:local"], {NEW: "http://127.0.0.1:8737/mcp"}, [f"{NEW}-offices.path", f"{NEW}-resources.timer", f"{NEW}-runner.service", f"{NEW}-sessions.timer"]))
        self.assertIn(["docker", "compose", "--file", str(share / OLD / "compose.yml"), "down", "--remove-orphans"], first["calls"])

        before = snapshot(self.home)
        second = self.install()
        self.assertEqual(snapshot(self.home), before)
        self.assertEqual({key: second[key] for key in ("images", "mcp", "enabled")}, {key: first[key] for key in ("images", "mcp", "enabled")})
        legacy_calls = [call for call in second["calls"][len(first["calls"]) :] if any(OLD in arg for arg in call)]
        self.assertEqual(legacy_calls, [["docker", "image", "inspect", f"{OLD}:local"], ["claude", "mcp", "get", OLD]])

    def test_check_reports_the_sessions_timer_the_install_enabled_as_active(self):
        for tool in ("curl", "journalctl"):
            (self.root / "bin" / tool).symlink_to("stub")
        timer = f"{NEW}-sessions.timer"
        self.assertIn(timer, self.install()["enabled"])
        checked = subprocess.run(["bash", str(SCRIPT), "check"], env=self.env, capture_output=True, text=True, timeout=120, check=False)
        self.assertIn(f"ok    {timer} active\n", checked.stdout, checked.stderr)
        state = json.loads(self.state.read_text(encoding="utf-8"))
        self.state.write_text(json.dumps({**state, "enabled": [unit for unit in state["enabled"] if unit != timer]}), encoding="utf-8")
        stopped = subprocess.run(["bash", str(SCRIPT), "check"], env=self.env, capture_output=True, text=True, timeout=120, check=False)
        self.assertIn(f"todo  {timer} off: agent states wait for make orchestrator-install\n", stopped.stdout, stopped.stderr)
        self.assertNotIn(f"{timer} active", stopped.stdout)

    def test_the_offices_unit_waits_for_the_installed_skill_scripts_of_this_tree(self):
        self.install()
        stale = self.home / ".claude" / "skills" / HOST_SCRIPTS[2]
        stale.write_text(stale.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        done = subprocess.run(["bash", str(SCRIPT), "install"], env=self.env, capture_output=True, text=True, timeout=120, check=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("run 'make install' to enable", done.stderr)
        self.assertNotIn(f"{NEW}-offices.path", json.loads(self.state.read_text(encoding="utf-8"))["enabled"])

    def test_the_runner_unit_waits_for_the_installed_skill_scripts_of_this_tree(self):
        self.assertIn(f"{NEW}-runner.service", self.install()["enabled"])
        runner = f"{NEW}-runner.service"
        for script in HOST_SCRIPTS:
            with self.subTest(script=script):
                installed = self.home / ".claude" / "skills" / script
                kept = installed.read_text(encoding="utf-8")
                installed.write_text(kept + "\n", encoding="utf-8")
                state = json.loads(self.state.read_text(encoding="utf-8"))
                self.state.write_text(json.dumps({**state, "calls": [], "enabled": sorted({*state["enabled"], runner})}), encoding="utf-8")
                done = subprocess.run(["bash", str(SCRIPT), "install"], env=self.env, capture_output=True, text=True, timeout=120, check=False)
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertIn(f"run 'make install' to enable {runner}", done.stderr)
                after = json.loads(self.state.read_text(encoding="utf-8"))
                self.assertNotIn(runner, after["enabled"])
                self.assertNotIn(["systemctl", "--user", "restart", runner], after["calls"])
                refused = subprocess.run(["bash", str(SCRIPT), "runner"], env=self.env, capture_output=True, text=True, timeout=120, check=False)
                self.assertEqual(refused.returncode, 1, refused.stderr)
                self.assertNotIn(runner, json.loads(self.state.read_text(encoding="utf-8"))["enabled"])
                installed.write_text(kept, encoding="utf-8")

    def test_install_refreshes_and_restarts_only_an_enabled_runner_unit(self):
        units = self.home / ".config" / "systemd" / "user"
        (units / "default.target.wants" / f"{OLD}-runner.service").unlink()
        (units / f"{OLD}-runner.service").unlink()
        shipped = (REPO_ROOT / "orchestrator" / "systemd" / f"{NEW}-runner.service").read_text(encoding="utf-8")
        restart = ["systemctl", "--user", "restart", f"{NEW}-runner.service"]
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                self.write(units / f"{NEW}-runner.service", "[Unit]\nstale\n")
                state = json.loads(self.state.read_text(encoding="utf-8"))
                self.state.write_text(json.dumps({**state, "calls": [], "enabled": [f"{NEW}-runner.service"] if enabled else []}), encoding="utf-8")
                calls = self.install()["calls"]
                self.assertEqual((units / f"{NEW}-runner.service").read_text(encoding="utf-8") == shipped, enabled)
                self.assertEqual(restart in calls, enabled)

    def test_every_shipped_service_pins_the_path(self):
        units = sorted((REPO_ROOT / "orchestrator" / "systemd").glob("*.service"))
        self.assertIn(f"{NEW}-runner.service", [unit.name for unit in units])
        for unit in units:
            with self.subTest(unit=unit.name):
                self.assertIn("Environment=PATH=/usr/bin:/bin", unit.read_text(encoding="utf-8").splitlines())

    def test_install_ships_no_bytecode_from_the_tree(self):
        planted = REPO_ROOT / "orchestrator" / "client" / "__pycache__" / "planted.cpython-0.pyc"
        planted.parent.mkdir(exist_ok=True)
        planted.write_bytes(b"planted")
        self.addCleanup(planted.unlink, True)
        self.install()
        self.assertEqual(sorted((self.home / ".local" / "share" / NEW).rglob("__pycache__")), [])

    def test_old_names_live_only_in_the_migration(self):
        done = subprocess.run(["git", "grep", "-niE", "kvb[-_]hub", "--", ".", ":!docs/requirements", f":!{Path(__file__).relative_to(REPO_ROOT)}"], cwd=REPO_ROOT, capture_output=True, text=True, check=False)
        hits = sorted(line.split(":", 2)[0] + ":" + line.split(":", 2)[2].strip() for line in done.stdout.splitlines())
        self.assertEqual(hits, ['orchestrator/templates/page-state.js:let userViews = validViews(stored(STORE.views, stored("kvb-hub.views", [])));', 'scripts/orchestrator.sh:LEGACY="kvb-hub"'])


if __name__ == "__main__":
    unittest.main()
