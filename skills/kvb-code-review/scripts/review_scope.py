from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

DEFAULTS = ("main", "master")
STAGED = "staged"
PULL = "pr"
BRANCH = "branch"
RANGE = "range"
GH_SECONDS = 30


class ScopeError(Exception):
    pass


@dataclass(frozen=True)
class Scope:
    """Args:
        kind: STAGED, PULL, BRANCH or RANGE.
        base: the commit the change starts from; HEAD for STAGED.
        head: the last commit of the change; None for STAGED, whose change
            is the index.
        spec: the target as the operator picked it.
    """

    kind: str
    base: str
    head: str | None
    spec: str


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise ScopeError(f"git {' '.join(args)}: {done.stderr.strip() or done.returncode}")
    return done.stdout


def git_bytes(repo: Path, args: list[str], given: bytes | None) -> bytes:
    done = subprocess.run(["git", *args], cwd=repo, input=given, capture_output=True, check=False)
    if done.returncode != 0:
        raise ScopeError(f"git {' '.join(args)}: {done.stderr.decode(errors='replace').strip() or done.returncode}")
    return done.stdout


def succeeds(repo: Path, *args: str) -> bool:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, check=False).returncode == 0


def commit(repo: Path, ref: str) -> str:
    return git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}").strip()


def upstream(repo: Path) -> str | None:
    done = subprocess.run(["git", "rev-parse", "--verify", "--quiet", "@{u}^{commit}"], cwd=repo, capture_output=True, text=True, check=False)
    return done.stdout.strip() if done.returncode == 0 else None


def default_branch(repo: Path) -> str | None:
    done = subprocess.run(["git", "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"], cwd=repo, capture_output=True, text=True, check=False)
    if done.returncode == 0 and done.stdout.strip():
        return done.stdout.strip().split("/", 1)[-1]
    return next((name for name in DEFAULTS if succeeds(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{name}")), None)


def pull_request(repo: Path, number: str) -> dict | None:
    """Returns:
        number, state, baseRefName and headRefOid of the pull request gh
        names for the branch (number "") or for that number; None without
        gh, without one, or when gh fails.
    """
    gh = shutil.which("gh")
    if gh is None:
        return None
    argv = [gh, "pr", "view", *([number] if number else []), "--json", "number,state,baseRefName,headRefOid"]
    try:
        done = subprocess.run(argv, cwd=repo, capture_output=True, text=True, check=False, timeout=GH_SECONDS)
    except subprocess.TimeoutExpired:
        return None
    if done.returncode != 0:
        return None
    try:
        data = json.loads(done.stdout)
    except ValueError:
        return None
    return data if isinstance(data, dict) and isinstance(data.get("number"), int) else None


def detect(repo: Path) -> str:
    """Returns:
        The recommended target: STAGED with staged changes, else `pr <n>`
        for an open pull request of the branch, else `branch <default>`
        with commits ahead of the default branch, else `range <upstream>..HEAD`
        with unpushed commits, else RANGE for the operator to name.
    """
    if not succeeds(repo, "diff", "--cached", "--quiet"):
        return STAGED
    found = pull_request(repo, "")
    if found is not None and found.get("state") == "OPEN":
        return f"{PULL} {found['number']}"
    default = default_branch(repo)
    if default is not None and int(git(repo, "rev-list", "--count", f"{default}..HEAD").strip()) > 0:
        return f"{BRANCH} {default}"
    pushed = upstream(repo)
    if pushed is not None and int(git(repo, "rev-list", "--count", f"{pushed}..HEAD").strip()) > 0:
        return f"{RANGE} {pushed}..HEAD"
    return RANGE


def unknown(spec: str) -> ScopeError:
    return ScopeError(f"target must be staged, pr <n>, branch <name> or range <a>..<b>, not {spec!r}")


def named(repo: Path, kind: str, value: str, spec: str) -> Scope:
    if kind == BRANCH:
        head = commit(repo, "HEAD")
        return Scope(BRANCH, git(repo, "merge-base", value, head).strip(), head, spec)
    if kind == RANGE and ".." in value:
        start, end = value.split("..", 1)
        return Scope(RANGE, commit(repo, start), commit(repo, end or "HEAD"), spec)
    if kind == PULL and value.isdigit():
        return pull_scope(repo, value, spec)
    raise unknown(spec)


def resolve(repo: Path, spec: str) -> Scope:
    parts = spec.split()
    if parts == [STAGED]:
        return Scope(STAGED, commit(repo, "HEAD"), None, spec)
    if len(parts) == 2:
        return named(repo, parts[0], parts[1], spec)
    raise unknown(spec)


def pull_scope(repo: Path, number: str, spec: str) -> Scope:
    found = pull_request(repo, number)
    if found is None:
        raise ScopeError(f"gh knows no pull request {number} here")
    head = commit(repo, "HEAD")
    if found.get("headRefOid") != head:
        raise ScopeError(f"HEAD is not the head of pull request {number}; check it out first: gh pr checkout {number}")
    base_ref = found.get("baseRefName") or ""
    remote = f"origin/{base_ref}"
    base_name = remote if succeeds(repo, "rev-parse", "--verify", "--quiet", remote) else base_ref
    return Scope(PULL, git(repo, "merge-base", base_name, head).strip(), head, spec)


def diff_args(scope: Scope) -> list[str]:
    return ["--cached", scope.base] if scope.head is None else [scope.base, scope.head]


def changed(repo: Path, scope: Scope) -> dict[str, str]:
    """Returns:
        Every path the change adds, copies, modifies or renames, with the
        blob it has after the change: the index entry for STAGED, else the
        entry in the head commit.
    """
    names = [name for name in git(repo, "diff", "--name-only", "-z", "--diff-filter=ACMR", *diff_args(scope)).split("\0") if name]
    if not names:
        return {}
    listing = git(repo, "ls-files", "-s", "-z", "--", *names) if scope.head is None else git(repo, "ls-tree", "-r", "-z", scope.head, "--", *names)
    blobs = {}
    for entry in listing.split("\0"):
        if not entry:
            continue
        meta, path = entry.split("\t", 1)
        fields = meta.split()
        blobs[path] = fields[1] if scope.head is None else fields[2]
    return blobs


def patch_id(repo: Path, scope: Scope) -> str:
    patch = git_bytes(repo, ["diff", *diff_args(scope)], None)
    if not patch.strip():
        return ""
    return git_bytes(repo, ["patch-id", "--stable"], patch).decode().split()[0]


def hunks(repo: Path, scope: Scope, paths: list[str]) -> str:
    return git(repo, "diff", "-U3", *diff_args(scope), "--", *paths) if paths else ""


def line_text(repo: Path, blob: str, line: int | None) -> str:
    if line is None or line < 1:
        return ""
    lines = git_bytes(repo, ["cat-file", "blob", blob], None).decode("utf-8", "replace").splitlines()
    return lines[line - 1].strip() if line <= len(lines) else ""


def tree(repo: Path) -> str:
    return git(repo, "rev-parse", "HEAD^{tree}").strip()


def dirty(repo: Path) -> bool:
    return bool(git(repo, "status", "--porcelain", "--untracked-files=no").strip())


def common_dir(repo: Path) -> Path:
    return Path(git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir").strip())


def push_base(repo: Path) -> str | None:
    """Returns:
        The commit a push starts from: the upstream, or without one the
        merge base with the default branch; None when neither exists.
    """
    pushed = upstream(repo)
    if pushed is not None:
        return pushed
    default = default_branch(repo)
    return None if default is None else git(repo, "merge-base", default, "HEAD").strip()
