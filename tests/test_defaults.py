"""Exercise defaults.py: the defaults a change adds, per language, in a temporary git repository."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "skills" / "kvb-code-no-defaults" / "scripts" / "defaults.py"
BASE = {
    "app.py": "import os\n\n\ndef old(a=1):\n    return a\n",
    "run.sh": 'echo "${OLD:-1}"\n',
    "Makefile": "OLD ?= 1\n",
    "lib.rs": "fn main() {}\n",
    "schema.sql": "CREATE TABLE t (id INT DEFAULT 0);\n",
    "main.tf": 'variable "old" {\n  default = 1\n}\n',
}
UNSTAGED = {
    "app.py": BASE["app.py"]
    + "\n\ndef new(a, b=2, *, c=None, d=False, e=\"\", f=[], g=()):\n"
    + "    return a, b, c, d, e, f, g\n"
    + "\n\nport = os.environ.get(\"PORT\", \"8080\")\n"
    + 'home = os.getenv("HOME", "")\n'
    + 'name = getattr(os, "name", "posix")\n'
    + "# the operator picked three retries for the flaky host\n"
    + 'retries = os.getenv("RETRIES", default="3")\n'
    + 'label = os.environ.get("LABEL") or "none"\n'
    + 'parser.add_argument("--level", default="info")\n'
    + 'parser.add_argument("--flag", default=False)\n'
    + 'size = {}.get("size", 0)\n'
    + "pick = lambda x=None, y=5: x\n",
    "run.sh": BASE["run.sh"]
    + ': "${NEW:=fallback}"\n'
    + 'echo "${SET:?SET is required} ${BLANK:-} ${QUOTED:-""}"\n',
    "Makefile": BASE["Makefile"]
    + "NEW ?= 2\nEMPTY ?=\nrun: ; echo $${PORT:-80} # port 80 is the fixed listen port\n",
    "lib.rs": BASE["lib.rs"]
    + "fn port(v: Option<u16>) -> u16 { v.unwrap_or(8080) }\n"
    + "fn name(v: Option<String>) -> String { v.unwrap_or_default() }\n"
    + "fn flag(v: Option<bool>) -> bool { v.unwrap_or(false) }\n"
    + "#[serde(default)]\n"
    + "// v.unwrap_or(1) in a comment is no code\n",
    "schema.sql": BASE["schema.sql"]
    + "CREATE TABLE u (n INT DEFAULT 5, note TEXT DEFAULT NULL, s TEXT DEFAULT '');\n"
    + "INSERT INTO u DEFAULT VALUES; -- DEFAULT 7 in a comment\n",
    "main.tf": BASE["main.tf"]
    + 'variable "port" {\n  default = 8080\n}\n'
    + 'variable "tags" {\n  default = {}\n}\n'
    + "locals {\n  default = 3\n}\n",
}
SITE = (
    'port: "{{ app_port | default(8080) }}"\n'
    "user: \"{{ app_user | default('') }}\"\n"
    "home: \"{{ lookup('env', 'HOME') | default('') }}\"\n"
    'list: "{{ items | default([]) }}"\n'
    'cmd: "echo ${PORT:-80} ${EMPTY:-}"\n'
)
STAGED = {
    "web.ts": (
        "export function connect(host: string, port = 8080, tls = false) {\n"
        '  const { retries = 3, name = "" } = options;\n'
        "  const timeout = options.timeout ?? 30;\n"
        '  const label = options.label || "anon";\n'
        "  const flag = options.flag || other;\n"
        "  const empty = options.empty ?? null;\n"
        "  return [host, port, tls, retries, name, timeout, label, flag, empty];\n"
        "}\n"
        "const handler = (event, limit = 10) => limit;\n"
    ),
    "site.yml": SITE,
    "Store.java": (
        "class Store {\n"
        '  int port(java.util.Map<String, Integer> m) { return m.getOrDefault("port", 8080); }\n'
        '  Integer none(java.util.Map<String, Integer> m) { return m.getOrDefault("x", null); }\n'
        "}\n"
    ),
    "Svc.cs": (
        "class Svc {\n"
        "  void Run(int retries = 3, string name = null) { }\n"
        '  string Host(string h) => h ?? "localhost";\n'
        "  string Must(string h) => h ?? throw new System.ArgumentNullException(nameof(h));\n"
        "}\n"
    ),
    "Dockerfile": "FROM debian\nARG PORT\nRUN echo ${PORT:-80}\n",
    "compose.yml.j2": (
        "services:\n"
        "  app:\n"
        '    image: "app:${TAG:-latest}"\n'
        "    user: \"{{ app_user | default('root') }}\"\n"
    ),
}
UNSTAGED_HITS = [
    ("Makefile:2", "make", "NEW ?= 2", False, False),
    ("Makefile:4", "make", "${PORT:-80}", False, True),
    ("app.py:12", "python", "os.environ.get('PORT', '8080')", False, False),
    ("app.py:14", "python", "getattr(os, 'name', 'posix')", False, False),
    ("app.py:16", "python", "os.getenv('RETRIES', default='3')", False, True),
    ("app.py:17", "python", "or 'none'", True, False),
    ("app.py:18", "python", "add_argument(default='info')", False, False),
    ("app.py:20", "python", "{}.get('size', 0)", False, False),
    ("app.py:21", "python", "lambda(y=5)", False, False),
    ("app.py:8", "python", "new(b=2)", False, False),
    ("app.py:8", "python", "new(f=[])", False, False),
    ("lib.rs:2", "rust", ".unwrap_or(8080)", False, False),
    ("lib.rs:3", "rust", ".unwrap_or_default()", False, False),
    ("lib.rs:5", "rust", "#[serde(default)]", False, False),
    ("main.tf:5", "terraform", "default = 8080", False, False),
    ("run.sh:2", "shell", "${NEW:=fallback}", False, False),
    ("schema.sql:2", "sql", "DEFAULT 5", False, False),
]
STAGED_HITS = [
    ("Dockerfile:3", "dockerfile", "${PORT:-80}", False, False),
    ("Store.java:2", "java", 'getOrDefault("port", 8080)', False, False),
    ("Svc.cs:2", "csharp", "int retries = 3", False, False),
    ("Svc.cs:3", "csharp", '?? "localhost"', True, False),
    ("compose.yml.j2:3", "compose", "${TAG:-latest}", False, False),
    ("compose.yml.j2:4", "jinja", "| default('root')", False, False),
    ("web.ts:1", "ts", "port = 8080", False, False),
    ("web.ts:2", "ts", "retries = 3", False, False),
    ("web.ts:3", "ts", "?? 30", True, False),
    ("web.ts:4", "ts", '|| "anon"', True, False),
    ("web.ts:9", "ts", "limit = 10", False, False),
]
SITE_HITS = [
    (1, "yaml", "| default(8080)", False, False),
    (3, "yaml", "lookup('env', ...) | default('')", False, False),
    (5, "yaml", "${PORT:-80}", False, False),
]


class TestDefaults(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name) / "repo"
        self.repo.mkdir()
        self.env = {
            "PATH": "/usr/bin:/bin",
            "HOME": tmp.name,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CEILING_DIRECTORIES": tmp.name,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.org",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.org",
        }
        self._git("init", "-q", "-b", "main")
        self._write(BASE)
        self._git("add", ".")
        self._git("commit", "-q", "-m", "base")

    def _git(self, *args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=self.repo, env=self.env, capture_output=True, text=True, check=True
        ).stdout

    def _write(self, files: dict[str, str]) -> None:
        for name, text in files.items():
            (self.repo / name).write_text(text, encoding="utf-8")

    def _change(self) -> None:
        self._write(STAGED)
        self._git("add", *STAGED)
        self._write(UNSTAGED)
        (self.repo / "site.yml").write_text("name: demo\n" + SITE, encoding="utf-8")

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args], env=self.env, capture_output=True, text=True, check=False
        )

    def _hits(self, *args: str) -> tuple[int, list[tuple]]:
        result = self._run("--repo", str(self.repo), "--json", *args)
        self.assertIn(result.returncode, (0, 1), result.stderr)
        rows = json.loads(result.stdout)
        return result.returncode, sorted(
            (f"{r['file']}:{r['line']}", r["language"], r["construct"], r["candidate"], r["justified"])
            for r in rows
        )

    def test_worktree_reports_staged_and_unstaged_additions_only(self):
        self._change()
        code, hits = self._hits()
        site = [(f"site.yml:{line + 1}", *rest) for line, *rest in SITE_HITS]
        self.assertEqual(code, 1)
        self.assertEqual(hits, sorted(UNSTAGED_HITS + STAGED_HITS + site))

    def test_staged_reads_the_index_version(self):
        self._change()
        code, hits = self._hits("--staged")
        site = [(f"site.yml:{line}", *rest) for line, *rest in SITE_HITS]
        self.assertEqual(code, 1)
        self.assertEqual(hits, sorted(STAGED_HITS + site))

    def test_permitted_values_are_silent(self):
        self._write(
            {
                "ok.py": (
                    "import os\n\n\n"
                    'def f(a=None, b=False, c="", d=(), *, e=b"", g=frozenset()):\n'
                    "    return a, b, c, d, e, g\n\n\n"
                    'x = os.environ.get("K", "") or []\n'
                    'y = {}.get("k", None)\n'
                    'z = getattr(os, "x", None)\n'
                    'w = os.getenv("W", default=False)\n'
                ),
                "ok.sh": 'echo "${A:-} ${B:-""} ${C:=}"\n',
                "ok.yml": "a: \"{{ x | default(false) }} {{ y | default(None) }} {{ z | default('') }}\"\n",
                "ok.ts": "function f(a = null, b = undefined, c = '') { return a ?? null; }\n",
            }
        )
        result = self._run(
            "--repo", str(self.repo), "--file", "ok.py", "--file", "ok.sh", "--file", "ok.yml", "--file", "ok.ts"
        )
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))

    def test_file_scans_an_untracked_file_whole(self):
        self._write({"extra.py": "def g(x=1):\n    return x\n"})
        self.assertEqual(self._hits(), (0, []))
        self.assertEqual(self._hits("--file", "extra.py"), (1, [("extra.py:1", "python", "g(x=1)", False, False)]))

    def test_text_output_marks_justified_and_candidate(self):
        self._write({"t.sh": "# the probe needs a fixed port\necho ${A:-b}\n", "t.ts": "x = y ?? 1;\n"})
        result = self._run("--repo", str(self.repo), "--file", "t.sh", "--file", "t.ts")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(
            result.stdout,
            't.sh:2\tshell\t${A:-b}\t: "${A:?set A in <file>}"\tjustified?\n'
            "t.ts:1\tts\t?? 1\t`if (a === undefined) throw`\tcandidate\n",
        )

    def test_exit_codes(self):
        self.assertEqual(self._run("--repo", str(self.repo)).returncode, 0)
        self.assertEqual(self._run().returncode, 2)
        self.assertEqual(self._run("--repo", str(self.repo.parent)).returncode, 2)
        self.assertEqual(self._run("--repo", str(self.repo), "--file", "missing.py").returncode, 2)
        self._write({"broken.py": "def (:\n"})
        self.assertEqual(self._run("--repo", str(self.repo), "--file", "broken.py").returncode, 2)


if __name__ == "__main__":
    unittest.main()
