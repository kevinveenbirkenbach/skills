from __future__ import annotations

import base64
import binascii
import csv
import datetime
import hashlib
import io
import json
import re

from .accounts import KEYS, valid_account
from .errors import Conflict, ToolError
from .fields import decode
from .ledger import Ledger
from .settings import section

FORMATS = {"csv": (",", "text/csv; charset=utf-8"), "tsv": ("\t", "text/tab-separated-values; charset=utf-8")}
SEPARATORS = (",", ";", "\t")
HEADER = ("provider", "email", "renewal_day", "renewal_time", "reset_day", "reset_time", "resubscribe", "autorenew", "limit", "note")
MAPPED = ("provider", "email", "renewal", "renewal_day", "renewal_time", "reset", "reset_day", "reset_time", "resubscribe", "autorenew", "limit", "note")
LABELS = {"provider": "Provider", "email": "Email", "renewal": "Renewal", "reset": "Next reset", "resubscribe": "Resubscribe", "autorenew": "Autorenew", "limit": "Weekly token limit", "note": "Note"}
MOMENTS = ("renewal", "reset")
REQUIRED = ("provider", "email", *MOMENTS)
SHORT_DAYS = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")
DAY_WORDS = (
    ("sun", "sunday", "so", "sonntag"),
    ("mon", "monday", "mo", "montag"),
    ("tue", "tuesday", "di", "dienstag"),
    ("wed", "wednesday", "mi", "mittwoch"),
    ("thu", "thursday", "do", "donnerstag"),
    ("fri", "friday", "fr", "freitag"),
    ("sat", "saturday", "sa", "samstag"),
)
WEEKDAYS = {word: index for index, words in enumerate(DAY_WORDS) for word in (*words, str(index))}
YES = ("yes", "true", "1", "ja")
NO = ("no", "false", "0", "nein", "")
CLOCK = re.compile(r"([0-9]{1,2}):([0-5][0-9])")
WHOLE = re.compile(r"[0-9]{1,16}")
INJECTION = ("=", "+", "-", "@", "\t", "\r")
GUARD = "'"
FILE_LIMIT = 256 << 10
ROW_LIMIT = 500
CHOICES = ("overwrite", "keep")
PREVIEW_KEYS = ("file", "separator", "mapping", "choices")
APPLY_KEYS = (*PREVIEW_KEYS, "digest")
DIGEST_LENGTH = 32


def guarded(value: str) -> str:
    return f"{GUARD}{value}" if value.startswith(INJECTION) else value


def unguarded(value: str) -> str:
    return value[1:] if value.startswith(GUARD) and value[1:].startswith(INJECTION) else value


def exported_row(account: dict) -> list[str]:
    limit = "" if account["limit"] is None else str(account["limit"])
    cells = [account["provider"], account["email"]]
    for name in MOMENTS:
        cells += [SHORT_DAYS[account[name]["day"]], account[name]["time"]]
    cells += [account["resubscribe"], "yes" if account["autorenew"] else "no", limit, account["note"]]
    return [guarded(cell) for cell in cells]


def export(accounts: list[dict], fmt: str) -> tuple[str, bytes]:
    """Args:
        accounts: the stored accounts in table order.
        fmt: csv or tsv; anything else raises ToolError.

    Returns:
        (content type, file bytes): HEADER and one line per account, every
        cell starting with a formula character prefixed with a quote.
    """
    if fmt not in FORMATS:
        raise ToolError(f"format must be one of {', '.join(FORMATS)}")
    separator, content_type = FORMATS[fmt]
    out = io.StringIO()
    writer = csv.writer(out, delimiter=separator, lineterminator="\r\n")
    writer.writerow(HEADER)
    writer.writerows(exported_row(account) for account in accounts)
    return content_type, out.getvalue().encode("utf-8")


def file_text(encoded: object) -> str:
    """Returns:
        The file's text without a leading byte order mark; a file that is no
        base64, over FILE_LIMIT or not UTF-8 raises ToolError.
    """
    if not isinstance(encoded, str):
        raise ToolError("file must be the file's bytes in base64")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise ToolError("file must be the file's bytes in base64") from None
    if len(data) > FILE_LIMIT:
        raise ToolError(f"the file is larger than {FILE_LIMIT >> 10} KiB")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ToolError("the file is not UTF-8 text") from None


def detected(text: str) -> str:
    first = text.split("\n", 1)[0]
    counts = {separator: first.count(separator) for separator in SEPARATORS}
    best = max(SEPARATORS, key=lambda separator: counts[separator])
    return best if counts[best] else ","


def separator_of(requested: object, text: str) -> str:
    if requested == "":
        return detected(text)
    if requested not in SEPARATORS:
        raise ToolError("separator must be empty, a comma, a semicolon or a tab")
    return requested


def table(text: str, separator: str) -> tuple[list[str], list[list[str]]]:
    """Returns:
        (header, rows): the first line and every non-empty line after it;
        more than ROW_LIMIT rows or broken quoting raises ToolError.
    """
    try:
        lines = [row for row in csv.reader(io.StringIO(text, newline=""), delimiter=separator) if any(cell.strip() for cell in row)]
    except csv.Error as error:
        raise ToolError(f"the file is no valid table: {error}") from None
    if not lines:
        raise ToolError("the file has no header line")
    if len(lines) - 1 > ROW_LIMIT:
        raise ToolError(f"the file has more than {ROW_LIMIT} rows")
    return [cell.strip() for cell in lines[0]], lines[1:]


def proposed(columns: list[str]) -> dict[str, int | None]:
    """Returns:
        Per field of MAPPED the first column whose header equals the field
        name or its table label, ignoring case, else None.
    """
    lowered = [column.lower() for column in columns]
    found: dict[str, int | None] = {}
    for name in MAPPED:
        names = {name, LABELS.get(name, name).lower()}
        found[name] = next((index for index, column in enumerate(lowered) if column in names), None)
    return found


def requested_mapping(raw: object, columns: list[str]) -> dict[str, int | None]:
    if raw is None:
        return proposed(columns)
    data = section(raw, "mapping", MAPPED)
    for name, index in data.items():
        if index is not None and (isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(columns)):
            raise ToolError(f"mapping.{name} must be a column number from 0 to {len(columns) - 1} or null")
    return data


def missing(mapping: dict[str, int | None]) -> list[str]:
    absent = [name for name in ("provider", "email") if mapping[name] is None]
    split = [name for name in MOMENTS if mapping[name] is None and None in (mapping[f"{name}_day"], mapping[f"{name}_time"])]
    return [name for name in REQUIRED if name in absent or name in split]


def cell(row: list[str], index: int | None) -> str | None:
    if index is None:
        return None
    return unguarded(row[index].strip()) if index < len(row) else ""


def weekday(value: str, column: str) -> int:
    day = WEEKDAYS.get(value.strip().lower())
    if day is None:
        raise ToolError(f"column {column}: no weekday from 0 (Sunday) to 6 or a day name")
    return day


def clock(value: str, column: str) -> str:
    match = CLOCK.fullmatch(value.strip())
    if match is None or int(match.group(1)) > 23:
        raise ToolError(f"column {column}: no time HH:MM")
    return f"{int(match.group(1)):02d}:{match.group(2)}"


def moment_of(row: list[str], mapping: dict[str, int | None], columns: list[str], name: str) -> dict:
    day_index, time_index = mapping[f"{name}_day"], mapping[f"{name}_time"]
    if day_index is not None and time_index is not None:
        return {"day": weekday(cell(row, day_index), columns[day_index]), "time": clock(cell(row, time_index), columns[time_index])}
    index = mapping[name]
    parts = cell(row, index).rsplit(None, 1)
    if len(parts) != 2:
        raise ToolError(f"column {columns[index]}: no weekday and time like Mon 09:00")
    return {"day": weekday(parts[0], columns[index]), "time": clock(parts[1], columns[index])}


def autorenew_of(value: str | None, column: str) -> bool:
    lowered = (value or "").lower()
    if lowered in YES:
        return True
    if lowered in NO:
        return False
    raise ToolError(f"column {column}: no yes/no, true/false, 1/0 or ja/nein")


def limit_of(value: str | None, column: str) -> int | None:
    if not value:
        return None
    if not WHOLE.fullmatch(value):
        raise ToolError(f"column {column}: no whole number of tokens")
    return int(value)


def column_name(columns: list[str], index: int | None) -> str:
    return "-" if index is None else columns[index]


def account_of(row: list[str], mapping: dict[str, int | None], columns: list[str]) -> dict:
    """Returns:
        The row as valid_account() accepts it, absent optional fields empty;
        a cell that cannot be read raises ToolError naming its column.
    """
    raw = {name: cell(row, mapping[name]) or "" for name in ("provider", "email", "resubscribe", "note")}
    raw["renewal"], raw["reset"] = (moment_of(row, mapping, columns, name) for name in MOMENTS)
    raw["autorenew"] = autorenew_of(cell(row, mapping["autorenew"]), column_name(columns, mapping["autorenew"]))
    raw["limit"] = limit_of(cell(row, mapping["limit"]), column_name(columns, mapping["limit"]))
    return valid_account(raw)


def parsed(rows: list[list[str]], mapping: dict[str, int | None], columns: list[str]) -> list[dict]:
    found = []
    for number, row in enumerate(rows, start=2):
        try:
            found.append({"line": number, "account": account_of(row, mapping, columns), "error": None})
        except ToolError as error:
            found.append({"line": number, "account": None, "error": str(error)})
    return found


def stored(account: dict) -> dict:
    return {name: account[name] for name in KEYS}


def digest(accounts: list[dict]) -> str:
    """Returns:
        The digest of the stored accounts with their ids, for apply to
        refuse a ledger that changed since the preview.
    """
    canonical = json.dumps([{**stored(account), "id": account["id"]} for account in accounts], sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:DIGEST_LENGTH]


def duplicates(found: list[dict]) -> None:
    lines: dict[str, list[int]] = {}
    for entry in found:
        if entry["account"] is not None:
            lines.setdefault(entry["account"]["email"].lower(), []).append(entry["line"])
    for entry in found:
        twins = lines.get(entry["account"]["email"].lower(), []) if entry["account"] is not None else []
        if len(twins) > 1:
            entry.update(account=None, error=f"email appears in lines {', '.join(map(str, twins))}")


def choices_of(raw: object) -> dict[str, str]:
    if not isinstance(raw, dict) or any(not isinstance(email, str) or choice not in CHOICES for email, choice in raw.items()):
        raise ToolError(f"choices must map an email to one of {', '.join(CHOICES)}")
    return {email.lower(): choice for email, choice in raw.items()}


def classified(entry: dict, known: dict[str, dict], choices: dict[str, str]) -> dict:
    if entry["error"] is not None:
        return {"line": entry["line"], "status": "error", "error": entry["error"]}
    account = entry["account"]
    email = account["email"].lower()
    existing = known.get(email)
    if existing is None:
        return {"line": entry["line"], "status": "new", "account": account}
    changed = [name for name in KEYS if stored(existing)[name] != account[name]]
    if not changed:
        return {"line": entry["line"], "status": "unchanged", "account": account, "id": existing["id"]}
    return {"line": entry["line"], "status": "update", "account": account, "id": existing["id"], "changed": changed, "choice": choices.get(email, "overwrite")}


def preview(body: dict, accounts: list[dict]) -> dict:
    """Args:
        body: {file, separator, mapping, choices}: file the bytes in base64,
            separator "" to detect it, mapping null for the proposal else
            a column number or null per field of MAPPED, choices overwrite
            or keep per conflicting email.
        accounts: the stored accounts.

    Returns:
        {separator, columns, mapping, missing, rows, errors, digest}: each
        row {line, status new|update|unchanged|error, account?, id?,
        changed?, choice?, error?}; rows stay empty while a required field
        is missing.
    """
    text = file_text(body["file"])
    separator = separator_of(body["separator"], text)
    columns, rows = table(text, separator)
    mapping = requested_mapping(body["mapping"], columns)
    choices = choices_of(body["choices"])
    absent = missing(mapping)
    found = [] if absent else parsed(rows, mapping, columns)
    duplicates(found)
    known = {account["email"].lower(): account for account in accounts}
    classes = [classified(entry, known, choices) for entry in found]
    errors = sum(entry["status"] == "error" for entry in classes)
    return {"separator": separator, "columns": columns, "mapping": mapping, "missing": absent, "rows": classes, "errors": errors, "digest": digest(accounts)}


def planned(result: dict) -> tuple[dict[str, dict], list[dict], dict]:
    """Returns:
        (changes by id, additions, counts): the overwrite updates, the new
        accounts and how many rows were added, updated, kept and unchanged;
        a missing field or an error row raises ToolError.
    """
    if result["missing"] or result["errors"]:
        raise ToolError("the import has missing fields or error rows; fix them in the preview first")
    rows = result["rows"]
    changes = {row["id"]: row["account"] for row in rows if row["status"] == "update" and row["choice"] == "overwrite"}
    additions = [row["account"] for row in rows if row["status"] == "new"]
    kept = sum(row["status"] == "update" and row["choice"] == "keep" for row in rows)
    unchanged = sum(row["status"] == "unchanged" for row in rows)
    return changes, additions, {"added": len(additions), "updated": len(changes), "kept": kept, "unchanged": unchanged}


class Transfer:
    def __init__(self, ledger: Ledger) -> None:
        self.ledger = ledger

    def exported(self, fmt: str, today: datetime.date) -> tuple[str, bytes, str]:
        """Returns:
            (content type, file bytes, file name accounts-<YYYY-MM-DD>.<fmt>).
        """
        content_type, data = export(self.ledger.listed(), fmt)
        return content_type, data, f"accounts-{today.isoformat()}.{fmt}"

    def preview(self, body: bytes) -> dict:
        return preview(section(decode(body), "body", PREVIEW_KEYS), self.ledger.listed())

    def apply(self, body: bytes) -> dict:
        """Args:
            body: the preview's body plus digest, the preview's ledger digest.

        Returns:
            The counts of planned(); the rows land in one ledger write, or
            none: an error row raises ToolError, a ledger changed since the
            preview raises Conflict.
        """
        data = section(decode(body), "body", APPLY_KEYS)
        accounts = self.ledger.listed()
        changes, additions, counts = planned(preview(data, accounts))

        def unchanged(current: list[dict]) -> None:
            if digest(current) != data["digest"]:
                raise Conflict({"reason": "the accounts changed since the preview", "digest": digest(current)})

        self.ledger.batch(unchanged, changes, additions)
        return counts
