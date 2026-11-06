from __future__ import annotations

import datetime
import fcntl
import json
import os
import tempfile
from pathlib import Path
from typing import NamedTuple

from passkey import verify_assertion
from signing import (
    Refused,
    checked_approval,
    checked_rule,
    item_hash,
    load_pinned,
    rule_allows,
)


class Trust(NamedTuple):
    approvers: Path
    replay: Path
    origin: str


def pinned(path: Path) -> list[dict]:
    entries = load_pinned(path)
    if not entries:
        raise Refused("no key is pinned")
    return entries


def write_private(path: Path, data: dict) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}-")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=1, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    except OSError:
        Path(name).unlink(missing_ok=True)
        raise


def pin(path: Path, entry: dict, now: float) -> list[dict]:
    stamp = datetime.datetime.fromtimestamp(now, datetime.UTC).isoformat(timespec="seconds")
    entries = [old for old in load_pinned(path) if old["id"] != entry["id"]] + [{**entry, "pinned": stamp}]
    write_private(path, {"credentials": entries})
    return entries


def read_store(store: Path) -> dict:
    try:
        data = json.loads(store.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"used": {}, "counts": {}}
    except (OSError, ValueError, RecursionError) as error:
        raise Refused(f"the replay store {store} is unreadable") from error
    counts = data.get("counts") if isinstance(data, dict) else None
    shaped = isinstance(counts, dict) and all(isinstance(last, dict) and isinstance(last.get("count"), int) and isinstance(last.get("nonce"), str) for last in counts.values())
    if not shaped or not isinstance(data.get("used"), dict):
        raise Refused(f"the replay store {store} is malformed")
    return data


def consume(store: Path, key: str, expires: int, credential: str, count: int, nonce: str, now: float) -> None:
    """Args:
        store: the executor's own replay store, outside the hub's reach.
        key: the one-time id, nonce and item hash.
        expires: until when the id must stay known.
        credential: the id of the key that signed.
        count: its signature counter; 0 when the authenticator keeps none.
        nonce: the payload nonce; one bulk signature carries one counter.
        now: the current time in epoch seconds.
    """
    store.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(store.with_name(f"{store.name}.lock"), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        state = read_store(store)
        used = {name: until for name, until in state["used"].items() if isinstance(until, int | float) and until > now}
        if key in used:
            raise Refused("this signature was already used for this item")
        last = state["counts"].get(credential)
        if last is not None and not (count > last["count"] or (count == last["count"] and (count == 0 or nonce == last["nonce"]))):
            raise Refused("the signature counter did not grow: a cloned authenticator or a replay")
        write_private(store, {"used": {**used, key: expires}, "counts": {**state["counts"], credential: {"count": count, "nonce": nonce}}})
    finally:
        os.close(descriptor)


def check(proof: object, item: dict, gate: str, trust: Trust, now: float) -> None:
    """Args:
        proof: {"payload", "assertion"} the kvb-hub relayed for the item.
        item: the executor's own item, built from what it is about to do.
        gate: pass or fail as the executor itself saw it; a rule approves a
            review on pass only.
        trust: the pinned keys, the executor's replay store and the origin.
        now: the current time in epoch seconds.

    Raises:
        Refused with the reason, unless a pinned key signed an unexpired
        approval that lists the item and is used here for the first time, or
        an unexpired rule whose pattern the item matches.
    """
    if not isinstance(proof, dict) or set(proof) != {"payload", "assertion"}:
        raise Refused("no signature")
    payload = proof["payload"]
    if isinstance(payload, dict) and payload.get("kind") == "rule":
        checked_rule(payload, now)
        verify_assertion(proof["assertion"], payload, pinned(trust.approvers), trust.origin)
        if not rule_allows(payload, item, gate, now):
            raise Refused("the signed rule does not match this item")
        return
    checked_approval(payload, now)
    count = verify_assertion(proof["assertion"], payload, pinned(trust.approvers), trust.origin)
    digest = item_hash(item)
    if digest not in payload["items"]:
        raise Refused("the signature does not list this item")
    consume(trust.replay, f"{payload['nonce']}:{digest}", payload["expires"], proof["assertion"]["id"], count, payload["nonce"], now)
