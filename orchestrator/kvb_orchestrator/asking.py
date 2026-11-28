from __future__ import annotations

import hashlib
import hmac
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
    TEXT_LIMIT,
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
ENDED = "ended"
IN_CLAUDE = "claude"
IN_CLAUDE_WORDS = "Open in Claude: answer it there; its hook stopped waiting for the hub"
RAN = "PostToolUse"
TURN_ENDS = ("Stop", "UserPromptSubmit")
SESSION_END = "SessionEnd"
CLOSING = (RAN, *TURN_ENDS, SESSION_END)
ANSWERS_LIMIT = 8
ANSWER_LIMIT = 4000


def dialog_state(record: dict, now: float) -> str:
    """Args:
        record: an ask or a decision.
        now: the current time in epoch seconds.

    Returns:
        Where its card stands over the lifecycle of its Claude dialog:
        pending while the hook waits for the hub; IN_CLAUDE once the hook
        stopped waiting on a bound record (the hook registration closes it
        by CLOSING), expired on an unbound one; allowed, denied or decided
        once the hub answered; TERMINAL once Claude answered it, ENDED once
        its session ended.
    """
    if record["status"] != "pending" or record.get("expires", now + 1) > now:
        return record["status"]
    return IN_CLAUDE if record.get("bound") else "expired"


def ran_answers(raw: object) -> dict[str, str]:
    """Args:
        raw: {question: answer} of an AskUserQuestion call that ran, at most
            ANSWERS_LIMIT texts of at most ANSWER_LIMIT characters each.

    Returns:
        The answers by stripped question, each answer stripped.
    """
    if not isinstance(raw, dict) or len(raw) > ANSWERS_LIMIT or not all(isinstance(question, str) and isinstance(answer, str) and len(question) <= TEXT_LIMIT and len(answer) <= ANSWER_LIMIT for question, answer in raw.items()):
        raise ToolError(f"answers must map at most {ANSWERS_LIMIT} questions to answers of at most {ANSWER_LIMIT} characters")
    visible([{"question": question, "answer": answer} for question, answer in raw.items()])
    return {question.strip(): answer.strip() for question, answer in raw.items()}


def bound_of(payload: dict) -> bool:
    """Returns:
        The optional bound flag the hook sends when its registration also
        closes the session's cards (CLOSING), popped from payload; False when
        absent.
    """
    bound = payload.pop("bound", False)
    if not isinstance(bound, bool):
        raise ToolError("bound must be true or false")
    return bound


def closer_of(payload: dict) -> str:
    """Args:
        payload: a registration or a close report, holding the optional
            closer, the hook's per-session token (permission_hook.closer_token()).

    Returns:
        The sha256 hex digest of the closer, popped from payload, the only
        form the hub keeps; empty when absent, as an older hook sends it.
    """
    if "closer" not in payload:
        return ""
    token = field(payload, "closer")
    payload.pop("closer")
    return hashlib.sha256(token.encode()).hexdigest()


def closes(record: dict, presented: str) -> bool:
    """Args:
        record: an ask or a decision.
        presented: closer_of() a close report, empty without a closer.

    Returns:
        True only when the record stores a closer digest (closer_of() of its
        registration) and presented equals it, compared in constant time.
    """
    stored = record.get("closer_digest", "")
    return bool(stored) and bool(presented) and hmac.compare_digest(stored, presented)


def ran_closes(record: dict, presented: str) -> bool:
    """Returns:
        Whether a RAN report with presented may close the record: by
        closes(), or for a record of an older hook, which stores no closer
        digest, by its call_key alone.
    """
    return closes(record, presented) or not record.get("closer_digest")


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
                and sealed patches, the call's signing.call_key(), which
                an older hook leaves out (ask_ran() closes the ask by it),
                bound (bound_of()) and closer (closer_of()), whose digest
                alone the ask keeps as closer_digest.
        """
        payload = decode(body)
        diff = valid_diff(payload.pop("diff")) if "diff" in payload else None
        sealed = valid_sealed(payload.pop("sealed"), diff) if "sealed" in payload else {}
        key = field(payload, "call_key") if "call_key" in payload else ""
        payload.pop("call_key", None)
        bound = bound_of(payload)
        closer = closer_of(payload)
        expect(payload, ("tool", *ASK_TEXTS, "timeout"))
        values = {name: bounded(payload, name, limit) for name, limit in ASK_TEXTS.items()}
        visible(values)
        lifetime = seconds(payload, "timeout", ASK_LIFETIME)
        created = time.time()
        fields = {**values, "tool": field(payload, "tool").strip(), "call_key": key, "bound": bound, "closer_digest": closer, "status": "pending", "decided": None, "proof": None, "diff_files": None if diff is None else len(diff)}
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
            body: what a hook of the CLOSING events reports, each with the
                session_id of its stdin: {"event": RAN, "call_key", "session"}
                and for an AskUserQuestion call its "answers" (ran_answers())
                once a tool call ran, keyed by signing.call_key(); an older
                hook sends only call_key and session, which counts as RAN.
                {"event", "session"} for a TURN_ENDS event, which ends a turn
                with every dialog of the main agent closed (a denial or an
                interrupt in Claude), and for SESSION_END. Each optionally
                carries closer, the session's token (closer_of()).

        Returns:
            {"asks", "decisions"}: the ids of the records now closed, each
            created before the report and of exactly that session. RAN closes
            the oldest pending ask of that key and, per question, the oldest
            pending decision of that key that ran_closes() admits, the
            decision with its answer as choice only when closes() holds, all
            TERMINAL (answered in Claude); a TURN_ENDS event closes every
            pending record of the main agent that closes() admits TERMINAL,
            never one of a subagent, whose dialog may still be open while the
            main agent waits; SESSION_END closes every pending record that
            closes() admits ENDED. A record of another session, one already
            decided or, for TURN_ENDS and SESSION_END, one without the
            matching closer digest stays as it is. Nothing is approved or
            denied, and no signature is relayed.
        """
        payload = decode(body)
        event = payload.get("event", RAN)
        if not isinstance(event, str) or event not in CLOSING:
            raise ToolError(f"event must be one of {', '.join(CLOSING)}")
        keyed = event == RAN
        optional = ("event", "answers", "closer") if keyed else ("event", "closer")
        expect(payload, (*(("call_key",) if keyed else ()), "session", *(name for name in optional if name in payload)))
        session = bounded(payload, "session", ASK_TEXTS["session"])
        if not session:
            raise ToolError("session must not be empty")
        presented = closer_of(payload)
        now = time.time()
        if keyed:
            key = field(payload, "call_key")
            answers = ran_answers(payload["answers"]) if "answers" in payload else {}
            return {"asks": self.close_ran(session, key, presented, now), "decisions": self.close_answered(session, key, answers, presented, now)}
        status = ENDED if event == SESSION_END else TERMINAL
        main = event in TURN_ENDS
        asks = [ask["id"] for ask in self.asks.pending() if ask["session"] == session and ask["created_ts"] <= now and not (main and ask["agent"]) and closes(ask, presented) and self.asks.decide(ask["id"], {"status": status})[1]]
        decisions = [decision["id"] for decision in self.decisions.pending() if decision.get("hooked") and decision["session"] == session and decision["created_ts"] <= now and not (main and decision.get("subagent")) and closes(decision, presented) and self.decisions.decide(decision["id"], {"status": status})[1]]
        for ask_id in asks:
            sealed_file(self.reviews.pages, "ask", ask_id).unlink(missing_ok=True)
        return {"asks": asks, "decisions": decisions}

    def close_ran(self, session: str, key: str, presented: str, now: float) -> list[str]:
        """Args:
            presented: closer_of() the report, empty without a closer.

        Returns:
            The id of the oldest pending ask of session and key created by
            now that ran_closes() admits, closed TERMINAL; empty when none is.
        """
        found = sorted((ask for ask in self.asks.pending() if ask.get("call_key") == key and ask["session"] == session and ask["created_ts"] <= now and ran_closes(ask, presented)), key=lambda ask: (ask["created_ts"], ask["id"]))
        closed = next((ask["id"] for ask in found if self.asks.decide(ask["id"], {"status": TERMINAL})[1]), None)
        if closed is None:
            return []
        sealed_file(self.reviews.pages, "ask", closed).unlink(missing_ok=True)
        return [closed]

    def close_answered(self, session: str, key: str, answers: dict[str, str], presented: str, now: float) -> list[str]:
        """Args:
            answers: ran_answers() of the call, empty for a call of another
                tool.
            presented: closer_of() the report, empty without a closer.

        Returns:
            The ids of the decisions closed TERMINAL: per question, the
            oldest pending decision the hook asked for session and key by
            now that ran_closes() admits, its choice the answer to its
            question when closes() holds, else None, as when answers lacks
            it.
        """
        found = sorted((decision for decision in self.decisions.pending() if decision.get("hooked") and decision.get("call_key") == key and decision["session"] == session and decision["created_ts"] <= now and ran_closes(decision, presented)), key=lambda decision: (decision["created_ts"], decision["id"]))
        closed: list[str] = []
        asked: set[str] = set()
        for decision in found:
            choice = answers.get(decision["question"]) if closes(decision, presented) else None
            if decision["question"] not in asked and self.decisions.decide(decision["id"], {"status": TERMINAL, "choice": choice})[1]:
                asked.add(decision["question"])
                closed.append(decision["id"])
        return closed

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
                kept for the hook instead of being posted. Optionally the
                call's signing.call_key() and subagent, the agent_type of a
                subagent's call, by which ask_ran() closes it, bound
                (bound_of()) and closer (closer_of()), whose digest alone
                the decision keeps as closer_digest; an older hook leaves
                them out.
        """
        payload = decode(body)
        key = field(payload, "call_key") if "call_key" in payload else ""
        subagent = bounded(payload, "subagent", ASK_TEXTS["agent"]) if "subagent" in payload else ""
        visible({"subagent": subagent})
        bound = bound_of(payload)
        closer = closer_of(payload)
        for name in ("call_key", "subagent"):
            payload.pop(name, None)
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
        fields = {"question": question, "options": parsed, "agent": asker, "recommended": recommended, "session": session, "hooked": True, "multi": multi, "call_key": key, "subagent": subagent, "bound": bound, "closer_digest": closer}
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
