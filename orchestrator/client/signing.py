from __future__ import annotations

import base64
import copy
import fnmatch
import hashlib
import json
import re
import unicodedata
from pathlib import Path

RP_ID = "localhost"
VERSION = 1
LIFETIME = 900
RULE_LIFETIME = 366 * 86400
ALGORITHMS = {-7: "ES256", -8: "EdDSA", -257: "RS256"}
HASH = re.compile(r"[0-9a-f]{64}")
NONCE = re.compile(r"[0-9a-f]{32}")
ID = re.compile(r"[0-9a-f]{16}")
CHAINED = re.compile(r"[;&|`$<>()\n\r]")
OFFICE = re.compile(r"chair|[a-z0-9][a-z0-9._-]{0,63}/[a-z0-9][a-z0-9._-]{0,63}")
SESSION = re.compile(r"(?!-)[A-Za-z0-9_-]{1,128}")
WORK = re.compile(r"(?=[^\x00-\x1f\x7f]*\S)[^\x00-\x1f\x7f]{1,300}")
HOLDER = re.compile(r"[^\x00-\x1f\x7f]{0,200}")
OFFICE_ACTIONS = ("appoint", "takeover", "recall")
OFFICE_KEYS = ("action", "office", "holder", "session", "work")
TASK = re.compile(r"[a-z0-9][a-z0-9._-]{0,99}(?:/[a-z0-9][a-z0-9._-]{0,99}){0,7}")
PRIO = re.compile(r"[1-9][0-9]{0,2}")
FIBONACCI = ("1", "2", "3", "5", "8", "13", "21", "34", "55", "89")
ESTIMATOR = "Operator"
COMMANDS = "operator/"
STATUSES = ("queued", "running", "blocked", "done", "stopped")
GATE_LEVELS = ("none", "quick", "test", "quality-high", "e2e")
GATE_ACTIONS = ("commit", "merge", "push", "pr")
GATE_REPO = re.compile(r"/[^\x00-\x1f\x7f]{0,4095}")
GATE_BRANCH = re.compile(r"(?![-/])(?!.*\.\.)(?!.*@\{)(?!.*//)[^\x00-\x20\x7f~^:?*\[\\]{1,255}(?<![/.])")
TOKEN_FREE_MERGE = "ancestor"
APPROVAL_KEYS = {"v", "kind", "items", "nonce", "expires"}
RULE_KEYS = {"v", "kind", "id", "kinds", "tool", "pattern", "scope", "expires"}
TARGET = "agents"
ALL_AGENTS = "*"
AGENT_LIMIT = 50
SETTINGS_FILE = "/.claude/settings.json"
SETTINGS_KEYS = ("file", "base", "changes")
SETTINGS_SECTIONS = ("permissions", "sandbox")
SETTINGS_LISTS = ("permissions.allow", "permissions.ask", "permissions.deny", "sandbox.filesystem.allowWrite", "sandbox.filesystem.denyRead", "sandbox.network.allowedDomains")
SETTINGS_OPS = ("add", "remove")
CHANGE_KEYS = ("list", "op", "entry")
CHANGE_LIMIT = 50
ENTRY = re.compile(r"(?=[^\x00-\x1f\x7f\ud800-\udfff]*\S)[^\x00-\x1f\x7f\ud800-\udfff]{1,500}")
SETTINGS_PATH = re.compile(r"/[^\x00-\x1f\x7f\ud800-\udfff]{0,4095}")
SURROGATE = re.compile(r"[\ud800-\udfff]")
UNSEEN = ("Cc", "Cf", "Zl", "Zp")
DEFAULT_IGNORABLE = ((0xAD, 0xAD), (0x34F, 0x34F), (0x61C, 0x61C), (0x115F, 0x1160), (0x17B4, 0x17B5), (0x180B, 0x180F), (0x200B, 0x200F), (0x202A, 0x202E), (0x2060, 0x206F), (0x3164, 0x3164), (0xFE00, 0xFE0F), (0xFEFF, 0xFEFF), (0xFFA0, 0xFFA0), (0xFFF0, 0xFFF8), (0x1BCA0, 0x1BCA3), (0x1D173, 0x1D17A), (0xE0000, 0xE0FFF))
IGNORABLE = frozenset(code for start, end in DEFAULT_IGNORABLE for code in range(start, end + 1))
EMOJI_TABLE = Path(__file__).with_name("emoji-variation.json")
HEX_CODE = re.compile(r"[0-9A-F]{4,6}")
PRESENTATION = (chr(0xFE0E), chr(0xFE0F))
FREE_TEXT = ("command", "text", "reason", "question", "description")
BREAKS = "\t\n"
DEPTH_LIMIT = 64
WARNINGS = (
    ("deletes recursively", re.compile(r"\brm\s+(?:-\S+\s+)*-\S*[rR]")),
    ("forces", re.compile(r"--force\b|\bpush\b.*\s-f\b")),
    ("pushes", re.compile(r"\bgit\b.*\bpush\b")),
    ("root", re.compile(r"\bsudo\b|\bdoas\b")),
    ("pipes into a shell", re.compile(r"\|\s*(?:sudo\s+)?(?:ba|z|k|da)?sh\b")),
    ("discards changes", re.compile(r"\bgit\b.*\b(?:reset\s+--hard|clean\s+-\S*f)")),
    ("Docker deletes", re.compile(r"\bdocker\s+(?:system\s+prune|volume\s+(?:rm|prune)|rmi?\b)")),
)


class Refused(Exception):
    pass


def origin_of(port: int) -> str:
    return f"http://{RP_ID}:{port}"


def b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")


def challenge(payload: dict) -> str:
    return b64encode(hashlib.sha256(canonical(payload)).digest())


def item_hash(item: dict) -> str:
    return hashlib.sha256(canonical(item)).hexdigest()


def ask_item(ask_id: str, tool: str, command: str, cwd: str, session: str) -> dict:
    return {"kind": "ask", "id": ask_id, "tool": tool, "command": command, "cwd": cwd, "session": session}


def review_item(review_id: str, repo: str, worktree: str, branch: str, tree: str) -> dict:
    return {"kind": "review", "id": review_id, "repo": repo, "worktree": worktree, "branch": branch, "tree": tree}


def operator_item(task: str, command: str, directory: str) -> dict:
    return {"kind": "operator", "id": task, "command": command, "directory": directory}


def cleanup_item(repository: str, branch: str, worktree: str, tip: str) -> dict:
    return {"kind": "cleanup", "repository": repository, "branch": branch, "worktree": worktree, "tip": tip}


def office_item(action: str, office: str, holder: str, session: str, work: str) -> dict:
    return {"kind": "office", "action": action, "office": office, "holder": holder, "session": session, "work": work}


def office_problem(order: object) -> str | None:
    """Args:
        order: {"action", "office", "holder", "session", "work"}: appoint
            gives a vacant office to the session, takeover hands the
            holder's office to the session, recall takes it from the
            holder; work is the claim's one-line --work.

    Returns:
        Why the order is malformed, or None.
    """
    if not isinstance(order, dict) or set(order) != set(OFFICE_KEYS) or not all(isinstance(order[name], str) for name in OFFICE_KEYS):
        return "an office order holds exactly action, office, holder, session and work as text"
    action, office, holder, session, work = (order[name] for name in OFFICE_KEYS)
    if action not in OFFICE_ACTIONS:
        return f"action must be one of {', '.join(OFFICE_ACTIONS)}"
    if not OFFICE.fullmatch(office):
        return "office must be chair, <dimension>/<line>, cluster/<slug> or work/<slug>"
    if not HOLDER.fullmatch(holder) or (action == "appoint") != (holder == ""):
        return "appoint names no holder, takeover and recall the current one"
    if action == "recall":
        return None if session == work == "" else "a recall names no successor and no work"
    if not SESSION.fullmatch(session) or session == holder:
        return "session must be the successor's session id, not the holder's"
    if not WORK.fullmatch(work):
        return "work must be one line of 1 to 300 characters"
    return None


def rule_request_item(request_id: str, kind: str, tool: str, pattern: str, scope: str, expires: int) -> dict:
    return {"kind": "rule-request", "id": request_id, "rule": kind, "tool": tool, "pattern": pattern, "scope": scope, "expires": expires}


def denial_item(subject: dict, channel: str, reason: str, to: str) -> dict:
    """Args:
        subject: the item an approval of it would sign.
        channel: the radio class that tells the requesting agent.
        reason: the operator's reason, possibly empty.
        to: the requesting agent's name for a direct channel, "*" for a
            class to all.

    Returns:
        The item a denial signs: its hash never equals the subject's, so no
        denial signature approves anything.
    """
    return {"kind": "deny", "subject": item_hash(subject), "channel": channel, "reason": reason, "to": to}


def message_item(to: str, cls: str, text: str, upload: str, voice: str, voice_sha256: str) -> dict:
    return {"kind": "message", "to": to, "class": cls, "text": text, "upload": upload, "voice": voice, "voice_sha256": voice_sha256}


def board_item(action: str, agents: list[str]) -> dict:
    """Args:
        action: the board action.
        agents: the session ids a night action is limited to, sorted; empty
            for every agent, which keeps the item of a board action without
            agents unchanged.

    Returns:
        The item the operator's passkey signs.
    """
    return {"kind": "board", "action": action, **({"agents": agents} if agents else {})}


def stream_item(origins: list[str], urls: list[str]) -> dict:
    return {"kind": "streams", "origins": origins, "urls": urls}


def task_item(task: str, argv: list[str]) -> dict:
    return {"kind": "task", "id": task, "argv": argv}


def board_flags(task: str, flags: list[str]) -> bool:
    if flags == ["--unpin"]:
        return True
    if len(flags) != 2:
        return False
    flag, value = flags
    if flag == "--prio":
        return bool(PRIO.fullmatch(value))
    if flag == "--status":
        return value in STATUSES
    linked = flag in ("--after", "--drop-after")
    return linked and value != task and bool(TASK.fullmatch(value)) and not value.startswith(COMMANDS)


def task_argv(task: object, argv: object) -> list[str]:
    """Args:
        task: the register task the change is for, a rasci.py slug outside
            operator/.
        argv: the rasci.py arguments, one of `set <task>` with exactly one
            of `--prio <1-999>`, `--unpin`, `--status <status>`,
            `--after <other>` or `--drop-after <other>` (other a register
            slug outside operator/), `estimate <task> Operator --value <fib>
            --complexity <fib>`, `estimate <task> Operator --value <fib>`
            (the operator's business value alone) or
            `estimate <task> Operator --drop`.

    Returns:
        argv, the hub and the runner check it the same way.

    Raises:
        Refused for every other task or argv.
    """
    if not isinstance(task, str) or not TASK.fullmatch(task) or task.startswith(COMMANDS):
        raise Refused("the task is no register task slug outside operator/")
    if not isinstance(argv, list) or not all(isinstance(part, str) for part in argv):
        raise Refused("the argv is no list of texts")
    rest = argv[3:]
    valued = len(rest) in (2, 4) and rest[0] == "--value" and rest[1] in FIBONACCI
    estimated = valued and (len(rest) == 2 or (rest[2] == "--complexity" and rest[3] in FIBONACCI))
    if (argv[:2] == ["set", task] and board_flags(task, argv[2:])) or (argv[:3] == ["estimate", task, ESTIMATOR] and (estimated or rest == ["--drop"])):
        return argv
    raise Refused("the argv is no task priority, status, dependency or WSJF estimate change of this task")


def gate_item(argv: list[str]) -> dict:
    return {"kind": "gate", "argv": argv}


def gate_argv(argv: object) -> list[str]:
    """Args:
        argv: the gates.py arguments, one of `rule set --repo R --branch B
            --action A --level L`, `rule drop --repo R --branch B --action A`,
            `parents add --repo R --branch B --parent P` (source operator) or
            `parents drop --repo R --branch B --parent P`; R an absolute path,
            B and P branch names, P not B.

    Returns:
        argv, the hub and the runner check it the same way.

    Raises:
        Refused for every other argv.
    """
    if not isinstance(argv, list) or not all(isinstance(part, str) for part in argv):
        raise Refused("the argv is no list of texts")
    head, values = argv[:2], dict(zip(argv[2::2], argv[3::2]))
    names = {("rule", "set"): ("--repo", "--branch", "--action", "--level"), ("rule", "drop"): ("--repo", "--branch", "--action"), ("parents", "add"): ("--repo", "--branch", "--parent"), ("parents", "drop"): ("--repo", "--branch", "--parent")}.get(tuple(head))
    if names is None or argv[2::2] != list(names) or len(argv) != 2 + 2 * len(names):
        raise Refused("the argv is no gates.py rule set|drop or parents add|drop of one branch")
    repo = values["--repo"]
    if not GATE_REPO.fullmatch(repo) or "/../" in f"{repo}/" or "/./" in f"{repo}/":
        raise Refused("the repository is no absolute path")
    branches = [values[name] for name in ("--branch", "--parent") if name in values]
    if not all(GATE_BRANCH.fullmatch(name) for name in branches) or len(set(branches)) != len(branches):
        raise Refused("the branch or parent is no branch name, or the branch is its own parent")
    if values.get("--action", GATE_ACTIONS[0]) not in GATE_ACTIONS or values.get("--level", GATE_LEVELS[0]) not in GATE_LEVELS:
        raise Refused(f"the action must be one of {', '.join(GATE_ACTIONS)} and the level one of {', '.join(GATE_LEVELS)}")
    return argv


def names_default(ref: object, default: object) -> bool:
    """Args:
        ref: a ref as pkgmgr names it, bare such as main or behind one
            remote such as origin/main, the remote-tracking ref it compares
            against when the remote has a HEAD.
        default: the repository's default branch as the tree file names it,
            without the remote (pkgmgr tree.py strips it).

    Returns:
        True when ref is the default branch.
    """
    if not isinstance(ref, str) or not isinstance(default, str) or not default:
        return False
    remote, _, name = ref.partition("/")
    return ref == default or (bool(remote) and name == default)


def token_free(entry: dict, default: object) -> bool:
    """Args:
        entry: a pkgmgr tree or gc plan item with merged_by, merged_into and
            remotes.
        default: the repository's default branch as the tree file names it.

    Returns:
        True for a local branch merged by ancestry into the default branch
        (names_default) that has no remote branch: deleting it needs no
        GitHub token.
    """
    return entry.get("merged_by") == TOKEN_FREE_MERGE and names_default(entry.get("merged_into"), default) and not entry.get("remotes")


def approval_payload(hashes: list[str], nonce: str, expires: int) -> dict:
    return {"v": VERSION, "kind": "approve", "items": sorted(set(hashes)), "nonce": nonce, "expires": expires}


def rule_payload(rule_id: str, kinds: list[str], tool: str, pattern: str, scope: str, expires: int) -> dict:
    return {"v": VERSION, "kind": "rule", "id": rule_id, "kinds": kinds, "tool": tool, "pattern": pattern, "scope": scope, "expires": expires}


def targeted(rule: dict, agents: list[str]) -> dict:
    """Args:
        rule: a rule_payload().
        agents: [ALL_AGENTS], or the sorted session ids of one agent or of a
            named group, resolved when the operator signs.

    Returns:
        The rule payload limited to those agents.
    """
    return {**rule, TARGET: agents}


def enable_item(rule: dict) -> dict:
    """Args:
        rule: the signed payload of a stored rule.

    Returns:
        The item a fresh approval lists to turn exactly that rule on again.
    """
    return {"kind": "enable", "rule": rule}


def agents_problem(agents: object) -> str | None:
    """Returns:
        Why agents is neither [ALL_AGENTS] nor 1 to AGENT_LIMIT sorted,
        distinct session ids, or None.
    """
    if agents == [ALL_AGENTS]:
        return None
    if not isinstance(agents, list) or not 1 <= len(agents) <= AGENT_LIMIT or not all(isinstance(agent, str) and SESSION.fullmatch(agent) for agent in agents):
        return f'agents must be ["{ALL_AGENTS}"] or 1 to {AGENT_LIMIT} session ids'
    return None if agents == sorted(set(agents)) else "agents must be sorted and distinct"


def checked_target(rule: dict) -> None:
    """Raises:
        Refused when the rule carries agents that agents_problem() refuses.
    """
    problem = agents_problem(rule[TARGET]) if TARGET in rule else None
    if problem:
        raise Refused(f"the rule names no target: {problem}")


def item_sessions(item: dict) -> set[str]:
    """Returns:
        The session an ask comes from; empty for every other item, which
        names none.
    """
    return {item["session"]} if item["kind"] == "ask" else set()


def reaches(rule: dict, sessions: set[str]) -> bool:
    """Args:
        rule: a checked rule payload.
        sessions: the sessions the item comes from; empty when the item names
            none, which only a rule for every agent reaches.

    Returns:
        True when the rule carries no agents or [ALL_AGENTS], or names one of
        the sessions.
    """
    return TARGET not in rule or rule[TARGET] == [ALL_AGENTS] or bool(sessions & set(rule[TARGET]))


def settings_item(file: str, base: str, changes: list[dict]) -> dict:
    return {"kind": "settings", "file": file, "base": base, "changes": changes}


def unseen(char: str) -> bool:
    """Returns:
        True for a character no prompt shows as itself: a category of UNSEEN,
        a space separator other than the space, or a code point of
        DEFAULT_IGNORABLE; page-reveal.js marks the same set.
    """
    category = unicodedata.category(char)
    return category in UNSEEN or (category == "Zs" and char != " ") or ord(char) in IGNORABLE


def emoji_base(code: int) -> bool:
    return 0x7F < code <= 0x10FFFF and not 0xD800 <= code <= 0xDFFF and not unseen(chr(code))


def variation_table(path: Path) -> frozenset[int]:
    """Args:
        path: the emoji variation table, a JSON object whose bases list the
            hex code points of emoji-variation-sequences.txt.

    Returns:
        The bases as code points.

    Raises:
        ValueError when bases is no list of hex strings, or names an ASCII
        code point, a surrogate or one unseen() names; like a missing file,
        this stops the module from loading, so no selector is ever accepted
        after an unchecked base.
    """
    bases = json.loads(path.read_text(encoding="utf-8"))["bases"]
    if not isinstance(bases, list) or not all(isinstance(code, str) and HEX_CODE.fullmatch(code) for code in bases):
        raise ValueError(f"{path}: bases must be a list of hex code points")
    codes = frozenset(int(code, 16) for code in bases)
    wrong = sorted(code for code in codes if not emoji_base(code))
    if wrong:
        raise ValueError(f"{path}: U+{wrong[0]:04X} is no visible non-ASCII emoji base")
    return codes


EMOJI_BASES = variation_table(EMOJI_TABLE)


def presented(text: str, index: int) -> bool:
    """Returns:
        True when text[index] is a variation selector of PRESENTATION right
        after a code point of EMOJI_BASES, a standardized emoji variation
        sequence such as the stopwatch of the score block that every prompt
        draws as the symbol itself; page-reveal.js skips the same pairs.
    """
    return text[index] in PRESENTATION and index > 0 and ord(text[index - 1]) in EMOJI_BASES


def hidden_char(text: str, name: str) -> str | None:
    """Returns:
        The first character of text that unseen() names, a tab or a line
        break only outside the FREE_TEXT fields, and no presented() selector;
        None when there is none.
    """
    allowed = BREAKS if name in FREE_TEXT else ""
    return next((char for index, char in enumerate(text) if unseen(char) and char not in allowed and not presented(text, index)), None)


def removal(value: dict) -> bool:
    return set(value) == set(CHANGE_KEYS) and value["op"] == "remove" and value["list"] in SETTINGS_LISTS


def hidden_problem(value: object, name: str) -> str | None:
    """Args:
        value: a text, or an object or list of them, that reaches a signed
            payload or the approval prompt; an object's texts are named by
            their keys. Only the entry of a settings change of op remove is
            exempt: removing an allow entry narrows access, but removing a
            deny, ask or denyRead entry widens it, and that is safe only
            because the writer removes exactly the signed text and the page
            marks every character unseen() names.
        name: the field a text sits in.

    Returns:
        Why the first text holding a character unseen() names (a bidi
        control, a zero-width character, a carriage return, a no-break space,
        a Hangul filler) is refused, since the prompt would show other text
        than what is signed; None when no text holds one.
    """
    if isinstance(value, dict):
        named = {key: child for key, child in value.items() if not (key == "entry" and removal(value))}
        return next(filter(None, (hidden_problem(child, str(key)) for key, child in named.items())), None)
    if isinstance(value, list):
        return next(filter(None, (hidden_problem(child, name) for child in value)), None)
    hidden = hidden_char(value, name) if isinstance(value, str) else None
    return None if hidden is None else f"{name} must hold no invisible, format, control or look-alike character such as U+{ord(hidden):04X}, which shows other text than what is signed"


def settings_file_problem(file: object) -> str | None:
    if not isinstance(file, str) or not SETTINGS_PATH.fullmatch(file) or not file.endswith(SETTINGS_FILE):
        return f"file must be the absolute path of a {SETTINGS_FILE.lstrip('/')}"
    if any(part in f"{file}/" for part in ("/../", "/./", "//")):
        return "file must name no . or .. and no empty part"
    return hidden_problem(file, "file")


def change_problem(change: object) -> str | None:
    if not isinstance(change, dict) or set(change) != set(CHANGE_KEYS) or not all(isinstance(change[name], str) for name in CHANGE_KEYS):
        return "a change holds exactly list, op and entry as text"
    if change["list"] not in SETTINGS_LISTS or change["op"] not in SETTINGS_OPS:
        return f"list must be one of {', '.join(SETTINGS_LISTS)} and op one of {', '.join(SETTINGS_OPS)}"
    return hidden_problem(change, "change") if ENTRY.fullmatch(change["entry"]) else "entry must be one line of 1 to 500 characters"


def settings_problem(item: object) -> str | None:
    """Args:
        item: {"file", "base", "changes"}: file the absolute path of a
            .claude/settings.json, base the sha256 of its bytes or "" while it
            is missing, changes 1 to CHANGE_LIMIT {"list", "op", "entry"},
            each list and entry once.

    Returns:
        Why the item is malformed, or None; the hub and the writer check it
        the same way.
    """
    if not isinstance(item, dict) or set(item) != set(SETTINGS_KEYS):
        return "a settings change holds exactly file, base and changes"
    if not isinstance(item["base"], str) or not (item["base"] == "" or HASH.fullmatch(item["base"])):
        return "base must be the sha256 of the file, or empty for a missing file"
    return settings_file_problem(item["file"]) or changes_problem(item["changes"])


def changes_problem(changes: object) -> str | None:
    if not isinstance(changes, list) or not 1 <= len(changes) <= CHANGE_LIMIT:
        return f"changes must list 1 to {CHANGE_LIMIT} changes"
    problem = next(filter(None, map(change_problem, changes)), None)
    if problem:
        return problem
    pairs = {(change["list"], change["entry"]) for change in changes}
    return None if len(pairs) == len(changes) else "each list and entry is changed once"


def settings_view(settings: dict) -> dict:
    """Returns:
        The permissions and sandbox sections of a settings object, the only
        part of the file the Agent Orchestrator receives.
    """
    return {name: settings[name] for name in SETTINGS_SECTIONS if isinstance(settings.get(name), dict)}


def plain_problem(value: object, depth: int) -> str | None:
    """Args:
        value: a parsed JSON value.
        depth: how many objects and lists hold it.

    Returns:
        Why value is unsafe to copy or write, a lone surrogate in any text or
        more than DEPTH_LIMIT levels, or None.
    """
    if isinstance(value, str):
        return "the file holds a lone surrogate" if SURROGATE.search(value) else None
    if not isinstance(value, (dict, list)):
        return None
    if depth >= DEPTH_LIMIT:
        return f"the file nests deeper than {DEPTH_LIMIT} levels"
    children = [*value, *value.values()] if isinstance(value, dict) else value
    return next(filter(None, (plain_problem(child, depth + 1) for child in children)), None)


def plain_copy(settings: dict) -> dict:
    """Raises:
        Refused for settings plain_problem() refuses, before deepcopy could
        recurse into them.
    """
    problem = plain_problem(settings, 0)
    if problem:
        raise Refused(problem)
    return copy.deepcopy(settings)


def apply_changes(settings: dict, changes: list[dict]) -> dict:
    """Args:
        settings: the parsed settings object.
        changes: changes settings_problem() accepts.

    Returns:
        A copy of settings with each change applied in order and every other
        key kept.

    Raises:
        Refused when settings nest deeper than DEPTH_LIMIT or hold a lone
        surrogate, an object on a list's path is no object, a list holds
        anything but text, an added entry is listed already or a removed one
        is not.
    """
    result = plain_copy(settings)
    for change in changes:
        *path, leaf = change["list"].split(".")
        node = result
        for name in path:
            node = node.setdefault(name, {})
            if not isinstance(node, dict):
                raise Refused(f"{name} is no object")
        entries = node.setdefault(leaf, [])
        if not isinstance(entries, list) or not all(isinstance(entry, str) for entry in entries):
            raise Refused(f"{change['list']} is no list of texts")
        listed = change["entry"] in entries
        if listed == (change["op"] == "add"):
            raise Refused(f"{change['list']} {'lists' if listed else 'does not list'} {change['entry']}")
        if listed:
            entries.remove(change["entry"])
        else:
            entries.append(change["entry"])
    return result


def warnings(command: str) -> list[str]:
    return [label for label, pattern in WARNINGS if pattern.search(command)]


def expiry(value: object, now: float, cap: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise Refused("the expiry is no whole number of epoch seconds")
    if value <= now:
        raise Refused("the signature has expired")
    if value > now + cap:
        raise Refused("the expiry lies too far ahead")
    return value


def checked_approval(payload: object, now: float) -> dict:
    if not isinstance(payload, dict) or set(payload) != APPROVAL_KEYS or payload["v"] != VERSION or payload["kind"] != "approve":
        raise Refused("the payload is no approval")
    items = payload["items"]
    if not isinstance(items, list) or not items or not all(isinstance(entry, str) and HASH.fullmatch(entry) for entry in items):
        raise Refused("the approval lists no item hashes")
    if not isinstance(payload["nonce"], str) or not NONCE.fullmatch(payload["nonce"]):
        raise Refused("the approval holds no nonce")
    expiry(payload["expires"], now, LIFETIME)
    return payload


def checked_rule(payload: object, now: float) -> dict:
    if not isinstance(payload, dict) or set(payload) - {TARGET} != RULE_KEYS or payload["v"] != VERSION or payload["kind"] != "rule":
        raise Refused("the payload is no rule")
    checked_target(payload)
    if not isinstance(payload["id"], str) or not ID.fullmatch(payload["id"]):
        raise Refused("the rule holds no id")
    kinds = payload["kinds"]
    if not isinstance(kinds, list) or not kinds or not all(isinstance(kind, str) for kind in kinds):
        raise Refused("the rule names no kinds")
    if not isinstance(payload["tool"], str) or not all(isinstance(payload[name], str) and payload[name] for name in ("pattern", "scope")):
        raise Refused("the rule needs a tool text, a pattern and a scope")
    expiry(payload["expires"], now, RULE_LIFETIME)
    return payload


def rule_allows(rule: dict, item: dict, gate: str, now: float) -> bool:
    return reaches(rule, item_sessions(item)) and pattern_allows(rule, item, gate, now)


def pattern_allows(rule: dict, item: dict, gate: str, now: float) -> bool:
    if rule["expires"] <= now or item["kind"] not in rule["kinds"]:
        return False
    if item["kind"] == "ask":
        named = fnmatch.fnmatchcase(item["tool"], rule["tool"]) and fnmatch.fnmatchcase(item["cwd"], rule["scope"])
        plain = not CHAINED.search(item["command"]) and not warnings(item["command"])
        return named and plain and fnmatch.fnmatchcase(item["command"], rule["pattern"])
    if item["kind"] == "review":
        return gate == "pass" and fnmatch.fnmatchcase(item["branch"], rule["pattern"]) and fnmatch.fnmatchcase(item["worktree"], rule["scope"])
    return False


def load_pinned(path: Path) -> list[dict]:
    try:
        mode = path.stat().st_mode
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError, RecursionError) as error:
        raise Refused(f"the pinned keys in {path} are unreadable") from error
    if mode & 0o022:
        raise Refused(f"{path} is writable by others")
    entries = data.get("credentials") if isinstance(data, dict) else None
    shaped = isinstance(entries, list) and all(isinstance(entry, dict) and isinstance(entry.get("id"), str) and entry.get("alg") in ALGORITHMS and isinstance(entry.get("spki"), str) for entry in entries)
    if not shaped:
        raise Refused(f"the pinned keys in {path} are malformed")
    return entries
