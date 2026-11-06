from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOKPATH = REPO_ROOT / "skills" / "kvb-org-organize" / "scripts" / "hookpath.py"


def _load():
    spec = importlib.util.spec_from_file_location("hookpath_under_test", HOOKPATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipIf(os.getuid() == 0, "every directory root creates is root-owned")
class TestHookpath(unittest.TestCase):
    def test_only_sealed_directories_survive_as_real_paths(self):
        hookpath = _load()
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            own = base / "bin"
            own.mkdir()
            link = base / "system"
            link.symlink_to("/usr/bin")
            path = os.pathsep.join([str(own), str(link), "", "/tmp", str(base / "missing"), "/usr/bin", "/bin"])
            expected = list(dict.fromkeys(str(Path(d).resolve()) for d in ("/usr/bin", "/bin")))
            self.assertEqual(hookpath.trusted(path).split(os.pathsep), expected)
            self.assertEqual(hookpath.trusted(str(own)), "")


if __name__ == "__main__":
    unittest.main()
