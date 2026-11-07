from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

CLIENT = Path(__file__).resolve().parents[1] / "client"


def client_module(name: str, uses: dict[str, ModuleType]) -> ModuleType:
    """Args:
        name: a module of orchestrator/client, loaded under its own
            kvb_orchestrator_<name> name.
        uses: the client modules it imports by their bare names; they are
            visible under those names only while it loads.
    """
    spec = importlib.util.spec_from_file_location(f"kvb_orchestrator_{name}", CLIENT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    before = {key: sys.modules.get(key) for key in uses}
    sys.modules.update(uses)
    try:
        spec.loader.exec_module(module)
    finally:
        for key, old in before.items():
            if old is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = old
    return module


signing = client_module("signing", {})
passkey = client_module("passkey", {"signing": signing})
verifier = client_module("verifier", {"signing": signing, "passkey": passkey})


def ask_signed(ask: dict) -> dict:
    return signing.ask_item(ask["id"], ask["tool"], ask["command"], ask["cwd"], ask["session"])


def review_signed(review: dict) -> dict:
    return signing.review_item(review["id"], review.get("repo", ""), review["worktree"], review["branch"], review["tree"])


def operator_signed(row: dict) -> dict:
    return signing.operator_item(row["task"], row["command"], row["directory"])


def request_signed(request: dict) -> dict:
    return signing.rule_request_item(request["id"], request["kind"], request["tool"], request["pattern"], request["scope"], int(request["expires"]))


def message_signed(message: dict) -> dict:
    upload = message["upload"]
    return signing.message_item(message["to"], message["class"], message["text"], "" if upload is None else upload["id"], message["voice"] or "", message["voice_sha256"])
