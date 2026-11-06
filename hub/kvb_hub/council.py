from __future__ import annotations

from pathlib import Path

from .records import epoch, read_json, shown

NEWS = "news.jsonl"
HUMAN = "Operator"
SESSION = " session"
ALARMS = (("MAYDAY", "mayday"), ("PAN-PAN", "pan-pan"))
CLASSES = ("broadcast", "direct", "security", "pan-pan", "mayday")
MODES = ("evening", "sunset")
RADIO_LIMIT = 5000
GRANT_LIMIT = 50
MAYDAY_ACTIVE = 7200


def agent(name: object) -> str:
    if not isinstance(name, str):
        return ""
    text = name.strip()
    if text.lower().endswith(SESSION):
        return text[: -len(SESSION)].strip()
    return text


def subagent(name: str) -> bool:
    return name.lower().startswith("subagent")


def ordered(names: set[str]) -> list[str]:
    return sorted(names, key=lambda name: (name.lower(), name))


def kind(row: dict, names: list[str]) -> str:
    if row.get("class") in CLASSES:
        return row["class"]
    text = row.get("text")
    for prefix, alarm in ALARMS:
        if isinstance(text, str) and text.lstrip().startswith(prefix):
            return alarm
    return "direct" if names else "broadcast"


def radio_row(row: dict, ts: float) -> dict:
    to = row.get("to")
    names = [name for name in map(agent, to) if name] if isinstance(to, list) else []
    return {"ts": ts, "from": agent(row.get("from")), "to": names, "class": kind(row, names), "text": shown(row.get("text"))}


def radio_rows(rows: list[dict], begin: float, end: float) -> list[dict]:
    found = [radio_row(row, ts) for row in rows if (ts := epoch(row.get("ts"))) is not None and begin <= ts <= end]
    return sorted(found, key=lambda row: row["ts"])[-RADIO_LIMIT:]


def claim_row(data: dict) -> dict:
    name = data.get("name")
    return {
        "office": shown(data.get("office")),
        "agent": agent(name),
        "address": name.strip() if isinstance(name, str) else "",
        "session": shown(data.get("session")),
        "runtime": shown(data.get("runtime")),
        "since": shown(data.get("since")),
        "beat": epoch(data.get("beat")),
        "work": shown(data.get("work")),
    }


def read_claims(council: Path) -> list[dict]:
    paths = sorted([*council.glob("cluster/*/claim.json"), *council.glob("work/*/claim.json")])
    return [claim_row(data) for data in map(read_json, paths) if isinstance(data, dict)]


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
    data = read_json(council / "night.json")
    mode = data.get("mode") if isinstance(data, dict) else None
    return mode if mode in MODES else "day"


def silence_of(council: Path, now: float) -> dict | None:
    data = read_json(council / "radio-silence.json")
    if not isinstance(data, dict):
        return None
    until = epoch(data.get("until"))
    if until is None or until <= now:
        return None
    return {"by": shown(data.get("by")), "text": shown(data.get("text")), "until": until}
