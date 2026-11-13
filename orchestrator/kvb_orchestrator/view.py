from __future__ import annotations

import time

from .asking import ask_row, decision_row
from .council import (
    MAYDAY_ACTIVE,
    NEWS,
    grants,
    message_rows,
    night_mode,
    night_parts,
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
from .phrasing import joined, phrase_parts
from .presence import presence, read_snapshot
from .receipts import inline, read_of
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
from .settings import media_origins, station_origins, valid_settings
from .signed import signing
from .skill_scripts import OUTPUT_LIMIT
from .tasks import queue_chain, queue_line, task_edges, task_rows

RADIO_WINDOW = 86400
JOBS_SHOWN = 20
ACTIVE = 900
INDEX_CSP = (
    "default-src 'none'; script-src 'nonce-{0}'; style-src 'nonce-{0}'; connect-src 'self'; media-src {1}; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)


def badges(inbox: list[dict], claims: list[dict], jobs: list[dict], now: float) -> dict[str, int]:
    return {
        "tasks": sum(1 for item in inbox if not item["until"]),
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

    def inlined(self, news: list[dict], window: tuple[float, float], now: float) -> dict[float, dict]:
        """Returns:
            inline() of the rows; empty when it fails, so the state builds
            without readers.
        """
        try:
            return inline(self.scripts.skills, self.council, self.receipt_names, self.receipt_reads, self.agent_sessions, news, window, now)
        except Exception:  # noqa: BLE001
            return {}

    def first(self, news: list[dict], history: list[dict], claims: list[dict], now: float) -> float:
        moments = [epoch(row.get("ts")) for row in news] + [epoch(row.get("start")) for row in history]
        moments += [iso_epoch(claim["since"]) for claim in claims] + [self.transcripts.first()]
        moments += [iso_epoch(record["created"]) for ledger in (self.reviews, self.asks, self.decisions, self.messages) for record in ledger.listed()]
        return min([now, *(moment for moment in moments if moment is not None)])

    def state(self, begin: float, end: float, now: float, steps: int) -> dict:
        tasks = read_register(self.council / REGISTER)
        news = read_jsonl(self.council / NEWS)
        history = self.history.rows()
        claims = read_claims(self.council)
        names = sessions(claims)
        directory = self.directory(claims, news, now)
        radio = []
        inlined = self.inlined(news, (begin, end), now)
        for row in message_rows(news, begin, end):
            source = directory.key(row["from"], row["ts"])
            targets = [directory.key(name, row["ts"]) for name in row["to"]]
            called = [directory.at(key, row["ts"]) or name for key, name in zip(targets, row["to"], strict=True)]
            word, rest = phrase_parts(row["class"], directory.at(source, row["ts"]) or row["from"], called, row["text"])
            spoken = {"speech": joined((word, rest)), "word": word, "rest": rest, "voice": self.speech.voice_of(source)}
            read = read_of(inlined, row["ts"])
            radio.append({**row, "source": source, "targets": targets, "now": directory.now(source), **spoken, **read})
        grant_rows = [{**grant, "target": directory.key(grant["to"], grant["ts"])} for grant in grants(history, (begin, end), claims, tasks)]
        self.watch.see(tasks, now)
        jobs = [{**{key: value for key, value in job.items() if key != "proof"}, "output": job["output"][-OUTPUT_LIMIT:]} for job in self.jobs.listed()[-JOBS_SHOWN:]]
        drawn = graph(radio, grant_rows, tasks, claims, end, directory)
        first = self.first(news, history, claims, now)
        drawn["track"] = track(drawn["nodes"], radio, tasks, claims, (min(max(begin, first), end), end), directory, steps)
        people = {node["id"]: {"name": node["label"], "now": directory.now(node["id"]) or node["label"], "names": node["names"]} for node in drawn["nodes"] if node["kind"] != "subagent"}
        settings = self.settings.get()
        inbox = self.inbox(now, tasks, directory)
        queue = queue_entries(self.council, self.history.rows)
        order = stored_order(self.council / AGENT_ORDER)
        rows = task_rows(tasks, queue, self.tree.get())
        chain = queue_chain(queue, tasks, order, now)
        return {
            "settings": settings,
            "media": media_origins(settings),
            "speech": {**self.speech.describe(), "gate": self.speech_gate.state()},
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
            "messages": [{**message_row(message), **read_of(inlined, epoch(message.get("relay_ts")))} for message in self.messages.listed() if begin <= message["created_ts"] <= end],
            "operator": operator_rows(tasks),
            "register": register_rows(tasks),
            "tasks": rows,
            "task_edges": task_edges(rows, chain),
            "queue_line": queue_line(chain, queue),
            "agent_order": agent_order(tasks, claims, order),
            "radio": radio,
            "claims": claims,
            "grants": grant_rows,
            "night": night_mode(self.council),
            "night_parts": night_parts(self.council),
            "presence": presence(read_snapshot(self.agent_sessions, now), night_parts(self.council), night_mode(self.council), claims, news, now),
            "silence": silence_of(self.council, now),
            "graph": drawn,
        }

    def signed_changes(self, settings: dict, saved: dict) -> list[dict]:
        """Args:
            settings: valid settings the page wants to save.
            saved: the settings saved now.

        Returns:
            The items the operator's passkey signs for this save: the station
            origins and the new urls when the settings name a stream url the
            saved ones do not, and the speech threshold when it differs from
            the saved one, since the hub's speech gate enforces it. The hub
            dials no url before it is signed, and resolves its redirect
            targets only after the signature.
        """
        urls = sorted({stream["url"] for stream in settings["streams"]} - {stream["url"] for stream in saved["streams"]})
        threshold = settings["speech"]["threshold"]
        streams = [signing.stream_item(station_origins(settings), urls)] if urls else []
        return streams + ([signing.threshold_item(threshold)] if threshold != saved["speech"]["threshold"] else [])

    def resolved(self, settings: dict, saved: dict) -> tuple[dict, list[str]]:
        """Args:
            settings: valid settings whose new stream urls the operator
                signed in this request.
            saved: the settings saved now.

        Returns:
            The settings with the via of each new url taken from its redirect
            chain, and of each saved url whose via is still None (unresolved)
            once Redirects.due allows a retry; every other stream keeps its
            saved via without a dial, and the page's via is never used. Also
            one line per stream whose chain did not resolve; its via stays
            None.
        """
        known = {stream["url"]: stream["via"] for stream in saved["streams"]}
        urls = {stream["url"] for stream in settings["streams"]}
        outcomes = self.redirects.resolve(sorted(url for url in urls if url not in known or (known[url] is None and self.redirects.due(url))))
        streams, problems = [], []
        for stream in settings["streams"]:
            via, problem = outcomes.get(stream["url"], (known.get(stream["url"]), ""))
            if problem:
                problems.append(f"{stream['name']}: {problem}")
            streams.append({**stream, "via": via})
        return {**settings, "streams": streams}, problems

    def sign_settings(self, body: bytes) -> dict:
        return self.challenge_for(self.signed_changes(valid_settings(decode(body)), self.settings.get()))

    def save_settings(self, body: bytes) -> dict:
        """Returns:
            {"settings", "problems"}: the saved settings, their via resolved
            once the proof holds, and why a chain did not resolve. A save
            that lands while this one resolves makes this one fail.
        """
        payload = decode(body)
        proof = payload.pop("proof", None)
        settings = valid_settings(payload)
        saved = self.settings.get()
        for change in self.signed_changes(settings, saved):
            self.operator_proven(proof, change)
        resolved, problems = self.resolved(settings, saved)
        return {"settings": self.settings.put(resolved, saved), "problems": problems}

    def render(self, nonce: str) -> tuple[str, str]:
        now = time.time()
        state = self.state(now - RADIO_WINDOW, now, now, 0)
        page = self.templates.get_template("index.html.j2").render(nonce=nonce, state=state, view=self.view_store.get(), icons=self.icons, emoji_bases=sorted(signing.EMOJI_BASES))
        return page, INDEX_CSP.format(nonce, " ".join(["'self'", *state["media"]]))
