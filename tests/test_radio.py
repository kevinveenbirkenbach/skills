"""Exercise radio.py: class rules, the store shared with news.py, radio silence, the three hooks and the listener."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RADIO = REPO_ROOT / "skills" / "kvb-org-radio" / "scripts" / "radio.py"
CLASSES = ("BROADCAST", "DIRECT", "SECURITY", "PAN-PAN", "MAYDAY")
LISTENER = (
    "import importlib.util, sys\n"
    "spec = importlib.util.spec_from_file_location('radio', sys.argv[1])\n"
    "radio = importlib.util.module_from_spec(spec)\n"
    "spec.loader.exec_module(radio)\n"
    "radio.POLL_SECONDS = 0.05\n"
    "sys.argv = [sys.argv[1], 'listen']\n"
    "sys.exit(radio.main())\n"
)


def strip(line: str) -> str:
    parts = line.split(" ", 3)
    if parts[0] != "RADIO" or parts[1] not in CLASSES:
        return line
    return f"{parts[1]} {parts[3]}"


class TestRadio(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name) / "home"
        self.root = Path(tmp.name) / "council"
        self.config = Path(tmp.name) / "config.json"
        sessions = self.home / ".claude" / "sessions"
        sessions.mkdir(parents=True)
        for sid, name in (("s1", "One"), ("s2", "Two"), ("s3", "Three")):
            (sessions / f"{sid}.json").write_text(json.dumps({"sessionId": sid, "name": name}), encoding="utf-8")

    def _env(self, sid: str | None) -> dict[str, str]:
        env = {
            "PATH": "/usr/bin:/bin",
            "HOME": str(self.home),
            "AGENTS_COUNCIL_ROOT": str(self.root),
            "AGENTS_COUNCIL_CONFIG": str(self.config),
        }
        if sid:
            env["CLAUDE_CODE_SESSION_ID"] = sid
        return env

    def _exec(self, sid: str | None, stdin: str, args: tuple[str, ...]) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(RADIO), *args],
            input=stdin, capture_output=True, text=True, env=self._env(sid), check=False, timeout=30,
        )

    def _cli(self, sid: str | None, *args: str) -> subprocess.CompletedProcess:
        return self._exec(sid, "", args)

    def _send(self, sid: str, *args: str) -> list[str]:
        result = self._cli(sid, *args)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.splitlines()

    def _hook(self, command: str, sid: str, **extra: str) -> str:
        result = self._exec(None, json.dumps({"session_id": sid, **extra}), (command,))
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def _prompt(self, sid: str) -> list[str]:
        return [strip(line) for line in self._hook("hook", sid).splitlines()]

    def _tool(self, sid: str) -> list[str]:
        out = self._hook("tool", sid)
        if not out:
            return []
        output = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], "PostToolBatch")
        return [strip(line) for line in output["additionalContext"].splitlines()]

    def _rows(self) -> list[dict]:
        return [json.loads(line) for line in (self.root / "news.jsonl").read_text(encoding="utf-8").splitlines()]

    def _pidfile(self, sid: str) -> Path:
        return self.root / "radio-listen" / f"{sid}.pid"

    def _listen(self, sid: str) -> subprocess.Popen:
        proc = subprocess.Popen(
            [sys.executable, "-c", LISTENER, str(RADIO)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=self._env(None),
        )
        self.addCleanup(self._stop, proc)
        proc.stdin.write(json.dumps({"session_id": sid}))
        proc.stdin.close()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and proc.poll() is None:
            pidfile = self._pidfile(sid)
            if pidfile.is_file() and pidfile.read_text(encoding="utf-8") == str(proc.pid):
                return proc
            time.sleep(0.02)
        self.fail(f"listener for {sid} did not start")

    def _stop(self, proc: subprocess.Popen) -> None:
        if proc.poll() is None:
            proc.kill()
        proc.communicate()

    def _finish(self, proc: subprocess.Popen) -> tuple[int, str]:
        _, err = proc.communicate(timeout=10)
        return proc.returncode, err

    def test_classes_are_validated(self):
        for args in (
            ("send", "broadcast", "x", "--to", "Two"),
            ("send", "direct", "x"),
            ("send", "mayday", "x", "--to", "Two"),
            ("send", "security", "x", "--wake"),
            ("send", "broadcast", "x", "--wake"),
            ("send", "bogus", "x"),
            ("send", "pan-pan", "   "),
        ):
            with self.subTest(args=args):
                self.assertEqual(self._cli("s1", *args).returncode, 2)
        self.assertEqual(self._cli(None, "send", "broadcast", "x").returncode, 2)
        self.assertEqual(
            self._send("s1", "send", "direct", "a   b", "--to", "Two", "--to", "Three"), ["sent direct to Two, Three"]
        )
        self.assertEqual(self._send("s1", "post", "board"), ["sent broadcast to all"])
        self.assertEqual(self._send("s1", "post", "one peer", "--to", "Two"), ["sent direct to Two"])
        self.assertEqual(
            [(r["class"], r["to"], r["text"], "wake" in r) for r in self._rows()],
            [("direct", ["Two", "Three"], "a b", False), ("broadcast", [], "board", False), ("direct", ["Two"], "one peer", False)],
        )

    def test_old_rows_are_read_and_new_rows_keep_the_old_keys(self):
        self.root.mkdir()
        now = time.time()
        old = [
            {"ts": now - 10, "from": "Three", "to": [], "text": "old board"},
            {"ts": now - 5, "from": "Three", "to": ["Two"], "text": "old direct"},
        ]
        (self.root / "news.jsonl").write_text("".join(json.dumps(r) + "\n" for r in old), encoding="utf-8")
        self.assertEqual(self._prompt("s2"), ["BROADCAST Three: old board", "DIRECT Three to Two: old direct"])
        self.assertEqual(float((self.root / "news-seen" / "s2").read_text(encoding="utf-8")), now - 5)
        self._send("s1", "send", "security", "new")
        rows = self._rows()
        self.assertEqual(rows[:2], old)
        for row in rows:
            self.assertIsInstance(row["ts"], float)
            self.assertIsInstance(row["from"], str)
            self.assertIsInstance(row["to"], list)
            self.assertIsInstance(row["text"], str)
        self.assertEqual(rows[2]["class"], "security")

    def test_ts_strictly_increases_under_the_lock(self):
        self.root.mkdir()
        row = {"ts": time.time() + 1000, "from": "Three", "to": [], "text": "clock ahead"}
        (self.root / "news.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
        self._send("s1", "post", "first")
        self._send("s1", "post", "second")
        stamps = [r["ts"] for r in self._rows()]
        self.assertGreater(stamps[1], stamps[0])
        self.assertGreater(stamps[2], stamps[1])

    def test_mayday_sets_silence_and_only_its_sender_clears_it(self):
        self.assertEqual(self._send("s1", "clear"), ["no radio silence active"])
        self.assertEqual(self._send("s1", "send", "mayday", "disk full")[0], "sent mayday to all")
        silence = self.root / "radio-silence.json"
        state = json.loads(silence.read_text(encoding="utf-8"))
        self.assertEqual(sorted(state), ["by", "since", "text", "until"])
        self.assertEqual((state["by"], state["text"], state["until"] - state["since"]), ("One", "disk full", 7200))
        self.assertEqual(state["since"], self._rows()[-1]["ts"])
        held = self._cli("s2", "clear")
        self.assertEqual(held.returncode, 3)
        self.assertIn("held by One", held.stdout)
        self.assertTrue(silence.exists())
        self.assertEqual(self._send("s1", "clear"), ["cleared radio silence by One"])
        self.assertFalse(silence.exists())
        self._send("s1", "send", "mayday", "again")
        self.assertEqual(self._send("s2", "clear", "--force"), ["cleared radio silence by One, forced by Two"])
        self.assertFalse(silence.exists())

    def test_a_wake_names_every_addressee_without_a_live_listener(self):
        self._pidfile("s2").parent.mkdir(parents=True)
        self._pidfile("s2").write_text(str(os.getpid()), encoding="utf-8")
        self.assertEqual(self._send("s1", "send", "mayday", "stop"), ["sent mayday to all", "wake: SendMessage to Three"])
        self.assertEqual(
            self._send("s1", "send", "direct", "answer", "--to", "Two", "--to", "Three", "--wake"),
            ["sent direct to Two, Three", "wake: SendMessage to Three"],
        )
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        self._pidfile("s2").write_text(str(dead.pid), encoding="utf-8")
        self.assertEqual(
            self._send("s1", "send", "direct", "answer", "--to", "Two", "--wake"),
            ["sent direct to Two", "wake: SendMessage to Two"],
        )
        self.assertEqual(self._send("s1", "send", "direct", "no wake", "--to", "Three"), ["sent direct to Three"])
        self.assertEqual([r.get("wake") for r in self._rows()], [None, True, True, None])

    def test_prompt_hook_puts_urgent_first_and_repeats_the_silence(self):
        self._send("s1", "post", "board")
        self._send("s1", "post", "for two", "--to", "Two")
        self._send("s1", "send", "security", "sec")
        self._send("s1", "send", "pan-pan", "pan")
        self._send("s1", "send", "mayday", "may")
        lines = self._prompt("s2")
        self.assertRegex(lines[0], r"^MAYDAY ACTIVE since \d\d:\d\d by One: may; no new heavy jobs until radio\.py clear$")
        self.assertEqual(
            lines[1:],
            ["MAYDAY One: may", "PAN-PAN One: pan", "SECURITY One: sec", "BROADCAST One: board", "DIRECT One to Two: for two"],
        )
        self.assertEqual(len(self._prompt("s2")), 1)
        self.assertNotIn("DIRECT One to Two: for two", self._prompt("s3"))
        self.assertEqual(len(self._prompt("s1")), 1)

    def test_prompt_hook_shows_ten_and_counts_the_rest(self):
        self._send("s1", "send", "security", "early warning")
        for n in range(12):
            self._send("s1", "post", f"item {n}")
        lines = self._prompt("s2")
        self.assertEqual(lines[0], "SECURITY One: early warning")
        self.assertEqual(lines[1:-1], [f"BROADCAST One: item {n}" for n in range(3, 12)])
        self.assertEqual(lines[-1], "RADIO 3 more items: radio.py show --all")
        self.assertEqual(self._prompt("s2"), [])

    def test_tool_hook_delivers_urgent_rows_once_and_the_prompt_skips_them(self):
        self._send("s1", "post", "board")
        self.assertEqual(self._tool("s2"), [])
        self._send("s1", "send", "pan-pan", "pan")
        self.assertEqual(self._tool("s2"), ["PAN-PAN One: pan"])
        self.assertEqual(self._tool("s2"), [])
        self.assertEqual(self._prompt("s2"), ["BROADCAST One: board"])
        self.assertEqual(self._tool("s3"), ["PAN-PAN One: pan"])
        self.assertEqual(self._tool("s1"), [])

    def test_tool_hook_skips_parsing_while_the_store_is_unchanged(self):
        self._send("s1", "post", "x")
        self.assertEqual(self._tool("s2"), [])
        news = self.root / "news.jsonl"
        before = news.stat()
        row = {"ts": time.time(), "from": "Three", "to": [], "text": "hidden", "class": "security"}
        with news.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")
        os.utime(news, ns=(before.st_atime_ns, before.st_mtime_ns))
        self.assertEqual(self._tool("s2"), [])
        os.utime(news, ns=(before.st_atime_ns, before.st_mtime_ns + 10**9))
        self.assertEqual(self._tool("s2"), ["SECURITY Three: hidden"])

    def test_hooks_skip_subagents_and_never_fail(self):
        self._send("s1", "send", "pan-pan", "pan")
        self.assertEqual(self._hook("hook", "s2", agent_id="a1"), "")
        self.assertEqual(self._hook("tool", "s2", agent_id="a1"), "")
        listen = subprocess.run(
            [sys.executable, "-c", LISTENER, str(RADIO)],
            input=json.dumps({"session_id": "s2", "agent_id": "a1"}),
            capture_output=True, text=True, env=self._env(None), check=False, timeout=30,
        )
        self.assertEqual((listen.returncode, listen.stderr), (0, ""))
        self.assertFalse(self._pidfile("s2").exists())
        self.assertFalse((self.root / "news-seen" / "s2").exists())
        for command in ("hook", "tool"):
            for stdin in ("not json", "{}", "[]"):
                with self.subTest(command=command, stdin=stdin):
                    result = self._exec(None, stdin, (command,))
                    self.assertEqual((result.returncode, result.stdout), (0, ""))

    def test_the_first_hook_notifies_the_operator_once(self):
        log = self.root.parent / "notified.log"
        script = "import sys; open(sys.argv[1], 'a').write(sys.argv[2] + '\\n')"
        self.config.write_text(json.dumps({"notify": [sys.executable, "-c", script, str(log)]}), encoding="utf-8")
        self._send("s1", "send", "mayday", "smoke")
        self._prompt("s2")
        self._prompt("s3")
        self.assertEqual(log.read_text(encoding="utf-8"), "Agents radio MAYDAY by One: smoke\n")

    def test_listener_wakes_on_mayday(self):
        proc = self._listen("s2")
        self.assertEqual(
            self._send("s1", "send", "mayday", "host down"), ["sent mayday to all", "wake: SendMessage to Three"]
        )
        code, err = self._finish(proc)
        self.assertEqual(code, 2)
        self.assertEqual([strip(line) for line in err.splitlines()], ["MAYDAY One: host down"])
        self.assertEqual(self._tool("s2"), [])
        self.assertEqual(len(self._prompt("s2")), 1)

    def test_listener_wakes_only_on_a_direct_wake(self):
        proc = self._listen("s2")
        self._send("s1", "post", "board")
        self._send("s1", "post", "plain", "--to", "Two")
        self._send("s1", "send", "pan-pan", "pan")
        self._send("s1", "send", "direct", "elsewhere", "--to", "Three", "--wake")
        time.sleep(0.5)
        self.assertIsNone(proc.poll())
        self.assertEqual(self._send("s1", "send", "direct", "answer me", "--to", "Two", "--wake"), ["sent direct to Two"])
        code, err = self._finish(proc)
        self.assertEqual(code, 2)
        self.assertEqual([strip(line) for line in err.splitlines()], ["PAN-PAN One: pan", "DIRECT One to Two: answer me"])
        self.assertEqual(self._prompt("s2"), ["BROADCAST One: board", "DIRECT One to Two: plain"])

    def test_listener_yields_to_a_newer_one(self):
        first = self._listen("s2")
        second = self._listen("s2")
        self.assertEqual(self._finish(first), (0, ""))
        self.assertIsNone(second.poll())
        self._pidfile("s2").write_text("0", encoding="utf-8")
        self.assertEqual(self._finish(second), (0, ""))


if __name__ == "__main__":
    unittest.main()
