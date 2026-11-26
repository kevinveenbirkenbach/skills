from __future__ import annotations

import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "skills" / "kvb-agent-optimize" / "scripts" / "graph.py"
GIT = shutil.which("git")
TASK = "work/code-graph-index"
NOTICE = "codebase-memory-mcp: no permanent daemon; run: systemctl --user enable --now kvb-code-graph.service"
PENDING = "codebase-memory-mcp: kvb-code-graph.service starts the permanent daemon within 120 s after the last session ends; nothing to do"
STUCK = "codebase-memory-mcp: no daemon although kvb-code-graph.service is active; check: journalctl --user -u kvb-code-graph.service"
FAKE_BINARY = """import json, os, sys, time
refused = {"refuse": "async", "vanish": "status"}
daemon_file = os.environ.get("FAKE_DAEMON_FILE")
mode = open(daemon_file).read().strip() if daemon_file else os.environ.get("FAKE_DAEMON", "none")
def log(entry):
    with open(os.environ["FAKE_SERVER_LOG"], "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\\n")
if sys.argv[1:] == ["daemon", "start"]:
    log({"daemon": "start"})
    if daemon_file and mode != "session":
        open(daemon_file, "w").write("permanent")
    sys.exit(0)
if sys.argv[1:] == ["daemon", "status"]:
    lines = {
        "permanent": "daemon: active (permanent)",
        "session": "daemon: active (session-managed)",
        "other": "daemon: up, pid 7",
    }
    print(lines.get(mode, "daemon: not running"))
    sys.exit(0 if mode in lines else 1)
log({"cwd": os.getcwd()})
server = os.environ.get("FAKE_SERVER", "block")
if server == "block":
    deadline = time.time() + 30
    while not os.path.exists(os.environ["FAKE_RELEASE"]) and time.time() < deadline:
        time.sleep(0.05)
    sys.exit(0)
for line in sys.stdin:
    request = json.loads(line)
    params = request.get("params") or {}
    log({"method": request.get("method"), "name": params.get("name"), "arguments": params.get("arguments")})
    if "id" not in request or server == "silent":
        continue
    result = {"protocolVersion": "2025-06-18", "capabilities": {}}
    if request["method"] == "tools/call" and refused.get(server) == ("status" if params["arguments"].get("status") else "async"):
        result = {"content": [{"type": "text", "text": "daemon index job limit reached; async requests do not queue"}], "isError": True}
    elif request["method"] == "tools/call":
        arguments = params["arguments"]
        state = "queued"
        if arguments.get("status"):
            state = {"serve": "succeeded", "fail": "failed", "running": "running"}[server]
            if state == "succeeded":
                open(os.path.join(os.environ["CBM_CACHE_DIR"], os.environ["FAKE_PROJECT"] + ".db"), "w").close()
        result = {"content": [{"type": "text", "text": json.dumps({"state": state})}]}
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)
"""
FAKE_SYSTEMCTL = """#!/bin/sh
echo "$*" >> "$FAKE_SYSTEMCTL_LOG"
if [ "$2" = is-active ]; then
  if [ "$FAKE_UNIT" = active ]; then echo active; exit 0; fi
  echo inactive
  exit 3
fi
exit 0
"""
FAKE_WATCH = """import os, sys
with open(os.environ["FAKE_WATCH_LOG"], "a", encoding="utf-8") as log:
    log.write(" ".join(sys.argv[1:]) + "\\n")
if sys.argv[1:] != ["status"]:
    time.sleep(5)
    sys.exit(3)
stage = os.environ.get("FAKE_MEMORY", "ok")
print(f"stage=ok free=100.0GB total=200.0GB samples=3 age=5s memory={stage} (MemAvailable 50 %)")
"""
FAKE_QUEUE = """import json, os, subprocess, sys, time
argv = sys.argv[1:]
with open(os.environ["FAKE_QUEUE_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps(argv) + "\\n")
if "--session" not in argv[:argv.index("--")]:
    sys.exit(2)
if os.environ.get("FAKE_QUEUE_REFUSE") == "1":
    print("queue: work/code-graph-index is no open task of the kvb-org-rasci register", file=sys.stderr)
    sys.exit(2)
if os.environ.get("FAKE_QUEUE_RUN") == "1":
    sys.exit(subprocess.run(argv[argv.index("--") + 1:]).returncode)
deadline = time.time() + 30
while not os.path.exists(os.environ["FAKE_RELEASE"]) and time.time() < deadline:
    time.sleep(0.05)
"""
FAKE_OPERATOR = """import json, os, sys, time
with open(os.environ["FAKE_OPERATOR_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps(sys.argv[1:]) + "\\n")
if "--session" not in sys.argv:
    sys.exit(2)
deadline = time.time() + float(os.environ.get("FAKE_OPERATOR_SLEEP", "0"))
while time.time() < deadline and not os.path.exists(os.environ["FAKE_RELEASE"]):
    time.sleep(0.05)
"""


def load_graph():
    spec = importlib.util.spec_from_file_location("kvb_code_graph", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines() if path.is_file() else []


def wait_for(predicate, seconds: float = 30) -> bool:
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.1)
    return predicate()


@unittest.skipUnless(GIT, "git not installed")
class CodeGraphCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()
        self.release = self.tmp / "release"
        self.addCleanup(self._release)
        self.cache = self.tmp / "cache"
        self.cache.mkdir()
        self.state = self.tmp / "state"
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        self.binary = bin_dir / "codebase-memory-mcp"
        self.binary.write_text(f"#!{sys.executable}\n{FAKE_BINARY}", encoding="utf-8")
        (bin_dir / "systemctl").write_text(FAKE_SYSTEMCTL, encoding="utf-8")
        for tool in self.binary, bin_dir / "systemctl":
            tool.chmod(0o755)
        self.skills = self.tmp / "skills"
        for path, body in (
            ("kvb-org-queue/scripts/queue.py", FAKE_QUEUE),
            ("kvb-org-organize/scripts/watch.py", f"import time\n{FAKE_WATCH}"),
            ("kvb-org-operator/scripts/operator.py", FAKE_OPERATOR),
        ):
            (self.skills / path).parent.mkdir(parents=True)
            (self.skills / path).write_text(body, encoding="utf-8")
        self.unit = self.tmp / ".config" / "systemd" / "user" / "kvb-code-graph.service"
        self.unit.parent.mkdir(parents=True)
        self.unit.write_text("[Unit]\n", encoding="utf-8")
        self.config = self.tmp / "config.json"
        self.write_config({"queue_file_threshold": 5, "queue_task": TASK})
        self.logs = {name: self.tmp / f"{name}.log" for name in ("server", "systemctl", "watch", "queue", "operator")}
        self.env = {
            "PATH": f"{bin_dir}:{os.environ.get('PATH', '/usr/bin:/bin')}",
            "HOME": str(self.tmp),
            "GIT_CEILING_DIRECTORIES": str(self.tmp),
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.org",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.org",
            "CBM_CACHE_DIR": str(self.cache),
            "KVB_CODE_GRAPH_STATE": str(self.state),
            "KVB_CODE_GRAPH_BIN": str(self.binary),
            "KVB_CODE_GRAPH_SKILLS": str(self.skills),
            "KVB_CODE_GRAPH_CONFIG": str(self.config),
            "FAKE_RELEASE": str(self.release),
            "FAKE_SERVER_LOG": str(self.logs["server"]),
            "FAKE_SYSTEMCTL_LOG": str(self.logs["systemctl"]),
            "FAKE_WATCH_LOG": str(self.logs["watch"]),
            "FAKE_QUEUE_LOG": str(self.logs["queue"]),
            "FAKE_OPERATOR_LOG": str(self.logs["operator"]),
            "FAKE_DAEMON": "permanent",
            "FAKE_UNIT": "active",
            "FAKE_MEMORY": "ok",
        }

    def write_config(self, data: dict) -> None:
        self.config.write_text(json.dumps(data), encoding="utf-8")

    def _git(self, cwd: Path, *args: str) -> None:
        subprocess.run([GIT, *args], cwd=cwd, env=self.env, check=True, capture_output=True)

    def _repo(self, name: str, files: int = 1, untracked: int = 0) -> Path:
        repo = self.tmp / name
        (repo / "pkg").mkdir(parents=True)
        for number in range(files):
            (repo / "pkg" / f"m{number}.py").write_text(f"def f{number}():\n    return {number}\n", encoding="utf-8")
        self._git(repo, "init", "-q")
        self._git(repo, "add", ".")
        self._git(repo, "commit", "-q", "-m", "init")
        for number in range(untracked):
            (repo / "pkg" / f"u{number}.py").write_text("x = 1\n", encoding="utf-8")
        return repo

    def _run_hook(self, event: dict, timeout: float = 60, **env: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-I", str(SCRIPT), "hook"],
            input=json.dumps(event),
            capture_output=True,
            text=True,
            env={**self.env, **env},
            check=False,
            timeout=timeout,
        )

    def _hook(self, session: str, cwd: Path, file_path: Path | None = None, **env: str) -> str:
        event = {"session_id": session, "cwd": str(cwd), "tool_name": "Read", "tool_input": {}}
        if file_path:
            event["tool_input"]["file_path"] = str(file_path)
        result = self._run_hook(event, **env)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def _log(self, root: Path, suffix: str = ".log") -> Path:
        return self.state / "logs" / f"{load_graph().project_name(str(root))}{suffix}"

    def _events(self, root: Path, kind: str) -> int:
        return sum(1 for line in lines(self._log(root)) if line.startswith(f"graph: {kind} "))

    def _inflight(self) -> dict:
        path = self.state / "inflight.json"
        return json.loads(path.read_text(encoding="utf-8") or "{}") if path.is_file() else {}

    def _release(self) -> None:
        graph = load_graph()
        with graph.locked_json(self.state / "inflight.json") as inflight:
            helpers = [entry.get("pid") for entry in inflight.values() if isinstance(entry, dict)]
        self.release.touch()
        wait_for(lambda: not any(graph.alive(pid) for pid in helpers), 15)

    def _age_deferred(self, session: str) -> None:
        path = self.state / "sessions" / f"{session}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["deferred"] = {root: stamp - 3600 for root, stamp in data["deferred"].items()}
        path.write_text(json.dumps(data), encoding="utf-8")

    def _queue_calls(self) -> list[list[str]]:
        return [json.loads(line) for line in lines(self.logs["queue"])]

    def _queued(self, expected: int) -> int:
        wait_for(lambda: len(lines(self.logs["queue"])) >= expected, 10)
        time.sleep(0.3)
        return len(lines(self.logs["queue"]))

    def _calls(self) -> list[dict]:
        return [json.loads(line) for line in lines(self.logs["server"])]


class TestCodeGraphHook(CodeGraphCase):
    def test_hook_resolves_git_root(self):
        repo = self._repo("main")
        self._git(repo, "worktree", "add", "-q", str(self.tmp / "linked"))
        library = self._repo("library")
        self.env.update(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="protocol.file.allow", GIT_CONFIG_VALUE_0="always")
        self._git(repo, "submodule", "add", "-q", str(library), "vendor/library")
        isolated = mock.patch.dict(os.environ, {"GIT_CEILING_DIRECTORIES": str(self.tmp), "KVB_CODE_GRAPH_STATE": str(self.state)})
        isolated.start()
        self.addCleanup(isolated.stop)
        graph = load_graph()
        self.assertEqual(graph.git_root(str(repo / "pkg" / "m0.py")), str(repo))
        self.assertEqual(graph.git_root(str(repo / "pkg" / "new" / "missing.py")), str(repo))
        self.assertEqual(graph.git_root(str(self.tmp / "linked" / "pkg" / "m0.py")), str(self.tmp / "linked"))
        self.assertEqual(graph.git_root(str(repo / "vendor" / "library" / "pkg")), str(repo / "vendor" / "library"))

    def test_hook_indexes_once_per_root(self):
        repo = self._repo("main")
        self._hook("s1", repo)
        self._hook("s1", repo, repo / "pkg" / "m0.py")
        self.assertEqual(self._events(repo, "spawn"), 1)
        self._hook("s2", repo)
        self.assertEqual(self._events(repo, "spawn"), 1)

    def test_hook_starts_one_helper_at_a_time_and_every_root_later(self):
        home = self._repo("home")
        other = self._repo("other")
        self._hook("s1", home, other / "pkg" / "m0.py")
        self.assertEqual((self._events(home, "spawn"), self._events(other, "spawn"), self._events(other, "defer")), (1, 0, 1))
        self.release.touch()
        self.assertTrue(wait_for(lambda: "failed_at" in self._inflight().get(str(home), {}), 15))
        self._age_deferred("s1")
        self._hook("s1", home, other / "pkg" / "m0.py")
        self.assertEqual((self._events(home, "spawn"), self._events(other, "spawn")), (1, 1))

    def test_a_read_never_runs_the_repository_fsmonitor(self):
        other = self.tmp / "other"
        other.mkdir()
        evil = self._repo("evil")
        marker = self.tmp / "fsmonitor-ran"
        script = self.tmp / "fsm.sh"
        script.write_text(f'#!/bin/sh\necho "$@" >> "{marker}"\nexit 1\n', encoding="utf-8")
        script.chmod(0o755)
        self._git(evil, "config", "core.fsmonitor", str(script))
        self._hook("s1", other, evil / "pkg" / "m0.py")
        self.assertEqual(self._events(evil, "spawn"), 1)
        self.assertFalse(marker.exists(), lines(marker))

    def test_slow_git_is_bounded_and_runs_once(self):
        repo = self._repo("main")
        count = self.tmp / "ls-files.count"
        wrapper = self.tmp / "slowgit"
        wrapper.mkdir()
        (wrapper / "git").write_text(
            f'#!/bin/sh\ncase "$*" in *ls-files*) echo x >> "{count}"; sleep 8 ;; esac\nexec {GIT} "$@"\n',
            encoding="utf-8",
        )
        (wrapper / "git").chmod(0o755)
        event = {"session_id": "s1", "cwd": str(repo), "tool_name": "Read", "tool_input": {}}
        started = time.monotonic()
        for _ in range(3):
            self.assertEqual(self._run_hook(event, timeout=5, PATH=f"{wrapper}:{self.env['PATH']}").returncode, 0)
        self.assertLess(time.monotonic() - started, 8)
        self.assertEqual((len(lines(count)), self._queued(1)), (1, 1))

    def test_a_stalled_git_root_is_recorded_and_skipped_at_once(self):
        repo = self._repo("fifo")
        fifo = self.tmp / "cfg.fifo"
        os.mkfifo(fifo)
        self._git(repo, "config", "include.path", str(fifo))
        durations = []
        for session in ("s1", "s1", "s1", "s2"):
            started = time.monotonic()
            event = {"session_id": session, "cwd": str(repo), "tool_name": "Read", "tool_input": {"file_path": str(repo / "pkg" / "m0.py")}}
            self.assertEqual(self._run_hook(event, timeout=20).returncode, 0)
            durations.append(round(time.monotonic() - started, 1))
        self.assertLess(max(durations[2:]), 1.0, durations)

    def test_one_slow_rev_parse_does_not_mark_the_root(self):
        repo = self._repo("main")
        count = self.tmp / "rev-parse.count"
        wrapper = self.tmp / "slowgit"
        wrapper.mkdir()
        (wrapper / "git").write_text(
            f'#!/bin/sh\ncase "$*" in *rev-parse*) echo x >> "{count}"; [ "$(wc -l < "{count}")" -eq 1 ] && sleep 8 ;; esac\nexec {GIT} "$@"\n',
            encoding="utf-8",
        )
        (wrapper / "git").chmod(0o755)
        for _ in range(2):
            self._hook("s1", repo, PATH=f"{wrapper}:{self.env['PATH']}")
        self.assertEqual(self._events(repo, "spawn"), 1)
        self.assertEqual(json.loads((self.state / "stalled.json").read_text(encoding="utf-8")), {})

    def test_stalled_json_is_pruned_and_written_only_on_change(self):
        repo = self._repo("main")
        stalls = self.state / "stalled.json"
        stalls.parent.mkdir(parents=True)
        stalls.write_text(json.dumps({"/gone": {"timeouts": 2, "at": time.time() - 7 * 3600}}), encoding="utf-8")
        self._hook("s1", repo)
        self.assertEqual(json.loads(stalls.read_text(encoding="utf-8")), {})
        written = stalls.stat().st_mtime_ns
        self._hook("s1", repo)
        self._hook("s2", repo)
        self.assertEqual(stalls.stat().st_mtime_ns, written)

    def test_hook_defers_what_its_budget_cannot_cover(self):
        repo = self._repo("main")
        graph = load_graph()
        absent = {"FAKE_DAEMON": "none", "FAKE_UNIT": "inactive"}
        event = {"session_id": "s1", "cwd": str(repo), "tool_name": "Read", "tool_input": {}}
        stdout = io.StringIO()
        with (
            mock.patch.dict(os.environ, {**self.env, **absent}),
            mock.patch("sys.stdin", io.StringIO(json.dumps(event))),
            mock.patch("sys.stdout", stdout),
        ):
            graph.STARTED = time.monotonic() - graph.HOOK_BUDGET + graph.GIT_TIMEOUT + 1
            self.assertEqual(graph.cmd_hook(), 0)
        self.assertEqual((stdout.getvalue(), self._events(repo, "spawn"), self._events(repo, "defer")), ("", 0, 1))
        self.assertEqual(json.loads(self._hook("s1", repo, **absent)), {"systemMessage": NOTICE})
        self.assertEqual(self._events(repo, "spawn"), 0)

    def test_nested_repositories_make_the_root_large(self):
        clone = self._repo("clone")
        self._repo("clone/vendor/big")
        gitlink = self._repo("gitlink")
        self._repo("gitlink/vendor/big")
        self._git(gitlink, "add", "vendor/big")
        for number, root in enumerate((clone, gitlink), start=1):
            with self.subTest(root=root.name):
                self._hook("s1", root)
                self.assertEqual((self._events(root, "spawn"), self._events(root, "queue"), self._queued(number)), (0, 1, number))

    def test_hook_skips_indexed_root(self):
        repo = self._repo("main")
        (self.cache / f"{load_graph().project_name(str(repo))}.db").write_bytes(b"")
        self._hook("s1", repo)
        self.assertEqual(self._events(repo, "spawn"), 0)
        self.assertEqual(lines(self.logs["watch"]), [])

    def test_hook_skips_non_git(self):
        plain = self.tmp / "plain"
        plain.mkdir()
        self._hook("s1", plain, plain / "x.py")
        self.assertFalse((self.state / "logs").exists())

    def test_hook_without_session_id_does_nothing(self):
        repo = self._repo("main")
        result = self._run_hook({"cwd": str(repo), "tool_input": {}}, FAKE_DAEMON="none")
        self.assertEqual((result.returncode, result.stdout), (0, ""))
        self.assertEqual((self._events(repo, "spawn"), lines(self.logs["queue"]), lines(self.logs["operator"])), (0, [], []))

    def test_small_root_reads_the_memory_stage_without_admit(self):
        repo = self._repo("main")
        self._hook("s1", repo)
        self.assertEqual(lines(self.logs["watch"]), ["status"])
        self.assertEqual((self._events(repo, "spawn"), lines(self.logs["queue"])), (1, []))

    def test_memory_warn_or_stop_starts_no_small_root(self):
        repo = self._repo("main")
        for number, stage in enumerate(("warn", "stop", "unknown")):
            with self.subTest(stage=stage):
                self._hook(f"s{number}", repo, FAKE_MEMORY=stage)
                self.assertEqual(self._events(repo, "spawn"), 0)

    def test_large_root_is_queued_with_the_session_and_never_admitted(self):
        repo = self._repo("big", files=6)
        self._hook("s1", repo, FAKE_MEMORY="stop")
        self.assertEqual((self._events(repo, "spawn"), self._events(repo, "queue"), self._queued(1)), (0, 1, 1))
        (argv,) = self._queue_calls()
        self.assertEqual(argv[:8], ["hold", "--kind", "test", "--task", TASK, "--session", "s1", "--"])
        self.assertEqual(argv[-6:], [str(SCRIPT), "index", "--root", str(repo), "--mode", "full"])
        self.assertEqual((lines(self.logs["watch"]), lines(self.logs["server"])), ([], []))

    def test_large_root_is_queued_once_for_twenty_sessions(self):
        repo = self._repo("big", files=6)
        with ThreadPoolExecutor(max_workers=10) as pool:
            list(pool.map(lambda number: self._hook(f"s{number}", repo), range(20)))
        self.assertEqual(self._queued(1), 1)
        self.assertEqual(self._events(repo, "spawn"), 0)

    def test_untracked_files_count_toward_the_threshold(self):
        repo = self._repo("main", files=1, untracked=6)
        self._hook("s1", repo)
        self.assertEqual((self._events(repo, "spawn"), self._queued(1)), (0, 1))

    def test_a_repository_with_submodules_is_large(self):
        repo = self._repo("main")
        (repo / ".gitmodules").write_text('[submodule "x"]\n\tpath = x\n\turl = ../x\n', encoding="utf-8")
        self._hook("s1", repo)
        self.assertEqual((self._events(repo, "spawn"), self._queued(1)), (0, 1))

    def test_incomplete_config_starts_nothing_and_says_so_once(self):
        repo = self._repo("main")
        for number, data in enumerate(({}, {"queue_task": TASK}, {"queue_file_threshold": 5}, {"queue_file_threshold": True, "queue_task": TASK})):
            with self.subTest(config=data):
                self.write_config(data)
                message = json.loads(self._hook(f"s{number}", repo))["systemMessage"]
                self.assertIn(str(self.config), message)
                self.assertIn("queue_file_threshold", message)
                self.assertEqual(self._hook(f"s{number}", repo), "")
        self.assertEqual((self._events(repo, "spawn"), self._queue_calls(), lines(self.logs["watch"])), (0, [], []))
        rows = [json.loads(line) for line in lines(self.logs["operator"])]
        self.assertEqual([row[:2] for row in rows], [["add", "kvb-code-graph-config"]])
        self.assertEqual(rows[0][rows[0].index("--check") + 1], "decision")
        self.assertEqual((rows[0].count("--option"), rows[0][rows[0].index("--recommended") + 1]), (2, "Configure"))

    def test_failed_index_backs_off_across_sessions(self):
        repo = self._repo("main")
        project = load_graph().project_name(str(repo))
        self._hook("s1", repo, FAKE_SERVER="fail", FAKE_PROJECT=project)
        self.assertTrue(wait_for(lambda: any(line.endswith(" failed") for line in lines(self._log(repo, ".index.log")))))
        self.assertTrue(wait_for(lambda: "failed_at" in self._inflight().get(str(repo), {}), 10))
        self._hook("s2", repo)
        self.assertEqual(self._events(repo, "spawn"), 1)
        inflight = json.loads((self.state / "inflight.json").read_text(encoding="utf-8"))
        inflight[str(repo)]["failed_at"] -= 7 * 3600
        (self.state / "inflight.json").write_text(json.dumps(inflight), encoding="utf-8")
        self._hook("s3", repo)
        self.assertEqual(self._events(repo, "spawn"), 2)

    def test_refused_queue_hold_backs_off_across_sessions(self):
        repo = self._repo("big", files=6)
        self._hook("s1", repo, FAKE_QUEUE_REFUSE="1")
        inflight = self.state / "inflight.json"
        self.assertTrue(wait_for(lambda: "failed_at" in json.loads(inflight.read_text(encoding="utf-8")).get(str(repo), {}), 10))
        for number in range(2, 5):
            self._hook(f"s{number}", repo, FAKE_QUEUE_REFUSE="1")
        self.assertEqual(self._queued(1), 1)
        self.assertIn("queue exit 2", json.loads(inflight.read_text(encoding="utf-8"))[str(repo)]["state"])

    def test_deferred_root_is_retried_after_the_pause(self):
        repo = self._repo("main")
        self._hook("s1", repo, FAKE_MEMORY="warn")
        self._hook("s1", repo)
        self.assertEqual(self._events(repo, "spawn"), 0)
        self._age_deferred("s1")
        self._hook("s1", repo)
        self.assertEqual(self._events(repo, "spawn"), 1)

    def test_notice_once_per_session_and_one_row(self):
        plain = self.tmp / "plain"
        plain.mkdir()
        absent = {"FAKE_DAEMON": "none", "FAKE_UNIT": "inactive"}
        first = self._hook("s1", plain, **absent)
        self.assertEqual(json.loads(first), {"systemMessage": NOTICE})
        self.assertEqual(self._hook("s1", plain, **absent), "")
        self.assertEqual(self._hook("s2", plain, **absent), first)
        rows = [json.loads(line) for line in lines(self.logs["operator"])]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][:2], ["add", "kvb-code-graph-daemon"])
        self.assertEqual(rows[0][rows[0].index("--check") + 1], "decision")
        self.assertEqual((rows[0].count("--option"), rows[0][rows[0].index("--recommended") + 1]), (2, "Enable"))
        self.assertEqual(rows[0][rows[0].index("--session") + 1], "s1")
        self.assertIn("systemctl --user enable --now kvb-code-graph.service", rows[0])

    def test_notice_survives_a_killed_first_call(self):
        plain = self.tmp / "plain"
        plain.mkdir()
        absent = {"FAKE_DAEMON": "none", "FAKE_UNIT": "inactive"}
        event = {"session_id": "s1", "cwd": str(plain), "tool_input": {}}
        with self.assertRaises(subprocess.TimeoutExpired):
            self._run_hook(event, timeout=3, FAKE_OPERATOR_SLEEP="20", **absent)
        self.assertEqual(json.loads(self._hook("s1", plain, **absent)), {"systemMessage": NOTICE})

    def test_notice_without_an_installed_unit_names_no_unit(self):
        plain = self.tmp / "plain"
        plain.mkdir()
        self.unit.unlink()
        message = json.loads(self._hook("s1", plain, FAKE_DAEMON="none", FAKE_UNIT="inactive"))["systemMessage"]
        self.assertNotIn("systemctl", message)
        self.assertIn("make install", message)
        self.assertEqual(lines(self.logs["operator"]), [])

    def test_notice_silent_with_daemon(self):
        plain = self.tmp / "plain"
        plain.mkdir()
        self.assertEqual(self._hook("s1", plain, FAKE_DAEMON="permanent", FAKE_UNIT="inactive"), "")
        self.assertEqual(self._hook("s2", plain, FAKE_DAEMON="other", FAKE_UNIT="active"), "")
        self.assertEqual(lines(self.logs["operator"]), [])

    def test_notice_names_the_true_remedy_and_rows_only_an_inactive_unit(self):
        plain = self.tmp / "plain"
        plain.mkdir()
        cases = (("session", "active", PENDING), ("none", "active", STUCK), ("session", "inactive", NOTICE), ("other", "inactive", NOTICE))
        for number, (daemon, unit, notice) in enumerate(cases):
            with self.subTest(daemon=daemon, unit=unit):
                self.assertEqual(json.loads(self._hook(f"s{number}", plain, FAKE_DAEMON=daemon, FAKE_UNIT=unit)), {"systemMessage": notice})
                rows = [json.loads(line)[1] for line in lines(self.logs["operator"])]
                self.assertEqual(rows, [] if unit == "active" else ["kvb-code-graph-daemon"])

    def test_hook_never_fails_on_bad_input(self):
        result = subprocess.run(
            [sys.executable, "-I", str(SCRIPT), "hook"],
            input="not json",
            capture_output=True,
            text=True,
            env=self.env,
            check=False,
        )
        self.assertEqual((result.returncode, result.stdout), (0, ""))


class TestCodeGraphHelper(CodeGraphCase):
    def _index(self, repo: Path, *args: str, **env: str) -> tuple[subprocess.CompletedProcess, float]:
        started = time.monotonic()
        result = subprocess.run(
            [sys.executable, "-I", str(SCRIPT), "index", "--root", str(repo), *args],
            capture_output=True,
            text=True,
            env={**self.env, "FAKE_PROJECT": load_graph().project_name(str(repo)), **env},
            check=False,
            timeout=60,
        )
        return result, time.monotonic() - started

    def test_helper_exits_on_a_silent_server(self):
        repo = self._repo("main")
        result, seconds = self._index(repo, "--call-timeout", "1", "--deadline", "30", FAKE_SERVER="silent")
        self.assertEqual(result.returncode, 1)
        self.assertLess(seconds, 10)
        self.assertIn("keeps running", result.stdout)

    def test_helper_enforces_the_overall_deadline(self):
        repo = self._repo("main")
        result, seconds = self._index(repo, "--call-timeout", "5", "--deadline", "3", FAKE_SERVER="running")
        self.assertEqual(result.returncode, 1)
        self.assertLess(seconds, 12)
        self.assertIn("deadline", result.stdout)

    def test_helper_ends_on_a_refused_or_unknown_job(self):
        for server in ("refuse", "vanish"):
            with self.subTest(server=server):
                repo = self._repo(server)
                result, seconds = self._index(repo, "--call-timeout", "5", "--deadline", "30", FAKE_SERVER=server)
                self.assertEqual(result.returncode, 1)
                self.assertLess(seconds, 8)
                self.assertIn("job limit reached", result.stdout)
                self.assertEqual(self._inflight()[str(repo)]["state"], "refused")

    def test_index_helpers_hold_one_slot(self):
        first, second = self._repo("first"), self._repo("second")
        holder = subprocess.Popen(
            [sys.executable, "-I", str(SCRIPT), "index", "--root", str(first), "--call-timeout", "20", "--deadline", "20"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=self.env,
        )
        self.addCleanup(holder.wait)
        self.addCleanup(holder.kill)
        self.assertTrue(wait_for(lambda: {"cwd": str(first)} in self._calls(), 10))
        result, _ = self._index(second, "--deadline", "2")
        self.assertEqual(result.returncode, 1)
        self.assertIn("slot", result.stdout)
        self.assertNotIn({"cwd": str(second)}, self._calls())

    def _supervise(self, *args: str, **env: str) -> tuple[subprocess.CompletedProcess, float]:
        self.logs["server"].unlink(missing_ok=True)
        started = time.monotonic()
        result = subprocess.run(
            [sys.executable, "-I", str(SCRIPT), "supervise", *args],
            capture_output=True, text=True, env={**self.env, **env}, check=False, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result, time.monotonic() - started

    def test_supervisor_starts_a_daemon_only_when_none_or_unknown_runs(self):
        for daemon, starts in (("none", 1), ("other", 1), ("session", 0), ("permanent", 0)):
            with self.subTest(daemon=daemon):
                self._supervise("--rounds", "1", FAKE_DAEMON=daemon)
                self.assertEqual(self._calls().count({"daemon": "start"}), starts)

    def test_supervisor_backs_off_only_failing_starts(self):
        result, seconds = self._supervise("--rounds", "8", "--pause", "0.2", FAKE_DAEMON="none")
        self.assertLess(seconds, 8 * 0.2 + 4)
        self.assertEqual(result.stdout.splitlines(), ["graph: supervise: daemon none"])
        self.assertIn(self._calls().count({"daemon": "start"}), range(3, 8))

    def test_supervisor_takes_over_within_one_round_after_the_session_daemon_ends(self):
        state, output = self.tmp / "daemon-state", self.tmp / "supervise.log"
        state.write_text("session", encoding="utf-8")
        with open(output, "w", encoding="utf-8") as log:
            supervisor = subprocess.Popen(
                [sys.executable, "-I", str(SCRIPT), "supervise", "--pause", "0.5"],
                stdout=log, env={**self.env, "FAKE_DAEMON_FILE": str(state)},
            )
        self.addCleanup(supervisor.wait)
        self.addCleanup(supervisor.kill)
        time.sleep(4)
        state.write_text("none", encoding="utf-8")
        ended = time.monotonic()
        self.assertTrue(wait_for(lambda: state.read_text(encoding="utf-8") == "permanent", 10))
        self.assertLess(time.monotonic() - ended, 1.5)
        expected = ["graph: supervise: daemon session-managed", "graph: supervise: daemon permanent"]
        self.assertTrue(wait_for(lambda: lines(output) == expected, 5), lines(output))


class TestCodeGraphPipeline(CodeGraphCase):
    def _pipeline(self, repo: Path, kind: str, **env: str) -> None:
        env = {"FAKE_SERVER": "serve", "FAKE_PROJECT": load_graph().project_name(str(repo)), **env}
        started = time.monotonic()
        self._hook("s1", repo, **env)
        self.assertLess(time.monotonic() - started, 10)
        graph = self.cache / f"{env['FAKE_PROJECT']}.db"
        log = self._log(repo, ".index.log")
        self.assertTrue(wait_for(graph.exists), lines(log))
        self.assertTrue(wait_for(lambda: any(line.endswith(" succeeded") for line in lines(log)), 15), lines(log))
        self.assertEqual([line.split()[:2] for line in lines(self._log(repo))], [["graph:", kind]])
        calls = self._calls()
        self.assertEqual(calls[0], {"cwd": str(repo)})
        self.assertEqual([call["method"] for call in calls[1:3]], ["initialize", "notifications/initialized"])
        tools = [call["arguments"] for call in calls if call.get("method") == "tools/call"]
        self.assertEqual(tools[0], {"repo_path": str(repo), "async": True, "mode": "full"})
        self.assertEqual(tools[-1], {"repo_path": str(repo), "status": True})
        self.assertTrue(all(call.get("name") == "index_repository" for call in calls if call.get("method") == "tools/call"))
        self.assertTrue(wait_for(lambda: str(repo) not in self._inflight(), 10))

    def test_small_root_hook_helper_server(self):
        repo = self._repo("main")
        self._pipeline(repo, "spawn")
        self.assertEqual(lines(self.logs["queue"]), [])

    def test_large_root_hook_queue_helper_server(self):
        repo = self._repo("big", files=6)
        self._pipeline(repo, "queue", FAKE_QUEUE_RUN="1")
        self.assertEqual(len(self._queue_calls()), 1)


class TestProjectName(unittest.TestCase):
    def test_project_name_matches_upstream(self):
        graph = load_graph()
        cases = {
            "/home/u/Repositories/github.com/u/skills/.worktrees/feature/workbench-w1-operator-tasks":
                "home-u-Repositories-github.com-u-skills-.worktrees-feature-workbench-w1-operator-tasks",
            "/tmp/release-17.0.0": "tmp-release-17.0.0",
            "/home/u/my project//x..y": "home-u-my-project-x.y",
            "/home/u/café": "home-u-cafc3a9",
        }
        for path, name in cases.items():
            with self.subTest(path=path):
                self.assertEqual(graph.project_name(path), name)


if __name__ == "__main__":
    unittest.main()
