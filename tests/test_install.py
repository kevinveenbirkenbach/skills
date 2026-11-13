"""Pin scripts/install.sh: the installed skill directories keep their inode, so a bind mount of them stays current."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

INSTALL = Path(__file__).resolve().parents[1] / "scripts" / "install.sh"
NPX = "#!/bin/sh\nmkdir -p .agents/skills/locked\necho locked > .agents/skills/locked/SKILL.md\n"
BYTECODE = ("__pycache__/radio.cpython-312.pyc", "json.pyc", "legacy.pyo")


class TestInstall(unittest.TestCase):
    def install(self, root: Path, target: Path, npx: str = NPX, planted: tuple[str, ...] = ()) -> None:
        repo, stubs = root / "repo", root / "bin"
        (repo / "scripts").mkdir(parents=True)
        shutil.copy(INSTALL, repo / "scripts" / "install.sh")
        (repo / "scripts" / "enable-plugins.js").write_text("", encoding="utf-8")
        (repo / "skills" / "own").mkdir(parents=True)
        (repo / "skills" / "own" / "SKILL.md").write_text("own", encoding="utf-8")
        for name in planted:
            (repo / name).parent.mkdir(parents=True, exist_ok=True)
            (repo / name).write_bytes(b"planted")
        stubs.mkdir()
        (stubs / "npx").write_text(npx, encoding="utf-8")
        (stubs / "npx").chmod(0o755)
        env = {**os.environ, "PATH": f"{stubs}:/usr/bin:/bin", "TARGET": str(target), "HOME": str(root / "home")}
        done = subprocess.run(["bash", str(repo / "scripts" / "install.sh")], env=env, capture_output=True, text=True, check=False)
        self.assertEqual(done.returncode, 0, done.stderr)

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
