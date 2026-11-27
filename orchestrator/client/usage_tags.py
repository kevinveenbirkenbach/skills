"""Returns:
    The helpers resources.py tokens tags each assistant message's usage with
    (skill, tool, subagent, repo) and counts the context per turn and the
    compactions of <state>/context.jsonl with; only names and counts leave a
    transcript, never prompt text, tool inputs or outputs. Nothing here
    writes a file or calls a language model.
"""

from __future__ import annotations

import bisect
import dataclasses
import json
import os
import re
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path

HOUR = 3600
DAY = 86400
TAGS = ("skill", "tool", "subagent", "repo")
COUNTS = (("input", "input_tokens"), ("output", "output_tokens"), ("cache_read", "cache_read_input_tokens"), ("cache_write", "cache_creation_input_tokens"))
NAMES = tuple(name for name, _ in COUNTS)
USAGE_OPEN = 2 * DAY
OTHER = "(other)"
UNTYPED = "(untyped)"
FOLD_LIMIT = 50
FOLDED = (1, 2, 4, 5, 6, 7, 8)
KILO = 1000
CONTEXT_PARTS = (0, 2)
COMPACT = b"compact_boundary"
TOOL_BLOCKS = ("tool_use", "server_tool_use")
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:+-]{0,63}")
AGENT_FILE = "agent-"
META = ".meta.json"


@dataclasses.dataclass
class Turn:
    key: str
    ts: float
    session: str
    model: str
    counts: tuple[int, ...]
    tools: set[str]
    sidechain: bool
    cwd: str
    subagent: str = ""


@dataclasses.dataclass
class Read:
    turns: list[Turn] = dataclasses.field(default_factory=list)
    skills: list[tuple[str, float, str]] = dataclasses.field(default_factory=list)
    compactions: list[tuple[str, float]] = dataclasses.field(default_factory=list)

    def extend(self, other: Read, subagent: str) -> None:
        """Args:
            other: one transcript's read.
            subagent: the agent type of that transcript, given to its
                sidechain turns only.
        """
        for turn in other.turns:
            turn.subagent = subagent if turn.sidechain else ""
        self.turns += other.turns
        self.skills += other.skills
        self.compactions += other.compactions


def named(value: object) -> str:
    """Returns:
        value when it is a name of at most 64 letters, digits and _.:+-
        starting with a letter or digit, else "".
    """
    return value if isinstance(value, str) and NAME.fullmatch(value) else ""


def blocks(message: dict) -> list[dict]:
    content = message.get("content")
    return [block for block in content if isinstance(block, dict)] if isinstance(content, list) else []


def tool_names(message: dict) -> set[str]:
    return {name for block in blocks(message) if block.get("type") in TOOL_BLOCKS and (name := named(block.get("name")))}


def skill_calls(message: dict) -> list[str]:
    """Returns:
        The skill name of every Skill tool_use block in message; only the
        input's skill field is read, never its args.
    """
    found = []
    for block in blocks(message):
        given = block.get("input") if block.get("type") == "tool_use" and block.get("name") == "Skill" else None
        name = named(given.get("skill")) if isinstance(given, dict) else ""
        if name:
            found.append(name)
    return found


def is_compaction(row: dict) -> bool:
    # Claude Code writes one {"type": "system", "subtype": "compact_boundary"} line per compaction, followed by a user line with isCompactSummary; only the boundary counts, so a compaction is not counted twice.
    return row.get("type") == "system" and row.get("subtype") == "compact_boundary" and row.get("isSidechain") is not True


def agent_type(path: Path, read_json: Callable[[Path], object]) -> str:
    """Args:
        path: a transcript; a sidechain one is <session>/subagents/agent-<id>.jsonl.
        read_json: the sampler's capped JSON reader, called with the
            transcript's agent-<id>.meta.json.

    Returns:
        The agentType that meta file names, UNTYPED without one; only that
        field is read.
    """
    if not path.name.startswith(AGENT_FILE):
        return UNTYPED
    data = read_json(path.with_name(path.name.removesuffix(".jsonl") + META))
    return (named(data.get("agentType")) if isinstance(data, dict) else "") or UNTYPED


def top_level(cwd: str) -> str:
    """Returns:
        The base name of the nearest directory at or above cwd that holds a
        .git entry, "" for none or a relative cwd.
    """
    if not cwd.startswith("/"):
        return ""
    # A removed worktree's cwd no longer exists, so the walk reaches the enclosing checkout, if any, and names that.
    path = Path(cwd)
    for folder in (path, *path.parents):
        if os.path.lexists(folder / ".git"):
            return named(folder.name)
    return ""


def repo_of(cwd: str, cache: dict[str, str]) -> str:
    if cwd not in cache:
        cache[cwd] = top_level(cwd)
    return cache[cwd]


def add(sums: dict[tuple, list[int]], key: tuple, counts: tuple[int, ...] | list[int]) -> None:
    total = sums.setdefault(key, [0] * len(counts))
    for index, value in enumerate(counts):
        total[index] += value


def kept_values(values: dict[str, int]) -> set[str]:
    ranked = sorted((value for value in values if value != OTHER), key=lambda value: (-values[value], value))
    return {OTHER, *ranked[:FOLD_LIMIT]}


def fold_position(sums: dict[tuple, list[int]], position: int) -> dict[tuple, list[int]]:
    totals: dict[tuple, dict[str, int]] = {}
    for key, counts in sums.items():
        bucket = totals.setdefault((key[0], key[3]), {})
        bucket[key[position]] = bucket.get(key[position], 0) + sum(counts)
    kept = {bucket: kept_values(values) for bucket, values in totals.items()}
    found: dict[tuple, list[int]] = {}
    for key, counts in sums.items():
        value = key[position] if key[position] in kept[(key[0], key[3])] else OTHER
        add(found, (*key[:position], value, *key[position + 1:]), counts)
    return found


def fold(sums: dict[tuple, list[int]]) -> dict[tuple, list[int]]:
    """Args:
        sums: per (t, agent, model, width, account, skill, tool, subagent,
            repo) the counts.

    Returns:
        sums with every dimension of FOLDED bounded per row (t, width): its
        FOLD_LIMIT values of the most tokens kept, ties by name, the others
        merged into OTHER.
    """
    for position in FOLDED:
        sums = fold_position(sums, position)
    return sums


def untagged(sums: dict[tuple, list[int]]) -> dict[tuple, list[int]]:
    """Returns:
        sums merged per (t, agent, model, width, account), the key of a
        tokens.jsonl row, unfolded.
    """
    found: dict[tuple, list[int]] = {}
    for key, counts in sums.items():
        add(found, key[:5], counts)
    return found


def token_rows(sums: dict[tuple, list[int]]) -> list[dict]:
    """Args:
        sums: per (t, agent, model, width, account, *tags) the counts in
            COUNTS order, account "" for a session the hook mapped to none,
            tags in TAGS order or left out.

    Returns:
        One row per key in key order; a row other than hourly names its
        width, a row of a mapped session its account, a row its tags but
        those that are "".
    """
    return [
        {
            "t": t, "agent": agent, "model": model, **dict(zip(NAMES, counts, strict=True)), **({} if width == HOUR else {"width": width}), **({"account": account} if account else {}),
            **{name: value for name, value in zip(TAGS, tagged, strict=False) if value},
        }
        for (t, agent, model, width, account, *tagged), counts in sorted(sums.items())
    ]


def usage_row(raw: bytes) -> dict | None:
    try:
        row = json.loads(raw)
    except (ValueError, RecursionError):
        return None
    if not isinstance(row, dict) or not isinstance(row.get("agent"), str) or not isinstance(row.get("model"), str):
        return None
    return row if isinstance(row.get("t"), int | float) and not isinstance(row["t"], bool) else None


def usage_key(row: dict, line: float) -> tuple:
    """Returns:
        (t, agent, model, width, account, *tags) of the usage row a row
        merges into: its day (UTC) when that day ended by line, else its
        hour.
    """
    day = int(row["t"] // DAY * DAY)
    account = row["account"] if isinstance(row.get("account"), str) else ""
    start, width = (day, DAY) if day + DAY <= line else (int(row["t"]), HOUR)
    return start, row["agent"], row["model"], width, account, *row_tags(row)


def trimmed(lines: Iterable[bytes], now: float, line: float) -> Iterator[str]:
    """Args:
        lines: the lines of usage.jsonl, read one at a time.
        now: epoch seconds of this run.
        line: a day that ended by it folds into one row per day and
            dimensions, kept forever.

    Returns:
        The lines of the trimmed file: a daily row, and an hourly row older
        than USAGE_OPEN whose day ended after line, unchanged and in order,
        as an earlier run already merged it; the rows of the last USAGE_OPEN
        and those of a day that ended by line merged per usage_key(),
        folded, after them. Only those rows stay in memory; a malformed line
        is dropped.
    """
    sums: dict[tuple, list[int]] = {}
    for raw in lines:
        row = usage_row(raw)
        if row is None:
            continue
        settled = row["t"] < now - USAGE_OPEN and int(row["t"] // DAY * DAY) + DAY > line
        if row.get("width") == DAY or settled:
            yield raw.decode("utf-8", "replace").rstrip("\n") + "\n"
        else:
            add(sums, usage_key(row, line), tuple(whole(row.get(name)) for name in NAMES))
    for row in token_rows(fold(sums)):
        yield json.dumps(row, separators=(",", ":")) + "\n"


def row_tags(row: dict) -> tuple[str, ...]:
    """Returns:
        The TAGS of a token row, "" for each one an older row lacks.
    """
    return tuple(row[name] if isinstance(row.get(name), str) else "" for name in TAGS)


def history_of(value: object) -> dict[str, list[tuple[float, str]]]:
    """Returns:
        Per session its skill calls [(time, name)] in time order from the
        skills map offsets.json keeps; a malformed entry is dropped.
    """
    if not isinstance(value, dict):
        return {}
    found = {}
    for session, calls in value.items():
        kept = sorted((float(call[0]), call[1]) for call in calls if isinstance(call, list) and len(call) == 2 and isinstance(call[0], int | float) and not isinstance(call[0], bool) and named(call[1])) if isinstance(calls, list) else []
        if isinstance(session, str) and kept:
            found[session] = kept
    return found


def add_calls(history: dict[str, list[tuple[float, str]]], calls: list[tuple[str, float, str]]) -> None:
    for session, ts, name in calls:
        history.setdefault(session, []).append((ts, name))
    for session in {session for session, _, _ in calls}:
        history[session] = sorted(set(history[session]))


def skill_at(history: dict[str, list[tuple[float, str]]], session: str, ts: float) -> str:
    """Returns:
        The name of the last skill call of session strictly before ts, ""
        before any.
    """
    calls = history.get(session, [])
    index = bisect.bisect_left(calls, (ts, "")) - 1
    return calls[index][1] if index >= 0 else ""


def kept_history(history: dict[str, list[tuple[float, str]]], floor: float, oldest: float) -> dict[str, list[list]]:
    """Returns:
        The skills map offsets.json keeps: per session its calls from floor
        on and the last one before it; a session whose last call lies before
        oldest is dropped.
    """
    kept = {}
    for session, calls in sorted(history.items()):
        if calls[-1][0] < oldest:
            continue
        start = max(bisect.bisect_left(calls, (floor, "")) - 1, 0)
        kept[session] = [[ts, name] for ts, name in calls[start:]]
    return kept


def tally(read: Read, history: dict[str, list[tuple[float, str]]], agent_of: Callable[[str], str], account_of: Callable[[str], str]) -> tuple[dict[tuple, list[int]], dict[tuple, list]]:
    """Args:
        read: the turns, skill calls and compactions of this run.
        history: per session its skill calls, those of read included.
        agent_of: a session's agent name.
        account_of: a session's account email, "" for none.

    Returns:
        (sums, context): per (hour, agent, model, HOUR, account, skill,
        tool, subagent, repo) the counts in the sampler's COUNTS order, tool
        the sorted, comma-joined tool names of the turn; per (day, agent) a
        histogram of the main thread's context per turn (input plus cache
        read, at CONTEXT_PARTS of the counts) in KILO tokens and its
        compactions.
    """
    sums: dict[tuple, list[int]] = {}
    context: dict[tuple, list] = {}
    repos: dict[str, str] = {}
    for turn in read.turns:
        agent = agent_of(turn.session)
        tags = (skill_at(history, turn.session, turn.ts), ",".join(sorted(turn.tools)), turn.subagent, repo_of(turn.cwd, repos))
        add(sums, (int(turn.ts // HOUR * HOUR), agent, turn.model, HOUR, account_of(turn.session), *tags), turn.counts)
        if not turn.sidechain:
            sizes = context.setdefault((int(turn.ts // DAY * DAY), agent), [{}, 0])[0]
            size = sum(turn.counts[index] for index in CONTEXT_PARTS) // KILO
            sizes[size] = sizes.get(size, 0) + 1
    for session, ts in read.compactions:
        context.setdefault((int(ts // DAY * DAY), agent_of(session)), [{}, 0])[1] += 1
    return sums, context


def context_rows(context: dict[tuple, list]) -> list[dict]:
    """Returns:
        One context row {t, agent, turns: {kilo: count}, compactions} per
        (day, agent) in key order.
    """
    return [{"t": t, "agent": agent, "turns": {str(kilo): turns[kilo] for kilo in sorted(turns)}, "compactions": compactions} for (t, agent), (turns, compactions) in sorted(context.items())]


def whole(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def compact_context(rows: list[dict], _now: float) -> list[dict]:
    """Returns:
        The context rows merged per day and agent, kept forever like the
        daily token rows; a malformed row is dropped.
    """
    context: dict[tuple, list] = {}
    for row in rows:
        t, agent, turns = row.get("t"), row.get("agent"), row.get("turns")
        if not whole(t) or not isinstance(agent, str) or not isinstance(turns, dict):
            continue
        entry = context.setdefault((t, agent), [{}, 0])
        for kilo, number in turns.items():
            if isinstance(kilo, str) and kilo.isdigit() and whole(number):
                entry[0][int(kilo)] = entry[0].get(int(kilo), 0) + number
        entry[1] += whole(row.get("compactions"))
    return context_rows(context)
