from __future__ import annotations

import json
import math
import os
import re
import threading
import time
from collections import deque
from pathlib import Path

from .records import epoch, iso_epoch, parse_line, shown

STREAM_KEEP = 20_000
STREAM_TEXT = 20_000
STREAM_CUT = 2000
STREAM_FIRST = 512 << 10
STREAM_AGE = 7 * 86400
STREAM_SCAN = 1.0
STREAM_KINDS = ("user", "assistant", "tool_call", "tool_result", "system")
SCHEDULED = re.compile(r"Scheduled (?:recurring job|one-shot task) ([0-9a-f]{6,32})")
CRON_LIFETIME = 7 * 86400
LOG_KEEP = 5000


def block_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for block in content:
        if isinstance(block, dict) and isinstance(block.get("text"), str):
            parts.append(block["text"])
        elif isinstance(block, dict) and block.get("type") == "image":
            parts.append("[image]")
    return "\n".join(parts)


def transcript_parts(row: dict) -> list[tuple[str, str]]:
    role = row.get("type")
    if role == "system":
        text = block_text(row.get("content"))
        return [("system", text)] if text else []
    message = row.get("message")
    if role not in ("user", "assistant") or not isinstance(message, dict):
        return []
    content = message.get("content")
    if isinstance(content, str):
        return [("system" if row.get("isMeta") else str(role), content)] if content else []
    found = []
    for block in content if isinstance(content, list) else []:
        part = block.get("type") if isinstance(block, dict) else None
        if part == "text":
            found.append((str(role), block_text([block])))
        elif part == "tool_use":
            found.append(("tool_call", f"{shown(block.get('name'))} {json.dumps(block.get('input'), ensure_ascii=False)}"))
        elif part == "tool_result":
            found.append(("tool_result", block_text(block.get("content"))))
    return [(name, text) for name, text in found if text]


def matches(entry: dict, name: str, filters: dict) -> bool:
    begin, end = filters["begin"], filters["end"]
    return all(
        (
            not filters["agent"] or name == filters["agent"],
            not filters["session"] or entry["session"] == filters["session"],
            filters["kinds"] is None or entry["kind"] in filters["kinds"],
            not filters["q"] or filters["q"] in entry["text"].lower(),
            begin is None or entry["ts"] >= begin,
            end is None or entry["ts"] <= end,
        )
    )


def text_of(value: object) -> str:
    return value[:STREAM_CUT] if isinstance(value, str) else ""


class Transcripts:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.lock = threading.Lock()
        self.offsets: dict[Path, int] = {}
        self.entries: deque[dict] = deque(maxlen=STREAM_KEEP)
        self.crons: dict[str, dict] = {}
        self.count = 0
        self.scanned = -math.inf

    def refresh(self) -> None:
        with self.lock:
            if time.monotonic() - self.scanned < STREAM_SCAN:
                return
            self.scanned = time.monotonic()
            try:
                paths = sorted(self.root.rglob("*.jsonl"))
            except OSError:
                paths = []
            for path in paths:
                self.read(path)

    def start(self, path: Path, info: os.stat_result) -> int:
        offset = self.offsets.get(path)
        if offset is None:
            recent = info.st_mtime >= time.time() - STREAM_AGE
            return max(info.st_size - STREAM_FIRST, 0) if recent else info.st_size
        return 0 if info.st_size < offset else offset

    def read(self, path: Path) -> None:
        try:
            info = path.stat()
            begin = self.start(path, info)
            with path.open("rb") as handle:
                handle.seek(begin)
                data = handle.read(max(info.st_size - begin, 0))
        except OSError:
            return
        end = data.rfind(b"\n") + 1
        self.offsets[path] = begin + end
        for raw in data[:end].splitlines():
            row = parse_line(raw.decode("utf-8", errors="replace"))
            if row is not None:
                self.add(path, row)

    def add(self, path: Path, row: dict) -> None:
        ts = iso_epoch(row.get("timestamp"))
        if ts is None:
            return
        session = row.get("sessionId") if isinstance(row.get("sessionId"), str) else path.stem
        sub = row.get("agentId") if isinstance(row.get("agentId"), str) else ""
        message = row.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        for block in content if isinstance(content, list) else []:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                self.schedule(block, ts, session, sub)
            elif isinstance(block, dict) and block.get("type") == "tool_result":
                self.scheduled(block)
        for name, text in transcript_parts(row):
            self.count += 1
            self.entries.append({"id": self.count, "ts": ts, "session": session, "sub": sub, "kind": name, "text": text[:STREAM_TEXT]})

    def end(self, kind_name: str, session: str, sub: str, ts: float) -> None:
        for cron in self.crons.values():
            if cron["type"] == kind_name and cron["session"] == session and cron["sub"] == sub and cron["deleted"] is None:
                cron["deleted"] = ts

    def schedule(self, block: dict, ts: float, session: str, sub: str) -> None:
        name, data, key = block.get("name"), block.get("input"), block.get("id")
        if not isinstance(data, dict) or not isinstance(key, str):
            return
        base = {"key": key, "session": session, "sub": sub, "created": ts, "deleted": None, "until": None, "job": "", "expression": "", "prompt": "", "reason": ""}
        delay = data.get("delaySeconds")
        if name == "CronCreate":
            self.crons[key] = {**base, "type": "cron", "expression": text_of(data.get("cron")), "prompt": text_of(data.get("prompt")), "until": ts + CRON_LIFETIME}
        elif name == "CronDelete":
            for cron in self.crons.values():
                if cron["type"] == "cron" and cron["job"] and cron["job"] == data.get("id") and cron["deleted"] is None:
                    cron["deleted"] = ts
        elif name == "ScheduleWakeup":
            self.end("wakeup", session, sub, ts)
            if data.get("stop") is not True and epoch(delay) is not None:
                wakeup = {"type": "wakeup", "expression": f"in {int(delay)} s", "prompt": text_of(data.get("prompt")), "reason": text_of(data.get("reason")), "until": ts + float(delay)}
                self.crons[key] = {**base, **wakeup}
        elif name == "Bash" and data.get("run_in_background") is True:
            self.crons[key] = {**base, "type": "background", "expression": text_of(data.get("description"))[:200] or "Bash", "prompt": text_of(data.get("command"))}
        while len(self.crons) > LOG_KEEP:
            del self.crons[min(self.crons, key=lambda name: self.crons[name]["created"])]

    def scheduled(self, block: dict) -> None:
        cron = self.crons.get(block.get("tool_use_id"))
        found = SCHEDULED.search(block_text(block.get("content")))
        if cron is not None and cron["type"] == "cron" and found:
            cron["job"] = found.group(1)

    def schedules(self) -> list[dict]:
        with self.lock:
            return [dict(cron) for cron in self.crons.values()]

    def since(self, after: int) -> list[dict]:
        with self.lock:
            return [entry for entry in self.entries if entry["id"] > after]

    def entry(self, entry_id: int) -> dict | None:
        with self.lock:
            return next((dict(entry) for entry in self.entries if entry["id"] == entry_id), None)

    def first(self) -> float | None:
        with self.lock:
            return min((entry["ts"] for entry in self.entries), default=None)

    def last(self) -> int:
        with self.lock:
            return self.count
