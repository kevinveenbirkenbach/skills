from __future__ import annotations

import importlib.util
import os
import signal
import stat
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
NOFOLLOW = REPO_ROOT / "skills" / "kvb-org-organize" / "scripts" / "nofollow.py"


def _load():
    spec = importlib.util.spec_from_file_location("nofollow_under_test", NOFOLLOW)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestNofollow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.nofollow = _load()

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.root = self.base / "council"
        self.root.mkdir(mode=0o700)
        self.victim = self.base / "victim"
        self.victim.write_text("keep", encoding="utf-8")
        self.victims = self.base / "victims"
        self.victims.mkdir()

    def writes(self, root: Path) -> dict:
        nofollow = self.nofollow

        def lock(path: Path) -> None:
            with nofollow.locked(root, path, 0o600, None):
                pass

        return {
            "replace": lambda path: nofollow.replace(root, path, "x", 0o600),
            "append": lambda path: nofollow.append(root, path, "x", 0o600),
            "lock": lock,
            "read": lambda path: nofollow.read_text(root, path),
            "create": lambda path: os.close(
                nofollow.open_below(root, path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            ),
        }

    def test_writes_land_below_the_root_in_private_directories(self):
        target = self.root / "a" / "b" / "f"
        self.nofollow.replace(self.root, target, "one", 0o600)
        self.nofollow.replace(self.root, target, "two", 0o600)
        self.nofollow.append(self.root, target, "+", 0o600)
        self.assertEqual(target.read_text(encoding="utf-8"), "two+")
        self.assertEqual(sorted(os.listdir(target.parent)), ["f"])
        self.assertEqual(stat.S_IMODE((self.root / "a").stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
        with self.nofollow.locked(self.root, self.root / "c" / "lock", 0o600, None) as handle:
            handle.write("held")
        self.assertEqual((self.root / "c" / "lock").read_text(encoding="utf-8"), "held")
        with self.nofollow.locked(self.root, self.root / "c" / "lock", 0o600, 1):
            pass
        self.assertEqual((self.root / "c" / "lock").read_text(encoding="utf-8"), "held")
        self.nofollow.unlink(self.root, target)
        self.assertFalse(target.exists())

    def test_replace_swaps_a_planted_link_and_keeps_its_target(self):
        dangling = self.base / "created"
        for target in (self.victim, dangling):
            with self.subTest(target=target.name):
                link = self.root / "f"
                link.symlink_to(target)
                self.nofollow.replace(self.root, link, "x", 0o600)
                self.assertFalse(link.is_symlink())
                self.assertEqual(link.read_text(encoding="utf-8"), "x")
                link.unlink()
        self.assertEqual(self.victim.read_text(encoding="utf-8"), "keep")
        self.assertFalse(dangling.exists())

    def test_a_symlinked_name_is_refused_and_its_target_kept(self):
        dangling = self.base / "created"
        followers = {name: write for name, write in self.writes(self.root).items() if name != "replace"}
        for name, write in followers.items():
            with self.subTest(write=name):
                link = self.root / name
                link.symlink_to(self.victim)
                with self.assertRaises(OSError):
                    write(link)
                self.assertEqual(self.victim.read_text(encoding="utf-8"), "keep")
                link.unlink()
                link.symlink_to(dangling)
                with self.assertRaises(OSError):
                    write(link)
                self.assertFalse(dangling.exists())

    def test_a_hard_linked_name_is_refused_and_its_target_kept(self):
        followers = {name: write for name, write in self.writes(self.root).items() if name not in ("replace", "create")}
        for name, write in followers.items():
            with self.subTest(write=name):
                link = self.root / name
                os.link(self.victim, link)
                with self.assertRaises(OSError):
                    write(link)
                self.assertEqual(self.victim.read_text(encoding="utf-8"), "keep")
                link.unlink()

    def test_a_symlinked_directory_is_refused_and_nothing_lands_in_its_target(self):
        (self.root / "d").symlink_to(self.victims)
        (self.victims / "f").write_text("keep", encoding="utf-8")
        for name, write in self.writes(self.root).items():
            with self.subTest(write=name):
                with self.assertRaises(OSError):
                    write(self.root / "d" / name)
                with self.assertRaises(OSError):
                    write(self.root / "d" / "deeper" / name)
        with self.assertRaises(OSError):
            self.nofollow.unlink(self.root, self.root / "d" / "f")
        self.assertEqual(os.listdir(self.victims), ["f"])
        self.assertEqual((self.victims / "f").read_text(encoding="utf-8"), "keep")

    def test_a_symlinked_root_is_refused(self):
        link = self.base / "link"
        link.symlink_to(self.victims)
        for name, write in self.writes(link).items():
            with self.subTest(write=name), self.assertRaises(OSError):
                write(link / name)
        self.assertEqual(os.listdir(self.victims), [])

    def test_a_path_outside_the_root_is_refused(self):
        escaped = self.base / "escaped"
        for path in (self.root / ".." / "escaped", self.root / "a" / ".." / ".." / "escaped", escaped, self.root):
            for name, write in self.writes(self.root).items():
                with self.subTest(path=str(path), write=name), self.assertRaises(OSError):
                    write(path)
        self.assertFalse(escaped.exists())
        self.assertFalse((self.root / "a").exists())

    def test_a_fifo_at_a_name_is_refused_without_blocking(self):
        def blocked(*_: object) -> None:
            raise AssertionError("blocked on a FIFO")

        previous = signal.signal(signal.SIGALRM, blocked)
        self.addCleanup(signal.signal, signal.SIGALRM, previous)
        self.addCleanup(signal.alarm, 0)
        followers = {name: access for name, access in self.writes(self.root).items() if name != "replace"}
        for name, access in followers.items():
            with self.subTest(access=name):
                fifo = self.root / name
                os.mkfifo(fifo, 0o600)
                signal.alarm(5)
                with self.assertRaises(OSError):
                    access(fifo)
                signal.alarm(0)

    def test_a_held_lock_times_out_instead_of_hanging(self):
        path = self.root / "lock"
        with self.nofollow.locked(self.root, path, 0o600, None):
            start = time.monotonic()
            with self.assertRaises(TimeoutError), self.nofollow.locked(self.root, path, 0o600, 0.2):
                pass
            self.assertLess(time.monotonic() - start, 5)

    def test_read_refuses_a_file_over_the_limit_and_replaces_undecodable_bytes(self):
        self.addCleanup(setattr, self.nofollow, "READ_LIMIT", self.nofollow.READ_LIMIT)
        self.nofollow.READ_LIMIT = 4
        (self.root / "f").write_bytes(b"\xff\n")
        self.assertEqual(self.nofollow.read_text(self.root, self.root / "f"), "�\n")
        (self.root / "f").write_bytes(b"12345")
        with self.assertRaises(OSError):
            self.nofollow.read_text(self.root, self.root / "f")

    def test_unlink_removes_a_planted_link_and_keeps_its_target(self):
        (self.root / "l").symlink_to(self.victim)
        self.nofollow.unlink(self.root, self.root / "l")
        self.assertFalse((self.root / "l").is_symlink())
        self.assertEqual(self.victim.read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()
