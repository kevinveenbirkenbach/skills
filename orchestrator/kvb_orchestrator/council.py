from __future__ import annotations

import re
from pathlib import Path

from .records import epoch, read_json, shown

NEWS = "news.jsonl"
HUMAN = "Operator"
SESSION = " session"
NOTE = re.compile(r"(\S.*?)\s+\([^()]*\)")
PREFIXES = (("MAYDAY", "mayday"), ("PAN-PAN", "pan-pan"))
CLASSES = ("post", "call", "newsletter", "broadcast", "mayday", "pan-pan", "security")
RECEIPT = "receipt"
ALARMS = ("mayday", "pan-pan", "security")
VERSION = 2
MODES = ("drain", "suspend")
RENAMED_MODES = {"evening": "drain", "sunset": "suspend"}
RADIO_LIMIT = 5000
GRANT_LIMIT = 50
MAYDAY_ACTIVE = 7200
CHAIR_OFFICE = "chair"
GROUPS = ("work", "cluster")
CLAIM_FILES = ("*/claim.json", "*/*/claim.json")
OFFICE = re.compile(r"[a-z0-9][a-z0-9._-]*(?:/[a-z0-9][a-z0-9._-]*)?")


def agent(name: object) -> str:
    if not isinstance(name, str):
        return ""
    text = name.strip()
    noted = NOTE.fullmatch(text)
    if noted and not subagent(text):
        text = noted.group(1)
    if text.lower().endswith(SESSION):
        return text[: -len(SESSION)].strip()
    return text


def subagent(name: str) -> bool:
    return name.lower().startswith("subagent")


def ordered(names: set[str]) -> list[str]:
    return sorted(names, key=lambda name: (name.lower(), name))


def kind(row: dict, names: list[str]) -> str:
    """Args:
        row: a news.jsonl row; rows without the version mark predate the
            split of radio and post and keep their old meaning.
        names: the addressees of the row.

    Returns:
        One of CLASSES or RECEIPT, the same reading as radio.py's kind().
    """
    cls = row.get("class")
    if row.get("v") == VERSION and cls in (*CLASSES, RECEIPT):
        return cls
    if cls in ALARMS:
        return cls
    text = row.get("text")
    for prefix, alarm in PREFIXES:
        if cls is None and isinstance(text, str) and text.lstrip().startswith(prefix):
            return alarm
    if cls == "direct" or (cls != "broadcast" and names):
        return "call" if row.get("wake") else "post"
    return "newsletter"


def radio_row(row: dict, ts: float) -> dict:
    to = row.get("to")
    names = [name for name in map(agent, to) if name] if isinstance(to, list) else []
    return {"ts": ts, "from": agent(row.get("from")), "to": names, "class": kind(row, names), "text": shown(row.get("text"))}


def radio_rows(rows: list[dict], begin: float, end: float) -> list[dict]:
    found = [radio_row(row, ts) for row in rows if (ts := epoch(row.get("ts"))) is not None and begin <= ts <= end]
    return sorted(found, key=lambda row: row["ts"])[-RADIO_LIMIT:]


def message_rows(rows: list[dict], begin: float, end: float) -> list[dict]:
    """Returns:
        radio_rows() without the receipts, which only feed the acks of their
        call.
    """
    return [row for row in radio_rows(rows, begin, end) if row["class"] != RECEIPT]


def office_kind(office: str) -> tuple[str, str, str]:
    """Args:
        office: an office of one or two segments.

    Returns:
        (kind, dimension, line): kind is chair, line for <dimension>/<line>,
        work or cluster for their groups, other for any other single
        segment; dimension and line are empty unless the kind is line.
    """
    head, _, rest = office.partition("/")
    if office == CHAIR_OFFICE:
        return "chair", "", ""
    if not rest:
        return "other", "", ""
    if head in GROUPS:
        return head, "", ""
    return "line", head, rest


def claim_row(office: str, data: dict) -> dict:
    name = data.get("name")
    kind, dimension, line = office_kind(office)
    return {
        "office": office,
        "kind": kind,
        "dimension": dimension,
        "line": line,
        "agent": agent(name),
        "address": name.strip() if isinstance(name, str) else "",
        "session": shown(data.get("session")),
        "runtime": shown(data.get("runtime")),
        "since": shown(data.get("since")),
        "beat": epoch(data.get("beat")),
        "work": shown(data.get("work")),
    }


def read_claims(council: Path) -> list[dict]:
    found = []
    for pattern in CLAIM_FILES:
        for path in council.glob(pattern):
            office = path.parent.relative_to(council).as_posix()
            data = read_json(path)
            if OFFICE.fullmatch(office) and isinstance(data, dict):
                found.append(claim_row(office, data))
    return sorted(found, key=lambda row: row["office"])


def sessions(claims: list[dict]) -> dict[str, str]:
    return {claim["session"]: claim["agent"] for claim in claims if claim["agent"] and claim["session"] != "-"}


def home(workdir: object, homes: dict[str, str]) -> str:
    if not isinstance(workdir, str):
        return ""
    matches = [path for path in homes if workdir == path or workdir.startswith(f"{path}/")]
    return homes[max(matches, key=len)] if matches else ""


def grants(rows: list[dict], window: tuple[float, float], claims: list[dict], tasks: dict[str, dict]) -> list[dict]:
    begin, end = window
    homes = {}
    for claim in claims:
        workdir = tasks.get(claim["office"], {}).get("workdir")
        if claim["agent"] and isinstance(workdir, str) and workdir.rstrip("/"):
            homes[workdir.rstrip("/")] = claim["agent"]
    found = []
    for row in rows:
        start = epoch(row.get("start"))
        holder = home(row.get("workdir"), homes)
        if start is not None and begin <= start <= end and holder:
            found.append({"ts": start, "to": holder, "kind": shown(row.get("kind")), "id": shown(row.get("id"))})
    return found[-GRANT_LIMIT:]


def night_mode(council: Path) -> str:
    """Args:
        council: the council directory; night.json in it may still hold a
            mode from before the rename, read as its successor.

    Returns:
        One of MODES, or day.
    """
    data = read_json(council / "night.json")
    mode = data.get("mode") if isinstance(data, dict) else None
    if isinstance(mode, str):
        mode = RENAMED_MODES.get(mode, mode)
    return mode if mode in MODES else "day"


def night_parts(council: Path) -> dict[str, str]:
    """Args:
        council: the council directory with night.json.

    Returns:
        Per session the part that differs from night_mode: drain or suspend
        for one set alone, day for the active and the resumed sessions while
        a mode holds.
    """
    data = read_json(council / "night.json")
    if not isinstance(data, dict):
        return {}
    resumed = data.get("resumed", data.get("awake"))
    working = [data.get("active"), *(resumed if isinstance(resumed, list) else [])]
    parts = {sid: "day" for sid in working if isinstance(sid, str)} if night_mode(council) != "day" else {}
    alone = data.get("parts")
    return {**parts, **({sid: mode for sid, mode in alone.items() if mode in MODES} if isinstance(alone, dict) else {})}


def silence_of(council: Path, now: float) -> dict | None:
    data = read_json(council / "radio-silence.json")
    if not isinstance(data, dict):
        return None
    until = epoch(data.get("until"))
    if until is None or until <= now:
        return None
    return {"by": shown(data.get("by")), "text": shown(data.get("text")), "until": until}
