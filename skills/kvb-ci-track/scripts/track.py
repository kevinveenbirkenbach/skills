#!/usr/bin/env python3
"""Track CI runs, pull request checks, scanning alerts and issues; report only what is new.

Environment:
    AGENTS_COUNCIL_ROOT, XDG_STATE_HOME, HOME: the council directory the
        kvb-org-organize councilroot.py resolves; each target is one JSON file
        in its track/ directory, the acks are track/acks.json.

Args:
    add run <owner/repo> <run id> [--rules <file>]: one Actions run.
    add pr <owner/repo> <number> [--rules <file>]: every Actions run of the
        pull request's current head commit.
    add alerts <owner/repo> [--codeql] [--secrets]: the open code scanning
        and secret scanning alerts; at least one flag.
    add issues <owner/repo> [--label <name> ...]: the open issues carrying
        every label given.
        add prints the target id; adding a tracked target again keeps its
        clusters, sets the rules anew and polls it again after it ended.
        --rules is a JSON file of the calling repository: {"job_name":
        [<regex>, ...], "lines": [{"id": <text>, "match": <regex>, "pick":
        "first"|"last", "context": <regex>, "side": "before"|"after"}, ...]}.
        Each job_name regex is cut from a job name after the matrix list
        " (...)"; the first lines rule whose match hits a kept output line
        of ci_failures.py makes the failing line, joined with the nearest
        context line on its side when one is given; without a hit
        ci_failures.py's failing line stands. Every regex passes
        kvb-git-hotfix's backtracking check.
    poll <target> [<target> ...]: one pass over the targets.
    wait <target> [<target> ...] --interval <s> --timeout <s>: poll every
        interval seconds inside this process until a poll exits 10, 20 or
        30, ERRORS polls in a row exit 3, or the next poll would start after
        the timeout; run it as a background task, its end wakes the agent.
    ack <fingerprint> --verdict <text>: silence a triaged cluster in every
        target, as an Alertmanager silence does.

Output:
    poll and wait print one line per cluster no earlier poll of the target
    saw and no ack silences:
    `<fingerprint>\\t<target>\\t<label>\\t<count>\\t<text>[\\t<hotfix> (<stage>)]`.
    For a run or pull request the label is the job name without its variant
    decorations, the count its failed jobs and the text the masked,
    normalised failing line, followed by the first kvb-git-hotfix signature
    that matches the masked line; for an alert the rule id or secret type
    and path:line, never a secret value; for an issue `#<n>` and its masked
    title. Logs are fetched with --allow-escape-sequences and never printed
    whole; every cell keeps only printable characters, whitespace controls
    becoming a space, so no log line, title or name sends a terminal
    sequence, forges a cell or dodges an ack with invisible characters.
    Errors go to stderr as `track: <target>: <message>`.

Exit codes:
    0 nothing new; 10 new clusters printed; 20 every target terminal (the
    run completed, the pull request closed or every run of its head
    completed) and every cluster acked; 30 every target terminal, a cluster
    not acked; 2 usage error, unknown target or fingerprint, bad rules
    file; 3 a target failed (gh, its answer or its rules) and nothing new.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import functools
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from types import ModuleType
from typing import NamedTuple

SKILLS = Path(__file__).resolve().parents[2]
HOTFIX = SKILLS / "kvb-git-hotfix" / "scripts" / "hotfix.py"
NEW, TERMINAL, STUCK, USAGE, BROKEN = 10, 20, 30, 2, 3
ENDS = (NEW, TERMINAL, STUCK)
ERRORS = 3
ACKS = "acks.json"
NUMBERED = ("run", "pr")
ALERTS = ("codeql", "secrets")
PICKS = ("first", "last")
SIDES = ("before", "after")
TEXT = 200
LINE = 400
PAGE = "per_page=30"
ISSUES = "1000"
GONE = ("HTTP 404", "HTTP 410")
JOBS = ".jobs[] | {id, name, status, conclusion}"
RUNS = ".workflow_runs[] | {id, status}"
CODEQL = ".[] | {number, rule: .rule.id, path: .most_recent_instance.location.path, line: .most_recent_instance.location.start_line}"
SECRETS = ".[] | {number, type: .secret_type}"
LOCATION = ".[0].details | {path, line: .start_line}"
REPO = re.compile(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+")
NUMBER = re.compile(r"[1-9][0-9]*")
SHA = re.compile(r"[0-9a-f]{40}")
FINGERPRINT = re.compile(r"[0-9a-f]{12}")
TARGET = re.compile(r"(?:run|pr|alerts|issues)-[A-Za-z0-9._+-]+")
SLUG = re.compile(r"[^A-Za-z0-9._-]+")
MATRIX = re.compile(r" \([^()]*\)")
URL_AUTH = re.compile(r"://[^/@\s]+@")
ASSIGNED = re.compile(r"""(?i)\b(password|passwd|token|secret|api[_-]?key)(["']?\s*[:=]\s*["']?)[^\s"',}]+""")
TOKEN = re.compile(r"[A-Za-z0-9_+=]{24,}")
LETTER = re.compile(r"[A-Za-z]")
DIGIT = re.compile(r"[0-9]")


def load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"kvb_track_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CI = load("ci_failures", SKILLS / "kvb-ci-artifacts" / "scripts" / "ci_failures.py")
COUNCIL = load("councilroot", SKILLS / "kvb-org-organize" / "scripts" / "councilroot.py")


@functools.cache
def hotfix() -> ModuleType:
    return load("hotfix", HOTFIX)


class Failed(Exception):
    """Args:
        message: the first stderr line of the gh call that failed.
    """


class Clients(NamedTuple):
    """Args:
        gh: runs gh with the argv after `gh`; returns (exit code, stdout,
            stderr).
        hint: `<task> (<stage>)` of the first hotfix whose signature matches
            a failing line, None without one.
    """

    gh: Callable[[list[str]], tuple[int, str, str]]
    hint: Callable[[str], str | None]


def spawn(command: list[str]) -> tuple[int, str, str]:
    done = subprocess.run(command, capture_output=True, check=False)
    return done.returncode, done.stdout.decode("utf-8", "replace"), done.stderr.decode("utf-8", "replace")


def gh(argv: list[str]) -> tuple[int, str, str]:
    return spawn(["gh", *argv])


def hotfix_hint(line: str) -> str | None:
    code, stdout, _ = spawn([sys.executable, "-I", str(HOTFIX), "match", "--line", line])
    lines = stdout.splitlines()
    cells = lines[0].split("\t") if lines else []
    return f"{cells[0]} ({cells[1]})" if code == 0 and len(cells) > 1 else None


def out(clients: Clients, argv: list[str]) -> str:
    code, stdout, stderr = clients.gh(argv)
    if code:
        messages = stderr.strip().splitlines()
        raise Failed((messages[0] if messages else f"gh {argv[0]} exited {code}")[:TEXT])
    return stdout


def rows(text: str) -> list[dict]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def hidden(match: re.Match) -> str:
    word = match.group()
    return "<token>" if LETTER.search(word) and DIGIT.search(word) else word


def printable(text: str) -> str:
    """Returns:
        text with every character str.isprintable() refuses dropped (control
        and format characters, zero-width ones included), a whitespace one
        such as a tab becoming a space.
    """
    return "".join(char if char.isprintable() else " " if char.isspace() else "" for char in text)


def masked(line: str) -> str:
    """Returns:
        line, printable() first, with URL credentials, the value after a
        password, token, secret or api key word and every run of 24 letters
        and digits that holds both replaced.
    """
    return TOKEN.sub(hidden, ASSIGNED.sub(r"\1\2<masked>", URL_AUTH.sub("://<auth>@", printable(line))))


def fingerprint(*parts: str) -> str:
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:12]


def pattern(text: object, where: str) -> str:
    if not isinstance(text, str) or not text:
        raise ValueError(f"rules {where} must be a non-empty regex")
    try:
        re.compile(text)
    except re.error as error:
        raise ValueError(f"rules {where} {text!r}: {error}") from error
    found = hotfix().risk(text)
    if found is not None:
        raise ValueError(f"rules {where} {text!r} {found}")
    return text


def rule(entry: object, index: int) -> dict:
    where = f"lines[{index}]"
    if not isinstance(entry, dict) or not isinstance(entry.get("id"), str) or entry.get("pick") not in PICKS:
        raise ValueError(f"rules {where} needs an id and a pick of {', '.join(PICKS)}")
    pattern(entry.get("match"), f"{where}.match")
    if ("context" in entry) != ("side" in entry) or ("side" in entry and entry["side"] not in SIDES):
        raise ValueError(f"rules {where} needs context and a side of {', '.join(SIDES)} together")
    if "context" in entry:
        pattern(entry["context"], f"{where}.context")
    return entry


def rules_of(path: str | None) -> dict:
    """Returns:
        {job_name, lines} of the rules file at path, every entry checked;
        both empty for None; ValueError naming what is wrong.
    """
    if path is None:
        return {"job_name": [], "lines": []}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"rules {path}: {error}") from error
    if not isinstance(data, dict) or not all(isinstance(data.get(key, []), list) for key in ("job_name", "lines")):
        raise ValueError(f"rules {path} must be an object whose job_name and lines are lists")
    names = [pattern(item, f"job_name[{index}]") for index, item in enumerate(data.get("job_name", []))]
    return {"job_name": names, "lines": [rule(entry, index) for index, entry in enumerate(data.get("lines", []))]}


def flat(text: str) -> list[str]:
    """Returns:
        The output_lines() of ci_failures.py as lines, each task's TASK line
        before its first kept line.
    """
    lines, last = [], None
    for task, line in CI.output_lines(text):
        if task and task != last:
            lines.append(task)
        last = task
        lines.append(line)
    return lines


def nearest(lines: list[str], index: int, entry: dict) -> str | None:
    span = range(index - 1, -1, -1) if entry["side"] == "before" else range(index + 1, len(lines))
    return next((lines[at] for at in span if re.search(entry["context"], lines[at])), None)


def ruled(lines: list[str], entry: dict) -> str | None:
    hits = [index for index, line in enumerate(lines) if re.search(entry["match"], line)]
    if not hits:
        return None
    index = hits[0] if entry["pick"] == "first" else hits[-1]
    extra = nearest(lines, index, entry) if "context" in entry else None
    if extra is None:
        return lines[index]
    return f"{extra} {lines[index]}" if entry["side"] == "before" else f"{lines[index]} {extra}"


def failing_line(text: str, rules: dict) -> str:
    lines = flat(text)
    for entry in rules["lines"]:
        found = ruled(lines, entry)
        if found is not None:
            return found
    return CI.failing(text)


def job_label(name: str, rules: dict) -> str:
    label = MATRIX.sub("", name)
    for cut in rules["job_name"]:
        label = re.sub(cut, "", label)
    return label.strip()


def job_line(clients: Clients, repo: str, job: dict, rules: dict) -> str:
    if job["conclusion"] == "cancelled":
        return "cancelled"
    try:
        log = out(clients, ["api", "--allow-escape-sequences", f"/repos/{repo}/actions/jobs/{int(job['id'])}/logs"])
    except Failed as error:
        if any(code in str(error) for code in GONE):
            return "no log"
        raise
    return failing_line(log, rules)


def run_jobs(clients: Clients, state: dict, run_id: str, rules: dict) -> None:
    """Args:
        clients: the gh and hotfix callables.
        state: the target; every failed job of the run not yet in its jobs
            is added there with fingerprint, label, text and masked line.
        run_id: the Actions run.
        rules: rules_of() the target's rules file.
    """
    listing = out(clients, ["api", "--paginate", f"/repos/{state['repo']}/actions/runs/{run_id}/jobs?{PAGE}", "--jq", JOBS])
    for job in rows(listing):
        key = str(job["id"])
        if key in state["jobs"] or job["status"] != "completed" or job["conclusion"] not in CI.FAILED:
            continue
        line = masked(job_line(clients, state["repo"], job, rules))[:LINE]
        label = job_label(job["name"], rules)
        text = CI.normalise(line)
        state["jobs"][key] = {"fp": fingerprint(label, text), "label": label, "text": text, "line": line}


def scan_run(clients: Clients, state: dict) -> tuple[list[dict], bool]:
    rules = rules_of(state["rules"])
    meta = json.loads(out(clients, ["api", f"/repos/{state['repo']}/actions/runs/{state['ref']}"]))
    run_jobs(clients, state, state["ref"], rules)
    return list(state["jobs"].values()), meta["status"] == "completed"


def scan_pr(clients: Clients, state: dict) -> tuple[list[dict], bool]:
    rules = rules_of(state["rules"])
    pull = json.loads(out(clients, ["api", f"/repos/{state['repo']}/pulls/{state['ref']}"]))
    head = pull["head"]["sha"]
    if not SHA.fullmatch(head):
        raise ValueError(f"pull request head {head!r} is no commit id")
    runs = rows(out(clients, ["api", f"/repos/{state['repo']}/actions/runs?head_sha={head}&per_page=100", "--jq", RUNS]))
    for item in runs:
        run_jobs(clients, state, str(int(item["id"])), rules)
    finished = pull["state"] == "closed" or (bool(runs) and all(item["status"] == "completed" for item in runs))
    return list(state["jobs"].values()), finished


def place(item: dict) -> str:
    path, line = item.get("path"), item.get("line")
    if not path:
        return "-"
    return path if line is None else f"{path}:{line}"


def secret_alerts(clients: Clients, state: dict) -> list[dict]:
    repo, found = state["repo"], []
    for item in rows(out(clients, ["api", "--paginate", f"/repos/{repo}/secret-scanning/alerts?state=open&{PAGE}", "--jq", SECRETS])):
        number = int(item["number"])
        fp = fingerprint("secret", repo, str(number))
        seen = state["clusters"].get(fp)
        if seen is None:
            where = out(clients, ["api", f"/repos/{repo}/secret-scanning/alerts/{number}/locations", "--jq", LOCATION]).strip()
            seen = {"label": f"secret {item['type']}", "text": place(json.loads(where)) if where else "-"}
        found.append({"fp": fp, "label": seen["label"], "text": seen["text"], "line": None})
    return found


def scan_alerts(clients: Clients, state: dict) -> tuple[list[dict], bool]:
    repo, found = state["repo"], []
    if "codeql" in state["flags"]:
        listing = out(clients, ["api", "--paginate", f"/repos/{repo}/code-scanning/alerts?state=open&{PAGE}", "--jq", CODEQL])
        found += [
            {"fp": fingerprint("codeql", repo, str(int(item["number"]))), "label": f"codeql {item['rule']}", "text": place(item), "line": None}
            for item in rows(listing)
        ]
    if "secrets" in state["flags"]:
        found += secret_alerts(clients, state)
    return found, False


def scan_issues(clients: Clients, state: dict) -> tuple[list[dict], bool]:
    argv = ["issue", "list", "--repo", state["repo"], "--state", "open", "--limit", ISSUES, "--json", "number,title"]
    for label in state["flags"]:
        argv += ["--label", label]
    found = [
        {"fp": fingerprint("issue", state["repo"], str(int(item["number"]))), "label": f"#{int(item['number'])}", "text": masked(item["title"])[:TEXT], "line": None}
        for item in json.loads(out(clients, argv))
    ]
    return found, False


SCANS = {"run": scan_run, "pr": scan_pr, "alerts": scan_alerts, "issues": scan_issues}


def report(clients: Clients, target: str, finding: dict, count: int) -> str:
    cells = [finding["fp"], target, finding["label"], str(count), finding["text"]]
    hint = None if finding["line"] is None else clients.hint(finding["line"])
    return "\t".join(printable(cell) for cell in (cells if hint is None else [*cells, hint]))


def settled(state: dict, acks: dict) -> bool:
    return state["terminal"] and all(fp in acks for fp in state["clusters"])


def poll_target(clients: Clients, state: dict, acks: dict) -> list[str]:
    """Returns:
        The report() line of every cluster state had not seen that no ack
        silences; state takes every cluster with its current count and
        whether the target is terminal.
    """
    findings, terminal = SCANS[state["kind"]](clients, state)
    counts, first = Counter(finding["fp"] for finding in findings), {}
    for finding in findings:
        first.setdefault(finding["fp"], finding)
    lines = []
    for finding in first.values():
        fp = finding["fp"]
        if fp not in state["clusters"] and fp not in acks:
            lines.append(report(clients, state["id"], finding, counts[fp]))
        state["clusters"][fp] = {"label": finding["label"], "text": finding["text"], "count": counts[fp]}
    state["terminal"] = terminal
    return lines


@contextlib.contextmanager
def locked(folder: Path, name: str) -> Iterator[None]:
    with open(folder / f"{name}.lock", "a", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def write(path: Path, data: dict) -> None:
    temp = path.with_name(f".{path.name}.{os.getpid()}")
    temp.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def outcome(lines: list[str], broken: bool, states: list[dict], acks: dict) -> int:
    if lines:
        return NEW
    if broken:
        return BROKEN
    if not all(state["terminal"] for state in states):
        return 0
    return TERMINAL if all(settled(state, acks) for state in states) else STUCK


def poll(folder: Path, targets: list[str], clients: Clients) -> int:
    acks, lines, states, broken = read(folder / ACKS), [], [], False
    for target in targets:
        with locked(folder, target):
            state = read(folder / f"{target}.json")
            if not state["terminal"]:
                try:
                    lines += poll_target(clients, state, acks)
                except (Failed, ValueError, KeyError, TypeError) as error:
                    print(f"track: {target}: {error}", file=sys.stderr)
                    broken = True
                    continue
                write(folder / f"{target}.json", state)
        states.append(state)
    for line in lines:
        print(line, flush=True)
    return outcome(lines, broken, states, acks)


def wait(folder: Path, targets: list[str], clients: Clients, interval: int, timeout: int) -> int:
    end, errors = time.monotonic() + timeout, 0
    while True:
        code = poll(folder, targets, clients)
        errors = errors + 1 if code == BROKEN else 0
        if code in ENDS or errors >= ERRORS or time.monotonic() + interval > end:
            return code
        time.sleep(interval)


def identity(args: argparse.Namespace) -> tuple[str, list[str]]:
    """Returns:
        (ref, flags) of the target args name: the number of a run or pull
        request, the alert kinds or the sorted labels; ValueError for a
        malformed number or no alert kind.
    """
    if args.kind in NUMBERED:
        if not NUMBER.fullmatch(args.ref):
            raise ValueError(f"add {args.kind} needs a number, not {args.ref!r}")
        return args.ref, []
    if args.kind == "alerts":
        flags = [name for name in ALERTS if getattr(args, name)]
        if not flags:
            raise ValueError("add alerts needs --codeql, --secrets or both")
        return "+".join(flags), flags
    if args.label is None:
        return "open", []
    labels = sorted(set(args.label))
    return "+".join(SLUG.sub("_", label) for label in labels), labels


def add(folder: Path, args: argparse.Namespace) -> str:
    if not REPO.fullmatch(args.repo):
        raise ValueError(f"{args.repo!r} is no owner/repo")
    ref, flags = identity(args)
    rules = None if args.rules is None else str(Path(args.rules).resolve())
    rules_of(rules)
    target = f"{args.kind}-{args.repo.replace('/', '_')}-{ref}"
    with locked(folder, target):
        path = folder / f"{target}.json"
        state = read(path)
        if not state:
            state = {"id": target, "kind": args.kind, "repo": args.repo, "ref": ref, "flags": flags, "jobs": {}, "clusters": {}}
        if state["repo"] != args.repo or state["flags"] != flags:
            raise ValueError(f"{target} already tracks {state['repo']} with {state['flags']}")
        write(path, {**state, "rules": rules, "terminal": False})
    return target


def ack(folder: Path, fp: str, verdict: str) -> None:
    targets = [path for path in folder.glob("*.json") if path.name != ACKS]
    if not FINGERPRINT.fullmatch(fp) or not any(fp in read(path).get("clusters", {}) for path in targets):
        raise ValueError(f"no tracked cluster has the fingerprint {fp!r}")
    if not verdict.strip():
        raise ValueError("--verdict must say what triage found")
    with locked(folder, "acks"):
        acks = read(folder / ACKS)
        acks[fp] = {"verdict": verdict, "ts": time.time()}
        write(folder / ACKS, acks)


def known(folder: Path, targets: list[str]) -> None:
    for target in targets:
        if not TARGET.fullmatch(target) or not (folder / f"{target}.json").is_file():
            raise ValueError(f"unknown target {target!r}; add prints the id")


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(prog="track.py", description=__doc__.splitlines()[0])
    commands = top.add_subparsers(dest="command", required=True)
    kinds = commands.add_parser("add").add_subparsers(dest="kind", required=True)
    for kind in NUMBERED:
        sub = kinds.add_parser(kind)
        sub.add_argument("repo")
        sub.add_argument("ref")
        sub.add_argument("--rules")
    sub = kinds.add_parser("alerts")
    sub.add_argument("repo")
    for name in ALERTS:
        sub.add_argument(f"--{name}", action="store_true")
    sub.set_defaults(rules=None)
    sub = kinds.add_parser("issues")
    sub.add_argument("repo")
    sub.add_argument("--label", action="append")
    sub.set_defaults(rules=None)
    commands.add_parser("poll").add_argument("targets", nargs="+")
    sub = commands.add_parser("wait")
    sub.add_argument("targets", nargs="+")
    sub.add_argument("--interval", type=int, required=True)
    sub.add_argument("--timeout", type=int, required=True)
    sub = commands.add_parser("ack")
    sub.add_argument("fingerprint")
    sub.add_argument("--verdict", required=True)
    return top


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    clients = Clients(gh, hotfix_hint)
    try:
        folder = COUNCIL.directory(COUNCIL.root(), "track")
        if args.command == "add":
            print(add(folder, args))
            return 0
        if args.command == "ack":
            ack(folder, args.fingerprint, args.verdict)
            print(f"acked {args.fingerprint}")
            return 0
        known(folder, args.targets)
        if args.command == "poll":
            return poll(folder, args.targets, clients)
        if args.interval < 1 or args.timeout < args.interval:
            raise ValueError("wait needs --interval of at least 1 and a --timeout no shorter than it")
        return wait(folder, args.targets, clients, args.interval, args.timeout)
    except (OSError, ValueError) as error:
        print(f"track: {error}", file=sys.stderr)
        return USAGE


if __name__ == "__main__":
    sys.exit(main())
