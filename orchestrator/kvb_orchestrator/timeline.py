from __future__ import annotations

import time

from .asking import ask_state
from .council import MAYDAY_ACTIVE, NEWS, radio_rows, read_claims, sessions
from .crons import cron_event
from .errors import Missing, ToolError
from .events import event, event_filters, wanted
from .fields import instant, single, whole
from .names import Directory
from .records import iso_epoch, read_jsonl
from .register import REGISTER, operator_rows, read_register
from .signed import signing
from .transcripts import STREAM_CUT, STREAM_KINDS, matches

STREAM_LIMIT = 2000
EVENT_LIMIT = 3000


class Timeline:
    def stream(self, query: dict[str, list[str]]) -> dict:
        self.transcripts.refresh()
        names = sessions(read_claims(self.council))
        wanted = single(query, "kind")
        kinds = None if not wanted else set(wanted.split(","))
        if kinds is not None and not kinds <= set(STREAM_KINDS):
            raise ToolError(f"kind must be a comma list of {', '.join(STREAM_KINDS)}")
        filters = {
            "agent": single(query, "agent") or "",
            "session": single(query, "session") or "",
            "kinds": kinds,
            "q": (single(query, "q") or "").lower(),
            "begin": instant(query, "from"),
            "end": instant(query, "to"),
        }
        limit = min(whole(query, "limit") or STREAM_LIMIT, STREAM_LIMIT)
        picked = [
            {**entry, "agent": names.get(entry["session"], ""), "text": entry["text"][:STREAM_CUT], "truncated": len(entry["text"]) > STREAM_CUT}
            for entry in self.transcripts.since(whole(query, "after") or 0)
            if matches(entry, names.get(entry["session"], ""), filters)
        ]
        picked.sort(key=lambda entry: (entry["ts"], entry["id"]))
        return {"entries": picked[-limit:], "last": self.transcripts.last(), "sessions": names}

    def entry(self, entry_id: int) -> dict:
        record = self.transcripts.entry(entry_id)
        if record is None:
            raise Missing(str(entry_id))
        return {"id": record["id"], "text": record["text"]}

    def timeline(self, begin: float, end: float, now: float, tasks: dict[str, dict], claims: list[dict], radio: list[dict], directory: Directory) -> list[dict]:
        rows = []
        for index, row in enumerate(radio_rows(radio, begin, end)):
            alarm = row["class"] in ("mayday", "pan-pan") and row["ts"] >= end - MAYDAY_ACTIVE
            title = f"{row['from'] or '?'} → {', '.join(row['to']) or 'alle'}"
            source = directory.key(row["from"], row["ts"])
            who = {"agent": directory.at(source, row["ts"]) or row["from"], "now": directory.now(source), "session": source}
            ref = {"to": row["to"], "class": row["class"], "targets": [directory.key(name, row["ts"]) for name in row["to"]]}
            rows.append(event({"id": f"radio:{row['ts']}:{index}", "ts": row["ts"], "kind": "radio", "part": row["class"], **who, "title": title, "text": row["text"], "waiting": alarm, "ref": ref}))
        for review in self.reviews.listed():
            created = iso_epoch(review["created"]) or now
            if created <= end and (review["status"] == "pending" or created >= begin):
                ref = {key: review.get(key, "") for key in ("id", "status", "gate", "score", "branch", "worktree", "tree", "files")}
                rows.append(event({"id": f"review:{review['id']}", "ts": created, "kind": "review", "title": review["title"], "text": review["notes"][:STREAM_CUT], "waiting": review["status"] == "pending", "ref": ref}))
        for ask in self.asks.listed():
            state = ask_state(ask, now)
            if ask["created_ts"] <= end and (state["status"] == "pending" or ask["created_ts"] >= begin):
                ref = {"id": ask["id"], "status": state["status"], "cwd": ask["cwd"], "tool": ask["tool"], "warnings": signing.warnings(ask["command"])}
                who = {"agent": directory.at(ask["session"], ask["created_ts"]), "now": directory.now(ask["session"]), "session": ask["session"]}
                rows.append(event({"id": f"ask:{ask['id']}", "ts": ask["created_ts"], "kind": "ask", **who, "title": ask["tool"], "text": ask["command"], "waiting": state["status"] == "pending", "ref": ref}))
        for decision in self.decisions.listed():
            if decision["created_ts"] <= end and (decision["status"] == "pending" or decision["created_ts"] >= begin):
                ref = {key: decision.get(key, "") for key in ("id", "status", "choice", "recommended", "options")}
                text = " · ".join(option["label"] for option in decision["options"])
                source = directory.key(decision["agent"], decision["created_ts"])
                who = {"agent": directory.at(source, decision["created_ts"]) or decision["agent"], "now": directory.now(source), "session": source}
                rows.append(event({"id": f"decision:{decision['id']}", "ts": decision["created_ts"], "kind": "decision", **who, "title": decision["question"][:300], "text": text, "waiting": decision["status"] == "pending", "ref": ref}))
        held = self.open_jobs()
        for row in operator_rows(tasks):
            first = self.watch.first(row["task"], now)
            if first <= end:
                ref = {key: row[key] for key in ("task", "directory", "check", "status")}
                rows.append(event({"id": f"operator:{row['task']}", "ts": first, "kind": "operator", "title": row["command"], "text": row["why"], "waiting": row["task"] not in held, "ref": ref}))
        rows += [change for change in self.watch.listed() if begin <= change["ts"] <= end]
        rows += [cron_event(cron, directory) for cron in self.schedules(claims, now) if cron["created"] <= end and (cron["active"] or cron["created"] >= begin)]
        rows += [row for row in self.log.listed() if begin <= row["ts"] <= end]
        rows += directory.renames(begin, end)
        return sorted(rows, key=lambda row: (row["ts"], row["id"]))

    def events(self, query: dict[str, list[str]]) -> dict:
        now = time.time()
        begin, end = self.span(query, now)
        filters = event_filters(query)
        limit = min(whole(query, "limit") or EVENT_LIMIT, EVENT_LIMIT)
        after = whole(query, "after") or 0
        self.transcripts.refresh()
        claims = read_claims(self.council)
        news = read_jsonl(self.council / NEWS)
        directory = self.directory(claims, news, now)
        filters["aliases"] = directory.aliases(filters["agent"]) if filters["agent"] else set()
        tasks = read_register(self.council / REGISTER)
        self.watch.see(tasks, now)
        rows = [row for row in self.timeline(begin, end, now, tasks, claims, news, directory) if wanted(row, filters)]
        live = instant(query, "to") is None
        entries = []
        for entry in self.transcripts.since(after) if "transcript" in filters["kinds"] else []:
            shaped = event({
                "id": f"transcript:{entry['id']}", "ts": entry["ts"], "kind": "transcript", "part": entry["kind"], "agent": directory.at(entry["session"], entry["ts"]),
                "now": directory.now(entry["session"]), "session": entry["session"], "sub": entry["sub"], "title": entry["kind"], "text": entry["text"][:STREAM_CUT],
                "ref": {"entry": entry["id"], "truncated": len(entry["text"]) > STREAM_CUT},
            })
            if entry["ts"] >= begin and (live or entry["ts"] <= end) and wanted(shaped, filters):
                entries.append(shaped)
        return {"events": rows[-limit:], "entries": entries[-limit:], "last": self.transcripts.last(), "sessions": sessions(claims)}
