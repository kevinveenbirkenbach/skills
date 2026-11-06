from __future__ import annotations

import time

from .council import HUMAN, agent, read_claims
from .crons import cron_state, queue_rows, timer_rows
from .errors import ToolError
from .fields import single
from .lifetimes import edge_times, lifetime, session_gone, subagent_rows
from .names import PSEUDO, SESSION_ID, Directory, title_sightings
from .records import epoch, iso_epoch
from .register import REGISTER, read_register
from .tree import assign


class Sources:
    def subagents(self, query: dict[str, list[str]]) -> dict:
        session = single(query, "session") or ""
        if not SESSION_ID.fullmatch(session):
            raise ToolError("session must be a session id")
        now = time.time()
        beats = [claim["beat"] for claim in read_claims(self.council) if claim["session"] == session and claim["beat"] is not None]
        try:
            path = next(iter(sorted(self.transcripts.root.glob(f"*/{session}.jsonl"))), None)
        except OSError:
            path = None
        times = edge_times(path) if path is not None else (None, None, None)
        life = lifetime(times, session_gone(max(beats, default=None), times[2], now))
        return {"session": session, **life, "subagents": subagent_rows(self.transcripts.root, session)}

    def directory(self, claims: list[dict], news: list[dict], now: float) -> Directory:
        claimed = {claim["session"] for claim in claims}
        sightings = title_sightings(self.transcripts.root, claimed, now) if self.names.due(now) else []
        sightings += [(claim["session"], claim["agent"], iso_epoch(claim["since"]), "claim") for claim in claims if claim["agent"] and claim["session"] != "-"]
        self.names.observe(sorted(sightings, key=lambda sighting: (sighting[2] is None, sighting[2] or 0.0)), now)
        known = {entry["name"] for entry in self.names.listed()}
        radio = []
        for row in news:
            name, ts = agent(row.get("from")), epoch(row.get("ts"))
            if name and name != HUMAN and name not in known and ts is not None:
                radio.append((f"{PSEUDO}{name}", name, ts, "radio"))
                known.add(name)
        self.names.observe(radio, now)
        return Directory(self.names.listed())

    def repositories(self) -> dict:
        tasks = read_register(self.council / REGISTER)
        return assign(self.tree.get(), tasks, read_claims(self.council), self.reviews.listed())

    def schedules(self, claims: list[dict], now: float) -> list[dict]:
        beats = {claim["session"]: claim["beat"] for claim in claims if claim["beat"] is not None}
        rows = [cron_state(cron, beats, now) for cron in self.transcripts.schedules()]
        return rows + timer_rows(self.timers) + queue_rows(self.council)
