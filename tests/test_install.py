"""Pin scripts/install.sh: the installed skill directories keep their inode, so a bind mount of them stays current."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

INSTALL = Path(__file__).resolve().parents[1] / "scripts" / "install.sh"
ORGANIZE = Path(__file__).resolve().parents[1] / "skills" / "kvb-org-organize"
NPX = "#!/bin/sh\nmkdir -p .agents/skills/locked\necho locked > .agents/skills/locked/SKILL.md\n"
BYTECODE = ("__pycache__/radio.cpython-312.pyc", "json.pyc", "legacy.pyo")
LIVE_MEMORY = {
    "warn": {"available": 15, "swap_free": 40, "psi_full": 5, "container_swap_gb": 4},
    "stop": {"available": 8, "swap_free": 10, "psi_full": 10, "container_swap_gb": 16},
}
SHIPPED = ORGANIZE / "config.default.json"
DEFAULT = json.loads(SHIPPED.read_text(encoding="utf-8"))
ROW_MEMORY = DEFAULT["memory_limits"]


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
