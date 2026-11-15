"""Pin scripts/install.sh: the installed skill directories keep their inode, so a bind mount of them stays current."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL = REPO_ROOT / "scripts" / "install.sh"
ORGANIZE = REPO_ROOT / "skills" / "kvb-org-organize"
UNIT = REPO_ROOT / "skills" / "kvb-agent-optimize" / "systemd" / "kvb-code-graph.service"
NPX = "#!/bin/sh\nmkdir -p .agents/skills/locked\necho locked > .agents/skills/locked/SKILL.md\n"
BYTECODE = ("__pycache__/radio.cpython-312.pyc", "json.pyc", "legacy.pyo")
LIVE_MEMORY = {
    "warn": {"available": 15, "swap_free": 40, "psi_full": 5, "container_swap_gb": 4},
    "stop": {"available": 8, "swap_free": 10, "psi_full": 10, "container_swap_gb": 16},
}
SHIPPED = ORGANIZE / "config.default.json"
DEFAULT = json.loads(SHIPPED.read_text(encoding="utf-8"))
ROW_MEMORY = DEFAULT["memory_limits"]
HOME_TOOLS = ("bash", "cp", "dirname", "find", "install", "ln", "mkdir", "python3", "rm")
COUNCIL_PARTS = ("scripts/orchestrator.sh", "skills/kvb-org-organize/scripts/councilroot.py", "skills/kvb-org-organize/scripts/nofollow.py")
AGENT_ROOTS = {"sandbox": {"filesystem": {"allowWrite": ["~/.local/state/agents-shared", "~/.local/state/agents-release/**"]}}}
CGROUP_KILL = """
case "$*" in *try-restart*kvb-code-graph*)
  unit=$(while IFS= read -r line; do echo "$line"; done < "$HOME/.config/systemd/user/kvb-code-graph.service")
  case "$unit" in *KillMode=process*) ;; *) echo "cgroup killed the daemon" >> "{daemon}" ;; esac
esac"""
HOME_UNITS = (
    "kvb-dream/systemd/kvb-dream-notify.service",
    "kvb-dream/systemd/kvb-dream-notify.timer",
    "kvb-org-queue-cleanup/systemd/kvb-org-queue-cleanup.service",
    "kvb-org-queue-cleanup/systemd/kvb-org-queue-cleanup.timer",
    "kvb-org-queue-cleanup/systemd/kvb-org-queue-cleanup.path",
)


def read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines() if path.is_file() else []


class TestInstall(unittest.TestCase):
    def install(self, root: Path, target: Path, npx: str = NPX, planted: tuple[str, ...] = (), config: Path | None = None,
                code: int = 0, stubs_extra: tuple[tuple[str, str], ...] = ()) -> subprocess.CompletedProcess:
        repo, stubs = root / "repo", root / "bin"
        (repo / "scripts").mkdir(parents=True)
        shutil.copy(INSTALL, repo / "scripts" / "install.sh")
        if config is not None:
            shutil.copytree(ORGANIZE, repo / "skills" / ORGANIZE.name, ignore=shutil.ignore_patterns("__pycache__"))
        (repo / "scripts" / "enable-plugins.js").write_text("", encoding="utf-8")
        (repo / "skills" / "own").mkdir(parents=True)
        (repo / "skills" / "own" / "SKILL.md").write_text("own", encoding="utf-8")
        for name in planted:
            (repo / name).parent.mkdir(parents=True, exist_ok=True)
            (repo / name).write_bytes(b"planted")
        stubs.mkdir()
        for name, text in (("npx", npx), *stubs_extra):
            (stubs / name).write_text(text, encoding="utf-8")
            (stubs / name).chmod(0o755)
        env = {**os.environ, "PATH": f"{stubs}:/usr/bin:/bin", "TARGET": str(target), "HOME": str(root / "home")}
        if config is not None:
            env |= {"AGENTS_COUNCIL_CONFIG": str(config), "AGENTS_COUNCIL_ROOT": str(root / "council")}
        done = subprocess.run(["bash", str(repo / "scripts" / "install.sh")], env=env, capture_output=True, text=True, check=False)
        self.assertEqual(done.returncode, code, done.stderr)
        return done

    def test_the_install_stops_before_any_copy_while_the_live_config_lacks_a_memory_bound_the_new_code_needs(self):
        for limits, code in ((LIVE_MEMORY, 2), (ROW_MEMORY, 0)):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                target = root / "target"
                target.mkdir()
                config = root / "config.json"
                config.write_text(json.dumps({**DEFAULT, "memory_limits": limits}), encoding="utf-8")
                before = config.stat()
                done = self.install(root, target, config=config, code=code)
                after = config.stat()
                self.assertEqual((after.st_ino, after.st_mtime_ns, after.st_mode), (before.st_ino, before.st_mtime_ns, before.st_mode))
                installed = sorted(path.name for path in target.iterdir())
                if code:
                    self.assertIn(
                        "lacks memory_limits.warn.psi_some, memory_limits.warn.swap_out_mb_min, memory_limits.stop.swap_out_mb_min;",
                        done.stderr,
                    )
                    self.assertEqual(installed, [])
                    self.assertFalse((root / "repo" / ".agents").exists())
                else:
                    self.assertEqual(installed, [".agents", ".claude"])
                self.assertEqual(json.loads(config.read_text(encoding="utf-8")), {**DEFAULT, "memory_limits": limits})

    def test_an_install_without_a_config_writes_the_shipped_default_as_the_initial_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "target"
            target.mkdir()
            config = root / "council-config" / "config.json"
            self.install(root, target, config=config)
            self.assertEqual(config.read_bytes(), SHIPPED.read_bytes())
            self.assertEqual(config.stat().st_mode & 0o777, 0o600)
            self.assertEqual(config.parent.stat().st_mode & 0o777, 0o700)

    def test_a_config_written_while_the_install_creates_its_folder_survives(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "target"
            target.mkdir()
            config = root / "council-config" / "config.json"
            racer = f"#!/bin/sh\nmkdir -p {config.parent}\necho '{{\"mine\": true}}' > {config}\nexec /usr/bin/install \"$@\"\n"
            done = self.install(root, target, config=config, stubs_extra=(("install", racer),))
            self.assertEqual(json.loads(config.read_text(encoding="utf-8")), {"mine": True})
            self.assertIn(str(config), done.stderr)

    def home_install(self, root: Path, binary: bool, config: bool = True, fail_now: bool = False) -> tuple[subprocess.CompletedProcess, list[str], list[str]]:
        repo, stubs, home = root / "repo", root / "bin", root / "home"
        (repo / "scripts").mkdir(parents=True)
        shutil.copy(INSTALL, repo / "scripts" / "install.sh")
        for part in COUNCIL_PARTS:
            (repo / part).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(REPO_ROOT / part, repo / part)
        for unit in HOME_UNITS:
            (repo / "skills" / unit).parent.mkdir(parents=True, exist_ok=True)
            (repo / "skills" / unit).write_text("[Unit]\n", encoding="utf-8")
        (repo / "skills" / UNIT.relative_to(REPO_ROOT / "skills")).parent.mkdir(parents=True)
        shutil.copy(UNIT, repo / "skills" / UNIT.relative_to(REPO_ROOT / "skills"))
        stubs.mkdir()
        for tool in HOME_TOOLS:
            (stubs / tool).symlink_to(shutil.which(tool))
        log, cbm = root / "systemctl.log", root / "cbm.log"
        now = '\ncase "$*" in *--now*kvb-code-graph*) exit 1 ;; esac' if fail_now else ""
        for name, body in (
            ("npx", NPX),
            ("systemctl", f'#!/bin/sh\necho "$*" >> "{log}"{now}{CGROUP_KILL.format(daemon=root / "daemon.log")}\nexit 0\n'),
            ("curl", "#!/bin/sh\nexit 22\n"),
            ("codebase-memory-mcp", f'#!/bin/sh\necho "$*" >> "{cbm}"\nexit 0\n'),
        ):
            (stubs / name).write_text(body, encoding="utf-8")
            (stubs / name).chmod(0o755)
        home.mkdir()
        (home / ".claude").mkdir()
        (home / ".claude" / "settings.json").write_text(json.dumps(AGENT_ROOTS), encoding="utf-8")
        if binary:
            (home / ".local" / "bin").mkdir(parents=True)
            shutil.copy(stubs / "codebase-memory-mcp", home / ".local" / "bin" / "codebase-memory-mcp")
        if config:
            (home / ".config" / "kvb-code-graph").mkdir(parents=True)
            (home / ".config" / "kvb-code-graph" / "config.json").write_text(
                '{"queue_file_threshold": 2000, "queue_task": "work/code-graph-index"}\n', encoding="utf-8"
            )
        env = {"PATH": str(stubs), "TARGET": str(home), "HOME": str(home), "AGENTS_COUNCIL_LEGACY": str(root / "legacy")}
        done = subprocess.run(["/bin/bash", str(repo / "scripts" / "install.sh")], env=env, capture_output=True, text=True, check=False)
        return done, read_lines(log), read_lines(cbm)

    def test_the_home_install_enables_the_code_graph_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            done, calls, _ = self.home_install(root, binary=True)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertIn("--user enable --now kvb-code-graph.service", calls)
            installed = root / "home" / ".config" / "systemd" / "user" / "kvb-code-graph.service"
            self.assertEqual(installed.read_text(encoding="utf-8"), UNIT.read_text(encoding="utf-8"))
            self.assertNotIn("kvb-code-graph: no config", done.stderr)

    def test_the_home_install_turns_the_daemon_auto_index_off(self):
        with tempfile.TemporaryDirectory() as tmp:
            done, _, cbm = self.home_install(Path(tmp), binary=True)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertIn("config set auto_index false", cbm)
            self.assertNotIn("config set auto_index true", cbm)

    def test_the_home_install_without_config_says_so_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            done, _, _ = self.home_install(Path(tmp), binary=True, config=False)
            self.assertEqual(done.returncode, 0, done.stderr)
            notes = [line for line in done.stderr.splitlines() if line.startswith("skills: kvb-code-graph: no config")]
            self.assertEqual(len(notes), 1, done.stderr)
            self.assertIn("queue_file_threshold", notes[0])
            self.assertIn("queue_task", notes[0])

    def test_a_reinstall_restarts_a_running_supervisor_on_the_new_unit(self):
        with tempfile.TemporaryDirectory() as tmp:
            done, calls, _ = self.home_install(Path(tmp), binary=True)
            self.assertEqual(done.returncode, 0, done.stderr)
            reload = max(number for number, call in enumerate(calls) if call == "--user daemon-reload")
            self.assertIn("--user try-restart kvb-code-graph.service", calls[reload:])

    def test_a_restart_of_the_supervisor_leaves_its_daemon_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            done, _, _ = self.home_install(Path(tmp), binary=True)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(read_lines(Path(tmp) / "daemon.log"), [])
            self.assertIn("KillMode=process", UNIT.read_text(encoding="utf-8").splitlines())

    def test_a_unit_that_cannot_start_now_takes_effect_at_next_login(self):
        with tempfile.TemporaryDirectory() as tmp:
            done, calls, _ = self.home_install(Path(tmp), binary=True, fail_now=True)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertIn("--user enable kvb-code-graph.service", calls)
            self.assertIn("takes effect at next login", done.stdout + done.stderr)

    def test_the_home_install_skips_the_service_without_the_binary(self):
        with tempfile.TemporaryDirectory() as tmp:
            done, calls, _ = self.home_install(Path(tmp), binary=False)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertFalse([call for call in calls if "kvb-code-graph" in call])
            self.assertIn("graphs keep their watch only while a session runs", done.stderr)

    def test_reinstall_empties_the_skill_directories_in_place(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "target"
            installed = [target / ".agents" / "skills", target / ".claude" / "skills"]
            for folder in installed:
                (folder / "stale").mkdir(parents=True)
            before = [folder.stat().st_ino for folder in installed]
            self.install(root, target)
            self.assertEqual([folder.stat().st_ino for folder in installed], before)
            for folder in installed:
                self.assertEqual(sorted(path.name for path in folder.iterdir()), ["locked", "own"])

    def test_a_project_install_links_every_skill_the_global_install_holds(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "target"
            target.mkdir()
            linked = (".agents/skills/locked", ".claude/skills/own")
            for folder in linked:
                (root / "home" / folder).mkdir(parents=True)
            self.install(root, target)
            for folder in (".agents/skills", ".claude/skills"):
                installed = {path.name: path.readlink() if path.is_symlink() else None for path in (target / folder).iterdir()}
                expected = {name: root / "home" / folder / name if f"{folder}/{name}" in linked else None for name in ("locked", "own")}
                self.assertEqual(installed, expected)

    def test_no_python_bytecode_reaches_the_installed_skills(self):
        locked = "".join(f"echo planted > .agents/skills/locked/scripts/{name}\n" for name in BYTECODE)
        npx = f"{NPX}mkdir -p .agents/skills/locked/scripts/__pycache__\n{locked}"
        for linked in (False, True):
            with self.subTest(linked=linked), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                target = root / "target"
                (target / ".agents" / "skills").mkdir(parents=True)
                if linked:
                    (target / ".claude").mkdir()
                    (target / ".claude" / "skills").symlink_to(Path("..") / ".agents" / "skills")
                self.install(root, target, npx, (*(f"skills/own/scripts/{name}" for name in BYTECODE), "skills/own/scripts/radio.py"))
                for folder in (".agents/skills", ".claude/skills"):
                    installed = target / folder
                    with self.subTest(folder=folder):
                        bytecode = [str(path.relative_to(installed)) for path in sorted(installed.rglob("*")) if path.name == "__pycache__" or path.suffix in (".pyc", ".pyo")]
                        self.assertEqual(bytecode, [])
                        self.assertTrue((installed / "own" / "scripts" / "radio.py").is_file())
                        self.assertTrue((installed / "locked" / "SKILL.md").is_file())


if __name__ == "__main__":
    unittest.main()
