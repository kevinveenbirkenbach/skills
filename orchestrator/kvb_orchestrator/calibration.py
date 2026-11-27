from __future__ import annotations

import datetime
import json
import math
import threading
from pathlib import Path

from .fields import decode
from .records import read_json, write_atomic
from .settings import number_in, section

CALIBRATION = "account-calibration.json"
SHARE = (0.0, 100.0)


def last_reset(reset: dict, now: float) -> float:
    """Args:
        reset: {day, time}: day 0 for Sunday to 6 for Saturday, time HH:MM,
            both in the hub's local time.
        now: epoch seconds.

    Returns:
        The epoch seconds of the latest such moment at or before now; days
        step by the calendar, so a DST change keeps the wall clock time, as
        Resources.lastMoment counts in the page.
    """
    hours, minutes = map(int, reset["time"].split(":"))
    at = datetime.datetime.fromtimestamp(now).replace(hour=hours, minute=minutes, second=0, microsecond=0)
    at -= datetime.timedelta(days=(at.isoweekday() % 7 - reset["day"]) % 7)
    if at.timestamp() > now:
        at -= datetime.timedelta(days=7)
    return at.timestamp()


def valid_share(body: bytes) -> float:
    """Args:
        body: {share}: the percent of the limit the provider shows.

    Returns:
        The share; another key, a missing one or a share outside 0 to 100
        raises ToolError.
    """
    low, high = SHARE
    return number_in(section(decode(body), "body", ("share",))["share"], "share", low, high)


def well_formed(entry: object) -> bool:
    if not isinstance(entry, dict) or set(entry) != {"share", "at"}:
        return False
    share, at = entry["share"], entry["at"]
    numbers = all(isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value) for value in (share, at))
    return numbers and SHARE[0] <= share <= SHARE[1]


class Calibrations:
    def __init__(self, file: Path) -> None:
        self.file = file
        self.lock = threading.Lock()
        data = read_json(file)
        self.items: dict[str, dict] = {key: value for key, value in data.items() if well_formed(value)} if isinstance(data, dict) else {}

    def write(self, items: dict[str, dict]) -> None:
        write_atomic(self.file, json.dumps(items, indent=1, sort_keys=True).encode("utf-8"))
        self.items = items

    def put(self, account_id: str, share: float, now: float) -> dict:
        """Returns:
            {share, at}: the stored calibration, at the epoch second it was
            set; tokens of the hours from at on count on top of it.
        """
        entry = {"share": share, "at": int(now)}
        with self.lock:
            self.write({**self.items, account_id: entry})
        return dict(entry)

    def current(self, accounts: list[dict], now: float) -> dict[str, dict]:
        """Args:
            accounts: the stored accounts, each with its id and reset.
            now: epoch seconds.

        Returns:
            Each account's calibration that is not older than its last
            reset; a calibration of an account that is gone or reset since
            is dropped from the file.
        """
        resets = {account["id"]: last_reset(account["reset"], now) for account in accounts}
        with self.lock:
            fresh = {key: entry for key, entry in self.items.items() if key in resets and entry["at"] >= resets[key]}
            if fresh != self.items:
                self.write(fresh)
            return {key: dict(entry) for key, entry in fresh.items()}
