from __future__ import annotations

import contextlib
import http.server
import json
import os
import shutil
import subprocess
import threading
from collections.abc import Iterator
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL = REPO_ROOT / "skills" / "kvb-code-review"
LENS_SCRIPTS = {
    "security": "kvb-check-security/scripts/security.py",
    "principles": "kvb-check-principles/scripts/principles.py",
    "performance": "kvb-check-efficiency/scripts/measure.py",
    "queue": "kvb-org-queue/scripts/queue.py",
}
OUTPUTS = {"security": {"security": 100, "findings": []}, "principles": [], "performance": {"efficiency": 90, "speed": 95}, "quality": {"findings": []}}
FAKE = """import json, os, subprocess, sys, time
NAME = {name!r}
with open(os.environ["REVIEW_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps([NAME, time.time(), sys.argv[1:]]) + "\\n")
if NAME == "queue":
    done = subprocess.run(sys.argv[sys.argv.index("--") + 1:], check=False)
    sys.exit(done.returncode)
if NAME == "quality" and sys.argv[1:] == ["--version"]:
    print("quality 0.3.0")
    sys.exit(0)
plan = json.loads(os.environ.get("REVIEW_FAKE", "{{}}")).get(NAME, {{}})
time.sleep(plan.get("sleep", 0))
print(json.dumps(plan.get("out", {default!r})))
sys.exit(plan.get("exit", 0))
"""
GH = """import json, os, sys
print(os.environ.get("GH_PR", ""))
sys.exit(0 if os.environ.get("GH_PR") else 1)
"""
STANDARDS = {
    "AGENTS.md": "# Agents\n\nThe whole agents body sentence that a brief must never carry.\n\n## Comments\n\nNo comments.\n",
    "CONTRIBUTING.md": "# Contributing\n\nRead the docs.\n",
    "docs/contributing/style.md": "# Style\n\n## Names\n\nNames say what a thing is.\n",
    "roles/web-app-x/AGENTS.md": "# Role x\n\nKeep the role small.\n",
}
GIT_ENV = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.org",
           "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.org"}


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, env={**os.environ, **GIT_ENV}, capture_output=True, text=True, check=True).stdout


def install(root: Path, with_quality: bool) -> dict[str, str]:
    """Args:
        root: a scratch folder that becomes a skills root and a bin folder.
        with_quality: whether a fake quality CLI is on PATH.

    Returns:
        The environment review.py runs in: PATH with the fake gh, the log
        every fake lens appends its start to, and the fake plan variable.
    """
    shutil.copytree(SKILL, root / "skills" / "kvb-code-review", ignore=shutil.ignore_patterns("__pycache__"))
    for name, script in LENS_SCRIPTS.items():
        path = root / "skills" / script
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(FAKE.format(name=name, default=OUTPUTS.get(name, {})), encoding="utf-8")
    (root / "skills" / "kvb-check-legal").mkdir(parents=True, exist_ok=True)
    (root / "skills" / "kvb-check-legal" / "checks.md").write_text("# Legal checks\n\n## Licences\n\nCheck them.\n", encoding="utf-8")
    bin_dir = root / "bin"
    bin_dir.mkdir()
    (bin_dir / "gh").write_text(f"#!/usr/bin/python3\n{GH}", encoding="utf-8")
    if with_quality:
        (bin_dir / "quality").write_text(f"#!/usr/bin/python3\n{FAKE.format(name='quality', default=OUTPUTS['quality'])}", encoding="utf-8")
    for tool in bin_dir.iterdir():
        tool.chmod(0o755)
    return {**os.environ, **GIT_ENV, "PATH": f"{bin_dir}:/usr/bin:/bin", "REVIEW_LOG": str(root / "lens.log"), "REVIEW_FAKE": "{}"}


def hub_home(root: Path, env: dict[str, str], port: int) -> dict[str, str]:
    """Returns:
        The environment with HOME at a folder whose installed hub .env
        publishes the port, as review_stamp.hub_port() reads it.
    """
    hub_env = root / "home" / ".local" / "share" / "kvb-orchestrator" / ".env"
    hub_env.parent.mkdir(parents=True, exist_ok=True)
    hub_env.write_text(f"KVB_ORCHESTRATOR_UID=1000\nKVB_ORCHESTRATOR_PORT={port}\n", encoding="utf-8")
    return {**env, "HOME": str(root / "home")}


def fixture(root: Path) -> Path:
    """Returns:
        A repository on master whose upstream origin/master holds the
        standards and src/app.py, with one unpushed commit that changes
        src/app.py and adds roles/web-app-x/tasks.yml.
    """
    remote, repo = root / "remote.git", root / "repo"
    subprocess.run(["git", "init", "--bare", "-b", "master", str(remote)], env={**os.environ, **GIT_ENV}, capture_output=True, check=True)
    repo.mkdir()
    git(repo, "init", "-b", "master")
    for name, text in {**STANDARDS, "src/app.py": "VALUE = 1\nNAME = 'app'\n"}.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "base")
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "-u", "origin", "master")
    change(repo, {"src/app.py": "VALUE = 2\nNAME = 'app'\n", "roles/web-app-x/tasks.yml": "- name: x\n"}, "change")
    return repo


def change(repo: Path, files: dict[str, str], message: str) -> None:
    for name, text in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", message)


def review(root: Path, env: dict[str, str], *args: str) -> subprocess.CompletedProcess:
    script = root / "skills" / "kvb-code-review" / "scripts" / "review.py"
    return subprocess.run(["/usr/bin/python3", "-I", str(script), *args], env=env, capture_output=True, text=True, timeout=120, check=False)


def starts(root: Path) -> list[list]:
    log = root / "lens.log"
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []


@contextlib.contextmanager
def hub(signed: dict[str, tuple[str, str]]) -> Iterator[int]:
    """Args:
        signed: per message id the text the operator signed and its agent.

    Returns:
        The port of a fake hub whose operator_message answers match for
        exactly those messages, as the real hub's tools/call does.
    """

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            arguments = request["params"]["arguments"]
            known = signed.get(arguments["id"])
            if known is not None and known == (arguments["text"], arguments["to"]):
                payload = {"match": True, "id": arguments["id"], "to": arguments["to"], "class": "call", "text": arguments["text"]}
                result = {"content": [{"type": "text", "text": json.dumps(payload)}], "structuredContent": payload, "isError": False}
            else:
                result = {"content": [{"type": "text", "text": "no match"}], "isError": True}
            body = json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
