from __future__ import annotations

import re

from .fields import LINE

SPEECH_LIMIT = 1000
SPOKEN_TEXT = 500
SPOKEN_NAME = 60
SPOKEN_GROUP = 120
ALARM_WORDS = {"pan-pan": "PAN-PAN", "security": "say-cure-ee-tay"}
ADDRESSED = ("post", "call", "receipt")
CALLS = re.compile(r"^(?:(?:MAYDAY|PAN[ -]?PAN|SECURIT[EÉY])\b[\s:,.;!-]*)+", re.IGNORECASE)
HUB_MARK = re.compile(r"\[kvb-orchestrator msg [0-9a-f]{16}\]")
HUB_FILE = re.compile(r"\s+file: /\S*$")
SPOKEN_LINE = re.compile(LINE.format(SPEECH_LIMIT))
HASH = re.compile(r"\b(?=[0-9a-f]*[a-f])(?=[0-9a-f]*[0-9])[0-9a-f]{7,}\b|[0-9]", re.IGNORECASE)
NATO = dict(zip("abcdef", ("alfa", "bravo", "charlie", "delta", "echo", "foxtrot")))
ICAO = dict(zip("0123456789", ("zero", "one", "two", "tree", "four", "fife", "six", "seven", "eight", "niner")))


def pronounced(text: str) -> str:
    """Args:
        text: a radio text as displayed.

    Returns:
        The text with each hex run of 7 or more characters holding a letter
        and a digit spelled in the NATO alphabet and every other digit
        spoken on its own in ICAO pronunciation.
    """
    return HASH.sub(spelled, text)


def spelled(found: re.Match) -> str:
    start, end = found.span()
    before = " " if start and found.string[start - 1].isalnum() else ""
    after = " " if end < len(found.string) and found.string[end].isalnum() else ""
    return before + " ".join(NATO.get(char) or ICAO[char] for char in found[0].lower()) + after


def clip(text: str, limit: int) -> str:
    words = " ".join(pronounced(text).split())
    if len(words) <= limit:
        return words
    return words[:limit].rsplit(" ", 1)[0] or words[:limit]


def spoken_text(cls: str, text: str) -> str:
    body = HUB_MARK.sub("", text)
    if body != text:
        body = HUB_FILE.sub("", body)
    if cls in ("mayday", *ALARM_WORDS):
        body = CALLS.sub("", body.strip())
    body = clip(body, SPOKEN_TEXT)
    return "" if body == "-" else body


def phrase(cls: str, sender: str, called: list[str], text: str) -> str:
    """Args:
        cls: the radio class of the row, one of council.CLASSES or receipt.
        sender: the sender's name valid at the row's time.
        called: the names of the called stations valid at the row's time.
        text: the radio text.

    Returns:
        The row in maritime radio phraseology (SMCP style), one line of at
        most SPEECH_LIMIT characters.
    """
    station = clip(sender, SPOKEN_NAME) or "unknown station"
    if cls == "mayday":
        head, end = f"MAYDAY MAYDAY MAYDAY, this is {station} {station} {station}", "over"
    elif cls in ALARM_WORDS:
        word = ALARM_WORDS[cls]
        head, end = f"{word} {word} {word}, all stations, this is {station}", "over"
    elif cls in ADDRESSED and called:
        group = clip(" and ".join(clip(name, SPOKEN_NAME) for name in called), SPOKEN_GROUP)
        head, end = f"{group}, {group}, this is {station}", "over"
    else:
        head, end = f"all stations, this is {station}", "out"
    return ", ".join(part for part in (head, spoken_text(cls, text), end) if part)
