from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .council import NEWS, ordered, read_claims
from .denying import DENIABLE
from .errors import ToolError
from .events import VIEWS
from .fields import bounded, decode, expect, message_text
from .records import read_jsonl
from .register import REGISTER, agent_order, read_register

NL_LIMIT = 2000
NL_ACTION_LIMIT = 20
LLM_TIMEOUT = 60
LLM_REPLY = 1 << 20


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


LLM_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect)
SCREENS = ("stream", "inbox", "rules", "agents", "artifacts", "tasks")
IDS = {"type": "array", "items": {"type": "string"}, "minItems": 1, "description": "Ids from items."}
NL_ACTIONS = [
    {"name": "approve", "description": "Approve inbox items; a decision takes its recommended option.", "parameters": {"ids": IDS}},
    {"name": "reject", "description": "Reject reviews, or deny asks, operator rows and rule requests; the requesting agent gets a post.", "parameters": {"ids": IDS}},
    {"name": "choose", "description": "Pick an option label of a decision.", "parameters": {"id": {"type": "string"}, "label": {"type": "string"}}},
    {"name": "snooze", "description": "Hide inbox items for some hours.", "parameters": {"ids": IDS, "hours": {"type": "number", "minimum": 1, "maximum": 192}}},
    {"name": "pin", "description": "Pin inbox items to the top.", "parameters": {"ids": IDS}},
    {"name": "view", "description": "Show a saved view of the stream.", "parameters": {"name": {"type": "string", "enum": list(VIEWS)}}},
    {"name": "open", "description": "Switch the screen.", "parameters": {"view": {"type": "string", "enum": list(SCREENS)}}},
    {"name": "message", "description": "Radio a direct message to an agent.", "parameters": {"to": {"type": "string"}, "text": {"type": "string"}}},
    {"name": "filter", "description": "Search the stream for a text.", "parameters": {"q": {"type": "string"}}},
]


def nl_messages(text: str, items: list[dict], agents: list[str]) -> list[dict]:
    schemas = [{"name": action["name"], "description": action["description"], "arguments": action["parameters"]} for action in NL_ACTIONS]
    system = (
        "You turn one command of the Agent Orchestrator operator into hub actions. Reply with exactly one JSON object "
        '{"actions": [{"name": "<action>", "arguments": {...}}]} and nothing else. Every action has one of these '
        f"names, and its arguments object holds exactly the listed properties: {json.dumps(schemas, ensure_ascii=False)}. "
        'Use only ids from items and names from agents. Reply {"actions": []} when nothing fits.'
    )
    user = json.dumps({"command": text, "items": items, "agents": agents}, ensure_ascii=False)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def nl_ids(arguments: dict, items: dict[str, dict]) -> list[dict]:
    ids = arguments["ids"]
    if not isinstance(ids, list) or not ids or not all(isinstance(ident, str) and ident in items for ident in ids):
        raise ToolError("ids must name inbox items")
    if len(set(ids)) != len(ids):
        raise ToolError("ids must be distinct")
    return [items[ident] for ident in ids]


def nl_item(item: dict, verb: str, label: str) -> dict:
    entry = {"kind": item["kind"], "id": item["id"], "verb": verb, "label": label, "sha256": item["sha256"]}
    return {**entry, "channel": "post", "reason": "", "to": item["to"]} if verb == "reject" and item["kind"] in DENIABLE else entry


def nl_action(raw: object, items: dict[str, dict], agents: list[str]) -> dict:
    if not isinstance(raw, dict) or set(raw) != {"name", "arguments"} or not isinstance(raw["arguments"], dict):
        raise ToolError("an action must be an object with name and arguments")
    schema = next((action for action in NL_ACTIONS if action["name"] == raw["name"]), None)
    if schema is None:
        raise ToolError(f"unknown action {str(raw['name'])[:40]!r}")
    name, arguments = schema["name"], raw["arguments"]
    expect(arguments, tuple(schema["parameters"]))
    if name in ("approve", "reject"):
        picked = nl_ids(arguments, items)
        if name == "reject" and any(item["kind"] not in ("review", *DENIABLE) or (item["kind"] != "review" and not item["deniable"]) for item in picked):
            raise ToolError("reject takes reviews, asks, operator rows and rule requests that wait")
        if name == "approve" and any(item["kind"] == "rule" for item in picked):
            raise ToolError("a rule request is accepted in its row with the passkey")
        if name == "approve" and any(item["kind"] == "decision" and not item["recommended"] for item in picked):
            raise ToolError("a decision without a recommended option needs choose")
        if name == "approve" and any(item["kind"] == "operator" and not item["runnable"] for item in picked):
            raise ToolError("that operator row holds no command to run")
        chosen = [nl_item(item, "approve" if name == "approve" else "reject", item["recommended"] if item["kind"] == "decision" else "") for item in picked]
        lines = [f"{item['kind']} {item['id']}: {item['command'] if item['kind'] == 'operator' else item['title']}" for item in picked]
        verb = "Freigeben" if name == "approve" else "Ablehnen"
        return {"name": name, "summary": f"{verb}:\n" + "\n".join(lines), "args": {"items": chosen}}
    if name == "choose":
        item = items.get(arguments["id"]) if isinstance(arguments["id"], str) else None
        if item is None or item["kind"] != "decision" or arguments["label"] not in [option["label"] for option in item["options"]]:
            raise ToolError("choose takes a decision id and one of its option labels")
        return {"name": name, "summary": f"Entscheiden: {item['title']} → {arguments['label']}", "args": {"items": [nl_item(item, "approve", arguments["label"])]}}
    if name in ("snooze", "pin"):
        picked = nl_ids(arguments, items)
        hours = arguments.get("hours")
        if name == "snooze" and (isinstance(hours, bool) or not isinstance(hours, int | float) or not 1 <= hours <= 192):
            raise ToolError("hours must be between 1 and 192")
        keys = [{"kind": item["kind"], "id": item["id"]} for item in picked]
        words = f"Zurückstellen ({hours} h)" if name == "snooze" else "Anheften"
        return {"name": name, "summary": f"{words}: " + ", ".join(item["title"][:80] for item in picked), "args": {"keys": keys, "hours": hours}}
    if name == "view":
        if arguments["name"] not in VIEWS:
            raise ToolError("unknown view")
        return {"name": name, "summary": f"Ansicht: {VIEWS[arguments['name']]['label']}", "args": {"name": arguments["name"]}}
    if name == "open":
        if arguments["view"] not in SCREENS:
            raise ToolError("unknown screen")
        return {"name": name, "summary": f"Öffnen: {arguments['view']}", "args": {"view": arguments["view"]}}
    if name == "message":
        text = message_text(arguments, "text")
        if arguments["to"] not in agents:
            raise ToolError("to must name a known agent")
        return {"name": name, "summary": f"Funk an {arguments['to']}: {text}", "args": {"to": arguments["to"], "text": text}}
    query = bounded(arguments, "q", 200)
    return {"name": name, "summary": f"Suchen: {query}", "args": {"q": query}}


def nl_actions(reply: str, items: list[dict], agents: list[str]) -> dict:
    text = reply.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        data = json.loads(text)
    except (ValueError, RecursionError):
        raise ToolError("the model answered no JSON object") from None
    if not isinstance(data, dict) or not isinstance(data.get("actions"), list):
        raise ToolError("the model answered no actions list")
    known = {item["id"]: item for item in items}
    accepted, rejected = [], []
    for raw in data["actions"][:NL_ACTION_LIMIT]:
        try:
            accepted.append(nl_action(raw, known, agents))
        except ToolError as error:
            rejected.append({"action": json.dumps(raw, ensure_ascii=False)[:300], "reason": str(error)})
    return {"actions": accepted, "rejected": rejected}


@dataclass(frozen=True)
class Model:
    url: str
    model: str
    key: str

    def enabled(self) -> bool:
        return bool(self.url and self.model)

    def complete(self, messages: list[dict]) -> str:
        target = self.url.rstrip("/")
        target = target if target.endswith("/chat/completions") else f"{target}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.key:
            headers["Authorization"] = f"Bearer {self.key}"
        body = json.dumps({"model": self.model, "messages": messages, "temperature": 0, "response_format": {"type": "json_object"}}).encode()
        request = urllib.request.Request(target, data=body, headers=headers, method="POST")
        try:
            with LLM_OPENER.open(request, timeout=LLM_TIMEOUT) as response:
                data = json.loads(response.read(LLM_REPLY))
            content = data["choices"][0]["message"]["content"]
        except (OSError, ValueError, KeyError, IndexError, TypeError) as error:
            raise ToolError(f"the model endpoint failed: {error}") from None
        if not isinstance(content, str):
            raise ToolError("the model endpoint answered no text")
        return content


def read_key(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, ValueError):
        return ""


class Language:
    def nl(self, body: bytes) -> dict:
        if not self.model.enabled():
            raise ToolError("the natural-language command line is off: set KVB_ORCHESTRATOR_LLM_URL and KVB_ORCHESTRATOR_LLM_MODEL in orchestrator/.env")
        payload = decode(body)
        expect(payload, ("text",))
        text = message_text(payload, "text")
        if len(text) > NL_LIMIT:
            raise ToolError(f"text must be at most {NL_LIMIT} characters")
        now = time.time()
        claims = read_claims(self.council)
        tasks = read_register(self.council / REGISTER)
        directory = self.directory(claims, read_jsonl(self.council / NEWS), now)
        self.watch.see(tasks, now)
        items = self.inbox(now, tasks, directory)
        agents = ordered({claim["agent"] for claim in claims if claim["agent"]} | set(agent_order(tasks, [], [])))
        shown_items = [{"id": item["id"], "kind": item["kind"], "title": item["title"][:200]} for item in items]
        return nl_actions(self.model.complete(nl_messages(text, shown_items, agents)), items, agents)
