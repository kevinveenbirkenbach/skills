#!/usr/bin/env python3
"""Share hotfixes through the kvb-org-rasci register and keep a worktree merged with them.

Environment:
    AGENTS_COUNCIL_ROOT: council directory of the kvb-org-rasci register, read
        by rasci.py; the rows are its tasks hotfix/<slug>.
    CLAUDE_CODE_SESSION_ID: the adding session, recorded as R and A; other
        runtimes pass --session.
    AGENTS_COUNCIL_CONFIG: read by watch.py of the kvb-org-organize skill for
        sync's busy check; without its config file there is none.

Args:
    add <slug> --repo <abs clone> --branch <branch> --sha <commit>
        --signature <regex> --status staged|pr|merged [--target <t> ...]
        [--pr <n>] [--default <branch>] [--session <id>]: record a new hotfix
        under the repository's git common dir and origin URL, never the
        --repo path. --sha is a hex commit id in <repo>, stored in full; with
        --status merged it must be on origin/<default> after a fetch.
        --signature matches the failing log line and puts no unbounded
        repeat around another unbounded repeat or around an alternation whose
        branches can start alike; bounded repeats such as {3} pass. Each
        --target is a make target or `deploy` the fix turns green, none listed
        means every target; --pr is the pull request number.
    update <slug> --status staged|pr|merged [--sha <commit>] [--pr <n>]
        [--repo <abs clone>] [--default <branch>] [--session <id>]: move a
        hotfix on. --sha resolves in the recorded git common dir or in
        --repo, which must be the same repository unless the recorded one is
        unknown, and records it anew. --status merged needs --sha, the commit
        as it sits on origin/<default> after a fetch. add and update with
        --status merged post a kvb-org-radio security item; a failed post
        only warns.
    pending --repo <dir> [--target <t> ...]: every hotfix of that repository
        against HEAD; with --target only those that turn one of the targets
        green, as void counts them.
    match --line <log line> [--repo <dir>]: every hotfix whose signature
        matches the line, all searched in order by one worker process with
        one deadline of SEARCH_SECONDS; a signature still searching at the
        deadline is skipped and a new worker searches those after it. With
        --repo, those of another repository are labelled and do not count.
    void --repo <dir> --target <t> [--target ...]: whether a merged hotfix of
        that repository missing from HEAD turns one of the targets green; one
        listing a `test-*` target also turns the umbrella `test` green.
    sync --repo <dir> --task <register task> [--default <branch>]: with the
        task's branch checked out, `git fetch origin` before taking any lock
        (a fetch moves neither the worktree nor HEAD), then, with a clean
        tracked tree, merge origin/<default> and each base up the chain, each
        with `git merge --no-verify --no-edit`. From the tree check to the
        last merge or abort it holds `kvb-gate-sync.lock`, with its PID and
        command recorded there, and the worktree lock of the kvb-check-gate
        skill's gate.py, and refuses while a `gate.py run` or `gate.py hold`
        holds it, naming the holder. A watch.py busy process it sees in <dir>
        also refuses, but processes in another sandbox's PID namespace stay
        unseen, so the lock is the guard. The default branch is origin/HEAD; --default is read
        only when that ref is missing and must agree with it otherwise.
        Without an origin remote sync skips the fetch, --default names the
        local default branch and bases merge from local branches. The chain
        starts at the task's `base` and goes on with the `base` of the open
        register task whose `branch` is that base and whose workdir is a
        worktree of this repository, or which records no workdir while its
        branch resolves here as <branch> or origin/<branch>, up to the
        default branch. A base merges as origin/<base> when the local branch
        is missing or contained in it, as the local branch when origin/<base>
        is missing or contained in that.

    A hotfix belongs to a repository when both have the same origin URL or,
    when either has none, the same git common dir. Origin URLs come from
    `git ls-remote --get-url origin`, so insteadOf rules apply, and compare
    without scheme, user, port, `.git` and trailing slash; a local path
    resolves against the worktree's top level, and the path on a
    case-insensitive host of CASELESS compares in lowercase. A merged hotfix
    missing from HEAD counts only when its sha is on origin/<default>; when
    it is not, one fetch decides. Every fetch (sync, pending, void, and add
    or update with --status merged) runs with GIT_TERMINAL_PROMPT=0 and is
    stopped after FETCH_SECONDS.

Output:
    add, update: `added hotfix/<slug>` or `updated hotfix/<slug>`.
    pending: `<verdict>\t<task>\t<status>\t<branch>\t<sha>\t<pr>` for each
        merged hotfix missing from HEAD (`missing (merge main)`, or
        `not on origin/<default>`) and each staged or pr one
        (`open, not merged`), then `hotfix: <n> missing, <m> open`.
    match: `<task>\t<status>\t<branch>\t<sha>\t<pr>\t<repository>` per match,
        with --repo prefixed `foreign\t` for another repository and
        `unknown\t` for an unresolvable one, or a `hotfix: no signature`
        line when nothing of the repository matches. A signature still
        searching at the SEARCH_SECONDS deadline is named on stderr and
        counts as no match.
    void: `void\t<task>\t<sha>\t<targets>` per hotfix that voids the run; a
        hotfix off origin/<default> voids nothing and is named on stderr.
    sync: `merged\t<ref>\t<new HEAD>` or `contained\t<ref>` per ref in merge
        order; `conflict\t<ref>\t<files>` on the first conflict.
    pending and void name every row whose repository is unknown (no origin
    URL and its git common dir gone) on stderr; such a row changes no exit
    code.

Exit codes:
    0 done; pending: none missing; match: a match of the repository; void:
        not void.
    1 pending: a merged hotfix is missing; match: no match.
    2 usage error, unknown task, dirty tracked tree, HEAD not on the task's
        branch, a held worktree, a chain row without workdir whose branch
        does not resolve, an unresolvable or diverged ref, a merge that
        failed without a conflict (aborted), a merged sha off
        origin/<default>; pending and void: a missing origin/HEAD or a
        failed fetch, unless void exits 3; match: the search worker did not
        start, did not get ready before the deadline or exited non-zero.
    3 void: a merged hotfix missing from HEAD turns a target green.
    4 sync: a merge conflicted and was aborted; earlier merges stay.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import importlib.util
import itertools
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from types import ModuleType
from typing import NoReturn

SKILLS = Path(__file__).resolve().parents[2]
RASCI = SKILLS / "kvb-org-rasci" / "scripts" / "rasci.py"
GATE = SKILLS / "kvb-check-gate" / "scripts" / "gate.py"
WATCH = SKILLS / "kvb-org-organize" / "scripts" / "watch.py"
RADIO = SKILLS / "kvb-org-radio" / "scripts" / "radio.py"
PREFIX = "hotfix/"
STAGES = ("staged", "pr", "merged")
REGISTER_STATUS = {"staged": "running", "pr": "running", "merged": "done"}
SHA = re.compile(r"^[0-9a-f]{7,40}$")
TARGET = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._%/+-]*$")
UMBRELLA = "test"
ORIGIN_HEAD = "refs/remotes/origin/HEAD"
GIT = ("git", "-c", "maintenance.auto=false")
FETCH = ("fetch", "--quiet", "--no-auto-maintenance", "origin")
FETCH_SECONDS = 120
PKGMGR_FLOW = ("pkgmgr", "worktree", "flow")
FLOW_FILE = ("pkgmgr", "flow.yml")
FLOW_SECONDS = 60
URL = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://(?:[^@/]*@)?(?P<host>[^/:]*)(?::\d*)?(?P<path>/.*)?$")
SCP = re.compile(r"^(?:[^@/:]+@)?(?P<host>[^/:]+):(?P<path>.*)$")
CASELESS = ("github.com", "gitlab.com", "codeberg.org", "bitbucket.org")
SEARCH_SECONDS = 3
SEARCH = (
    "import json, re, sys\n"
    "data = json.loads(sys.stdin.buffer.read())\n"
    "print('ready', flush=True)\n"
    "for pattern in data['patterns']:\n"
    "    print(int(re.search(pattern, data['line']) is not None), flush=True)\n"
)
CLASSES = {"DIGIT": r"\d", "SPACE": r"\s", "WORD": r"\w", "LINEBREAK": r"\n"}
PROBES = frozenset(map(chr, range(128))) | {"é", "٠", "　"}
NESTED = "repeats a group that repeats itself, like (a+)+"
OVERLAP = "repeats an alternation whose branches can start alike, like (a|ab|b)*"


def fail(message: str) -> NoReturn:
    print(f"hotfix: {message}", file=sys.stderr)
    sys.exit(2)


def report(problems: list[str]) -> None:
    for problem in problems:
        print(f"hotfix: {problem}", file=sys.stderr)


def module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def git(where: str, *args: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            [*GIT, *args], cwd=where, stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False
        )
    except OSError as error:
        return subprocess.CompletedProcess([*GIT, *args], 128, "", str(error))


def git_out(where: str, *args: str) -> str:
    result = git(where, *args)
    if result.returncode:
        fail(f"git {' '.join(args)} in {where}: {(result.stderr or result.stdout).strip()}")
    return result.stdout


def fetch(where: str) -> subprocess.CompletedProcess:
    command = [*GIT, *FETCH]
    try:
        return subprocess.run(
            command, cwd=where, stdin=subprocess.DEVNULL, capture_output=True, text=True,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"}, timeout=FETCH_SECONDS, check=False,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(command, 124, "", f"stopped after {FETCH_SECONDS} s")
    except OSError as error:
        return subprocess.CompletedProcess(command, 128, "", str(error))


def fetched(where: str) -> None:
    result = fetch(where)
    if result.returncode:
        fail(f"git fetch origin in {where}: {(result.stderr or result.stdout).strip()}")


def ancestor(where: str, rev: str, of: str) -> bool:
    return git(where, "merge-base", "--is-ancestor", rev, of).returncode == 0


def resolves(where: str, ref: str) -> bool:
    return git(where, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").returncode == 0


def task_of(rasci: ModuleType, slug: str) -> str:
    if not rasci.TASK.match(slug):
        fail(f"invalid slug {slug!r}; use lowercase letters, digits, '.', '_', '-' and '/'")
    return PREFIX + slug


def worktree(value: str) -> str:
    path = os.path.realpath(value)
    if not os.path.isdir(path):
        fail(f"{value} is no directory")
    if identity(path) is None:
        fail(f"{value} is not a git repository")
    return path


def clone(value: str) -> str:
    if not os.path.isabs(value):
        fail(f"--repo {value!r} is not an absolute path")
    return worktree(value)


def normalized(url: str, top: str) -> str:
    """Compare form of an origin URL.

    Args:
      url: the origin URL with insteadOf rules applied.
      top: the directory a local relative path is relative to.
    """
    url = url.strip()
    found = URL.match(url) or (None if url.startswith((".", "/")) else SCP.match(url))
    host, path = (found["host"].lower(), found["path"] or "") if found else ("", url)
    if host:
        path = path.rstrip("/").removesuffix(".git").rstrip("/").lstrip("/")
        return f"{host}/{path.lower() if host in CASELESS else path}"
    if not path:
        return ""
    return os.path.realpath(os.path.join(top, path)).removesuffix(".git").rstrip("/")


def origin_url(where: str) -> str:
    if not git(where, "config", "--get", "remote.origin.url").stdout.strip():
        return ""
    url = git(where, "ls-remote", "--get-url", "origin").stdout
    top = git(where, "rev-parse", "--show-toplevel")
    return normalized(url, top.stdout.strip() if top.returncode == 0 else where)


def identity(where: str) -> tuple[str, str] | None:
    if not where or not os.path.isdir(where):
        return None
    common = git(where, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if common.returncode:
        return None
    return os.path.realpath(common.stdout.strip()), origin_url(where)


def same(one: tuple[str, str], other: tuple[str, str]) -> bool:
    if one[1] and other[1]:
        return one[1] == other[1]
    return one[0] == other[0]


def recorded(row: dict) -> tuple[str, str] | None:
    common, origin = row.get("common_dir") or "", row.get("origin") or ""
    if not origin and not os.path.isdir(common):
        return None
    return common, origin


def repository(row: dict) -> str:
    return row.get("origin") or row.get("common_dir") or "-"


def unknown(task: str, row: dict) -> str:
    return (
        f"{task}: repository unknown (no origin URL, git dir {row.get('common_dir') or '-'} gone); record it with "
        f"`hotfix.py update {task.removeprefix(PREFIX)} --status {row['stage']} --sha {row['sha']} --repo <clone>`"
    )


def hex_id(sha: str) -> str:
    if not SHA.match(sha):
        fail(f"--sha {sha!r} is no hex commit id of 7 to 40 characters")
    return sha


def commit(where: str, sha: str) -> str:
    found = git(where, "rev-parse", "--verify", "--quiet", f"{hex_id(sha)}^{{commit}}")
    if found.returncode:
        fail(f"--sha {sha} is no commit in {where}")
    return found.stdout.strip()


def default_branch(where: str, given: str | None) -> str:
    head = git(where, "symbolic-ref", "--quiet", ORIGIN_HEAD)
    if head.returncode == 0:
        name = head.stdout.strip().removeprefix("refs/remotes/origin/")
        if given is not None and given != name:
            fail(f"origin/HEAD names {name}, --default says {given}")
        return name
    if given is None:
        fail(f"{ORIGIN_HEAD} is missing in {where}; pass --default <branch> or run `git remote set-head origin --auto`")
    return branch_name(where, given, "--default")


def landed(where: str, sha: str, given: str | None) -> str:
    hex_id(sha)
    fetched(where)
    name = default_branch(where, given)
    full = commit(where, sha)
    if not ancestor(where, full, f"refs/remotes/origin/{name}"):
        fail(f"--sha {sha} is not on origin/{name}; record the commit as it sits there, a squash or rebase merge "
             "changes it")
    return full


def branch_name(where: str, name: str, what: str) -> str:
    if name.startswith("-") or git(where, "check-ref-format", f"refs/heads/{name}").returncode:
        fail(f"{what} {name!r} is no valid branch name")
    return name


def children(value: object, subpattern: type) -> list:
    if isinstance(value, subpattern):
        return [value]
    if isinstance(value, (tuple, list)):
        return [sub for item in value for sub in children(item, subpattern)]
    return []


def either(tests: list[Callable[[str], bool]]) -> Callable[[str], bool]:
    return lambda char: any(test(char) for test in tests)


def risk(text: str) -> str | None:
    parser, c = getattr(re, "_parser", None), getattr(re, "_constants", None)
    if parser is None or c is None:
        print("hotfix: this Python hides re's parser; --signature is not checked for runaway backtracking",
              file=sys.stderr)
        return None
    loose = (c.MAX_REPEAT, c.MIN_REPEAT)
    repeats = (*loose, c.POSSESSIVE_REPEAT)
    barriers = (c.ATOMIC_GROUP, c.POSSESSIVE_REPEAT)
    probes = PROBES | set(text)

    def parts(av: object) -> list:
        return children(av, parser.SubPattern)

    def unbounded(op: object, av: object) -> bool:
        return op in loose and av[1] == c.MAXREPEAT

    def inside(pattern: object, hit: Callable[[object, object], bool]) -> bool:
        return any(
            hit(op, av) or (op not in barriers and any(inside(part, hit) for part in parts(av)))
            for op, av in pattern.data
        )

    def overlapping(op: object, av: object) -> bool:
        if op != c.BRANCH:
            return False
        heads = [start(branch) for branch in av[1]]
        return any(
            (one_empty and two_empty) or any(one(char) and two(char) for char in probes)
            for (one, one_empty), (two, two_empty) in itertools.combinations(heads, 2)
        )

    def start(pattern: object) -> tuple[Callable[[str], bool], bool]:
        tests = []
        for op, av in pattern.data:
            test, empty = first(op, av)
            tests.append(test)
            if not empty:
                return either(tests), False
        return either(tests), True

    def first(op: object, av: object) -> tuple[Callable[[str], bool], bool]:
        if op == c.LITERAL:
            return (lambda char: char == chr(av)), False
        if op == c.NOT_LITERAL:
            return (lambda char: char != chr(av)), False
        if op == c.ANY:
            return (lambda char: True), False
        if op == c.IN:
            return member(av), False
        if op in (c.AT, c.ASSERT, c.ASSERT_NOT):
            return (lambda char: False), True
        if op in repeats:
            test, empty = start(av[2])
            return test, empty or av[0] == 0
        if op in (c.SUBPATTERN, c.ATOMIC_GROUP, c.BRANCH):
            heads = [start(part) for part in parts(av)]
            return either([test for test, _ in heads]), any(empty for _, empty in heads)
        return (lambda char: True), True

    def member(items: list) -> Callable[[str], bool]:
        negated = bool(items) and items[0][0] == c.NEGATE
        kept = [item for item in items if item[0] != c.NEGATE]
        return lambda char: any(holds(op, av, char) for op, av in kept) != negated

    def holds(op: object, av: object, char: str) -> bool:
        if op == c.LITERAL:
            return char == chr(av)
        if op == c.RANGE:
            return av[0] <= ord(char) <= av[1]
        if op == c.CATEGORY:
            name = av.name.removeprefix("CATEGORY_").removeprefix("LOC_").removeprefix("UNI_")
            klass = CLASSES.get(name.removeprefix("NOT_"))
            return klass is None or (re.fullmatch(klass, char) is not None) != name.startswith("NOT_")
        return True

    def scan(pattern: object) -> str | None:
        for op, av in pattern.data:
            if unbounded(op, av) and inside(av[2], unbounded):
                return NESTED
            if unbounded(op, av) and inside(av[2], overlapping):
                return OVERLAP
            for part in parts(av):
                found = scan(part)
                if found is not None:
                    return found
        return None

    return scan(parser.parse(text))


def signature(text: str) -> str:
    if not text.strip():
        fail("--signature must not be empty")
    try:
        re.compile(text)
    except re.error as error:
        fail(f"--signature {text!r}: {error}")
    found = risk(text)
    if found is not None:
        fail(f"--signature {text!r} {found}, which backtracks without end on a near miss; match the stable part "
             "instead")
    return text


def searched(patterns: list[str], line: str) -> list[bool]:
    """Search the line with every pattern in order in one worker until SEARCH_SECONDS pass.

    Args:
      patterns: signatures that compile.
      line: the log line.

    Returns:
      one verdict per pattern; fewer when the deadline passed, the next pattern still searching.
    """
    payload = json.dumps({"line": line, "patterns": patterns}).encode("ascii")
    late = False
    try:
        with subprocess.Popen(
            [sys.executable, "-I", "-c", SEARCH], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ) as worker:
            try:
                out, err = worker.communicate(payload, timeout=SEARCH_SECONDS)
            except subprocess.TimeoutExpired:
                late = True
                worker.kill()
                out, err = worker.communicate()
    except OSError as error:
        fail(f"cannot start the signature search worker {sys.executable}: {error.strerror or error}")
    *lines, tail = out.decode("ascii", "replace").split("\n")
    verdicts = lines[1:]
    if late and lines[:1] != ["ready"]:
        fail(f"the signature search worker did not get ready within {SEARCH_SECONDS} s")
    complete = late or (worker.returncode == 0 and not tail and len(verdicts) == len(patterns))
    if lines[:1] != ["ready"] or not complete or len(verdicts) > len(patterns) or set(verdicts) - {"0", "1"}:
        reason = err.decode("utf-8", "replace").strip().splitlines()[-1:] or ["no message"]
        fail(f"the signature search worker exited {worker.returncode}: {reason[0]}")
    return [verdict == "1" for verdict in verdicts]


def make_targets(values: list[str] | None) -> list[str]:
    for value in values or []:
        if not TARGET.match(value):
            fail(f"--target {value!r} is no make target name")
    return list(dict.fromkeys(values or []))


def turns_green(greens: list[str], wanted: set[str]) -> bool:
    if not greens or wanted & set(greens):
        return True
    return UMBRELLA in wanted and any(green.startswith(f"{UMBRELLA}-") for green in greens)


def number(value: int | None) -> int | None:
    if value is not None and value < 1:
        fail("--pr must be 1 or higher")
    return value


def hotfixes(rasci: ModuleType) -> list[tuple[str, dict]]:
    return [(t, row) for t, row in sorted(rasci.load().items()) if t.startswith(PREFIX) and "stage" in row]


def of_repository(rasci: ModuleType, repo: str) -> tuple[list[tuple[str, dict]], list[str]]:
    here = identity(repo)
    rows, unknowns = [], []
    for task, row in hotfixes(rasci):
        theirs = recorded(row)
        if theirs is None:
            unknowns.append(unknown(task, row))
        elif same(theirs, here):
            rows.append((task, row))
    return rows, unknowns


def for_targets(rows: list[tuple[str, dict]], targets: list[str] | None) -> list[tuple[str, dict]]:
    if targets is None:
        return rows
    wanted = set(make_targets(targets))
    return [(task, row) for task, row in rows if turns_green(row.get("targets") or [], wanted)]


def missing(repo: str, rows: list[tuple[str, dict]], problems: list[str]) -> tuple[list, list, str]:
    absent = [(t, row) for t, row in rows if row["stage"] == "merged" and not ancestor(repo, row["sha"], "HEAD")]
    if not absent:
        return [], [], ""
    head = git(repo, "symbolic-ref", "--quiet", ORIGIN_HEAD)
    if head.returncode:
        problems.append(f"{ORIGIN_HEAD} is missing in {repo}, so {', '.join(t for t, _ in absent)} stay unchecked; "
                        "run `git remote set-head origin --auto`")
        return [], [], ""
    ref = head.stdout.strip()
    on = {t for t, row in absent if ancestor(repo, row["sha"], ref)}
    if len(on) < len(absent):
        result = fetch(repo)
        if result.returncode:
            unchecked = ", ".join(t for t, _ in absent if t not in on)
            problems.append(f"git fetch origin in {repo} failed, so {unchecked} stay unchecked: {result.stderr.strip()}")
            return [(t, row) for t, row in absent if t in on], [], ""
        on = {t for t, row in absent if ancestor(repo, row["sha"], ref)}
    shown = ref.removeprefix("refs/remotes/")
    return [(t, row) for t, row in absent if t in on], [(t, row) for t, row in absent if t not in on], shown


def pr_cell(row: dict) -> str:
    return f"#{row['pr']}" if row.get("pr") else "-"


def cmd_add(rasci: ModuleType, args: argparse.Namespace) -> int:
    task = task_of(rasci, args.slug)
    if task in rasci.load():
        fail(f"{task} is already in the register; move it on with update")
    repo = clone(args.repo)
    common, origin = identity(repo)
    entry = {
        "common_dir": common,
        "origin": origin,
        "branch": branch_name(repo, args.branch, "--branch"),
        "signature": signature(args.signature),
        "targets": make_targets(args.target),
        "stage": args.status,
    }
    pr = number(args.pr)
    if pr is not None:
        entry["pr"] = pr
    entry["sha"] = landed(repo, args.sha, args.default) if args.status == "merged" else commit(repo, args.sha)
    council = module("council", rasci.COUNCIL)
    sid, _ = council.caller(args.session)
    entry["roles"] = {council.live_sessions().get(sid) or sid: "RA"}
    rasci.apply_status(entry, REGISTER_STATUS[args.status])
    with rasci.database() as tasks:
        if task in tasks:
            fail(f"{task} is already in the register; move it on with update")
        tasks[task] = entry
    print(f"added {task}")
    if args.status == "merged":
        announce(task, entry, args.session)
    return 0


def announce(task: str, entry: dict, session: str | None) -> None:
    """Post a merged hotfix as a kvb-org-radio security item; never fails the caller.

    Args:
      task: the register task, hotfix/<slug>.
      entry: its register row.
      session: the caller's --session, for runtimes without CLAUDE_CODE_SESSION_ID.
    """
    if not RADIO.is_file():
        return
    text = (
        f"HOTFIX merged: {task} {entry.get('sha', '-')[:12]} on {repository(entry)}; "
        "hotfix.py sync before your next deploy, merge or gate"
    )
    command = [sys.executable, str(RADIO), "send", "security", text]
    if session:
        command += ["--session", session]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        print(f"hotfix: radio announcement failed: {error}", file=sys.stderr)
        return
    if result.returncode != 0:
        print(f"hotfix: radio announcement failed: {result.stderr.strip()}", file=sys.stderr)


def located(task: str, entry: dict, given: str | None) -> tuple[str, dict]:
    if given is None:
        common = entry.get("common_dir") or ""
        if not os.path.isdir(common):
            fail(f"{task}: its git dir {common or '-'} is gone; pass --repo <a clone of {repository(entry)}>")
        return common, {}
    repo = clone(given)
    here = identity(repo)
    theirs = recorded(entry)
    if theirs is not None and not same(theirs, here):
        fail(f"--repo {given} is another repository than {task}'s {repository(entry)}")
    return repo, {"common_dir": here[0], "origin": here[1]}


def cmd_update(rasci: ModuleType, args: argparse.Namespace) -> int:
    task = task_of(rasci, args.slug)
    pr = number(args.pr)
    if args.status == "merged" and args.sha is None:
        fail("--status merged needs --sha, the commit as it sits on the default branch")
    entry = rasci.load().get(task)
    if entry is None or "stage" not in entry:
        fail(f"{task}: no hotfix in the register; record it with add")
    fields: dict = {}
    if args.repo is not None or args.sha is not None:
        where, fields = located(task, entry, args.repo)
        if args.sha is not None:
            fields["sha"] = landed(where, args.sha, args.default) if args.status == "merged" else commit(where, args.sha)
    if pr is not None:
        fields["pr"] = pr
    with rasci.database() as tasks:
        entry = tasks.get(task)
        if entry is None or "stage" not in entry:
            fail(f"{task}: no hotfix in the register; record it with add")
        entry.update(fields)
        entry["stage"] = args.status
        rasci.apply_status(entry, REGISTER_STATUS[args.status])
    print(f"updated {task}")
    if args.status == "merged":
        announce(task, entry, args.session)
    return 0


def cmd_pending(rasci: ModuleType, args: argparse.Namespace) -> int:
    repo = worktree(args.repo)
    rows, unknowns = of_repository(rasci, repo)
    rows = for_targets(rows, args.target)
    problems: list[str] = []
    on, off, shown = missing(repo, rows, problems)
    verdicts = {t: "missing (merge main)" for t, _ in on} | {t: f"not on {shown}" for t, _ in off}
    opened = 0
    for task, row in rows:
        if row["stage"] != "merged":
            verdict = "open, not merged"
            opened += 1
        elif task in verdicts:
            verdict = verdicts[task]
        else:
            continue
        print("\t".join((verdict, task, row["stage"], row["branch"], row["sha"], pr_cell(row))))
    report([*unknowns, *problems])
    print(f"hotfix: {len(on)} missing, {opened} open")
    if problems:
        return 2
    return 1 if on else 0


def cmd_match(rasci: ModuleType, args: argparse.Namespace) -> int:
    here = identity(worktree(args.repo)) if args.repo is not None else None
    rows = []
    for task, row in hotfixes(rasci):
        try:
            re.compile(row["signature"])
        except re.error as error:
            print(f"hotfix: {task}: signature does not compile ({error}), skipped", file=sys.stderr)
            continue
        rows.append((task, row))
    hits = []
    while rows:
        verdicts = searched([row["signature"] for _, row in rows], args.line)
        hits += [entry for entry, hit in zip(rows[:len(verdicts)], verdicts, strict=True) if hit]
        if len(verdicts) == len(rows):
            break
        task, row = rows[len(verdicts)]
        print(f"hotfix: {task}: signature {row['signature']!r} still searched this line at the {SEARCH_SECONDS} s "
              "deadline, skipped; its A must narrow it", file=sys.stderr)
        rows = rows[len(verdicts) + 1:]
    found = 0
    for task, row in hits:
        cells = [task, row["stage"], row["branch"], row["sha"], pr_cell(row), repository(row)]
        theirs = recorded(row)
        if here is not None and theirs is None:
            cells.insert(0, "unknown")
        elif here is not None and not same(theirs, here):
            cells.insert(0, "foreign")
        else:
            found += 1
        print("\t".join(cells))
    if not found:
        print("hotfix: no signature matches" if here is None else "hotfix: no signature of this repository matches")
    return 0 if found else 1


def cmd_void(rasci: ModuleType, args: argparse.Namespace) -> int:
    repo = worktree(args.repo)
    rows, unknowns = of_repository(rasci, repo)
    rows = for_targets(rows, args.target)
    problems: list[str] = []
    on, off, shown = missing(repo, rows, problems)
    for task, row in off:
        print(f"hotfix: {task}: {row['sha']} is not on {shown} (a squash or rebase merge?), so it voids nothing; "
              "its A must record the commit as it sits there", file=sys.stderr)
    for task, row in on:
        print("\t".join(("void", task, row["sha"], ",".join(row.get("targets") or []) or "all targets")))
    report([*unknowns, *problems])
    if on:
        return 3
    return 2 if problems else 0


@contextlib.contextmanager
def locked(repo: str, command: list[str]) -> Iterator[None]:
    """Hold gate.py's sync lock and worktree lock of the worktree.

    Args:
      repo: the worktree.
      command: sync's command line, recorded in the sync lock.
    """
    if not GATE.is_file():
        yield
        return
    gate = module("gate", GATE)
    git_dir = Path(git_out(repo, "rev-parse", "--absolute-git-dir").strip())
    with (
        open(git_dir / gate.SYNC_LOCK, "a", encoding="utf-8") as sync,
        open(git_dir / gate.RUN_LOCK, "a", encoding="utf-8") as run,
    ):
        fcntl.flock(sync, fcntl.LOCK_EX)
        gate.claim(sync, command)
        try:
            fcntl.flock(run, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fail(f"a gate.py run or hold holds {repo} ({gate.holder(git_dir / gate.RUN_LOCK)}); sync once it ends")
        yield


def watched(repo: str) -> None:
    if WATCH.is_file():
        watch = module("watch", WATCH)
        config = watch.load_config()
        if config is not None and watch.busy(repo, config["busy_processes"]):
            fail(f"a busy process (watch.py busy_processes) runs in {repo}, a gate or deploy; sync once it ends")


def chain(repo: str, tasks: dict[str, dict], task: str, default: str, ended: tuple[str, ...]) -> list[str]:
    here = identity(repo)
    places: dict[str, tuple[str, str] | None] = {}
    found: list[str] = []
    base = tasks[task].get("base")
    while base and base != default:
        if base in found:
            fail(f"base chain of {task} loops: {' <- '.join([*found, base])}")
        found.append(branch_name(repo, base, "base"))
        upstream = {}
        for name, row in sorted(tasks.items()):
            if row.get("branch") != base or not row.get("base") or row.get("status") in ended:
                continue
            workdir = row.get("workdir") or ""
            if not workdir:
                if not (resolves(repo, f"refs/heads/{base}") or resolves(repo, f"refs/remotes/origin/{base}")):
                    fail(f"{name} records no workdir and its branch {base} resolves neither as {base} nor as "
                         f"origin/{base} in {repo}; record it with `rasci.py set {name} --workdir <dir>`")
                upstream[name] = row["base"]
                continue
            if workdir not in places:
                places[workdir] = identity(workdir)
            if places[workdir] is None:
                print(f"hotfix: {name}: workdir {workdir} is no git repository, its base is not followed",
                      file=sys.stderr)
            elif same(places[workdir], here):
                upstream[name] = row["base"]
        if len(set(upstream.values())) > 1:
            named = ", ".join(f"{t}={b}" for t, b in sorted(upstream.items()))
            fail(f"branch {base} has several bases in the register: {named}")
        base = next(iter(upstream.values()), None)
    return found


def base_ref(repo: str, base: str) -> tuple[str, str]:
    local, remote = f"refs/heads/{base}", f"refs/remotes/origin/{base}"
    if not resolves(repo, remote):
        if not resolves(repo, local):
            fail(f"{base} does not resolve in {repo}")
        return base, local
    if not resolves(repo, local) or ancestor(repo, local, remote):
        return f"origin/{base}", remote
    if ancestor(repo, remote, local):
        return base, local
    fail(f"{base} and origin/{base} have diverged in {repo}; merge one into the other first")


def flow_ref(repo: str, name: object) -> tuple[str, str]:
    if not isinstance(name, str):
        fail(f"the merge flow of {repo} lists {name!r} as pull, no branch name")
    branch_name(repo, name, "flow pull")
    if resolves(repo, f"refs/remotes/{name}"):
        return name, f"refs/remotes/{name}"
    return base_ref(repo, name)


def flow_pulls(repo: str) -> list[tuple[str, str]]:
    """The pull list of the worktree's merge flow, as refs to merge.

    Args:
      repo: the worktree.

    Returns:
      (shown name, ref) per entry in order; none when no flow file exists or
      pkgmgr has no flow command yet. An invalid flow file fails with exit 2.
    """
    git_dir = Path(git_out(repo, "rev-parse", "--absolute-git-dir").strip())
    if not os.path.lexists(git_dir.joinpath(*FLOW_FILE)):
        return []
    try:
        result = subprocess.run(
            [*PKGMGR_FLOW, repo, "--json"], stdin=subprocess.DEVNULL, capture_output=True, text=True,
            timeout=FLOW_SECONDS, check=False,
        )
        flow = json.loads(result.stdout) if result.returncode == 0 else {}
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return []
    source = flow.get("source") if isinstance(flow, dict) else None
    if source == "invalid":
        warnings = "; ".join(str(warning) for warning in flow.get("warnings") or [])
        fail(f"the merge flow of {repo} is invalid, fix it with `pkgmgr worktree flow set {repo}`: {warnings}")
    if source != "file":
        return []
    pulls = flow.get("pull")
    if not isinstance(pulls, list):
        fail(f"the merge flow of {repo} carries no pull list")
    return [flow_ref(repo, name) for name in pulls]


def default_ref(repo: str, given: str | None) -> tuple[str, tuple[str, str]]:
    if git(repo, "config", "--get", "remote.origin.url").stdout.strip():
        default = default_branch(repo, given)
        fetched(repo)
        return default, (f"origin/{default}", f"refs/remotes/origin/{default}")
    if given is None:
        fail(f"{repo} has no origin remote; pass --default <branch>, its local default branch")
    default = branch_name(repo, given, "--default")
    return default, (default, f"refs/heads/{default}")


def cmd_sync(rasci: ModuleType, args: argparse.Namespace) -> int:
    repo = worktree(args.repo)
    tasks = rasci.load()
    if args.task not in tasks:
        fail(f"{args.task}: not in the register")
    branch = tasks[args.task].get("branch")
    if not branch:
        fail(f"{args.task} records no branch; set it with `rasci.py set {args.task} --branch <branch>`")
    head = git(repo, "symbolic-ref", "--quiet", "HEAD").stdout.strip()
    if head != f"refs/heads/{branch}":
        fail(f"{repo} has {head.removeprefix('refs/heads/') or 'a detached HEAD'} checked out, "
             f"{args.task} works on {branch}")
    default, first = default_ref(repo, args.default)
    with locked(repo, ["hotfix.py", "sync", "--repo", repo, "--task", args.task]):
        watched(repo)
        dirty = [line[3:] for line in git_out(repo, "status", "--porcelain=v1", "--untracked-files=no").splitlines()]
        if dirty:
            fail(f"tracked files are dirty, commit them first: {', '.join(dirty)}")
        if not resolves(repo, first[1]):
            fail(f"{first[0]} does not resolve in {repo}")
        bases = chain(repo, tasks, args.task, default, rasci.ENDED)
        steps = [first, *(base_ref(repo, base) for base in bases)]
        steps += [pull for pull in flow_pulls(repo) if pull[1] not in {ref for _, ref in steps}]
        for shown, ref in steps:
            if ancestor(repo, ref, "HEAD"):
                print(f"contained\t{shown}")
                continue
            result = git(repo, "merge", "--no-verify", "--no-edit", ref)
            if result.returncode == 0:
                print(f"merged\t{shown}\t{git_out(repo, 'rev-parse', 'HEAD').strip()}")
                continue
            files = git(repo, "diff", "--name-only", "--diff-filter=U").stdout.splitlines()
            if git(repo, "rev-parse", "--verify", "--quiet", "MERGE_HEAD").returncode == 0:
                git_out(repo, "merge", "--abort")
            if not files:
                fail(f"git merge {shown} failed and was aborted: {(result.stderr or result.stdout).strip()}")
            print(f"conflict\t{shown}\t{','.join(files)}")
            print(f"hotfix: merging {shown} conflicts in {', '.join(files)}; merge aborted", file=sys.stderr)
            return 4
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("add")
    p.add_argument("slug")
    for flag in ("--repo", "--branch", "--sha", "--signature"):
        p.add_argument(flag, required=True)
    p.add_argument("--status", choices=STAGES, required=True)
    p.add_argument("--target", action="append")
    p.add_argument("--pr", type=int)
    p.add_argument("--default")
    p.add_argument("--session")
    p.set_defaults(func=cmd_add)
    p = sub.add_parser("update")
    p.add_argument("slug")
    p.add_argument("--status", choices=STAGES, required=True)
    p.add_argument("--sha")
    p.add_argument("--pr", type=int)
    p.add_argument("--repo")
    p.add_argument("--default")
    p.add_argument("--session")
    p.set_defaults(func=cmd_update)
    p = sub.add_parser("pending")
    p.add_argument("--repo", required=True)
    p.add_argument("--target", action="append")
    p.set_defaults(func=cmd_pending)
    p = sub.add_parser("match")
    p.add_argument("--line", required=True)
    p.add_argument("--repo")
    p.set_defaults(func=cmd_match)
    p = sub.add_parser("void")
    p.add_argument("--repo", required=True)
    p.add_argument("--target", action="append", required=True)
    p.set_defaults(func=cmd_void)
    p = sub.add_parser("sync")
    p.add_argument("--repo", required=True)
    p.add_argument("--task", required=True)
    p.add_argument("--default")
    p.set_defaults(func=cmd_sync)
    args = parser.parse_args()
    return args.func(module("rasci", RASCI), args)


if __name__ == "__main__":
    sys.exit(main())
