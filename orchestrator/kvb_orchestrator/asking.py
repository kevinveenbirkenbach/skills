from __future__ import annotations

import time

from .choosing import EVERYONE, PICKED, answer_text, decision_status
from .council import agent, read_claims
from .diffs import sealed_file, store_diff, store_sealed, valid_diff, valid_sealed
from .errors import Conflict, Missing, ToolError
from .fields import (
    COMMAND_LIMIT,
    DESCRIPTION_LIMIT,
    MCP_WAIT_CAP,
    OPTION_LIMIT,
    PATH_LIMIT,
    WAIT_CAP,
    bounded,
    decode,
    expect,
    field,
    instant,
    message_text,
    seconds,
    visible,
)
from .signed import ask_signed

ASK_LIFETIME = 3600
PREVIEW_LIMIT = 4000
ASK_TEXTS = {"command": COMMAND_LIMIT, "cwd": PATH_LIMIT, "session": 200, "agent": 200}
ANSWERS = {"allow": "allowed", "deny": "denied"}
RECOMMENDED = "(Recommended)"
TERMINAL = "terminal"


def ask_state(ask: dict, now: float) -> dict:
    status = "expired" if ask["status"] == "pending" and ask["expires"] <= now else ask["status"]
    return {"id": ask["id"], "status": status, "decided": ask["decided"], "proof": ask.get("proof"), "channel": ask.get("channel", ""), "reason": ask.get("reason", ""), "to": ask.get("to", "")}


def ask_row(ask: dict, names: dict[str, str]) -> dict:
    keys = ("id", "tool", "command", "cwd", "session", "created_ts", "expires")
    return {**{key: ask[key] for key in keys}, "agent": names.get(ask["session"], ""), "subagent": ask["agent"]}


def decision_state(decision: dict) -> dict:
    """Returns:
        The status and choice, with the id and text of the operator's
        passkey-signed answer when a click chose it, else None for both.
    """
    message = decision.get("message")
    answer = None if message is None else answer_text(decision, decision["choice"])
    return {**{key: decision[key] for key in ("id", "status", "choice", "decided")}, "message": message, "answer": answer}


def decision_row(decision: dict) -> dict:
    return {key: decision[key] for key in ("id", "question", "options", "agent", "created_ts")}


def option_of(option: object) -> dict:
    """Args:
        option: {"label", "description"} and an optional "preview", a
            multi-line mockup, snippet or table shown beside the options.

    Returns:
        The option with its texts stripped; "preview" only when it was given
        and is not empty.
    """
    if not isinstance(option, dict):
        raise ToolError("every option must be an object with label and description")
    expect(option, ("label", "description", *(("preview",) if "preview" in option else ())))
    label = field(option, "label").strip()
    description = bounded(option, "description", DESCRIPTION_LIMIT).strip()
    preview = bounded(option, "preview", PREVIEW_LIMIT).rstrip() if "preview" in option else ""
    visible({"description": description, "preview": preview})
    return {"label": label, "description": description, **({"preview": preview} if preview.strip() else {})}


def choice_of(arguments: dict) -> tuple[str, list[dict]]:
    """Returns:
        The question and the options of a decision, each passed by
        option_of(), once the labels are distinct.
    """
    question = message_text(arguments, "question")
    visible({"question": question})
    options = arguments["options"]
    if not isinstance(options, list) or not 1 <= len(options) <= OPTION_LIMIT:
        raise ToolError(f"options must be a list of 1 to {OPTION_LIMIT} objects")
    parsed = [option_of(option) for option in options]
    if len({option["label"] for option in parsed}) != len(parsed):
        raise ToolError("option labels must be distinct")
    return question, parsed


class Asking:
    def ask(self, body: bytes) -> dict:
        """Args:
            body: the hook's ask: tool, ASK_TEXTS, timeout, optionally its diff
                and sealed patches, and the call's signing.call_key(), which
                an older hook leaves out; ask_ran() closes the ask by it.
        """
        payload = decode(body)
        diff = valid_diff(payload.pop("diff")) if "diff" in payload else None
        sealed = valid_sealed(payload.pop("sealed"), diff) if "sealed" in payload else {}
        key = field(payload, "call_key") if "call_key" in payload else ""
        payload.pop("call_key", None)
        expect(payload, ("tool", *ASK_TEXTS, "timeout"))
        values = {name: bounded(payload, name, limit) for name, limit in ASK_TEXTS.items()}
        visible(values)
        lifetime = seconds(payload, "timeout", ASK_LIFETIME)
        created = time.time()
        fields = {**values, "tool": field(payload, "tool").strip(), "call_key": key, "status": "pending", "decided": None, "proof": None, "diff_files": None if diff is None else len(diff)}
        with self.asks.changed:
            ask_id = self.asks.fresh()
            if diff is not None:
                store_diff(self.reviews.pages, "ask", ask_id, diff)
            if sealed:
                store_sealed(self.reviews.pages, "ask", ask_id, sealed)
            record = self.asks.insert(ask_id, {**fields, "created_ts": created, "expires": created + lifetime})
        self.automate("ask", record)
        return {"id": record["id"], "status": record["status"]}

    def ask_ran(self, body: bytes) -> dict:
        """Args:
            body: {"call_key", "session"}: the PostToolUse report of a tool
                call that ran, keyed by signing.call_key().

        Returns:
            {"closed"}: the id of the oldest ask of that session and key still
            pending and created before the report, now TERMINAL, as answered
            in the terminal; null when none is. An ask of another session or
            one already decided stays as it is. Nothing is approved or
            denied, and no signature is relayed.
        """
        payload = decode(body)
        expect(payload, ("call_key", "session"))
        key = field(payload, "call_key")
        session = bounded(payload, "session", ASK_TEXTS["session"])
        if not session:
            raise ToolError("session must not be empty")
        now = time.time()
        found = sorted((ask for ask in self.asks.pending() if ask.get("call_key") == key and ask["session"] == session and ask["created_ts"] <= now), key=lambda ask: (ask["created_ts"], ask["id"]))
        closed = next((ask["id"] for ask in found if self.asks.decide(ask["id"], {"status": TERMINAL})[1]), None)
        if closed is not None:
            sealed_file(self.reviews.pages, "ask", closed).unlink(missing_ok=True)
        return {"closed": closed}

    def ask_wait(self, ask_id: str, query: dict[str, list[str]]) -> dict:
        wait = instant(query, "wait")
        record = self.asks.get(ask_id)
        if record is None:
            raise Missing(ask_id)
        left = max(record["expires"] - time.time(), 0.0)
        record = self.asks.wait(ask_id, min(wait or 0.0, WAIT_CAP, left))
        state = ask_state(record, time.time())
        if state["status"] == "expired":
            sealed_file(self.reviews.pages, "ask", ask_id).unlink(missing_ok=True)
        return state

    def settle(self, kind_name: str, item_id: str, verb: str, body: bytes) -> dict:
        if kind_name == "asks" and verb in ANSWERS:
            record = self.asks.get(item_id)
            if record is None:
                raise Missing(item_id)
            if ask_state(record, time.time())["status"] == "expired":
                raise Conflict(ask_state(record, time.time()))
            proof = None
            if verb == "allow":
                payload = decode(body)
                expect(payload, ("proof",))
                proof = self.covered(payload["proof"], [ask_signed(record)], time.time())
            decided, changed = self.asks.decide(item_id, {"status": ANSWERS[verb], "proof": proof})
            if not changed:
                raise Conflict(ask_state(decided, time.time()))
            return ask_state(decided, time.time())
        raise Missing(verb)

    def question(self, body: bytes) -> dict:
        """Args:
            body: {"question", "options", "session", "timeout", "multi"}: one
                question of an AskUserQuestion call the permission hook
                mirrors as a decision; it expires after timeout seconds, a
                multi one takes several options as a pick (choosing.picks),
                its recommendation is the options labelled RECOMMENDED
                (the first of them for a single one), and a signed pick is
                kept for the hook instead of being posted.
        """
        payload = decode(body)
        expect(payload, ("question", "options", "session", "timeout", "multi"))
        question, parsed = choice_of(payload)
        multi = payload["multi"]
        if not isinstance(multi, bool):
            raise ToolError("multi must be true or false")
        session = bounded(payload, "session", ASK_TEXTS["session"]).strip()
        if not session:
            raise ToolError("session must not be empty")
        visible({"session": session})
        created = time.time()
        asker = self.directory(read_claims(self.council), [], created).now(session) or session
        if EVERYONE in asker:
            raise ToolError(f"the asking session's name holds {EVERYONE}")
        marked = [option["label"] for option in parsed if option["label"].endswith(RECOMMENDED)]
        recommended = PICKED.join(marked) if multi else next(iter(marked), "")
        fields = {"question": question, "options": parsed, "agent": asker, "recommended": recommended, "session": session, "hooked": True, "multi": multi}
        record = self.decisions.add({**fields, "status": "pending", "choice": None, "decided": None, "proof": None, "created_ts": created, "expires": created + seconds(payload, "timeout", ASK_LIFETIME)})
        return {"id": record["id"], "status": record["status"]}

    def question_wait(self, decision_id: str, query: dict[str, list[str]]) -> dict:
        """Returns:
            The state of a decision the permission hook asked: status
            (pending, decided or expired), the choice, the operator's
            signature over the pick and the to it was signed for.
        """
        wait = instant(query, "wait")
        record = self.decisions.get(decision_id)
        if record is None or not record.get("hooked"):
            raise Missing(decision_id)
        record = self.decisions.wait(decision_id, min(wait or 0.0, WAIT_CAP, max(record["expires"] - time.time(), 0.0)))
        return {"id": decision_id, "status": decision_status(record, time.time()), "choice": record["choice"], "proof": record["proof"], "to": agent(record["agent"])}

    def decision_request(self, arguments: dict) -> dict:
        expect(arguments, ("question", "options", "agent", "recommended"))
        question, parsed = choice_of(arguments)
        recommended = arguments["recommended"]
        if not isinstance(recommended, str) or recommended.strip() not in ["", *(option["label"] for option in parsed)]:
            raise ToolError("recommended must be one of the option labels or an empty string")
        asker = field(arguments, "agent").strip()
        if EVERYONE in asker:
            raise ToolError(f"agent names the asking agent, never a name with {EVERYONE}")
        fields = {"question": question, "options": parsed, "agent": asker, "recommended": recommended.strip()}
        record = self.decisions.add({**fields, "status": "pending", "choice": None, "decided": None, "created_ts": time.time()})
        self.automate("decision", record)
        return {"id": record["id"], "status": record["status"], "url": self.url()}

    def decision_wait(self, arguments: dict) -> dict:
        expect(arguments, ("id", "timeout_seconds"))
        decision_id = field(arguments, "id")
        record = self.decisions.wait(decision_id, seconds(arguments, "timeout_seconds", MCP_WAIT_CAP))
        if record is None:
            raise ToolError(f"no decision {decision_id}")
        return decision_state(record)
