from __future__ import annotations

import contextlib
import datetime
import re
from pathlib import Path

from .calibration import CALIBRATION, Calibrations, valid_share
from .errors import Missing, ToolError
from .fields import FIELDS, decode, visible
from .ledger import Ledger
from .records import read_jsonl
from .resources import HOUR, RESOURCES, TOKENS, rows_between
from .settings import flag, section

ACCOUNTS = "accounts.json"
SESSION_ACCOUNTS = "session-accounts.jsonl"
KEYS = ("provider", "email", "renewal", "reset", "resubscribe", "autorenew", "limit", "note")
MOMENT = ("day", "time")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63})*\.[A-Za-z]{2,24}")
TIME = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]")
DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
PROVIDER = re.compile(r"(?=[^\x00-\x1f\x7f]*\S)[^\x00-\x1f\x7f]{1,40}")
NOTE_LIMIT = 200
LIMIT_CAP = 10**15
RECENT = 8 * 24 * HOUR
COUNTS = ("input", "output", "cache_read", "cache_write")


def moment(value: object, name: str) -> dict:
    """Returns:
        {day, time}: day 0 for Sunday to 6 for Saturday as Date.getDay()
        counts, time HH:MM local; anything else raises ToolError.
    """
    data = section(value, name, MOMENT)
    day, time = data["day"], data["time"]
    if isinstance(day, bool) or not isinstance(day, int) or not 0 <= day <= 6:
        raise ToolError(f"{name}.day must be a weekday from 0 (Sunday) to 6 (Saturday)")
    if not isinstance(time, str) or not TIME.fullmatch(time):
        raise ToolError(f"{name}.time must be a time HH:MM")
    return {"day": day, "time": time}


def resubscribe(value: object) -> str:
    if value == "":
        return ""
    if isinstance(value, str) and DATE.fullmatch(value):
        with contextlib.suppress(ValueError):
            return datetime.date.fromisoformat(value).isoformat()
    raise ToolError("resubscribe must be a date YYYY-MM-DD or empty")


def valid_account(raw: object) -> dict:
    """Args:
        raw: the account as the page sent it, every key of KEYS.

    Returns:
        The account; a missing or unknown key, a bad email, weekday, time or
        date, or a negative limit raises ToolError.
    """
    data = section(raw, "account", KEYS)
    if not isinstance(data["provider"], str) or not PROVIDER.fullmatch(data["provider"]):
        raise ToolError("provider must be one line of 1 to 40 characters")
    if not isinstance(data["email"], str) or not EMAIL.fullmatch(data["email"]):
        raise ToolError("email must be an address like name@example.org")
    limit = data["limit"]
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or not 0 <= limit <= LIMIT_CAP):
        raise ToolError(f"limit must be empty or a whole number of tokens from 0 to {LIMIT_CAP}")
    if not isinstance(data["note"], str) or len(data["note"]) > NOTE_LIMIT:
        raise ToolError(f"note must be text of at most {NOTE_LIMIT} characters")
    account = {
        "provider": data["provider"].strip(),
        "email": data["email"],
        "renewal": moment(data["renewal"], "renewal"),
        "reset": moment(data["reset"], "reset"),
        "resubscribe": resubscribe(data["resubscribe"]),
        "autorenew": flag(data["autorenew"], "autorenew"),
        "limit": limit,
        "note": data["note"].strip(),
    }
    visible({"provider": account["provider"], "note": account["note"]})
    return account


def mapping(file: Path) -> dict[str, str]:
    """Returns:
        Each session's email, the last line the SessionStart hook wrote for
        it winning, in the order the sessions first appear.
    """
    found: dict[str, str] = {}
    for row in read_jsonl(file):
        session, email = row.get("session"), row.get("email")
        if isinstance(session, str) and isinstance(email, str) and EMAIL.fullmatch(email):
            found[session] = email
    return found


def active(file: Path) -> str | None:
    """Returns:
        The email of the newest mapping line: the account the host's
        Claude Code logged in with at the last session start.
    """
    emails = [row.get("email") for row in read_jsonl(file)]
    valid = [email for email in emails if isinstance(email, str) and EMAIL.fullmatch(email)]
    return valid[-1] if valid else None


def usage(rows: list[dict], now: float) -> dict[str, dict]:
    """Args:
        rows: token rows {t, agent, model, input, output, cache_read,
            cache_write, account?, width?}.
        now: the epoch seconds the recent hours end at.

    Returns:
        Per account email, "" for rows of no mapped session: {total, hours},
        total the tokens of every row, hours [t, tokens] per hourly row of
        the last 8 days in time order, for the page to sum from the local
        weekly reset and midnight.
    """
    found: dict[str, dict] = {}
    for row in rows:
        account = row.get("account") if isinstance(row.get("account"), str) else ""
        tokens = sum(value for value in (row.get(name) for name in COUNTS) if isinstance(value, int) and not isinstance(value, bool) and value > 0)
        entry = found.setdefault(account, {"total": 0, "hours": {}})
        entry["total"] += tokens
        t = row.get("t")
        if "width" not in row and isinstance(t, int | float) and now - RECENT <= t <= now:
            entry["hours"][int(t)] = entry["hours"].get(int(t), 0) + tokens
    return {account: {"total": entry["total"], "hours": sorted(entry["hours"].items())} for account, entry in found.items()}


class Accounts:
    def __init__(self, state: Path, kept: Path, council: Path) -> None:
        self.ledger = Ledger(state / ACCOUNTS)
        self.calibrations = Calibrations(state / CALIBRATION)
        self.tokens = kept / RESOURCES / TOKENS
        self.sessions = council / SESSION_ACCOUNTS

    def view(self, now: float) -> dict:
        """Returns:
            {accounts, active, usage, calibrations}: the stored accounts, the
            active account's email or None, usage() of every token row, and
            per account id the calibration set since its last reset.
        """
        listed = self.ledger.listed()
        return {
            "accounts": listed, "active": active(self.sessions), "usage": usage(rows_between(self.tokens, 0, now, 0), now),
            "calibrations": self.calibrations.current(listed, now),
        }

    def calibrate(self, account_id: str, body: bytes, now: float) -> dict:
        """Args:
            body: {share}: the percent of the limit the provider shows now.

        Returns:
            {share, at}: the stored calibration; an unknown id raises
            Missing, a share outside 0 to 100 ToolError.
        """
        if self.ledger.get(account_id) is None:
            raise Missing("no such account")
        return self.calibrations.put(account_id, valid_share(body), now)

    def save(self, body: bytes) -> dict:
        """Args:
            body: {account, id}: id "" adds the account, else it replaces
                the account of that id.
        """
        data = section(decode(body), "body", ("account", "id"))
        account = valid_account(data["account"])
        if data["id"] == "":
            return self.ledger.add(account)
        changed = self.ledger.change(self.known(data), account)
        if changed is None:
            raise Missing("no such account")
        return changed

    def drop(self, account_id: str) -> dict:
        if not self.ledger.remove(account_id):
            raise Missing("no such account")
        return {"removed": account_id}

    @staticmethod
    def known(data: dict) -> str:
        pattern, hint = FIELDS["id"]
        if not isinstance(data["id"], str) or not pattern.fullmatch(data["id"]):
            raise ToolError(f"id must be empty or {hint}")
        return data["id"]
