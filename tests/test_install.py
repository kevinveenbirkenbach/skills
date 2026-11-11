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


class TestInstall(unittest.TestCase):
    def test_reinstall_empties_the_skill_directories_in_place(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, target, stubs = root / "repo", root / "target", root / "bin"
            (repo / "scripts").mkdir(parents=True)
            shutil.copy(INSTALL, repo / "scripts" / "install.sh")
            (repo / "scripts" / "enable-plugins.js").write_text("", encoding="utf-8")
            (repo / "skills" / "own").mkdir(parents=True)
            (repo / "skills" / "own" / "SKILL.md").write_text("own", encoding="utf-8")
            stubs.mkdir()
            (stubs / "npx").write_text(NPX, encoding="utf-8")
            (stubs / "npx").chmod(0o755)
            installed = [target / ".agents" / "skills", target / ".claude" / "skills"]
            for folder in installed:
                (folder / "stale").mkdir(parents=True)
            before = [folder.stat().st_ino for folder in installed]
            env = {**os.environ, "PATH": f"{stubs}:/usr/bin:/bin", "TARGET": str(target)}
            done = subprocess.run(["bash", str(repo / "scripts" / "install.sh")], env=env, capture_output=True, text=True, check=False)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual([folder.stat().st_ino for folder in installed], before)
            for folder in installed:
                self.assertEqual(sorted(path.name for path in folder.iterdir()), ["locked", "own"])


if __name__ == "__main__":
    unittest.main()
