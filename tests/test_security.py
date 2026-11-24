"""Exercise security.py of kvb-check-security against a fake medusa: weights, locations, exit codes, hand review."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SECURITY = REPO_ROOT / "skills" / "kvb-check-security" / "scripts" / "security.py"
GIT_DIR = os.path.dirname(shutil.which("git"))
PLACEHOLDER = "placeholder-value-never-shown"
FAKE = """#!{shebang}
import json, os, pathlib, subprocess, sys, time
args = sys.argv[1:]
pathlib.Path(__file__).with_name("argv.json").write_text(json.dumps(args))
pathlib.Path(__file__).with_name("home.txt").write_text(os.environ["HOME"])
pathlib.Path(__file__).with_name("timeout.txt").write_text(os.environ.get("MEDUSA_SCANNER_TIMEOUT", "unset"))
if os.environ.get("FAKE_MEDUSA_CHILD"):
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    pathlib.Path(__file__).with_name("child.txt").write_text(str(child.pid))
pathlib.Path(__file__).with_name("pid.txt").write_text(str(os.getpid()))
time.sleep(float(os.environ.get("FAKE_MEDUSA_SLEEP", "0")))
pathlib.Path(os.environ["HOME"], ".medusa").mkdir()
target, out = pathlib.Path(args[1]), pathlib.Path(args[args.index("-o") + 1])
out.mkdir(parents=True)
limit = int(os.environ.get("FAKE_MEDUSA_FILE_LIMIT", str(2 * 1024 * 1024)))
findings, taken, counted = [], 0, 0
for path in sorted(p for p in target.rglob("*") if p.is_file()):
    if path.suffix.lower() not in (".py", ".json", ".js") and not path.name.startswith("Dockerfile"):
        continue
    if path.name == os.environ.get("FAKE_MEDUSA_LOSE") or any(p in str(path.relative_to(target)) for p in ("build", "env")):
        continue
    taken += 1
    if path.stat().st_size > limit:
        continue
    counted += path.read_bytes().count(b"\\n") + 1
    cut = int(os.environ.get("FAKE_MEDUSA_LINE_LIMIT", "50000"))
    for number, text in enumerate(path.read_text().split("\\n")[:cut], 1):
        for severity in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"):
            if "MARK-" + severity in text:
                findings.append({{
                    "severity": severity, "rule_id": "FAKE-" + severity, "file": str(path), "line": number,
                    "code": text,
                }})
        if "MARK-FILE" in text:
            findings.append({{"severity": "MEDIUM", "rule_id": "FAKE-FILE", "file": str(path), "line": None}})
if not taken:
    print("No files found to scan")
    sys.exit(0)
report = {{"findings": findings, "scan_summary": {{"files_scanned": taken, "lines_scanned": counted}}}}
if os.environ.get("FAKE_MEDUSA_SHAPE") == "other":
    report = {{"issues": findings}}
if os.environ.get("FAKE_MEDUSA_SHAPE") == "nocounts":
    report = {{"findings": findings, "scan_summary": {{"files_scanned": taken}}}}
(out / "medusa-scan-20261104-120000.json").write_text(json.dumps(report))
sys.stdout.write(os.environ.get("FAKE_MEDUSA_STDOUT", "").replace("TREE", str(target)))
sys.exit(int(os.environ.get("FAKE_MEDUSA_EXIT", "0")))
"""
BASE = "class RuleBasedScanner:\n    MAX_RULE_SCAN_LINES = {lines}\n"
CONFIG = """@dataclass
class MedusaConfig:
    exclude_paths: List[str] = field(default_factory=lambda: ["build/", "env/"])
    exclude_files: List[str] = field(default_factory=lambda: ["*.min.js"])
"""
PARALLEL = """MAX_SCAN_FILE_SIZE = {size}
PER_SCANNER_TIMEOUT = {timeout}


class MedusaParallelScanner:
    FILE_SCANNERS = {{".py": "python", ".json": "json", ".js": "javascript"}}

    def find_scannable_files(self):
        special_exact_names: Set[str] = {{"mcp.json"}}
        special_prefixes = ("Dockerfile", ".env")
        env_suffix = ".env"
        ai_context_dir_names: Set[str] = {{".claude"}}
"""
HAND = "review trust boundaries, secrets and injection in the diff by hand, then pass --security '~<n>' to kvb-check-score"


def gone(pid: int, wait: float = 5.0) -> bool:
    until = time.monotonic() + wait
    while True:
        try:
            state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
        except OSError:
            return True
        if state in "ZX":
            return True
        if time.monotonic() >= until:
            return False
        time.sleep(0.05)


def ended(pids: list[int]) -> None:
    for pid in pids:
        if not gone(pid, 0):
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def security_module():
    spec = importlib.util.spec_from_file_location("kvb_check_security_workers", SECURITY)
    security = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(security)
    return security


class TestScanWorkers(unittest.TestCase):
    def test_medusa_takes_95_percent_of_the_physical_cores_and_leaves_one_free(self):
        security = security_module()
        for cores, workers in ((1, 1), (2, 1), (4, 3), (14, 13), (20, 19), (40, 38), (100, 95)):
            with self.subTest(cores=cores):
                self.assertEqual(security.scan_workers(cores), workers)

    def test_physical_cores_count_core_ids_per_socket_and_skip_hyperthreads(self):
        security = security_module()
        block = "processor\t: {n}\nphysical id\t: {socket}\ncore id\t\t: {core}\n\n"
        cpuinfo = "".join(block.format(n=n, socket=n // 4, core=n % 2) for n in range(8))
        self.assertEqual(security.physical_cores(cpuinfo), 4)
        self.assertEqual(security.physical_cores(""), os.cpu_count())


class TestSecurity(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        venv = self.base / "venv"
        self.bin = venv / "bin"
        self.bin.mkdir(parents=True)
        real = Path(sys.executable).resolve()
        (self.bin / "python").symlink_to(real)
        (venv / "pyvenv.cfg").write_text(f"home = {real.parent}\ninclude-system-site-packages = false\n", encoding="utf-8")
        version = f"python{sys.version_info.major}.{sys.version_info.minor}"
        self.package = venv / "lib" / version / "site-packages" / "medusa"
        self.limits()
        (self.package / "__init__.py").write_text("", encoding="utf-8")
        (self.package / "config.py").write_text(CONFIG, encoding="utf-8")
        self.medusa = self.bin / "medusa"
        self.medusa.write_text(FAKE.format(shebang=f"{self.bin / 'python'} -E"), encoding="utf-8")
        medusa = self.medusa
        medusa.chmod(0o755)
        self.repo = self.base / "repo"
        self.repo.mkdir()
        self.env = {
            "PATH": f"{self.bin}:{GIT_DIR}",
            "HOME": str(self.base),
            "AGENTS_COUNCIL_ROOT": str(self.base / "council"),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.org",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.org",
        }
        self.git("init", "-q", "-b", "main")
        self.write("app.py", "print(1)\n")
        self.write("old.py", "x = 1  # MARK-CRITICAL\n")
        self.write("gone.py", "y = 2  # MARK-HIGH\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "base")

    def limits(
        self, size: str = "2 * 1024 * 1024", lines: str = "50_000",
        timeout: str = 'int(os.environ.get("MEDUSA_SCANNER_TIMEOUT") or 60)',
    ) -> None:
        parallel = PARALLEL.format(size=size, timeout=timeout)
        for name, text in (("core/parallel.py", parallel), ("scanners/base.py", BASE.format(lines=lines))):
            (self.package / name).parent.mkdir(parents=True, exist_ok=True)
            (self.package / name).write_text(text, encoding="utf-8")

    def git(self, *args: str) -> None:
        subprocess.run(["git", *args], cwd=self.repo, env=self.env, capture_output=True, check=True)

    def started(self, *names: str) -> list[int]:
        """Returns:
            the pids the fake medusa writes to names (default: its own and its
            child's), once all are written; all are killed on cleanup.
        """
        markers = [self.bin / name for name in names or ("pid.txt", "child.txt")]
        until = time.monotonic() + 20
        while not all(m.exists() and m.read_text() for m in markers) and time.monotonic() < until:
            time.sleep(0.05)
        pids = [int(m.read_text()) for m in markers]
        self.addCleanup(ended, pids)
        return pids

    def write(self, path: str, text: str) -> None:
        (self.repo / path).parent.mkdir(parents=True, exist_ok=True)
        (self.repo / path).write_text(text, encoding="utf-8")

    def scan(self, *extra: str, env: dict[str, str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SECURITY), "--repo", str(self.repo), "--base", "HEAD", *extra],
            cwd=self.base, env=env, capture_output=True, text=True, check=False,
        )

    def test_changed_and_untracked_files_are_weighted(self):
        self.write("app.py", f"print(1)\ntoken = '{PLACEHOLDER}'  # MARK-HIGH\n")
        self.write("new.py", "a = 1  # MARK-LOW\nb = 2\nc = 3  # MARK-MEDIUM\nd = 4  # MARK-INFO\n")
        (self.repo / "gone.py").unlink()
        (self.repo / "link.py").symlink_to(self.repo / "old.py")
        result = self.scan(env=self.env)
        self.assertEqual(
            result.stdout,
            "🛡️ security 63 % (medusa: 4 findings in 2 files: high app.py:2, medium new.py:3, low new.py:1, "
            "info new.py:4)\n",
        )
        self.assertEqual(result.returncode, 3, result.stderr)
        argv = json.loads((self.bin / "argv.json").read_text(encoding="utf-8"))
        self.assertEqual(
            [argv[0], *argv[2:4], argv[4], *argv[6:]],
            ["scan", "--format", "json", "-o", "--no-cache", "--workers", str(security_module().host_workers())],
        )
        result = self.scan("--json", env=self.env)
        self.assertNotIn(PLACEHOLDER, result.stdout + result.stderr)
        found = json.loads(result.stdout)
        self.assertEqual(
            {k: found[k] for k in ("security", "files", "critical", "high", "medium", "low", "info")},
            {"security": 63, "files": 2, "critical": 0, "high": 1, "medium": 1, "low": 1, "info": 1},
        )
        self.assertEqual(
            found["findings"][0],
            {
                "severity": "high", "rule": "FAKE-HIGH", "path": "app.py", "line": 2,
                "sha1": hashlib.sha1(f"token = '{PLACEHOLDER}'  # MARK-HIGH".encode()).hexdigest(),
                "context": hashlib.sha1(f"print(1)\ntoken = '{PLACEHOLDER}'  # MARK-HIGH".encode()).hexdigest(),
            },
        )
        self.assertEqual(found["accepted"], [])
        home = Path((self.bin / "home.txt").read_text(encoding="utf-8"))
        self.assertNotEqual(home, self.base)
        self.assertTrue(home.name == "home" and home.parent.name.startswith("kvb-security-"), home)

    def accept(self, *flags: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SECURITY), "accept", "--repo", str(self.repo), *flags],
            cwd=self.base, env=self.env, capture_output=True, text=True, check=False,
        )

    def test_accepted_false_positive_leaves_the_score_until_its_line_changes(self):
        line = "x = compute()  # MARK-CRITICAL"
        self.write("app.py", f"print(1)\n{line}\n")
        sha1 = hashlib.sha1(line.encode()).hexdigest()
        result = self.accept("--rule", "FAKE-CRITICAL", "--path", "app.py", "--sha1", sha1, "--reason", "fixture marker")
        self.assertEqual(result.returncode, 0, result.stderr)
        listing = self.base / "council" / "security-accepted.jsonl"
        row = json.loads(listing.read_text(encoding="utf-8"))
        self.assertEqual(
            {k: row[k] for k in ("rule", "path", "sha1", "reason", "repo")},
            {"rule": "FAKE-CRITICAL", "path": "app.py", "sha1": sha1, "reason": "fixture marker",
             "repo": str(self.repo.resolve())},
        )
        result = self.scan(env=self.env)
        self.assertEqual(
            (result.stdout, result.returncode),
            ("🛡️ security 100 % (medusa: 0 findings, 1 accepted in 1 file)\n", 0),
        )
        accepted = json.loads(self.scan("--json", env=self.env).stdout)["accepted"]
        self.assertEqual([(a["rule"], a["path"], a["line"]) for a in accepted], [("FAKE-CRITICAL", "app.py", 2)])
        self.write("app.py", "print(1)\nx = compute(2)  # MARK-CRITICAL\n")
        result = self.scan(env=self.env)
        self.assertEqual(
            (result.stdout, result.returncode),
            ("🛡️ security 50 % (medusa: 1 finding in 1 file: critical app.py:2)\n", 1),
        )

    def test_one_acceptance_never_hides_an_identical_line_elsewhere(self):
        twin = "x = fetch(url)  # MARK-HIGH"
        self.write("app.py", f"print(1)\n{twin}\ny = 2\n{twin}\n")
        sha1 = hashlib.sha1(twin.encode()).hexdigest()
        both = ("🛡️ security 50 % (medusa: 2 findings in 1 file: high app.py:2, high app.py:4)\n", 3)
        listing = self.base / "council" / "security-accepted.jsonl"
        listing.parent.mkdir(parents=True)
        listing.write_text(json.dumps({"rule": "FAKE-HIGH", "path": "app.py", "sha1": sha1}) + "\n", encoding="utf-8")
        result = self.scan(env=self.env)
        self.assertEqual((result.stdout, result.returncode), both)
        listing.unlink()
        refused = self.accept("--rule", "FAKE-HIGH", "--path", "app.py", "--sha1", sha1, "--reason", "fixture")
        self.assertEqual(refused.returncode, 2)
        self.assertIn("the line occurs 2 times in app.py; name the reviewed one with --line", refused.stderr)
        self.assertFalse(listing.exists())
        wrong = self.accept("--rule", "FAKE-HIGH", "--path", "app.py", "--sha1", sha1, "--line", "3", "--reason", "fixture")
        self.assertEqual(wrong.returncode, 2)
        self.assertIn("--sha1 is not the sha1 of line 3 of app.py", wrong.stderr)
        named = self.accept("--rule", "FAKE-HIGH", "--path", "app.py", "--sha1", sha1, "--line", "4", "--reason", "fixture")
        self.assertEqual(named.returncode, 0, named.stderr)
        result = self.scan(env=self.env)
        self.assertEqual(
            (result.stdout, result.returncode),
            ("🛡️ security 75 % (medusa: 1 finding, 1 accepted in 1 file: high app.py:2)\n", 3),
        )
        self.write("app.py", f"print(1)\n{twin}\ny = 3\n{twin}\n")
        result = self.scan(env=self.env)
        self.assertEqual((result.stdout, result.returncode), both)

    def test_kept_rows_count_and_broken_rows_stop(self):
        line = "y = other()  # MARK-HIGH"
        self.write("app.py", f"{line}\n")
        kept = self.base / ".local" / "state" / "agents-council" / "security-accepted.jsonl"
        kept.parent.mkdir(parents=True)
        sha1 = hashlib.sha1(line.encode()).hexdigest()
        kept.write_text(json.dumps({"rule": "FAKE-HIGH", "path": "app.py", "sha1": sha1}) + "\n", encoding="utf-8")
        result = self.scan(env=self.env)
        self.assertEqual(result.stdout, "🛡️ security 100 % (medusa: 0 findings, 1 accepted in 1 file)\n")
        kept.write_text('{"rule": "FAKE-HIGH"}\n', encoding="utf-8")
        result = self.scan(env=self.env)
        self.assertEqual(result.returncode, 2)
        self.assertIn("security-accepted.jsonl:1: want a JSON row with rule, path and sha1", result.stderr)
        result = self.accept("--rule", "R", "--path", "app.py", "--sha1", "XYZ", "--reason", "r")
        self.assertEqual(result.returncode, 2)
        self.assertIn("--sha1 must be 40 lowercase hex digits", result.stderr)

    def test_a_file_level_finding_is_accepted_by_the_sha1_of_its_file_until_the_file_changes(self):
        text = "FROM debian  # MARK-FILE\n"
        self.write("Dockerfile", text)
        sha1 = hashlib.sha1(text.encode()).hexdigest()
        self.assertEqual(json.loads(self.scan("--json", env=self.env).stdout)["findings"][0]["sha1"], sha1)
        result = self.accept("--rule", "FAKE-FILE", "--path", "Dockerfile", "--sha1", sha1, "--reason", "fixture")
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.scan(env=self.env)
        self.assertEqual(result.stdout, "🛡️ security 100 % (medusa: 0 findings, 1 accepted in 1 file)\n")
        self.write("Dockerfile", text + "USER app\n")
        self.assertEqual(self.scan(env=self.env).returncode, 3)

    def test_one_accept_takes_every_rule_of_a_line(self):
        line = "z = both()  # MARK-HIGH MARK-LOW"
        self.write("app.py", f"{line}\n")
        sha1 = hashlib.sha1(line.encode()).hexdigest()
        result = self.accept(
            "--rule", "FAKE-HIGH", "--rule", "FAKE-LOW", "--path", "app.py", "--sha1", sha1, "--reason", "fixture"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("accepted FAKE-HIGH, FAKE-LOW app.py", result.stdout)
        result = self.scan(env=self.env)
        self.assertEqual(result.stdout, "🛡️ security 100 % (medusa: 0 findings, 2 accepted in 1 file)\n")

    def test_mjs_and_cjs_files_medusa_skips_are_scanned_and_reported_at_their_repository_path(self):
        line = "run(request.query)  // MARK-HIGH"
        self.write("tool.mjs", f"import run from 'run';\n{line}\n")
        result = self.scan(env=self.env)
        self.assertEqual(
            (result.stdout, result.returncode),
            ("🛡️ security 75 % (medusa: 1 finding in 1 file: high tool.mjs:2)\n", 3),
        )
        sha1 = hashlib.sha1(line.encode()).hexdigest()
        result = self.accept(
            "--rule", "FAKE-HIGH", "--path", "tool.mjs", "--sha1", sha1, "--line", "2", "--reason", "fixture"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.write("tool.mjs.js", "a  // MARK-MEDIUM\n")
        self.write("lib.CJS", "b  // MARK-LOW\n")
        result = self.scan(env=self.env)
        self.assertEqual(
            (result.stdout, result.returncode),
            ("🛡️ security 88 % (medusa: 2 findings, 1 accepted in 3 files: medium tool.mjs.js:1, low lib.CJS:1)\n", 3),
        )

    def test_a_folder_named_like_the_alias_keeps_both_paths_apart(self):
        self.write("tool.mjs", "a  // MARK-HIGH\n")
        self.write("tool.mjs.js/inner.py", "b  # MARK-LOW\n")
        result = self.scan(env=self.env)
        self.assertEqual(
            (result.stdout, result.returncode),
            ("🛡️ security 73 % (medusa: 2 findings in 2 files: high tool.mjs:1, low tool.mjs.js/inner.py:1)\n", 3),
        )

    def test_the_cache_keeps_the_repository_path_of_an_aliased_file(self):
        text = "a  // MARK-HIGH\n"
        self.write("tool.mjs", text)
        first = json.loads(self.scan("--json", env=self.env).stdout)
        (self.repo / "tool.mjs").unlink()
        self.write("tool.mjs.js", text)
        second = json.loads(self.scan("--json", env=self.env).stdout)
        self.assertEqual([f["path"] for f in first["findings"] + second["findings"]], ["tool.mjs", "tool.mjs.js"])

    def test_a_nested_mjs_file_is_reported_at_its_nested_path(self):
        self.write("a/b/tool.mjs", "a  // MARK-MEDIUM\n")
        result = self.scan(env=self.env)
        self.assertEqual(
            (result.stdout, result.returncode),
            ("🛡️ security 90 % (medusa: 1 finding in 1 file: medium a/b/tool.mjs:1)\n", 3),
        )

    def test_an_mjs_file_name_without_room_for_the_alias_is_scanned_under_a_short_one(self):
        name = "t" * 250 + ".mjs"
        self.write(name, "a  // MARK-LOW\n")
        found = json.loads(self.scan("--json", env=self.env).stdout)
        self.assertEqual((found["files"], [(f["path"], f["line"]) for f in found["findings"]]), (1, [(name, 1)]))

    def test_an_mjs_only_diff_scores_from_a_real_scan_and_only_a_complete_run_is_cached(self):
        argv = self.bin / "argv.json"
        folder = self.base / "council" / "security-cache"
        self.write("tool.mjs", "a  // MARK-HIGH\n")
        rerun = "medusa run incomplete, nothing cached, rerun once the host is idle"
        timeout = "1 scanner error(s)/timeout(s) during scan: JavaScriptScanner (1)"
        cases = (
            ({"FAKE_MEDUSA_STDOUT": f"⚠️  {timeout}\n"}, f"{rerun}: {timeout}"),
            ({"FAKE_MEDUSA_FILE_LIMIT": "4"}, f"{rerun}: medusa counted 0 of 2 lines"),
        )
        for extra, problem in cases:
            with self.subTest(problem=problem):
                argv.unlink(missing_ok=True)
                result = self.scan(env={**self.env, **extra})
                self.assertEqual((result.stdout, result.returncode), (f"🛡️ security – ({problem}: {HAND})\n", 4))
                self.assertTrue(argv.exists())
                self.assertEqual(list(folder.glob("*.json")), [])
        scored = ("🛡️ security 75 % (medusa: 1 finding in 1 file: high tool.mjs:1)\n", 3)
        argv.unlink()
        result = self.scan(env=self.env)
        self.assertEqual((result.stdout, result.returncode), scored)
        self.assertTrue(argv.exists())
        self.assertEqual(len(list(folder.glob("*.json"))), 1)
        argv.unlink()
        result = self.scan(env=self.env)
        self.assertEqual((result.stdout, result.returncode), scored)
        self.assertFalse(argv.exists())

    def test_critical_exits_1_and_floors_at_0(self):
        self.write("app.py", "a  # MARK-CRITICAL\nb  # MARK-CRITICAL\nc  # MARK-CRITICAL\n")
        result = self.scan(env=self.env)
        self.assertTrue(result.stdout.startswith("🛡️ security 0 % (medusa: 3 findings in 1 file: critical app.py:1, "))
        self.assertEqual(result.returncode, 1)

    def test_more_than_five_locations_are_cut(self):
        self.write("app.py", "".join(f"v{n}  # MARK-LOW\n" for n in range(7)))
        result = self.scan(env=self.env)
        self.assertEqual(
            result.stdout,
            "🛡️ security 86 % (medusa: 7 findings in 1 file: low app.py:1, low app.py:2, low app.py:3, "
            "low app.py:4, low app.py:5, +2 more)\n",
        )
        self.assertEqual(result.returncode, 3)

    def test_clean_and_empty_changes_are_100(self):
        result = self.scan(env=self.env)
        self.assertEqual((result.stdout, result.returncode), ("🛡️ security 100 % (medusa: 0 findings in 0 files)\n", 0))
        self.assertFalse((self.bin / "argv.json").exists())
        self.write("app.py", "print(2)\n")
        result = self.scan(env=self.env)
        self.assertEqual((result.stdout, result.returncode), ("🛡️ security 100 % (medusa: 0 findings in 1 file)\n", 0))

    def test_missing_medusa_asks_for_a_review_by_hand(self):
        if shutil.which("medusa", path=GIT_DIR):
            self.skipTest("a real medusa sits next to git")
        self.write("app.py", "print(2)\n")
        result = self.scan(env={**self.env, "PATH": GIT_DIR})
        self.assertEqual((result.stdout, result.returncode), (f"🛡️ security – (medusa missing: {HAND})\n", 4))
        result = self.scan("--json", env={**self.env, "PATH": GIT_DIR})
        self.assertEqual(json.loads(result.stdout), {"security": None, "problem": "medusa missing"})

    def test_unreadable_report_asks_for_a_review_by_hand(self):
        self.write("app.py", "print(2)\n")
        result = self.scan(env={**self.env, "FAKE_MEDUSA_SHAPE": "other"})
        self.assertEqual(result.returncode, 4)
        self.assertRegex(result.stdout, r"^🛡️ security – \(medusa report unreadable: .*holds no findings list")

    def test_a_rescan_of_unchanged_files_reads_the_cache_and_any_edit_runs_medusa_again(self):
        self.write("app.py", "print(1)\nx = 1  # MARK-HIGH\n")
        argv = self.bin / "argv.json"
        first = self.scan("--json", env=self.env)
        self.assertTrue(argv.exists())
        argv.unlink()
        again = self.scan("--json", env=self.env)
        self.assertEqual((again.stdout, again.returncode), (first.stdout, first.returncode))
        self.assertFalse(argv.exists())
        self.assertEqual(len(list((self.base / "council" / "security-cache").glob("*.json"))), 1)
        self.write("app.py", "print(1)\nx = 2  # MARK-HIGH\n")
        edited = self.scan("--json", env=self.env)
        self.assertTrue(argv.exists())
        self.assertNotEqual(json.loads(edited.stdout)["findings"][0]["sha1"], json.loads(first.stdout)["findings"][0]["sha1"])
        argv.unlink()
        (self.repo / "app.py").chmod(0o755)
        self.scan(env=self.env)
        self.assertTrue(argv.exists())
        argv.unlink()
        medusa = self.bin / "medusa"
        os.utime(medusa, ns=(medusa.stat().st_atime_ns, medusa.stat().st_mtime_ns + 1))
        self.scan(env=self.env)
        self.assertTrue(argv.exists())
        argv.unlink()
        self.scan(env={**self.env, "MEDUSA_TRACE_RULES": "1"})
        self.assertTrue(argv.exists())

    def test_an_expired_tampered_or_shared_cache_runs_medusa(self):
        self.write("app.py", "print(2)\n")
        argv = self.bin / "argv.json"
        folder = self.base / "council" / "security-cache"
        self.scan(env=self.env)
        [entry] = folder.glob("*.json")
        os.utime(entry, (0, 0))
        argv.unlink()
        self.scan(env=self.env)
        self.assertTrue(argv.exists())
        self.assertEqual(list(folder.glob("*.json")), [entry])
        self.assertGreater(entry.stat().st_mtime, 0)
        entry.write_text('[{"severity": "none"}]', encoding="utf-8")
        argv.unlink()
        result = self.scan(env=self.env)
        self.assertTrue(argv.exists())
        self.assertEqual(result.stdout, "🛡️ security 100 % (medusa: 0 findings in 1 file)\n")
        folder.chmod(0o777)
        entry.unlink()
        argv.unlink()
        self.scan(env=self.env)
        self.assertTrue(argv.exists())
        self.assertEqual(list(folder.glob("*.json")), [])

    def test_an_incomplete_run_is_never_cached_and_never_scored(self):
        self.write("app.py", "print(2)\n")
        argv = self.bin / "argv.json"
        folder = self.base / "council" / "security-cache"
        warn = "⚠️  "
        rerun = "medusa run incomplete, nothing cached, rerun once the host is idle"
        cases = (
            ({"FAKE_MEDUSA_STDOUT": f"Found 1 scannable files\n{warn}1 scanner error(s)/timeout(s) during scan: "
              "OWASPLLMScanner (1)\n"}, f"{rerun}: 1 scanner error(s)/timeout(s) during scan: OWASPLLMScanner (1)"),
            ({"FAKE_MEDUSA_STDOUT": f"{warn}1 director(ies) could not be read and were skipped (e.g. TREE/locked)\n"},
             f"{rerun}: 1 director(ies) could not be read and were skipped (e.g. locked)"),
            ({"FAKE_MEDUSA_EXIT": "3"}, f"{rerun}: medusa exit 3"),
            ({"FAKE_MEDUSA_FILE_LIMIT": "4"}, f"{rerun}: medusa counted 0 of 2 lines"),
            ({"FAKE_MEDUSA_SHAPE": "nocounts"},
             ("medusa report unreadable: medusa-scan-20261104-120000.json holds no files_scanned and lines_scanned "
              "counts (medusa exit 0)")),
        )
        for extra, problem in cases:
            with self.subTest(problem=problem):
                result = self.scan(env={**self.env, **extra})
                self.assertEqual((result.stdout, result.returncode), (f"🛡️ security – ({problem}: {HAND})\n", 4))
                self.assertEqual(list(folder.glob("*.json")), [])
        result = self.scan("--json", env={**self.env, "FAKE_MEDUSA_EXIT": "3"})
        self.assertEqual(json.loads(result.stdout), {"security": None, "problem": f"{rerun}: medusa exit 3"})
        argv.unlink()
        complete = self.scan(env=self.env)
        self.assertEqual((complete.stdout, complete.returncode), ("🛡️ security 100 % (medusa: 0 findings in 1 file)\n", 0))
        self.assertTrue(argv.exists())
        self.assertEqual(len(list(folder.glob("*.json"))), 1)
        argv.unlink()
        again = self.scan(env=self.env)
        self.assertEqual((again.stdout, again.returncode), (complete.stdout, complete.returncode))
        self.assertFalse(argv.exists())

    def test_a_file_medusa_never_covers_is_named_with_its_limit_and_never_cached(self):
        argv = self.bin / "argv.json"
        folder = self.base / "council" / "security-cache"
        never = "medusa never covers this diff, nothing cached"
        big = "x = 1  # MARK-CRITICAL\n" + "#" * (2 * 1024 * 1024) + "\n"
        cases = (
            ({"big.json": big}, {}, f"{never}: big.json has {len(big)} bytes, over medusa's 2097152 byte file limit", False),
            ({"long.py": "x\n" * 50_000 + "y = 1  # MARK-CRITICAL\n"}, {},
             f"{never}: long.py has 50002 lines, over medusa's 50000 line regex limit", False),
            ({"cr.py": "x\r" * 50_000 + "y = 1  # MARK-CRITICAL\r"}, {},
             f"{never}: cr.py has 50002 lines, over medusa's 50000 line regex limit", False),
            ({"new.py": "x = 1  # MARK-CRITICAL\n"}, {"FAKE_MEDUSA_LOSE": "new.py"},
             f"{never}: medusa took up 1 of 2 files its rules take up", True),
            ({}, {"FAKE_MEDUSA_STDOUT": "⚠️  Skipped TREE/app.py (3 MB exceeds 2 MB limit)\n"},
             f"{never}: Skipped app.py (3 MB exceeds 2 MB limit)", True),
        )
        self.write("app.py", "print(2)\n")
        for files, extra, problem, ran in cases:
            with self.subTest(problem=problem):
                argv.unlink(missing_ok=True)
                for name, text in files.items():
                    self.write(name, text)
                result = self.scan(env={**self.env, **extra})
                self.assertEqual((result.stdout, result.returncode), (f"🛡️ security – ({problem}: {HAND})\n", 4))
                self.assertEqual(argv.exists(), ran)
                self.assertEqual(list(folder.glob("*.json")), [])
                for name in files:
                    (self.repo / name).unlink()

    def test_a_type_medusa_never_scans_is_listed_and_the_rest_scored(self):
        argv = self.bin / "argv.json"
        self.write("tpl.conf.j2", "token  # MARK-CRITICAL\n")
        never = "medusa never covers this diff, nothing cached"
        result = self.scan(env=self.env)
        self.assertEqual((result.stdout, result.returncode), (
            f"🛡️ security – ({never}: medusa scans none of its files, not covered: tpl.conf.j2: {HAND})\n", 4,
        ))
        self.assertFalse(argv.exists())
        self.write("app.py", "print(1)\nx = 1  # MARK-HIGH\n")
        scored = ("🛡️ security 75 % (medusa: 1 finding in 1 file: high app.py:2; not covered: tpl.conf.j2)\n", 3)
        result = self.scan(env=self.env)
        self.assertEqual((result.stdout, result.returncode), scored)
        argv.unlink()
        result = self.scan(env=self.env)
        self.assertEqual((result.stdout, result.returncode), scored)
        self.assertFalse(argv.exists())
        found = json.loads(self.scan("--json", env=self.env).stdout)
        self.assertEqual((found["files"], found["not_covered"]), (1, ["tpl.conf.j2"]))
        self.medusa.write_text(FAKE.format(shebang="/usr/bin/env -S python -E"), encoding="utf-8")
        result = self.scan(env=self.env)
        self.assertEqual((result.stdout, result.returncode), scored)
        self.assertTrue(argv.exists())
        (self.package / "scanners" / "base.py").unlink()
        result = self.scan(env=self.env)
        unread = f"{never}: medusa's own types, exclusions and limits are unreadable from its source: {HAND}"
        self.assertEqual((result.stdout, result.returncode), (f"🛡️ security – ({unread})\n", 4))

    def test_a_file_behind_a_symlinked_folder_is_never_copied(self):
        self.write("dir/a.py", "x = 1\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "dir")
        outside = self.base / "outside"
        outside.mkdir()
        (outside / "a.py").write_text("secret = 1  # MARK-CRITICAL\n", encoding="utf-8")
        shutil.rmtree(self.repo / "dir")
        (self.repo / "dir").symlink_to(outside)
        self.write("app.py", "print(1)\nx = 1  # MARK-LOW\n")
        found = json.loads(self.scan("--json", env=self.env).stdout)
        self.assertEqual(([(f["path"], f["severity"]) for f in found["findings"]], found["files"]), ([("app.py", "low")], 1))

    def test_a_file_a_path_exclusion_drops_is_scanned_and_named_at_its_repository_path(self):
        self.write("app.py", "print(1)\nx = 1  # MARK-HIGH\n")
        self.write("utils/env/run.py", "y = 1  # MARK-LOW\n")
        self.write("environ.py", "z = 1  # MARK-LOW\n")
        self.write("build/lib.min.js", "a  // MARK-CRITICAL\n")
        found = json.loads(self.scan("--json", env=self.env).stdout)
        self.assertEqual(
            sorted((f["path"], f["line"], f["severity"]) for f in found["findings"]),
            [("app.py", 2, "high"), ("environ.py", 1, "low"), ("utils/env/run.py", 1, "low")],
        )
        self.assertEqual((found["files"], found["not_covered"]), (3, ["build/lib.min.js"]))
        sha1 = next(f["sha1"] for f in found["findings"] if f["path"] == "utils/env/run.py")
        accepted = self.accept("--rule", "FAKE-LOW", "--path", "utils/env/run.py", "--sha1", sha1, "--reason", "fixture")
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        again = json.loads(self.scan("--json", env=self.env).stdout)
        self.assertEqual(sorted(f["path"] for f in again["findings"]), ["app.py", "environ.py"])

    def test_medusa_limits_come_from_its_source(self):
        mark = "y = 1  # MARK-CRITICAL\n"
        cases = (
            (("64", "50_000"), ("64", "50000"), "wide.py", "#" * 70 + "\n" + mark,
             "wide.py has 94 bytes, over medusa's 64 byte file limit"),
            (("2 * 1024", "100"), ("2048", "100"), "tall.py", "\n" * 120 + mark,
             "tall.py has 122 lines, over medusa's 100 line regex limit"),
        )
        for (size, lines), (fake_size, fake_lines), name, text, problem in cases:
            with self.subTest(problem=problem):
                self.limits(size=size, lines=lines)
                self.write(name, text)
                fake = {"FAKE_MEDUSA_FILE_LIMIT": fake_size, "FAKE_MEDUSA_LINE_LIMIT": fake_lines}
                result = self.scan(env={**self.env, **fake})
                self.assertEqual(
                    (result.stdout, result.returncode),
                    (f"🛡️ security – (medusa never covers this diff, nothing cached: {problem}: {HAND})\n", 4),
                )
                (self.repo / name).unlink()

    def test_the_scanner_timeout_reaches_medusa_in_place_of_the_callers_and_takes_whole_seconds_only(self):
        spec = importlib.util.spec_from_file_location("kvb_check_security", SECURITY)
        security = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(security)
        knob = self.bin / "timeout.txt"
        cases = (((), str(security.TIMEOUT)), (("--timeout", "86400"), "86400"))
        for number, (extra, handed) in enumerate(cases, 2):
            with self.subTest(handed=handed):
                self.write("app.py", f"print({number})\n")
                result = self.scan(*extra, env={**self.env, "MEDUSA_SCANNER_TIMEOUT": "5"})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(knob.read_text(encoding="utf-8"), handed)
        for flag in ("--timeout", "--deadline"):
            for value in ("0", "-1", "1.5", "x", "86401"):
                with self.subTest(flag=flag, value=value):
                    result = self.scan(flag, value, env=self.env)
                    self.assertEqual(result.returncode, 2)
                    self.assertIn(f"want whole seconds from 1 to 86400, got {value!r}", result.stderr)

    def test_a_scanner_fault_claims_no_cause_medusa_cannot_tell_apart(self):
        self.write("app.py", "print(2)\n")
        timed = "1 scanner error(s)/timeout(s) during scan: ModelAttackScanner (1)"
        unread = "1 director(ies) could not be read and were skipped (e.g. locked)"
        capped = (
            "a scanner crashed or hit medusa's fixed 2 s cap (medusa counts both together): rerun when idle; "
            "if it repeats, give medusa the MEDUSA_SCANNER_TIMEOUT knob"
        )
        erred = "scanner error (no scanner reached the 2 s cap): rerun when idle"
        rerun = "rerun once the host is idle"
        cases = (
            ("2", "2.2", timed, capped),
            ("2", "0", timed, erred),
            ("2", "2.2", unread, rerun),
            ("config.scanner_timeout()", "2.2", timed, rerun),
        )
        for timeout, sleep, line, advice in cases:
            with self.subTest(timeout=timeout, sleep=sleep, line=line):
                self.limits(timeout=timeout)
                result = self.scan(env={**self.env, "FAKE_MEDUSA_STDOUT": f"⚠️  {line}\n", "FAKE_MEDUSA_SLEEP": sleep})
                problem = f"medusa run incomplete, nothing cached, {advice}: {line}"
                self.assertEqual((result.stdout, result.returncode), (f"🛡️ security – ({problem}: {HAND})\n", 4))

    def test_a_medusa_run_past_the_deadline_takes_its_whole_group_and_names_the_flag_to_raise(self):
        self.write("app.py", "print(2)\n")
        start = time.monotonic()
        result = self.scan("--deadline", "1", env={**self.env, "FAKE_MEDUSA_SLEEP": "30", "FAKE_MEDUSA_CHILD": "1"})
        self.assertLess(time.monotonic() - start, 8)
        problem = (
            "medusa run incomplete, nothing cached, medusa ran past its 1 s --deadline: "
            "rerun it in the background with --deadline raised, up to 86400"
        )
        self.assertEqual((result.stdout, result.returncode), (f"🛡️ security – ({problem}: {HAND})\n", 4))
        self.assertTrue(all(gone(pid) for pid in self.started()))
        self.assertEqual(list((self.base / "council" / "security-cache").glob("*.json")), [])

    def test_a_stop_signal_to_security_py_takes_medusa_and_its_child_along(self):
        self.write("app.py", "print(2)\n")
        env = {**self.env, "FAKE_MEDUSA_SLEEP": "30", "FAKE_MEDUSA_CHILD": "1"}
        for number in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP, signal.SIGKILL):
            with self.subTest(signal=number.name):
                for name in ("pid.txt", "child.txt"):
                    (self.bin / name).unlink(missing_ok=True)
                security = subprocess.Popen(
                    [sys.executable, str(SECURITY), "--repo", str(self.repo), "--base", "HEAD"], cwd=self.base,
                    env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
                )
                medusa, child = self.started()
                os.killpg(security.pid, number)
                self.assertEqual(security.wait(timeout=20), -number)
                self.assertTrue(gone(medusa))
                if number != signal.SIGKILL:
                    self.assertTrue(gone(child))

    def test_the_cache_key_holds_the_timeout_medusa_got_not_the_callers(self):
        self.write("app.py", "print(2)\n")
        argv = self.bin / "argv.json"
        self.scan(env={**self.env, "MEDUSA_SCANNER_TIMEOUT": "5"})
        argv.unlink()
        self.scan(env={**self.env, "MEDUSA_SCANNER_TIMEOUT": "6"})
        self.assertFalse(argv.exists())
        self.scan("--timeout", "7", env=self.env)
        self.assertTrue(argv.exists())

    def test_signals_the_caller_ignores_stay_ignored_and_the_scan_scores(self):
        self.write("app.py", "print(2)\n")
        ignored = (signal.SIGHUP, signal.SIGINT)
        previous = {number: signal.signal(number, signal.SIG_IGN) for number in ignored}
        try:
            security = subprocess.Popen(
                [sys.executable, str(SECURITY), "--repo", str(self.repo), "--base", "HEAD"], cwd=self.base,
                env={**self.env, "FAKE_MEDUSA_SLEEP": "2"}, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, start_new_session=True,
            )
        finally:
            for number, handler in previous.items():
                signal.signal(number, handler)
        self.started("pid.txt")
        for number in ignored:
            os.killpg(security.pid, number)
        out, _ = security.communicate(timeout=20)
        self.assertEqual((out, security.returncode), ("🛡️ security 100 % (medusa: 0 findings in 1 file)\n", 0))

    def test_the_first_stop_signal_ignores_the_others_and_kills_the_group(self):
        spec = importlib.util.spec_from_file_location("kvb_check_security_halt", SECURITY)
        security = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(security)
        for number in security.STOPS:
            self.addCleanup(signal.signal, number, signal.signal(number, signal.default_int_handler))
        sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
        self.addCleanup(ended, [sleeper.pid])
        security.halt([sleeper.pid], security.STOPS)
        self.assertEqual([signal.getsignal(number) for number in security.STOPS], [signal.SIG_IGN] * len(security.STOPS))
        self.assertEqual(sleeper.wait(timeout=10), -signal.SIGKILL)

    def test_a_libc_without_prctl_only_loses_the_parent_death_signal(self):
        self.write("app.py", "print(2)\n")
        wrap = (
            "import ctypes, runpy, sys; ctypes.CDLL = lambda *args, **kwargs: object(); "
            "sys.argv = sys.argv[1:]; runpy.run_path(sys.argv[0], run_name='__main__')"
        )
        result = subprocess.run(
            [sys.executable, "-c", wrap, str(SECURITY), "--repo", str(self.repo), "--base", "HEAD"],
            cwd=self.base, env=self.env, capture_output=True, text=True, check=False,
        )
        self.assertEqual(
            (result.stdout, result.returncode), ("🛡️ security 100 % (medusa: 0 findings in 1 file)\n", 0), result.stderr,
        )

    def test_usage_errors_exit_2(self):
        result = subprocess.run(
            [sys.executable, str(SECURITY), "--repo", str(self.repo), "--base", "nope"],
            env=self.env, capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 2)
        result = subprocess.run(
            [sys.executable, str(SECURITY), "--repo", str(self.base / "absent"), "--base", "HEAD"],
            env=self.env, capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
