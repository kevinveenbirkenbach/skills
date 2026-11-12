from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "skills" / "kvb-code-clean" / "scripts" / "comments.py"
BASE = {
    "casc.yaml.j2": "# Header kept from the base.\njenkins:\n  url: x\n",
    "app.py": "def old():\n    return 1\n",
    "run.sh": "#!/bin/bash\necho old\n",
}
UNSTAGED = {
    "casc.yaml.j2": BASE["casc.yaml.j2"]
    + "{# Without an override the plugin requests every scope. #}\n"
    + "  scopes: \"openid\"\n"
    + "  # a yaml narration line\n"
    + '  note: "{{ value }}"\n',
    "app.py": BASE["app.py"]
    + "\n\ndef new(a):\n"
    + '    """Return a."""\n'
    + "    # explain the next line\n"
    + "    return a  # noqa: E501\n",
    "run.sh": BASE["run.sh"]
    + "# shellcheck disable=SC2086\n"
    + 'echo "#not a comment" $X\n',
}
STAGED = {
    "style.css": "a { color: red; }\n/* palette narration */\n",
    "page.html.j2": "<p>{{ title }}</p>\n<!-- layout note -->\n{# jinja note #}\n",
    "Dockerfile": "FROM debian\n# install the tools\nRUN true\n",
}
UNSTAGED_HITS = [
    ("app.py:6", "python", "docstring", False),
    ("app.py:7", "python", "comment", False),
    ("app.py:8", "python", "comment", True),
    ("casc.yaml.j2:4", "jinja+yaml", "comment", False),
    ("casc.yaml.j2:6", "jinja+yaml", "comment", False),
    ("run.sh:3", "shell", "comment", True),
]
STAGED_HITS = [
    ("Dockerfile:2", "dockerfile", "comment", False),
    ("page.html.j2:2", "jinja+html", "comment", False),
    ("page.html.j2:3", "jinja+html", "comment", False),
    ("style.css:2", "css", "comment", False),
]


class TestComments(unittest.TestCase):
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

    def _hits(self, *args: str) -> tuple[int, list[tuple]]:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--repo", str(self.repo), "--json", *args],
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertIn(result.returncode, (0, 1), result.stderr)
        rows = json.loads(result.stdout)
        return result.returncode, sorted(
            (f"{r['file']}:{r['line']}", r["language"], r["kind"], r["directive"]) for r in rows
        )

    def test_worktree_reports_every_added_comment_and_nothing_from_the_base(self):
        self._change()
        code, hits = self._hits()
        self.assertEqual(code, 1)
        self.assertEqual(hits, sorted(UNSTAGED_HITS + STAGED_HITS))

    def test_staged_reads_the_index_version(self):
        self._change()
        code, hits = self._hits("--staged")
        self.assertEqual(code, 1)
        self.assertEqual(hits, sorted(STAGED_HITS))

    def test_directives_alone_exit_zero(self):
        self._write({"run.sh": BASE["run.sh"] + "# shellcheck disable=SC2086\necho $X\n"})
        code, hits = self._hits()
        self.assertEqual(code, 0)
        self.assertEqual(hits, [("run.sh:3", "shell", "comment", True)])

    def test_file_scans_an_untracked_template_whole(self):
        (self.repo / "new.yml.j2").write_text("a: 1\n{# narration #}\n", encoding="utf-8")
        code, hits = self._hits("--file", "new.yml.j2")
        self.assertEqual(code, 1)
        self.assertEqual(hits, [("new.yml.j2:2", "jinja+yaml", "comment", False)])


if __name__ == "__main__":
    unittest.main()
