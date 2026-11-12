import json
import os
import shlex
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
GATES = REPO_ROOT / "skills" / "kvb-check-gate" / "scripts" / "gates.py"
QUEUE = REPO_ROOT / "skills" / "kvb-org-queue" / "scripts" / "queue.py"
OPEN_MEMORY = {"available": -1, "swap_free": -1, "psi_full": 1000, "container_swap_gb": 1e9}


class Scratch(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.base = Path(scratch.name).resolve()
        self.council = self.base / "council"
        self.home = self.base / "home"
        self.home.mkdir()
        self.env = {
            "PATH": os.environ["PATH"],
            "HOME": str(self.home),
            "TMPDIR": str(self.base),
            "GATES_DB": str(self.base / "gates.db"),
            "AGENTS_COUNCIL_ROOT": str(self.council),
            "AGENTS_COUNCIL_CONFIG": str(self.base / "config.json"),
            "CLAUDE_CODE_SESSION_ID": "s1",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CEILING_DIRECTORIES": str(self.base.parent),
        }
        self.repo = self.base / "repo"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "t@example.org")
        self.git("config", "user.name", "t")
        self.commit("a")

    def git(self, *args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args], cwd=cwd or self.repo, env=self.env, capture_output=True, text=True, check=check
        )

    def out(self, *args: str) -> str:
        return self.git(*args).stdout.strip()

    def commit(self, name: str, content: str | None = None) -> subprocess.CompletedProcess:
        (self.repo / name).write_text(content or name, encoding="utf-8")
        self.git("add", name)
        return self.git("commit", "-q", "-m", name, check=False)

    def gates(self, *args: str, cwd: Path | None = None, extra: dict | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(GATES), *args], cwd=cwd or self.repo, env={**self.env, **(extra or {})},
            capture_output=True, text=True, check=False,
        )

    def resolve(self, branch: str, action: str = "merge") -> str:
        return self.gates("resolve", "--repo", str(self.repo), "--branch", branch, "--action", action).stdout.strip()

    def receipt(self, tree: str, level: str, gpu: str = "false") -> None:
        added = self.gates(
            "receipt", "add", "--repo", str(self.repo), "--tree", tree, "--level", level, "--log", "/l.log",
            extra={"INFINITO_TEST_GPU": gpu},
        )
        self.assertEqual(added.returncode, 0, added.stderr)

    def parents(self, branch: str) -> list[dict]:
        shown = json.loads(self.gates("show", "--json", "--repo", str(self.repo)).stdout)
        return shown[str(self.repo)][branch]["parents"]


class TestGates(Scratch):
    def test_a_branch_takes_its_own_rule_else_the_strictest_of_all_parents_else_none(self):
        repo = str(self.repo)
        self.assertEqual(self.resolve("fix"), "none\t-")
        for parent, level in (("iam", "test"), ("production", "quality-high")):
            self.gates("rule", "set", "--repo", repo, "--branch", parent, "--action", "merge", "--level", level)
            self.gates("parents", "add", "--repo", repo, "--branch", "fix", "--parent", parent)
        self.assertEqual(self.resolve("fix"), "quality-high\tproduction")
        self.gates("rule", "set", "--repo", repo, "--branch", "fix", "--action", "merge", "--level", "quick")
        self.assertEqual(self.resolve("fix"), "quick\tfix")
        self.assertEqual(self.resolve("fix", "push"), "none\t-")

    def test_derive_gives_each_branch_its_nearest_ancestor_tips_and_the_default_branch_none(self):
        self.git("checkout", "-q", "-b", "feature")
        self.commit("b")
        self.git("checkout", "-q", "-b", "fix")
        self.commit("c")
        derived = self.gates("parents", "derive", "--repo", str(self.repo)).stdout.splitlines()
        self.assertEqual(sorted(derived), ["feature\tmain\tderived", "fix\tfeature\tderived"])
        self.assertEqual(self.parents("main"), [])
        self.assertEqual(self.parents("fix"), [{"parent": "feature", "source": "derived"}])

    def test_the_tree_covers_unstaged_and_untracked_files_but_not_ignored_ones(self):
        tree = lambda: self.gates("tree", "--worktree", str(self.repo)).stdout.strip()
        self.assertEqual(tree(), self.out("rev-parse", "HEAD^{tree}"))
        self.commit(".gitignore", "ignored\n")
        (self.repo / "ignored").write_text("x", encoding="utf-8")
        self.assertEqual(tree(), self.out("rev-parse", "HEAD^{tree}"))
        (self.repo / "a").write_text("changed", encoding="utf-8")
        (self.repo / "new").write_text("new", encoding="utf-8")
        dirty = tree()
        self.assertEqual(self.out("status", "--porcelain"), "M a\n?? new")
        self.git("add", "-A")
        self.assertEqual(dirty, self.out("write-tree"))

    def test_a_receipt_meets_its_own_level_and_every_lower_one_above_quick_only_with_the_gpu_off(self):
        repo, tree = str(self.repo), self.out("rev-parse", "HEAD^{tree}")
        check = lambda level: self.gates("receipt", "check", "--repo", repo, "--tree", tree, "--level", level).returncode
        self.assertEqual(check("quick"), 1)
        self.receipt(tree, "test", gpu="true")
        self.assertEqual((check("quick"), check("test")), (0, 1))
        self.receipt(tree, "test")
        self.assertEqual((check("quick"), check("test"), check("quality-high")), (0, 0, 1))
        [row, _] = [json.loads(line) for line in (self.council / "gate-receipts.jsonl").read_text().splitlines()]
        self.assertEqual(
            [row[k] for k in ("repo", "tree", "level", "gpu", "log")], [repo, tree, "test", "true", "/l.log"]
        )

    def test_a_receipt_kept_under_the_state_directory_counts_once_the_council_root_lost_it(self):
        repo, tree = str(self.repo), self.out("rev-parse", "HEAD^{tree}")
        self.receipt(tree, "quality-high")
        kept = self.home / ".local" / "state" / "agents-council" / "gate-receipts.jsonl"
        kept.parent.mkdir(parents=True)
        (self.council / "gate-receipts.jsonl").rename(kept)
        check = self.gates("receipt", "check", "--repo", repo, "--tree", tree, "--level", "quality-high")
        self.assertEqual(check.returncode, 0)

    def test_a_row_whose_id_is_no_string_is_skipped(self):
        repo, tree = str(self.repo), self.out("rev-parse", "HEAD^{tree}")
        self.receipt(tree, "test")
        with (self.council / "gate-receipts.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"id": ["x"], "repo": repo, "tree": tree, "level": "e2e"}) + "\n")
        check = self.gates("receipt", "check", "--repo", repo, "--tree", tree, "--level", "test")
        self.assertEqual((check.returncode, check.stderr), (0, ""))

    def test_a_receipt_older_than_30_days_neither_counts_nor_survives_the_next_write(self):
        repo, tree = str(self.repo), self.out("rev-parse", "HEAD^{tree}")
        old = {"id": "old", "repo": repo, "tree": tree, "level": "test", "gpu": "false", "at": time.time() - 31 * 86400}
        kept = self.home / ".local" / "state" / "agents-council" / "gate-receipts.jsonl"
        kept.parent.mkdir(parents=True)
        self.council.mkdir()
        journals = (self.council / "gate-receipts.jsonl", kept)
        for path in journals:
            path.write_text(json.dumps(old) + "\n", encoding="utf-8")
        check = self.gates("receipt", "check", "--repo", repo, "--tree", tree, "--level", "test")
        self.assertEqual(check.returncode, 1)
        self.receipt("other", "test")
        for path in journals:
            self.assertNotIn('"id": "old"', path.read_text(encoding="utf-8"))
        self.assertEqual(len(journals[0].read_text(encoding="utf-8").splitlines()), 1)

    def test_a_branch_cannot_be_its_own_parent(self):
        result = self.gates("parents", "add", "--repo", str(self.repo), "--branch", "fix", "--parent", "fix")
        self.assertEqual(result.returncode, 2)

    def test_record_takes_the_branches_at_a_new_branch_start_and_a_drop_outlives_the_journal(self):
        self.git("branch", "twin")
        self.git("checkout", "-q", "-b", "fix")
        recorded = self.gates("parents", "record", "--worktree", str(self.repo))
        self.assertEqual(recorded.stdout.split(), ["main", "twin"])
        self.assertFalse((self.base / "gates.db").exists())
        self.assertEqual(self.parents("fix"), [{"parent": "main", "source": "recorded"}, {"parent": "twin", "source": "recorded"}])
        self.gates("parents", "drop", "--repo", str(self.repo), "--branch", "fix", "--parent", "twin")
        self.assertEqual(self.parents("fix"), [{"parent": "main", "source": "recorded"}])
        self.gates("parents", "derive", "--repo", str(self.repo))
        self.assertEqual(self.parents("fix"), [{"parent": "main", "source": "recorded"}])
        self.commit("b")
        self.assertEqual(self.gates("parents", "record", "--worktree", str(self.repo)).stdout, "")

    def test_quick_refuses_broken_staged_files_and_receipts_the_index_tree_when_green(self):
        for name, content in (("ok.py", "x = 1\n"), ("ok.json", "{}"), ("ok.sh", "echo ok\n")):
            (self.repo / name).write_text(content, encoding="utf-8")
        self.git("add", "-A")
        green = self.gates("quick", "--worktree", str(self.repo))
        self.assertEqual((green.returncode, green.stderr), (0, ""))
        [row] = [json.loads(line) for line in (self.council / "gate-receipts.jsonl").read_text().splitlines()]
        self.assertEqual((row["level"], row["tree"]), ("quick", self.out("write-tree")))
        for name, content, needle in (
            ("bad.py", "def (:\n", "bad.py:"),
            ("bad.json", "{", "bad.json:"),
            ("bad.sh", "if then\n", "bad.sh:"),
            ("spaced.txt", "trailing \n", "trailing whitespace"),
        ):
            with self.subTest(name=name):
                (self.repo / name).write_text(content, encoding="utf-8")
                self.git("add", name)
                red = self.gates("quick", "--worktree", str(self.repo))
                self.assertEqual(red.returncode, 1)
                self.assertIn(needle, red.stderr)
                self.git("rm", "-q", "--cached", name)
        self.assertEqual(len((self.council / "gate-receipts.jsonl").read_text().splitlines()), 1)

    def test_quick_checks_this_whole_repository_in_under_30_seconds(self):
        clone = self.base / "skills"
        self.git("clone", "-q", "--shared", str(REPO_ROOT), str(clone), cwd=self.base)
        started = time.monotonic()
        result = self.gates("quick", "--worktree", str(clone), cwd=clone)
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertLess(time.monotonic() - started, 30)

    def test_hooks_install_leaves_the_git_config_untouched_and_works_beside_its_lock(self):
        config = self.repo / ".git" / "config"
        before = config.read_bytes()
        lock = self.repo / ".git" / "config.lock"
        lock.write_bytes(b"")
        installed = self.gates("hooks", "install", "--repo", str(self.repo))
        self.assertEqual(installed.returncode, 0, installed.stderr)
        self.assertEqual(config.read_bytes(), before)
        self.assertEqual(lock.read_bytes(), b"")

    def test_hooks_install_refuses_a_foreign_hook_and_rewrites_its_own(self):
        installed = self.gates("hooks", "install", "--repo", str(self.repo))
        self.assertEqual(installed.returncode, 0, installed.stderr)
        hooks = self.repo / ".git" / "hooks"
        names = ["pre-commit", "commit-msg", "pre-merge-commit", "pre-push", "post-checkout"]
        self.assertEqual(installed.stdout.split(), [str(hooks / name) for name in names])
        for name in names:
            self.assertTrue(os.access(hooks / name, os.X_OK))
            self.assertIn(f"gates.py hook {name} ", (hooks / name).read_text(encoding="utf-8"))
        self.assertEqual(self.gates("hooks", "install", "--repo", str(self.repo)).returncode, 0)
        (hooks / "pre-push").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        refused = self.gates("hooks", "install", "--repo", str(self.repo))
        self.assertEqual(refused.returncode, 2)
        self.assertIn("did not write: pre-push", refused.stderr)
        self.assertEqual((hooks / "pre-push").read_text(encoding="utf-8"), "#!/bin/sh\nexit 0\n")


class TestInstalledHooks(Scratch):
    def setUp(self):
        super().setUp()
        self.commit("Makefile", "test:\n\ttrue\n")
        (self.base / "config.json").write_text(json.dumps({
            "disk": str(self.base),
            "thresholds_gb": {"warn": 0, "stop": 0, "critical": 0},
            "projection_minutes": 30,
            "slot_need_gb": {"test": 0, "quality-high": 0},
            "load_limits": {"cpu_percent": 101, "mem_percent": 101, "sample_seconds": 0.1},
            "budget_percent": {"ram": 75, "cpu": 100},
            "memory_limits": {stage: OPEN_MEMORY for stage in ("warn", "stop")},
            "heavy_commands": [],
            "never_block": [],
        }), encoding="utf-8")
        self.council.mkdir()
        (self.council / "rasci.json").write_text(json.dumps({
            "work/gate": {"roles": {}, "status": "running", "branch": "main"},
        }), encoding="utf-8")
        installed = self.gates("hooks", "install", "--repo", str(self.repo))
        self.assertEqual(installed.returncode, 0, installed.stderr)
        self.assertTrue(all(Path(line).is_relative_to(self.repo) for line in installed.stdout.split()))

    def rule(self, branch: str, action: str, level: str) -> None:
        self.gates("rule", "set", "--repo", str(self.repo), "--branch", branch, "--action", action, "--level", level)

    def produce_command(self, stderr: str) -> list[str]:
        lines = stderr.splitlines()
        return shlex.split(lines[lines.index(next(l for l in lines if l.endswith("Produce it with:"))) + 1])

    def test_a_commit_is_refused_without_a_receipt_and_passes_after_the_queue_gate_it_names(self):
        self.rule("main", "commit", "test")
        head = self.out("rev-parse", "HEAD")
        refused = self.commit("b")
        self.assertEqual(refused.returncode, 1)
        self.assertEqual(self.out("rev-parse", "HEAD"), head)
        tree = self.out("write-tree")
        self.assertIn(f"gates: commit on main needs test (rule of main); no receipt for tree {tree} meets it.", refused.stderr)
        command = self.produce_command(refused.stderr)
        log = self.base / f"gate-{tree[:12]}-test.log"
        self.assertEqual(command[:6], ["env", "-C", str(self.repo), "INFINITO_TEST_GPU=false", "python3", str(QUEUE)])
        self.assertEqual(
            command[6:], ["hold", "--kind", "test", "--task", "work/gate", "--receipt", "test", "--log", str(log), "--", "make", "test"]
        )
        gate = subprocess.run(command, cwd=self.base, env=self.env, capture_output=True, text=True, timeout=120, check=False)
        self.assertEqual(gate.returncode, 0, gate.stderr)
        self.assertIn(f"queue: receipt test for tree {tree}", gate.stderr)
        self.assertEqual(log.read_text(encoding="utf-8"), "true\n")
        passed = self.git("commit", "-q", "-m", "b", check=False)
        self.assertEqual(passed.returncode, 0, passed.stderr)
        self.assertEqual(self.out("rev-parse", "HEAD^{tree}"), tree)

    def test_a_merge_below_the_level_inherited_from_a_parent_is_refused(self):
        self.rule("main", "merge", "quality-high")
        self.git("checkout", "-q", "-b", "feature")
        self.git("checkout", "-q", "-b", "fix")
        self.assertEqual(self.commit("b").returncode, 0)
        self.git("checkout", "-q", "feature")
        merge = lambda: self.git("merge", "-q", "--no-ff", "-m", "merge fix", "fix", check=False)
        refused = merge()
        self.assertEqual(refused.returncode, 1)
        self.assertIn("merge on feature needs quality-high (rule of main)", refused.stderr)
        tree = self.out("write-tree")
        concluded = self.git("commit", "-q", "-m", "concluded", check=False)
        self.assertEqual(concluded.returncode, 1)
        self.assertIn("merge on feature needs quality-high (rule of main)", concluded.stderr)
        self.git("merge", "--abort")
        self.receipt(tree, "test")
        self.assertIn("needs quality-high", merge().stderr)
        self.git("merge", "--abort")
        self.receipt(tree, "quality-high")
        passed = merge()
        self.assertEqual(passed.returncode, 0, passed.stderr)
        self.assertEqual(len(self.out("log", "-1", "--format=%P").split()), 2)

    def merged_push(self, merge: list[str], branch: str) -> None:
        self.git("checkout", "-q", "-b", branch)
        self.assertEqual(self.commit(branch).returncode, 0)
        self.git("checkout", "-q", "main")
        self.git("merge", "-q", *merge, branch)
        if merge == ["--squash"]:
            warned = self.git("commit", "-q", "-m", branch, check=False)
            self.assertEqual(warned.returncode, 1)
            self.assertIn("merge on main needs quality-high", warned.stderr)
            self.git("commit", "-q", "--no-verify", "-m", branch)
        refused = self.git("push", "-q", "origin", "main", check=False)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("merge on main needs quality-high", refused.stderr)
        self.receipt(self.out("rev-parse", "HEAD^{tree}"), "quality-high")
        passed = self.git("push", "-q", "origin", "main", check=False)
        self.assertEqual(passed.returncode, 0, passed.stderr)
        self.assertEqual(self.out("rev-parse", "origin/main"), self.out("rev-parse", "HEAD"))

    def test_a_fast_forward_or_squash_merge_meets_the_merge_level_before_its_push(self):
        self.git("init", "-q", "--bare", str(self.base / "remote.git"), cwd=self.base)
        self.git("remote", "add", "origin", str(self.base / "remote.git"))
        self.rule("main", "merge", "quality-high")
        for merge, branch in (([], "fix"), (["--ff"], "forced"), (["--squash"], "squashed")):
            with self.subTest(merge=merge):
                self.merged_push(merge, branch)

    def test_a_commit_on_a_detached_head_takes_the_rebased_branch_else_the_default_branch(self):
        self.git("checkout", "-q", "-b", "feature")
        self.assertEqual(self.commit("a", "feature\n").returncode, 0)
        self.git("checkout", "-q", "main")
        self.assertEqual(self.commit("a", "main\n").returncode, 0)
        self.git("checkout", "-q", "feature")
        self.rule("feature", "commit", "test")
        self.assertNotEqual(self.git("rebase", "-q", "main", check=False).returncode, 0)
        (self.repo / "a").write_text("both\n", encoding="utf-8")
        self.git("add", "a")
        rebasing = self.git("commit", "-q", "-m", "resolved", check=False)
        self.assertEqual(rebasing.returncode, 1)
        self.assertIn("commit on feature needs test", rebasing.stderr)
        self.git("rebase", "--abort")
        self.git("checkout", "-q", "--detach", "main")
        self.rule("main", "commit", "test")
        detached = self.commit("b")
        self.assertEqual(detached.returncode, 1)
        self.assertIn("commit on main needs test", detached.stderr)

    def test_post_checkout_maps_a_remote_tip_to_its_branch_and_else_records_the_default_branch(self):
        self.git("init", "-q", "--bare", str(self.base / "remote.git"), cwd=self.base)
        self.git("remote", "add", "origin", str(self.base / "remote.git"))
        self.assertEqual(self.commit("b").returncode, 0)
        self.git("push", "-q", "origin", "main")
        self.git("reset", "-q", "--hard", "HEAD~1")
        self.git("worktree", "add", "-q", "--no-track", "-b", "x", str(self.base / "x"), "origin/main")
        self.git("worktree", "add", "-q", "-b", "y", str(self.base / "y"), "HEAD~1")
        self.assertEqual(self.parents("x"), [{"parent": "main", "source": "recorded"}])
        self.assertEqual(self.parents("y"), [{"parent": "main", "source": "recorded"}])

    def test_post_checkout_exits_0_when_it_cannot_record(self):
        self.council.chmod(0o777)
        switched = self.git("checkout", "-q", "-b", "feature", check=False)
        self.assertEqual(switched.returncode, 0, switched.stderr)
        self.assertIn("post-checkout recorded no parents", switched.stderr)
        self.assertEqual(self.out("branch", "--show-current"), "feature")

    def test_a_push_onto_another_branch_needs_the_level_of_both(self):
        self.git("init", "-q", "--bare", str(self.base / "remote.git"), cwd=self.base)
        self.git("remote", "add", "origin", str(self.base / "remote.git"))
        self.rule("main", "push", "test")
        self.git("branch", "feature")
        refused = self.git("push", "-q", "origin", "feature:main", check=False)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("push on main needs test", refused.stderr)

    def test_post_checkout_records_the_branches_at_a_new_branch_start_as_parents(self):
        self.git("checkout", "-q", "-b", "feature")
        self.git("worktree", "add", "-q", "-b", "side", str(self.base / "side"))
        self.git("checkout", "-q", "main")
        self.assertEqual(self.parents("feature"), [{"parent": "main", "source": "recorded"}])
        self.assertEqual(
            self.parents("side"), [{"parent": "feature", "source": "recorded"}, {"parent": "main", "source": "recorded"}]
        )
        self.assertEqual(self.parents("main"), [])

    def test_a_push_is_refused_without_a_receipt_and_passes_with_one(self):
        self.git("init", "-q", "--bare", str(self.base / "remote.git"), cwd=self.base)
        self.git("remote", "add", "origin", str(self.base / "remote.git"))
        self.rule("main", "push", "test")
        refused = self.git("push", "-q", "origin", "main", check=False)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("push on main needs test", refused.stderr)
        tree, head = self.out("rev-parse", "HEAD^{tree}"), self.out("rev-parse", "HEAD")
        self.receipt(tree, "test")
        passed = self.git("push", "-q", "origin", "main", check=False)
        self.assertEqual(passed.returncode, 0, passed.stderr)
        self.assertEqual(self.out("rev-parse", "origin/main"), head)

    def test_each_receipt_check_stays_under_a_second_on_its_refusing_path(self):
        for action in ("commit", "merge", "push"):
            self.rule("main", action, "test")
        head = self.out("rev-parse", "HEAD")
        for name, args, stdin in (
            ("commit-msg", [".git/COMMIT_EDITMSG"], ""),
            ("pre-merge-commit", [], ""),
            ("pre-push", ["origin", "url"], f"refs/heads/main {head} refs/heads/main {'0' * 40}\n"),
        ):
            timings = []
            for _ in range(3):
                started = time.monotonic()
                result = subprocess.run(
                    [sys.executable, str(GATES), "hook", name, *args], cwd=self.repo, env=self.env, input=stdin,
                    capture_output=True, text=True, check=False,
                )
                timings.append(time.monotonic() - started)
            with self.subTest(hook=name):
                self.assertEqual(result.returncode, 1)
                self.assertIn("queue.py hold", result.stderr)
                self.assertLess(min(timings), 1)


if __name__ == "__main__":
    unittest.main()
