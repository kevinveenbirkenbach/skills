from __future__ import annotations

import hashlib
import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "orchestrator" / "client"
REMINDER = ROOT / "skills" / "kvb-dream" / "hooks" / "reminder.sh"
ORCHESTRATOR = ROOT / "scripts" / "orchestrator.sh"
sys.path[:0] = [str(CLIENT)]
staged_diff = importlib.import_module("staged_diff")
permission_hook = importlib.import_module("permission_hook")
passkey = importlib.import_module("passkey")
sandbox_paths = importlib.import_module("sandbox_paths")
GIT_ENV = {
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
}
ALLOW = {"behavior": "allow"}


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, env={**os.environ, **GIT_ENV}, check=True, capture_output=True, text=True).stdout


def probe(path: Path, marker: Path, tail: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\n: > '{marker}'\n{tail}\n", encoding="utf-8")
    path.chmod(0o755)
    return path


class Scratch(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(os.path.realpath(tmp.name))
        self.marker = self.root / "planted-code-ran"


class Isolated(Scratch):
    def setUp(self):
        super().setUp()
        for patch in (
            mock.patch.object(staged_diff, "CACHE", self.root / "cache" / "secret-rules.json"),
            mock.patch.object(sandbox_paths, "MANAGED", self.root / "managed"),
            mock.patch.dict(os.environ, {**GIT_ENV, "HOME": str(self.root), "CLAUDE_CONFIG_DIR": str(self.root / ".claude"), "CLAUDE_PROJECT_DIR": str(self.root / "project")}),
        ):
            patch.start()
            self.addCleanup(patch.stop)


class TestPermissionHookGit(Isolated):
    def setUp(self):
        super().setUp()
        self.repo = self.root / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        (self.repo / "base.txt").write_text("one\n", encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "base")
        (self.repo / "base.txt").write_text("two\n", encoding="utf-8")
        (self.repo / "added.txt").write_text("fresh\n", encoding="utf-8")
        git(self.repo, "add", "-A")
        self.ask = {"tool": "Bash", "command": "git commit -m x", "cwd": str(self.repo), "session": "s", "agent": ""}

    def hook_path(self) -> tuple[str | None, dict, dict | None]:
        pinned, shown = permission_hook.commit_diff(self.ask, None)
        return pinned, shown, permission_hook.bound(ALLOW, self.ask, pinned)

    def assert_clean_run(self) -> None:
        _, shown, chosen = self.hook_path()
        self.assertEqual(([entry["path"] for entry in shown["diff"]], chosen), (["added.txt", "base.txt"], ALLOW))
        self.assertFalse(self.marker.exists())

    def test_a_planted_post_index_change_hook_never_runs(self):
        probe(self.repo / ".git" / "hooks" / "post-index-change", self.marker, "exit 0")
        self.assert_clean_run()

    def test_a_planted_core_hooks_path_never_runs(self):
        hooks = self.root / "planted-hooks"
        for name in ("post-index-change", "pre-commit", "reference-transaction"):
            probe(hooks / name, self.marker, "exit 0")
        git(self.repo, "config", "core.hooksPath", str(hooks))
        self.assert_clean_run()

    def test_a_planted_git_earlier_on_path_never_runs(self):
        planted = probe(self.root / "bin" / "git", self.marker, 'exec /usr/bin/git "$@"')
        with mock.patch.dict(os.environ, {"PATH": f"{planted.parent}{os.pathsep}{os.environ['PATH']}"}):
            self.assert_clean_run()

    def test_the_hook_path_leaves_the_index_file_untouched(self):
        index = self.repo / ".git" / "index"
        before = (index.read_bytes(), index.stat().st_mtime_ns)
        self.hook_path()
        self.assertEqual((index.read_bytes(), index.stat().st_mtime_ns), before)

    def test_the_binding_changes_with_the_staged_tree_and_only_with_it(self):
        pinned = staged_diff.binding(self.repo)
        self.assertEqual(staged_diff.bound_diff(self.repo, pinned, None), staged_diff.review_diff(self.repo, None))
        (self.repo / "added.txt").write_text("unstaged\n", encoding="utf-8")
        git(self.repo, "status", "--porcelain")
        self.assertEqual(staged_diff.binding(self.repo), pinned)
        git(self.repo, "add", "added.txt")
        content = staged_diff.binding(self.repo)
        self.assertNotEqual(content, pinned)
        with self.assertRaises(staged_diff.DiffError):
            staged_diff.bound_diff(self.repo, pinned, None)
        (self.repo / "added.txt").chmod(0o755)
        git(self.repo, "add", "added.txt")
        self.assertNotIn(staged_diff.binding(self.repo), (pinned, content))
        (self.repo / "added.txt").write_text("fresh\n", encoding="utf-8")
        (self.repo / "added.txt").chmod(0o644)
        git(self.repo, "add", "added.txt")
        self.assertEqual(staged_diff.binding(self.repo), pinned)

    def test_an_index_with_unmerged_paths_has_no_binding(self):
        oid = git(self.repo, "hash-object", "-w", "base.txt").strip()
        entries = f"0 {'0' * len(oid)}\tbase.txt\n100644 {oid} 1\tbase.txt\n100644 {oid} 2\tbase.txt\n"
        subprocess.run(["git", "update-index", "--index-info"], cwd=self.repo, input=entries, env={**os.environ, **GIT_ENV}, check=True, capture_output=True, text=True)
        with self.assertRaises(staged_diff.DiffError):
            staged_diff.binding(self.repo)


def stage_a(repo: Path) -> None:
    (repo / "a.txt").write_text("two\n", encoding="utf-8")
    git(repo, "add", "a.txt")


def restage_a(repo: Path) -> None:
    (repo / "a.txt").write_text("three\n", encoding="utf-8")
    git(repo, "add", "a.txt")


def chmod_a(repo: Path) -> None:
    (repo / "a.txt").chmod(0o755)
    git(repo, "add", "a.txt")


def intend_new(repo: Path) -> None:
    (repo / "new.txt").write_text("x\n", encoding="utf-8")
    git(repo, "add", "-N", "new.txt")


def swap_empty_to_intent(repo: Path) -> None:
    git(repo, "rm", "-q", "--cached", "empty.txt")
    git(repo, "add", "-N", "empty.txt")


def stage_a_and_intend_empty(repo: Path) -> None:
    stage_a(repo)
    (repo / "fresh_empty.txt").write_text("", encoding="utf-8")
    git(repo, "add", "-N", "fresh_empty.txt")


def stage_intended_empty(repo: Path) -> None:
    git(repo, "add", "fresh_empty.txt")


def add_gitlink(repo: Path) -> None:
    git(repo, "update-index", "--add", "--cacheinfo", f"160000,{git(repo, 'rev-parse', 'HEAD').strip()},mod")


def skip_a(repo: Path) -> None:
    git(repo, "update-index", "--skip-worktree", "a.txt")


def refresh(repo: Path) -> None:
    os.utime(repo / "a.txt", ns=(1, 1))
    git(repo, "status", "--porcelain")


def sparse(repo: Path) -> None:
    git(repo, "sparse-checkout", "init", "--cone", "--sparse-index")
    git(repo, "sparse-checkout", "set", "sub")


def split_v4(repo: Path) -> None:
    git(repo, "update-index", "--index-version", "4")
    git(repo, "update-index", "--split-index")


def uncache_c(repo: Path) -> None:
    git(repo, "rm", "-q", "--cached", "other/c.txt")


def odd_names(repo: Path) -> None:
    (repo / "tab\tname.txt").write_text("t\n", encoding="utf-8")
    (repo / "new\nline.txt").write_text("n\n", encoding="utf-8")
    git(repo, "add", "-A")


def to_symlink(repo: Path) -> None:
    (repo / "a.txt").unlink()
    (repo / "a.txt").symlink_to("other/c.txt")
    git(repo, "add", "a.txt")


CASES = {
    "content": (stage_a, restage_a),
    "mode only": (stage_a, chmod_a),
    "intent-to-add new file": (stage_a, intend_new),
    "tracked empty file swapped to intent-to-add": (stage_a, swap_empty_to_intent),
    "intent-to-add empty file staged for real": (stage_a_and_intend_empty, stage_intended_empty),
    "gitlink added": (stage_a, add_gitlink),
    "skip-worktree flag": (stage_a, skip_a),
    "stat refresh only": (stage_a, refresh),
    "sparse index": (stage_a, sparse),
    "index v4 and split index": (stage_a, split_v4),
    "rm --cached": (stage_a, uncache_c),
    "tab and newline names": (stage_a, odd_names),
    "file to symlink": (stage_a, to_symlink),
}


def hide_staged_b(flag: str) -> Callable[[Path], None]:
    def hide(repo: Path) -> None:
        (repo / "sub" / "b.txt").write_text("evil\n", encoding="utf-8")
        git(repo, "add", "sub/b.txt")
        (repo / "sub" / "b.txt").write_text("b\n", encoding="utf-8")
        git(repo, "update-index", flag, "sub/b.txt")
    return hide


def flag_after(change: Callable[[Path], None], path: str, flag: str) -> Callable[[Path], None]:
    def flagged(repo: Path) -> None:
        change(repo)
        git(repo, "update-index", flag, path)
    return flagged


def sparse_no_cone(repo: Path) -> None:
    git(repo, "sparse-checkout", "set", "--no-cone", "/sub/")


UNREAD_CASES = {
    "staged change hidden by assume-unchanged": hide_staged_b("--assume-unchanged"),
    "staged change hidden by skip-worktree": hide_staged_b("--skip-worktree"),
    "sparse index in cone mode": sparse,
    "sparse checkout without cone": sparse_no_cone,
    "intent-to-add new file with skip-worktree": flag_after(intend_new, "new.txt", "--skip-worktree"),
    "intent-to-add new file with assume-unchanged": flag_after(intend_new, "new.txt", "--assume-unchanged"),
    "tracked empty file swapped to intent-to-add with skip-worktree": flag_after(swap_empty_to_intent, "empty.txt", "--skip-worktree"),
}


class TestDebugLayout(unittest.TestCase):
    def test_an_unexpected_ls_files_debug_layout_fails_closed_with_its_own_message(self):
        entry = b"100644 e69de29bb2d1d6434b8b29ae775ad8c2e48c5391 0\t%s\0  ctime: 0:0\n  mtime: 0:0\n  dev: 0\tino: 0\n  uid: 0\tgid: 0\n  size: 0\tflags: %s\n"
        good = entry % (b"a", b"20004000") + entry % (b"b", b"0")
        self.assertEqual(staged_diff.flagged(good), [(b"100644 e69de29bb2d1d6434b8b29ae775ad8c2e48c5391 0\ta", 0x20004000), (b"100644 e69de29bb2d1d6434b8b29ae775ad8c2e48c5391 0\tb", 0)])
        broken = {
            "extra line after flags": entry % (b"a", b"0") + b"  extra: 1\n" + entry % (b"b", b"0"),
            "flags not hex": entry % (b"a", b"zz"),
            "flags with a suffix": entry % (b"a", b"0 extended"),
            "one line missing": entry.replace(b"  dev: 0\tino: 0\n", b"") % (b"a", b"0"),
            "trailing garbage": good + b"junk",
        }
        for name, raw in broken.items():
            with self.subTest(layout=name), self.assertRaisesRegex(staged_diff.DiffError, "^unexpected ls-files --debug layout$"):
                staged_diff.flagged(raw)


class Repos(Isolated):
    def fresh(self, name: str) -> Path:
        repo = self.root / name
        (repo / "sub").mkdir(parents=True)
        (repo / "other").mkdir()
        git(repo, "init", "-q", "-b", "main")
        for path, text in (("a.txt", "one\n"), ("empty.txt", ""), ("sub/b.txt", "b\n"), ("other/c.txt", "c\n")):
            (repo / path).write_text(text, encoding="utf-8")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "base")
        return repo

    def ids(self, repo: Path) -> tuple[str, str]:
        return git(repo, "write-tree").strip(), staged_diff.binding(repo)

    def recorded(self, repo: Path) -> list[tuple[str, str]]:
        lines = git(repo, "diff-tree", "--no-commit-id", "--name-status", "-r", "HEAD~1", "HEAD").splitlines()
        return sorted((path, status) for status, path in (line.split("\t", 1) for line in lines))


class TestBindingMatchesWriteTree(Repos):
    def test_the_binding_changes_exactly_when_the_tree_git_write_tree_records_changes(self):
        for name, (setup, mutate) in CASES.items():
            with self.subTest(case=name):
                repo = self.fresh(name.replace(" ", "-"))
                setup(repo)
                before = self.ids(repo)
                mutate(repo)
                after = self.ids(repo)
                self.assertEqual(before[1] != after[1], before[0] != after[0])
                self.assertEqual(shown(staged_diff.bound_diff(repo, after[1], None)), shown(staged_diff.tree_diff(repo, after[0], None)))

    def test_the_preview_lists_exactly_what_git_commit_records(self):
        for name, setup in {"intent-to-add new file": intend_new, **UNREAD_CASES}.items():
            with self.subTest(case=name):
                repo = self.fresh(name.replace(" ", "-"))
                stage_a(repo)
                setup(repo)
                preview = shown(staged_diff.bound_diff(repo, staged_diff.binding(repo), None))
                git(repo, "commit", "-q", "-m", "x")
                self.assertEqual(preview, self.recorded(repo))

    def test_an_allow_turns_into_a_deny_when_a_tracked_empty_file_is_swapped_to_intent_to_add(self):
        repo = self.fresh("swap")
        stage_a(repo)
        ask = {"tool": "Bash", "command": "git commit -m x", "cwd": str(repo), "session": "s", "agent": ""}
        pinned, attached = permission_hook.commit_diff(ask, None)
        self.assertEqual(shown(attached["diff"]), [("a.txt", "M")])
        swap_empty_to_intent(repo)
        self.assertEqual(permission_hook.bound(ALLOW, ask, pinned), {"behavior": "deny", "message": permission_hook.CHANGED})


def shown(diff: list[dict]) -> list[tuple[str, str]]:
    return sorted((entry["path"], entry["status"]) for entry in diff)


WORKTREE_FORMS = (
    "git commit -a -m x", "git commit -am x", "git commit -av -m x", "git commit -m x -a", "git commit --all -m x",
    "git commit --all= -m x", "git commit --al -m x", "git commit -i -m x a.txt", "git commit --include -m x a.txt",
    "git commit -o -m x a.txt", "git commit --only -m x a.txt", "git commit -m x a.txt", "git commit -m x -- a.txt",
    "git commit -p -m x", "git commit --interactive", "git commit --pathspec-from-file=list -m x",
    "git commit -a -m x ; true", "git commit -am x&&true", "git add -A && git commit -m x", "sh -c 'git commit -am x'",
    "git -c core.fileMode=false commit -am x", "env GIT_INDEX_FILE=other git commit -m x", "/usr/bin/git commit -am x",
)
NOT_APPROVABLE = "kvb-orchestrator: commit reads the working tree; stage the files and commit the index"
AMEND_FORMS = ("git commit --amend --no-edit", "git commit --amend -m x", "git commit -m x --amend", "git commit --amen -m x")


def gitlink_without_folder(repo: Path) -> None:
    git(repo, "update-index", "--add", "--cacheinfo", f"160000,{git(repo, 'rev-parse', 'HEAD').strip()},mod")
    git(repo, "commit", "-q", "-m", "link")
    stage_a(repo)


def file_mode_off_index_x(repo: Path) -> None:
    stage_a(repo)
    git(repo, "config", "core.fileMode", "false")
    git(repo, "update-index", "--chmod=+x", "other/c.txt")


def clean_filter(repo: Path) -> None:
    (repo / ".gitattributes").write_text("*.txt filter=upper\n", encoding="utf-8")
    git(repo, "add", ".gitattributes")
    stage_a(repo)
    git(repo, "config", "filter.upper.clean", "tr a-z A-Z")


REVIEWER_STATES = {
    "gitlink whose folder is gone": gitlink_without_folder,
    "core.fileMode=false with +x only in the index": file_mode_off_index_x,
    "clean filter": clean_filter,
}


class TestWorkingTreeCommitsAreNotApprovable(Repos):
    def ask(self, repo: Path, command: str) -> dict:
        return {"tool": "Bash", "command": command, "cwd": str(repo), "session": "s", "agent": ""}

    def test_no_commit_form_that_reads_the_working_tree_is_approved(self):
        repo = self.fresh("forms")
        stage_a(repo)
        for command in WORKTREE_FORMS:
            with self.subTest(command=command):
                ask = self.ask(repo, command)
                pinned, attached = permission_hook.commit_diff(ask, None)
                self.assertEqual((pinned, attached), (None, {}))
                self.assertIsNone(permission_hook.bound(ALLOW, ask, pinned))

    def test_an_amend_is_never_approved_and_a_plain_commit_of_the_same_index_still_binds(self):
        repo = self.fresh("amend")
        stage_a(repo)
        for command in AMEND_FORMS:
            with self.subTest(command=command):
                ask = self.ask(repo, command)
                self.assertEqual(permission_hook.commit_diff(ask, None), (None, {}))
                self.assertIsNone(permission_hook.bound(ALLOW, ask, None))
        plain = self.ask(repo, "git commit --no-amend -m x")
        pinned, attached = permission_hook.commit_diff(plain, None)
        self.assertEqual((shown(attached["diff"]), permission_hook.bound(ALLOW, plain, pinned)), ([("a.txt", "M")], ALLOW))

    def test_the_reviewer_states_give_commit_all_no_approval_and_a_plain_commit_its_bound_one(self):
        for name, setup in REVIEWER_STATES.items():
            with self.subTest(state=name):
                repo = self.fresh(name.replace(" ", "-").replace("=", "-"))
                setup(repo)
                everything = self.ask(repo, "git commit -am x")
                self.assertEqual(permission_hook.commit_diff(everything, None), (None, {}))
                self.assertIsNone(permission_hook.bound(ALLOW, everything, None))
                plain = self.ask(repo, "git commit -m x")
                pinned, attached = permission_hook.commit_diff(plain, None)
                self.assertEqual((pinned is not None, permission_hook.bound(ALLOW, plain, pinned)), (True, ALLOW))
                self.assertIn(("a.txt", "M"), shown(attached["diff"]))

    def test_the_hook_creates_no_ask_and_names_the_reason_for_such_a_commit(self):
        repo = self.fresh("hook")
        stage_a(repo)
        hook = {"tool_name": "Bash", "tool_input": {"command": "git commit -am x"}, "cwd": str(repo), "session_id": "s"}
        argv = ["/usr/bin/python3", "-E", "-s", str(CLIENT / "permission_hook.py"), "--port", "1", "--timeout", "1", "--approvers", str(self.root / "approvers.json"), "--replay", str(self.root / "replay.json")]
        done = subprocess.run(argv, input=json.dumps(hook), capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual((done.returncode, done.stdout, done.stderr.strip()), (0, "", NOT_APPROVABLE))


class TestHookGitEnvironment(Isolated):
    def test_planted_git_variables_in_the_hook_environment_are_never_used(self):
        repo = self.root / "repo"
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        (repo / "base.txt").write_text("one\n", encoding="utf-8")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "base")
        (repo / "base.txt").write_text("two\n", encoding="utf-8")
        (repo / "added.txt").write_text("fresh\n", encoding="utf-8")
        git(repo, "add", "-A")
        expected = hashlib.sha256(subprocess.run(["git", "ls-files", "-s", "-z"], cwd=repo, env={**os.environ, **GIT_ENV}, capture_output=True, check=True).stdout).hexdigest()
        decoys = {"GIT_DIR": self.root / "decoy-git", "GIT_EXEC_PATH": self.root / "decoy-exec", "GIT_INDEX_FILE": self.root / "decoy-index", "GIT_CONFIG_GLOBAL": self.root / "decoy-gitconfig"}
        decoys["GIT_DIR"].mkdir()
        decoys["GIT_EXEC_PATH"].mkdir()
        decoys["GIT_INDEX_FILE"].write_bytes(b"DIRC")
        decoys["GIT_CONFIG_GLOBAL"].write_text("[[[\n", encoding="utf-8")
        for decoy in decoys.values():
            decoy.chmod(0)
            self.addCleanup(decoy.chmod, 0o700)
        seen, run = [], subprocess.run

        def spy(*args, **kwargs):
            seen.append(kwargs.get("env"))
            return run(*args, **kwargs)

        ask = {"tool": "Bash", "command": "git commit -m x", "cwd": str(repo), "session": "s", "agent": ""}
        with mock.patch.dict(os.environ, {name: str(path) for name, path in decoys.items()}), mock.patch.object(subprocess, "run", spy):
            pinned = staged_diff.binding(repo)
            preview = shown(staged_diff.bound_diff(repo, pinned, None))
            chosen = permission_hook.bound(ALLOW, ask, permission_hook.commit_diff(ask, None)[0])
        self.assertEqual((pinned, preview, chosen), (expected, [("added.txt", "A"), ("base.txt", "M")], ALLOW))
        self.assertTrue(seen)
        for env in seen:
            self.assertLessEqual(set(env), {"HOME", "LANG", "LC_ALL", "LC_CTYPE", "GIT_OPTIONAL_LOCKS", "GIT_NO_LAZY_FETCH", "GIT_CONFIG_NOSYSTEM", "GIT_CONFIG_GLOBAL", "PATH"})
            self.assertEqual((env["GIT_CONFIG_GLOBAL"], env["PATH"]), (os.devnull, staged_diff.TRUSTED_PATH))


class TestPasskeyOpenssl(Scratch):
    def test_a_planted_openssl_earlier_on_path_never_runs_nor_forges_a_signature(self):
        planted = probe(self.root / "bin" / "openssl", self.marker, "exit 0")
        spki = passkey.EC_PREFIX + b"\x04" + bytes(64)
        with mock.patch.dict(os.environ, {"PATH": f"{planted.parent}{os.pathsep}{os.environ['PATH']}"}):
            self.assertFalse(passkey.by_openssl(-7, spki, b"data", b"signature"))
        self.assertFalse(self.marker.exists())


class TestReminderHook(Scratch):
    def setUp(self):
        super().setUp()
        self.work = self.root / "work"
        self.work.mkdir()

    def run_reminder(self, path: str) -> subprocess.CompletedProcess:
        env = {**os.environ, "HOME": str(self.root), "DREAM_STAMP_DIR": str(self.root / "stamps"), "PATH": path}
        return subprocess.run(["/usr/bin/bash", str(REMINDER)], cwd=self.work, input='{"session_id": "abc"}', env=env, capture_output=True, text=True, timeout=30, check=False)

    def test_a_planted_json_module_in_the_cwd_is_never_imported(self):
        (self.work / "json.py").write_text(f"open({str(self.marker)!r}, 'w').close()\n", encoding="utf-8")
        done = self.run_reminder(os.environ["PATH"])
        self.assertFalse(self.marker.exists())
        self.assertIn("DREAM HINT", done.stdout)

    def test_a_planted_python3_earlier_on_path_never_runs(self):
        planted = probe(self.root / "bin" / "python3", self.marker, 'exec /usr/bin/python3 "$@"')
        done = self.run_reminder(f"{planted.parent}{os.pathsep}{os.environ['PATH']}")
        self.assertFalse(self.marker.exists())
        self.assertIn("DREAM HINT", done.stdout)


class TestPermissionHookInstall(Scratch):
    def test_the_installed_command_is_absolute_isolated_and_imports_its_modules(self):
        home = self.root / "home"
        hub = home / ".local" / "share" / "kvb-orchestrator"
        shutil.copytree(CLIENT, hub / "client", ignore=shutil.ignore_patterns("__pycache__"))
        (hub / ".env").write_text("KVB_ORCHESTRATOR_PORT=1\n", encoding="utf-8")
        (home / ".claude").mkdir(parents=True)
        env = {**os.environ, "HOME": str(home)}
        subprocess.run(["/usr/bin/bash", str(ORCHESTRATOR), "hook"], env=env, check=True, capture_output=True, text=True, timeout=60)
        settings = json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8"))
        command = settings["hooks"]["PermissionRequest"][-1]["hooks"][0]["command"]
        self.assertTrue(command.startswith("/usr/bin/python3 -E -s "), command)
        planted = probe(self.root / "bin" / "python3", self.marker, 'exec /usr/bin/python3 "$@"')
        work = self.root / "work"
        work.mkdir()
        (work / "json.py").write_text(f"open({str(self.marker)!r}, 'w').close()\n", encoding="utf-8")
        run = {**env, "PATH": f"{planted.parent}{os.pathsep}{os.environ['PATH']}"}
        done = subprocess.run(["/usr/bin/bash", "-c", command], cwd=work, input="no hook input", env=run, capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual((done.returncode, done.stdout, done.stderr), (0, "", ""))
        self.assertFalse(self.marker.exists())


if __name__ == "__main__":
    unittest.main()
