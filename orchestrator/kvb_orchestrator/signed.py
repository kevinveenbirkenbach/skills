from __future__ import annotations

import importlib.util
from pathlib import Path

SIGNING_SPEC = importlib.util.spec_from_file_location("kvb_orchestrator_signing", Path(__file__).resolve().parents[1] / "client" / "signing.py")
signing = importlib.util.module_from_spec(SIGNING_SPEC)
SIGNING_SPEC.loader.exec_module(signing)


def ask_signed(ask: dict) -> dict:
    return signing.ask_item(ask["id"], ask["tool"], ask["command"], ask["cwd"], ask["session"])


def review_signed(review: dict) -> dict:
    return signing.review_item(review["id"], review.get("repo", ""), review["worktree"], review["branch"], review["tree"])


def operator_signed(row: dict) -> dict:
    return signing.operator_item(row["task"], row["command"], row["directory"])
