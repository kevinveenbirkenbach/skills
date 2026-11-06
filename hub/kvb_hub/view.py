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
from .errors import ToolError
from .events import VIEWS
from .fields import decode, instant, single
from .graph import graph
from .messaging import message_row
from .orbits import TRACK_STEPS, track
from .phrasing import phrase
from .records import epoch, iso_epoch, read_jsonl
from .register import REGISTER, operator_rows, priority, read_register, register_rows
from .reviewing import review_row
from .settings import media_origins
from .skill_scripts import OUTPUT_LIMIT

RADIO_WINDOW = 86400
JOBS_SHOWN = 20
INDEX_CSP = (
    "default-src 'none'; script-src 'nonce-{0}'; style-src 'nonce-{0}'; connect-src 'self'; media-src {1}; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)


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
        return {
            "settings": settings,
            "media": media_origins(settings),
            "speech": self.speech.describe(),
            "people": people,
            "inbox": self.inbox(now, tasks, directory),
            "pending": self.batches.listed(),
            "rules": [{**{key: value for key, value in rule.items() if key != "proof"}, "signed": rule.get("proof") is not None} for rule in self.rules.listed()],
            "approvers": self.keys(),
            "jobs": jobs,
            "views": VIEWS,
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
            "priority": priority(tasks),
            "radio": radio,
            "claims": claims,
            "grants": grant_rows,
            "night": night_mode(self.council),
            "silence": silence_of(self.council, now),
            "graph": drawn,
        }

    def save_settings(self, body: bytes) -> dict:
        return self.settings.put(decode(body))

    def render(self, nonce: str) -> tuple[str, str]:
        now = time.time()
        state = self.state(now - RADIO_WINDOW, now, now, 0)
        page = self.templates.get_template("index.html.j2").render(nonce=nonce, state=state)
        return page, INDEX_CSP.format(nonce, " ".join(["'self'", *state["media"]]))
