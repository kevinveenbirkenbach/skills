from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta, timezone

from .fields import LINE

SPEECH_LIMIT = 1000
SPOKEN_TEXT = 500
SPOKEN_NAME = 60
SPOKEN_GROUP = 120
ALARM_WORDS = {"pan-pan": "PAN-PAN", "security": "say-cure-ee-tay"}
PROCEDURE = {"mayday": "MAYDAY", **ALARM_WORDS}
ADDRESSED = ("post", "call", "receipt")
CALLS = re.compile(r"^(?:(?:MAYDAY|PAN[ -]?PAN|SECURIT[EÉY])\b[\s:,.;!-]*)+", re.IGNORECASE)
HUB_MARK = re.compile(r"\[kvb-orchestrator msg [0-9a-f]{16}\]")
HUB_FILE = re.compile(r"\s+file: /\S*$")
SPOKEN_LINE = re.compile(LINE.format(SPEECH_LIMIT))
NATO = dict(zip("abcdef", ("Alfa", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot")))
ICAO = dict(zip("0123456789", ("Ze-ro", "One", "Two", "Tree", "Fow-er", "Fife", "Six", "Seven", "Eight", "Ni-ner")))
SPOKEN = {**NATO, **ICAO, ".": "Decimal"}
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")
MONTH_NUMBER = {name[:3].lower(): number for number, name in enumerate(MONTHS, 1)}
MONTH = "|".join(f"{name[:3]}(?:{name[3:]})?" for name in MONTHS)
SEGMENT = r"[\w.@+-]+"
PATH = re.compile(rf"(?<![\w.~/:@+-])(?:(?P<root>~?/){SEGMENT}(?:/{SEGMENT})*|{SEGMENT}(?:/{SEGMENT})+)/?(?<=[\w@+/-])")
EXTENSION = re.compile(r"\.[0-9A-Za-z]{1,5}$")
NAME_SPACES = str.maketrans({".": " dot ", "-": " ", "_": " "})
CLOCK = r"(?P<hour>[0-9]{1,2}):(?P<minute>[0-9]{2})(?::(?P<second>[0-9]{2}))?"
UTC_MARK = r"Z\b|\s*(?i:UTC|Zulu)\b(?![+-][0-9])"
DATE_TIME = re.compile(
    r"(?<![\w.:/+-])(?:(?P<year>[0-9]{4})-(?P<month>[0-9]{2})-(?P<day>[0-9]{2})"
    rf"|(?P<named_day>[0-9]{{1,2}})(?:st|nd|rd|th)?\s+(?P<name>(?i:{MONTH}))\s+(?P<named_year>[0-9]{{4}}))"
    rf"(?:(?:T|,?\s+(?:at\s+)?){CLOCK}(?:\.[0-9]+)?(?P<zone>{UTC_MARK}|[+-][0-9]{{2}}(?::?[0-9]{{2}})?)?)?(?![\w:])"
)
TIME = re.compile(rf"(?<![\w.:])(?:{CLOCK}(?P<zone>{UTC_MARK})?(?![0-9:])|(?P<packed>[0-9]{{4}})Z\b)")
SPELLED = re.compile(r"\b(?=[0-9a-f]*[a-f])(?=[0-9a-f]*[0-9])[0-9a-f]{7,}\b|(?:\bv)?[0-9]+(?:\.[0-9]+)+|[0-9]", re.IGNORECASE)


def pronounced(text: str) -> str:
    """Args:
        text: a radio text as displayed.

    Returns:
        The text as the radio speaks it, in this order: paths as "file" or
        "folder" with their name and parent, date-times as DTG converted to
        Zulu, times as four digits with Zulu for UTC, a dot between digits
        as Decimal, each hex run of 7 or more characters holding a letter
        and a digit in the NATO alphabet and every other digit on its own in
        ICAO words.
    """
    for pattern, speak in ((PATH, path_words), (DATE_TIME, date_words), (TIME, time_words), (SPELLED, spelled)):
        text = pattern.sub(speak, text)
    return text


def padded(found: re.Match, words: str) -> str:
    start, end = found.span()
    before = " " if start and found.string[start - 1].isalnum() else ""
    after = " " if end < len(found.string) and found.string[end].isalnum() else ""
    return before + words + after


def digits(text: str) -> str:
    return " ".join(ICAO[char] for char in text)


def spelled(found: re.Match) -> str:
    return padded(found, " ".join(SPOKEN[char] for char in found[0].lower().removeprefix("v")))


def segment_words(segment: str) -> str:
    return " ".join(SPELLED.sub(spelled, segment.translate(NAME_SPACES)).split())


def path_words(found: re.Match) -> str:
    root = found["root"] or ""
    chain = found[0].removeprefix(root).rstrip("/").split("/")
    typed = EXTENSION.search(chain[-1])
    if not root and not typed:
        return found[0]
    names = [segment_words(segment) for segment in chain]
    if root == "/" and chain[0] == "tmp":
        names[0] = "temp"
    if root == "~/":
        names.insert(0, "home")
    kind = "file" if typed and not found[0].endswith("/") else "folder"
    return padded(found, f"{kind} {names[-1]}" + (f" in {names[-2]}" if len(names) > 1 else ""))


def date_words(found: re.Match) -> str:
    if found["year"]:
        year, month, day = int(found["year"]), int(found["month"]), int(found["day"])
    else:
        year, month, day = int(found["named_year"]), MONTH_NUMBER[found["name"][:3].lower()], int(found["named_day"])
    zone = (found["zone"] or "").strip()
    try:
        moment = datetime(year, month, day, int(found["hour"] or 0), int(found["minute"] or 0))
        if zone[:1] in ("+", "-"):
            shift = timedelta(hours=int(zone[1:3]), minutes=int(zone[3:].lstrip(":") or 0))
            moment = moment.replace(tzinfo=timezone(-shift if zone[0] == "-" else shift)).astimezone(UTC)
    except (ValueError, OverflowError):
        return found[0]
    clock = digits(f"{moment:%d%H%M}" if found["hour"] else f"{moment:%d}")
    return padded(found, f"{clock}{' Zulu' if zone else ''} {MONTHS[moment.month - 1]} {digits(f'{moment.year % 100:02}')}")


def time_words(found: re.Match) -> str:
    clock = found["packed"] or found["hour"].zfill(2) + found["minute"] + (found["second"] or "")
    if int(clock[:2]) > 23 or int(clock[2:4]) > 59 or int(clock[4:] or 0) > 59:
        return found[0]
    return padded(found, digits(clock) + (" Zulu" if found["packed"] or found["zone"] else ""))


def clip(text: str, limit: int) -> str:
    words = " ".join(pronounced(text).split())
    if len(words) <= limit:
        return words
    return words[:limit].rsplit(" ", 1)[0] or words[:limit]


def spoken_text(cls: str, text: str) -> str:
    body = HUB_MARK.sub("", text)
    if body != text:
        body = HUB_FILE.sub("", body)
    if cls in PROCEDURE:
        body = CALLS.sub("", body.strip())
    body = clip(body, SPOKEN_TEXT)
    return "" if body == "-" else body


def procedure(cls: str) -> str:
    """Args:
        cls: the radio class of the row.

    Returns:
        The procedure word of a MAYDAY, PAN-PAN or SÉCURITÉ row spoken three
        times, the same line for every row of the class; "" for any other
        class.
    """
    word = PROCEDURE.get(cls)
    return f"{word} {word} {word}" if word else ""


PROCEDURE_LINES = frozenset(procedure(cls) for cls in PROCEDURE)


def phrase_parts(cls: str, sender: str, called: list[str], text: str) -> tuple[str, str]:
    """Args:
        cls: the radio class of the row, one of council.CLASSES or receipt.
        sender: the sender's name valid at the row's time.
        called: the names of the called stations valid at the row's time.
        text: the radio text.

    Returns:
        (word, rest): the procedure word line of the row, "" for a routine
        class, and the rest of the row in maritime radio phraseology (SMCP
        style).
    """
    station = clip(sender, SPOKEN_NAME) or "unknown station"
    if cls == "mayday":
        head, end = f"this is {station} {station} {station}", "over"
    elif cls in ALARM_WORDS:
        head, end = f"all stations, this is {station}", "over"
    elif cls in ADDRESSED and called:
        group = clip(" and ".join(clip(name, SPOKEN_NAME) for name in called), SPOKEN_GROUP)
        head, end = f"{group}, {group}, this is {station}", "over"
    else:
        head, end = f"all stations, this is {station}", "out"
    return procedure(cls), joined((head, spoken_text(cls, text), end))


def joined(parts: tuple[str, ...]) -> str:
    return ", ".join(part for part in parts if part)


def phrase(cls: str, sender: str, called: list[str], text: str) -> str:
    """Args:
        cls: the radio class of the row, one of council.CLASSES or receipt.
        sender: the sender's name valid at the row's time.
        called: the names of the called stations valid at the row's time.
        text: the radio text.

    Returns:
        The row in maritime radio phraseology (SMCP style), its procedure
        word line first, one line of at most SPEECH_LIMIT characters.
    """
    return joined(phrase_parts(cls, sender, called, text))
