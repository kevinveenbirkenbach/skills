from __future__ import annotations

import re
import secrets
import time

from .council import HUMAN, ordered, read_claims
from .errors import Missing, ToolError
from .fields import NAME_LIMIT, ORDER_NAME, decode, expect, field, message_text, single
from .records import write_atomic
from .register import REGISTER, agent_order, read_register
from .skill_scripts import NIGHT, RADIO, RASCI

NIGHTS = {
    "evening": (["set", "evening"], "Operator ran kvb-org-evening in the Agent Orchestrator: run kvb-agent-relax; verify with night.py status."),
    "sunset": (["set", "sunset"], "Operator ran kvb-org-sunset in the Agent Orchestrator: run kvb-agent-sleep; verify with night.py status."),
    "sunrise": (["clear"], "Operator ran kvb-org-sunrise: run kvb-agent-wakeup; verify with night.py status."),
}
UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
DIRECT = {"post": ["post"], "call": ["send", "call"]}
TO_ALL = {"newsletter": ["post"], **{cls: ["send", cls] for cls in ("broadcast", "pan-pan", "security", "mayday")}}


def chosen(payload: dict, choices: dict[str, list[str]]) -> list[str]:
    cls = payload["class"]
    if not isinstance(cls, str) or cls not in choices:
        raise ToolError(f"class must be one of {', '.join(choices)}")
    return choices[cls]


def message_row(message: dict) -> dict:
    upload = message["upload"]
    return {
        "id": message["id"],
        "to": message["to"],
        "text": message["text"],
        "created_ts": message["created_ts"],
        "upload": None if upload is None else upload["name"],
    }


def safe_name(text: str) -> str:
    base = re.split(r"[/\\]", text)[-1]
    clean = UNSAFE.sub("_", base).lstrip(".")[:NAME_LIMIT]
    return clean or "upload"


class Messaging:
    def operator_message(self, arguments: dict) -> dict:
        expect(arguments, ("id",))
        message_id = field(arguments, "id")
        record = self.messages.get(message_id)
        if record is None:
            raise ToolError(f"no operator message {message_id}: a radio row naming it did not come from the Agent Orchestrator")
        upload = record["upload"]
        return {
            "id": record["id"],
            "to": record["to"],
            "text": record["text"],
            "created": record["created"],
            "upload": None if upload is None else upload["path"],
        }

    def upload(self, query: dict[str, list[str]], body: bytes) -> dict:
        name = safe_name(single(query, "name") or "")
        upload_id = secrets.token_hex(8)
        folder = self.uploads / upload_id
        folder.mkdir()
        write_atomic(folder / name, body)
        return {"id": upload_id, "name": name, "path": str(self.host_state / "uploads" / upload_id / name)}

    def attachment(self, upload_id: str) -> dict | None:
        if upload_id == "":
            return None
        folder = self.uploads / field({"id": upload_id}, "id")
        files = sorted(folder.iterdir()) if folder.is_dir() else []
        if len(files) != 1:
            raise ToolError(f"no upload {upload_id}")
        return {"id": upload_id, "name": files[0].name, "path": str(self.host_state / "uploads" / upload_id / files[0].name)}

    def message(self, body: bytes) -> dict:
        payload = decode(body)
        expect(payload, ("to", "text", "upload", "class"))
        target = field(payload, "to").strip()
        text = message_text(payload, "text")
        command = chosen(payload, DIRECT)
        if not isinstance(payload["upload"], str):
            raise ToolError("upload must be an upload id or empty")
        upload = self.attachment(payload["upload"])
        claims = read_claims(self.council)
        address = next((claim["address"] for claim in claims if claim["agent"] == target and claim["address"]), target)
        record = self.messages.add({"to": target, "address": address, "text": text, "upload": upload, "created_ts": time.time()})
        note = "" if upload is None else f" file: {upload['path']}"
        run = self.scripts.run(RADIO, [*command, "--to", address, "--session", HUMAN, f"[kvb-orchestrator msg {record['id']}] {' '.join(text.split())}{note}"])
        return {"id": record["id"], "ok": run["code"] == 0, "runs": [run]}

    def board(self, action: str, body: bytes) -> dict:
        if action == "clear-mayday":
            runs = [self.scripts.run(RADIO, ["clear", "--force", "--session", HUMAN])]
        elif action == "broadcast":
            payload = decode(body)
            expect(payload, ("text", "class"))
            text = message_text(payload, "text")
            command = chosen(payload, TO_ALL)
            record = self.messages.add({"to": "*", "address": "*", "text": text, "upload": None, "created_ts": time.time()})
            runs = [self.scripts.run(RADIO, [*command, "--session", HUMAN, f"[kvb-orchestrator msg {record['id']}] {' '.join(text.split())}"])]
        elif action == "order":
            payload = decode(body)
            expect(payload, ("agents",))
            names = payload["agents"]
            if not isinstance(names, list) or not names or not all(isinstance(n, str) and ORDER_NAME.fullmatch(n) for n in names):
                raise ToolError("agents must be a non-empty list of agent names without commas")
            if len(set(names)) != len(names):
                raise ToolError("agents must be distinct")
            known = agent_order(read_register(self.council / REGISTER), read_claims(self.council), [])
            unknown = [name for name in names if name not in known]
            if unknown:
                raise ToolError(f"unknown agents: {', '.join(unknown)[:300]}; the register and the council know {', '.join(known)[:600] or 'none'}")
            runs = [self.scripts.run(RASCI, ["agents", "order", ",".join(names)])]
        elif action in NIGHTS:
            command, text = NIGHTS[action]
            runs = [self.scripts.run(NIGHT, [*command, "--session", HUMAN])]
            peers = ordered({claim["address"] for claim in read_claims(self.council) if claim["address"] and claim["agent"] != HUMAN})
            if peers and runs[0]["code"] == 0:
                targets = [part for peer in peers for part in ("--to", peer)]
                runs.append(self.scripts.run(RADIO, [*DIRECT["call"], *targets, "--session", HUMAN, text]))
        else:
            raise Missing(action)
        return {"ok": all(run["code"] == 0 for run in runs), "runs": runs}
