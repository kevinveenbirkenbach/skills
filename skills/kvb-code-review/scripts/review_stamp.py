from __future__ import annotations

import datetime
import json
import shlex
from pathlib import Path

import review_memory
import review_scope
from review_lenses import BLOCKING, SEVERITIES

CLEAN = "clean"
BLOCKED = "blocked"
PENDING = "pending"
WAIVED = "waived"
MISSING = "missing"
CONFIRMED = "confirmed"
REFUTED = "refuted"
WAIVE = "Waive"
KEEP = "Keep blocked"
HUB_SECONDS = 10
OPERATORS = ("&&", "||", ";", "|")
PUSHED = "pushed:"
FLAGS = ("--check", "--dir", "--command")
PUSH_TOOLS = ("gipsn", "git-sign-push")
PUSH_WORDS = ("push", "gipsn")
COLUMNS = ("Severity", "Lens", "File:line", "Finding", "Skeptic", "Evidence")
PORT_KEY = "KVB_ORCHESTRATOR_PORT="
QUOTES = "'\""


class Refused(Exception):
    pass


def skeptic(entry: dict, verdicts: dict) -> str:
    """Returns:
        CONFIRMED or REFUTED once the lens skeptic, and for a critical or
        high finding also its own skeptic, judged it; PENDING before.
    """
    roles = ("lens", "blocker") if entry["severity"] in BLOCKING else ("lens",)
    found = [verdicts.get(f"{entry['key']}:{role}") for role in roles]
    if any(item is not None and item["verdict"] == REFUTED for item in found):
        return REFUTED
    return PENDING if None in found else CONFIRMED


def decide(findings: list[dict], verdicts: dict, unreviewed: list[str]) -> str:
    states = [(entry, skeptic(entry, verdicts)) for entry in findings]
    if any(entry["severity"] in BLOCKING and state == CONFIRMED for entry, state in states):
        return BLOCKED
    return PENDING if unreviewed or any(state == PENDING for _, state in states) else CLEAN


def cell(text: object) -> str:
    return " ".join(str(text).split()).replace("|", "\\|")


def table(findings: list[dict], verdicts: dict) -> str:
    ranked = sorted(findings, key=lambda entry: (SEVERITIES.index(entry["severity"]), entry["lens"], entry["path"], entry["line"] or 0))
    rows = [f"| {' | '.join(COLUMNS)} |", f"| {' | '.join('---' for _ in COLUMNS)} |"]
    for entry in ranked:
        state = skeptic(entry, verdicts)
        proof = verdicts.get(f"{entry['key']}:lens", {}).get("evidence") or entry["evidence"]
        place = entry["path"] if entry["line"] is None else f"{entry['path']}:{entry['line']}"
        rows.append(f"| {' | '.join(cell(item) for item in (entry['severity'], entry['lens'], place, entry['message'], state, proof))} |")
    return "\n".join(rows)


def stamps(repo: Path) -> Path:
    return review_scope.common_dir(repo) / review_memory.STAMPS


def now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")


def stamp(repo: Path, scope: review_scope.Scope, verdict: str, versions: dict[str, str]) -> str:
    """Returns:
        The stamped tree; Refused when the tracked tree is dirty, the review
        is pending, or its target is not everything the push sends.
    """
    if review_scope.dirty(repo):
        raise Refused("the tracked tree is dirty; commit or drop the changes first")
    head = review_scope.commit(repo, "HEAD")
    base = review_scope.push_base(repo)
    if scope.head != head or base is None or scope.base != base:
        raise Refused(f"the target must be everything the push sends: range {base or '<upstream>'}..HEAD, not {scope.spec}")
    if verdict == PENDING:
        raise Refused("the review is pending: a lens or a skeptic has not answered")
    tree = review_scope.tree(repo)
    with review_memory.held(stamps(repo)) as data:
        data[tree] = {"verdict": verdict, "target": scope.spec, "base": base, "head": head, "stamped": now(), "lenses": versions}
    return tree


def entry_of(repo: Path) -> tuple[str, dict | None]:
    tree = review_scope.tree(repo)
    return tree, review_memory.read(stamps(repo)).get(tree)


def question(repo: Path) -> str:
    return f"Waive the review for the push of tree {review_scope.tree(repo)} in {repo}?"


def hub_port() -> int:
    """Returns:
        The port the installed hub publishes, KVB_ORCHESTRATOR_PORT of the
        .env the operator's install writes outside every agent's sandbox;
        Refused when no hub is installed.
    """
    # Trip-wire: never take the port from argv or the stamp file; an agent writes both and could aim verify at its own listener.
    env = Path.home() / ".local" / "share" / "kvb-orchestrator" / ".env"
    try:
        lines = env.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise Refused(f"no installed hub: {error}") from error
    for line in lines:
        value = line.removeprefix(PORT_KEY)
        if value != line and value.isdigit():
            return int(value)
    raise Refused(f"{env} names no {PORT_KEY.rstrip('=')}")


def operator_message(port: int, message: str, answer: str, agent: str) -> dict:
    import urllib.request

    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "operator_message", "arguments": {"id": message, "text": answer, "to": agent}}}
    request = urllib.request.Request(f"http://127.0.0.1:{port}/mcp", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=HUB_SECONDS) as reply:
            data = json.load(reply)
    except (OSError, ValueError) as error:
        raise Refused(f"the hub on port {port} did not answer: {error}") from error
    result = data.get("result") if isinstance(data, dict) else None
    if not isinstance(result, dict) or result.get("isError") or not isinstance(result.get("structuredContent"), dict):
        content = result.get("content") if isinstance(result, dict) else None
        raise Refused(f"the hub refused the waiver: {content[0].get('text') if content else data}")
    return result["structuredContent"]


def verify(message: str, answer: str, agent: str, tree: str) -> None:
    signed = operator_message(hub_port(), message, answer, agent)
    if signed.get("match") is not True or " ".join(str(signed.get("text")).split()) != " ".join(answer.split()):
        raise Refused("the signed text differs from the waiver")
    if f"tree {tree}" not in answer or not answer.endswith(f"): {WAIVE}"):
        raise Refused(f"the signed answer does not waive tree {tree}")


def waive(repo: Path, message: str, answer: str, agent: str) -> str:
    tree = review_scope.tree(repo)
    verify(message, answer, agent, tree)
    with review_memory.held(stamps(repo)) as data:
        data[tree] = {"verdict": WAIVED, "message": message, "answer": answer, "agent": agent, "waived": now()}
    return tree


def options(tokens: list[str]) -> dict[str, str]:
    """Args:
        tokens: the shell words after `operator.py add`.

    Returns:
        The last value of --check, --dir and --command up to the first shell
        operator, as `--flag value` or `--flag=value`.
    """
    found = {}
    for position, item in enumerate(tokens):
        if item in OPERATORS:
            break
        name, joined, value = item.partition("=")
        if joined and name in FLAGS:
            found[name] = value
        elif item in FLAGS and position + 1 < len(tokens):
            found[item] = tokens[position + 1]
    return found


def pushes(command: str) -> bool:
    try:
        words = [Path(word.strip(QUOTES)).name for part in shlex.split(command) for word in part.split()]
    except ValueError:
        return any(word in command for word in PUSH_WORDS)
    return any(word in PUSH_TOOLS for word in words) or any(word == "git" and "push" in words[position + 1:] for position, word in enumerate(words))


def target(found: dict[str, str]) -> str | None:
    check = found.get("--check")
    if check is not None and check.startswith(PUSHED):
        return check.removeprefix(PUSHED)
    if "--command" in found and "--dir" in found and pushes(found["--command"]):
        return found["--dir"]
    return None


def adds(tokens: list[str]) -> list[int]:
    return [start + 2 for start, token in enumerate(tokens[:-1]) if Path(token).name == "operator.py" and tokens[start + 1] == "add"]


def pushed_dirs(command: str) -> list[str]:
    """Returns:
        The directory of every push row in the shell command, in order: each
        `operator.py add` with `--check pushed:<dir>`, or whose --command
        runs git push, gipsn or git-sign-push in its --dir.
    """
    if "operator.py" not in command or not any(word in command for word in PUSH_WORDS):
        return []
    try:
        tokens = shlex.split(command)
    except ValueError:
        return []
    return [directory for start in adds(tokens) if (directory := target(options(tokens[start:]))) is not None]


def refusal(directory: str) -> str | None:
    """Returns:
        Why a push row for the directory may not be added, or None when its
        HEAD tree carries a clean stamp or a waiver the hub verifies again.
    """
    repo = Path(directory)
    try:
        tree, entry = entry_of(repo)
    except (review_scope.ScopeError, ValueError, TypeError, OSError) as error:
        return f"no clean review: {error}"
    if entry is None or entry.get("verdict") not in (CLEAN, WAIVED):
        return f"no clean review for tree {tree}"
    if entry["verdict"] == WAIVED:
        try:
            verify(entry["message"], entry["answer"], entry["agent"], tree)
        except (Refused, KeyError) as error:
            return f"no clean review for tree {tree}: the waiver did not verify ({error})"
    return None
