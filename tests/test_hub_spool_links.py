from __future__ import annotations

import contextlib
import errno
import hashlib
import importlib.util
import io
import json
import os
import shutil
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hub_support import HUB, ORIGIN, verifier

JOB_ID = "0123456789abcdef"
JOB = f"{JOB_ID}.json"
OTHER_ID = "fedcba9876543210"
ME = os.getuid()


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"kvb_orchestrator_{name}_spool_links", HUB / "client" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


offices = load("offices")
cleanup = load("cleanup")


def digest(root: Path) -> list[tuple[str, str, str]]:
    found = []
    for folder, dirs, files in os.walk(root):
        for name in dirs + files:
            path = Path(folder) / name
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                content = f"link {os.readlink(path)}"
            elif stat.S_ISREG(mode):
                content = hashlib.sha256(path.read_bytes()).hexdigest()
            else:
                content = "dir"
            found.append((str(path.relative_to(root)), oct(mode), content))
    return sorted(found)


def root_owned(*folders: Path, mine: bool = False):
    """Args:
        folders: the directories os.fstat reports as root's that no one else
            can write.
        mine: report every inode of this uid the same way.
    """
    inodes = {(folder.stat().st_dev, folder.stat().st_ino) for folder in folders}
    real = os.fstat

    def fstat(fd: int) -> os.stat_result:
        found = real(fd)
        if (found.st_dev, found.st_ino) not in inodes and not (mine and found.st_uid == ME):
            return found
        fields = list(found[:10])
        fields[0] &= ~0o022
        fields[4] = 0
        return os.stat_result(fields)

    return mock.patch("os.fstat", side_effect=fstat)


class SpoolLinks:
    module = None

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        self.spool = base / "state" / "spool"
        self.jobs, self.results = self.spool / "jobs", self.spool / "results"
        self.victim = base / "victim"
        for folder in (self.jobs, self.results, self.victim / "jobs" / "sub", self.victim / "results"):
            folder.mkdir(mode=0o700, parents=True)
        for path in (self.victim / "jobs" / JOB, self.victim / "jobs" / "keep.txt", self.victim / "jobs" / "sub" / "inner.txt", self.victim / "results" / JOB):
            self.plant_job(path)
        self.before = digest(self.victim)
        trust = verifier.Trust(approvers=base / "approvers.json", replay=base / "replay.json", origin=ORIGIN)
        self.runner = self.unit(trust, base)

    def plant_job(self, path: Path | None = None) -> None:
        (path or self.jobs / JOB).write_text(json.dumps({"v": 1, "id": JOB_ID, "items": []}), encoding="utf-8")

    def cycle(self) -> tuple[int, list[str]]:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            handled = self.module.cycle(self.jobs, self.results, self.runner)
        return handled, stderr.getvalue().splitlines()

    def assert_refused(self) -> None:
        handled, lines = self.cycle()
        self.assertEqual((handled, len(lines)), (0, 1), lines)
        self.assertIn("refused, nothing done", lines[0])
        self.assertEqual(digest(self.victim), self.before)

    def test_a_linked_jobs_dir_is_refused(self):
        self.jobs.rmdir()
        self.jobs.symlink_to(self.victim / "jobs")
        self.assert_refused()
        self.assertEqual(list(self.results.iterdir()), [])

    def test_a_linked_results_dir_is_refused(self):
        self.results.rmdir()
        self.results.symlink_to(self.victim / "results")
        self.plant_job()
        self.assert_refused()
        self.assertEqual([path.name for path in self.jobs.iterdir()], [JOB])

    def test_a_linked_spool_dir_above_both_is_refused(self):
        shutil.rmtree(self.spool)
        self.spool.symlink_to(self.victim)
        self.assert_refused()

    def test_a_jobs_dir_others_can_write_is_refused(self):
        self.plant_job()
        self.jobs.chmod(0o770)
        self.assert_refused()
        self.assertEqual([path.name for path in self.jobs.iterdir()], [JOB])

    def test_a_linked_job_file_is_removed_as_the_link(self):
        (self.jobs / JOB).symlink_to(self.victim / "jobs" / JOB)
        (self.jobs / "keep.txt").symlink_to(self.victim / "jobs" / "keep.txt")
        self.cycle()
        self.assertEqual(list(self.jobs.iterdir()), [])
        self.assertEqual(digest(self.victim), self.before)
        self.assertIn("unreadable job", json.loads((self.results / JOB).read_text(encoding="utf-8"))["error"])

    def test_a_subdir_that_is_or_holds_a_link_is_removed_without_following(self):
        (self.jobs / "linked").symlink_to(self.victim / "jobs")
        held = self.jobs / "sub" / "deeper"
        held.mkdir(parents=True)
        (self.jobs / "sub" / "dir").symlink_to(self.victim / "jobs")
        (self.jobs / "sub" / "file").symlink_to(self.victim / "jobs" / "keep.txt")
        (held / "victim").symlink_to(self.victim)
        self.cycle()
        self.assertEqual(list(self.jobs.iterdir()), [])
        self.assertEqual(digest(self.victim), self.before)

    def test_spool_dirs_swapped_for_links_mid_cycle_change_nothing_outside(self):
        self.plant_job()
        (self.jobs / "keep.txt").write_text("spool", encoding="utf-8")
        (self.jobs / "sub").mkdir()
        moved = self.spool / "moved"
        real = self.runner.job

        def swap(*args):
            if not moved.exists():
                moved.mkdir()
                for name in ("jobs", "results"):
                    (self.spool / name).rename(moved / name)
                    (self.spool / name).symlink_to(self.victim / name)
            return real(*args)

        with mock.patch.object(self.runner, "job", side_effect=swap):
            self.assertEqual(self.cycle()[0], 1)
        self.assertEqual(digest(self.victim), self.before)
        self.assertEqual((list((moved / "jobs").iterdir()), [path.name for path in (moved / "results").iterdir()]), ([], [JOB]))

    def test_a_subdir_swapped_for_a_link_before_its_removal_is_kept(self):
        (self.jobs / "sub").mkdir()
        (self.jobs / "sub" / "inner.txt").write_text("spool", encoding="utf-8")
        real = shutil.rmtree

        def swap(path, *args, **kwargs):
            if not (self.spool / "moved").exists():
                (self.jobs / "sub").rename(self.spool / "moved")
                (self.jobs / "sub").symlink_to(self.victim / "jobs")
            return real(path, *args, **kwargs)

        with mock.patch("shutil.rmtree", side_effect=swap):
            handled, lines = self.cycle()
        self.assertEqual(digest(self.victim), self.before)
        self.assertEqual((handled, len(lines), (self.jobs / "sub").is_symlink()), (0, 1, True), lines)

    @unittest.skipIf(ME == 0, "a unit running as root follows no link")
    def test_a_link_in_a_dir_only_root_can_write_is_followed_by_a_unit_of_another_uid(self):
        real = self.spool.parent / "real"
        self.spool.rename(real)
        self.spool.symlink_to(real)
        self.plant_job()
        self.assert_refused()
        with root_owned(self.spool.parent, *self.spool.parent.parents):
            self.assertEqual(self.cycle(), (1, []))
        self.assertEqual(([path.name for path in (real / "jobs").iterdir()], [path.name for path in (real / "results").iterdir()]), ([], [JOB]))

    def test_a_unit_running_as_root_follows_no_link(self):
        self.jobs.rmdir()
        self.jobs.symlink_to(self.victim / "jobs")
        with root_owned(self.spool, *self.spool.parents, mine=True), mock.patch("os.getuid", return_value=0), mock.patch("os.geteuid", return_value=0):
            self.assert_refused()

    def test_a_link_in_a_root_dir_below_a_dir_of_another_uid_is_not_followed(self):
        self.jobs.rmdir()
        self.jobs.symlink_to(self.victim / "jobs")
        with root_owned(self.spool, *self.spool.parent.parent.parents):
            self.assert_refused()

    def plant_other(self) -> None:
        (self.jobs / f"{OTHER_ID}.json").write_text(json.dumps({"v": 1, "id": OTHER_ID, "items": []}), encoding="utf-8")

    def test_a_result_that_cannot_be_written_keeps_its_job_beside_the_results(self):
        self.plant_job()
        self.plant_other()
        (self.results / JOB).mkdir()
        (self.results / JOB / "planted").write_text("hub", encoding="utf-8")
        handled, lines = self.cycle()
        self.assertEqual((handled, len(lines)), (1, 1), lines)
        self.assertIn(f"no result for {JOB}", lines[0])
        self.assertIn("malformed job", lines[0])
        self.assertEqual(list(self.jobs.iterdir()), [])
        self.assertEqual(sorted(path.name for path in self.results.iterdir()), [f".{JOB_ID}.unreported", JOB, f"{OTHER_ID}.json"])
        self.assertEqual([path.name for path in (self.results / JOB).iterdir()], ["planted"])
        self.assertEqual(json.loads((self.results / f".{JOB_ID}.unreported").read_text(encoding="utf-8"))["id"], JOB_ID)

    def test_a_full_disk_keeps_every_job_unreported_and_runs_none_again(self):
        self.plant_job()
        self.plant_other()
        with mock.patch("os.fsync", side_effect=OSError(errno.ENOSPC, "No space left on device")):
            handled, lines = self.cycle()
        self.assertEqual((handled, len(lines)), (0, 2), lines)
        self.assertEqual(sorted(path.name for path in self.results.iterdir()), [f".{JOB_ID}.unreported", f".{OTHER_ID}.unreported"])
        self.assertEqual(self.cycle(), (0, []))
        self.assertEqual(len(list(self.results.iterdir())), 2)

    def test_a_job_that_can_be_neither_kept_nor_removed_leaves_the_cycle_going(self):
        self.plant_job()
        self.plant_other()
        for name in (JOB, f".{JOB_ID}.unreported"):
            (self.results / name).mkdir()
            (self.results / name / "planted").write_text("hub", encoding="utf-8")
        real = verifier.remove_at

        def stuck(folder, name):
            if name == JOB:
                raise PermissionError(errno.EACCES, "Permission denied")
            return real(folder, name)

        with mock.patch.object(verifier, "remove_at", side_effect=stuck):
            handled, lines = self.cycle()
        self.assertEqual((handled, len(lines)), (1, 2), lines)
        self.assertIn(f"kept {JOB}", lines[1])
        self.assertTrue((self.results / f"{OTHER_ID}.json").is_file())


class TestOfficesSpoolLinks(SpoolLinks, unittest.TestCase):
    module = offices

    def unit(self, trust: verifier.Trust, base: Path):
        return offices.Offices(trust, base / "council", base / "council.py", base / "home")


class TestCleanupSpoolLinks(SpoolLinks, unittest.TestCase):
    module = cleanup

    def unit(self, trust: verifier.Trust, base: Path):
        return cleanup.Cleanup(trust, base / "tree.json", base / "pkgmgr")


if __name__ == "__main__":
    unittest.main()
