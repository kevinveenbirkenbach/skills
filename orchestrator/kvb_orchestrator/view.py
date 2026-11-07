from __future__ import annotations

import time

from .asking import ask_row, decision_row
from .council import (
    MAYDAY_ACTIVE,
    NEWS,
    grants,
    night_mode,
    radio_rows,
    read_claims,
    sessions,
    silence_of,
)
from .crons import queue_entries
from .errors import ToolError
from .events import KINDS, VIEWS
from .fields import decode, instant, single
from .graph import graph
from .jobs import JOB_OPEN
from .messaging import message_row
from .orbits import TRACK_STEPS, track
from .phrasing import phrase
from .records import epoch, iso_epoch, read_jsonl
from .register import (
    AGENT_ORDER,
    REGISTER,
    agent_order,
    operator_rows,
    read_register,
    register_rows,
    stored_order,
)
from .reviewing import review_row
from .settings import media_origins, valid_settings
from .signed import signing
from .skill_scripts import OUTPUT_LIMIT
from .tasks import task_rows

RADIO_WINDOW = 86400
JOBS_SHOWN = 20
ACTIVE = 900
INDEX_CSP = (
    "default-src 'none'; script-src 'nonce-{0}'; style-src 'nonce-{0}'; connect-src 'self'; media-src {1}; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)


def badges(inbox: list[dict], claims: list[dict], jobs: list[dict], now: float) -> dict[str, int]:
    return {
        "inbox": sum(1 for item in inbox if not item["until"]),
        "agents": len({claim["agent"] for claim in claims if claim["beat"] is not None and claim["beat"] >= now - ACTIVE}),
        "artifacts": sum(1 for job in jobs if job["status"] in JOB_OPEN),
    }


class View:
    def span(self, query: dict[str, list[str]], now: float) -> tuple[float, float]:
        end = instant(query, "to")
        end = now if end is None else min(end, now)
        begin = instant(query, "from")
        begin = end - RADIO_WINDOW if begin is None else begin
        if begin > end:
            raise ToolError("from must not lie after to")
        return begin, end

    def window(self, query: dict[str, list[str]]) -> dict:
        now = time.time()
        begin, end = self.span(query, now)
        sampled = single(query, "track")
        if sampled not in (None, "1"):
            raise ToolError("track must be 1 or left out")
        self.tree.beat()
        return self.state(begin, end, now, TRACK_STEPS if sampled else 0)

    def first(self, news: list[dict], history: list[dict], claims: list[dict], now: float) -> float:
        moments = [epoch(row.get("ts")) for row in news] + [epoch(row.get("start")) for row in history]
        moments += [iso_epoch(claim["since"]) for claim in claims] + [self.transcripts.first()]
        moments += [iso_epoch(record["created"]) for ledger in (self.reviews, self.asks, self.decisions, self.messages) for record in ledger.listed()]
        return min([now, *(moment for moment in moments if moment is not None)])

    def state(self, begin: float, end: float, now: float, steps: int) -> dict:
        tasks = read_register(self.council / REGISTER)
        news = read_jsonl(self.council / NEWS)
        history = read_jsonl(self.council / "queue-history.jsonl")
        claims = read_claims(self.council)
        names = sessions(claims)
        directory = self.directory(claims, news, now)
        radio = []
        for row in radio_rows(news, begin, end):
            source = directory.key(row["from"], row["ts"])
            targets = [directory.key(name, row["ts"]) for name in row["to"]]
            called = [directory.at(key, row["ts"]) or name for key, name in zip(targets, row["to"], strict=True)]
            spoken = {"speech": phrase(row["class"], directory.at(source, row["ts"]) or row["from"], called, row["text"]), "voice": self.speech.voice_of(source)}
            radio.append({**row, "source": source, "targets": targets, "now": directory.now(source), **spoken})
        grant_rows = [{**grant, "target": directory.key(grant["to"], grant["ts"])} for grant in grants(history, (begin, end), claims, tasks)]
        self.watch.see(tasks, now)
        jobs = [{**{key: value for key, value in job.items() if key != "proof"}, "output": job["output"][-OUTPUT_LIMIT:]} for job in self.jobs.listed()[-JOBS_SHOWN:]]
        drawn = graph(radio, grant_rows, tasks, claims, end, directory)
        first = self.first(news, history, claims, now)
        drawn["track"] = track(drawn["nodes"], radio, tasks, claims, (min(max(begin, first), end), end), directory, steps)
        people = {node["id"]: {"name": node["label"], "now": directory.now(node["id"]) or node["label"], "names": node["names"]} for node in drawn["nodes"] if node["kind"] != "subagent"}
        settings = self.settings.get()
        inbox = self.inbox(now, tasks, directory)
        return {
            "settings": settings,
            "media": media_origins(settings),
            "speech": self.speech.describe(),
            "people": people,
            "inbox": inbox,
            "badges": badges(inbox, claims, self.jobs.listed(), now),
            "pending": self.batches.listed(),
            "rules": [{**{key: value for key, value in rule.items() if key != "proof"}, "signed": rule.get("proof") is not None} for rule in self.rules.listed()],
            "approvers": self.keys(),
            "jobs": jobs,
            "views": VIEWS,
            "kinds": dict(KINDS),
            "llm": self.model.enabled(),
            "now": now,
            "since": begin,
            "until": end,
            "first": first,
            "alarm_since": end - MAYDAY_ACTIVE,
            "reviews": [row for row in map(review_row, self.reviews.pending()) if row["created_ts"] <= end],
            "asks": [ask_row(ask, names) for ask in self.asks.pending() if ask["expires"] > now and ask["created_ts"] <= end],
            "decisions": [decision_row(decision) for decision in self.decisions.pending() if decision["created_ts"] <= end],
            "messages": [message_row(message) for message in self.messages.listed() if begin <= message["created_ts"] <= end],
            "operator": operator_rows(tasks),
            "register": register_rows(tasks),
            "tasks": task_rows(tasks, queue_entries(self.council), self.tree.get()),
            "agent_order": agent_order(tasks, claims, stored_order(self.council / AGENT_ORDER)),
            "radio": radio,
            "claims": claims,
            "grants": grant_rows,
            "night": night_mode(self.council),
            "silence": silence_of(self.council, now),
            "graph": drawn,
        }

    def stream_change(self, raw: dict) -> dict | None:
        """Returns:
            The item the operator's passkey signs when the settings let the
            page load audio from an origin the saved ones do not, else None.
        """
        origins = media_origins(valid_settings(raw))
        return signing.stream_item(origins) if set(origins) - set(media_origins(self.settings.get())) else None

    def sign_settings(self, body: bytes) -> dict:
        change = self.stream_change(decode(body))
        return self.challenge_for([] if change is None else [change])

    def save_settings(self, body: bytes) -> dict:
        payload = decode(body)
        proof = payload.pop("proof", None)
        change = self.stream_change(payload)
        if change is not None:
            self.operator_proven(proof, change)
        return self.settings.put(payload)

    def render(self, nonce: str) -> tuple[str, str]:
        now = time.time()
        state = self.state(now - RADIO_WINDOW, now, now, 0)
        page = self.templates.get_template("index.html.j2").render(nonce=nonce, state=state, icons=self.icons)
        return page, INDEX_CSP.format(nonce, " ".join(["'self'", *state["media"]]))
