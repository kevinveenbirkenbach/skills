from __future__ import annotations

import copy
import json
import re
import threading
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

from .council import CLASSES
from .errors import ToolError
from .fields import FIELDS, NAME_LIMIT, expect
from .records import read_json, write_atomic

THEMES = ("sky", "light", "dark", "custom")
TONES = ("mayday", "review", "direct", "radio")
COLOR = re.compile(r"#[0-9a-f]{6}")
CLOCK = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]")
MIDNIGHT = "24:00"
STREAMS_LIMIT = 20
STREAM_URL = re.compile(r"https?://[A-Za-z0-9._~:/?#\[\]@!$&()*+,;=%-]{1,2040}")
HOSTNAME = re.compile(r"(?=.{1,253}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*")
VIA = re.compile(r"https://(?P<wild>\*\.)?(?P<host>[a-z0-9.-]{1,253})(?::(?P<port>[1-9][0-9]{0,4}))?")
VIA_LIMIT = 8
DEFAULT_PORTS = {"http": 80, "https": 443}
SETTINGS = {
    "latitude": 0.0,
    "longitude": 0.0,
    "theme": "sky",
    "colors": {"top": "#0b1020", "bottom": "#2b3a67", "accent": "#8fadff"},
    "music": {"on": False, "volume": 0.4},
    "sounds": {
        "mayday": {"on": True, "volume": 0.9},
        "review": {"on": True, "volume": 0.6},
        "direct": {"on": True, "volume": 0.5},
        "radio": {"on": False, "volume": 0.25},
    },
    "squelch": 1.0,
    "notify": True,
    "streams": [],
    "speech": {"on": False, "classes": ["mayday", "pan-pan", "security"], "muted": []},
    "space": {
        "graph": {"axis": "none", "yaw": 30.0, "pitch": 20.0, "zoom": 1.0, "pan_x": 0.0, "pan_y": 0.0},
        "sky": {"azimuth": 180.0, "altitude": 0.0, "fov": 180.0},
    },
}
SPACE_AXES = ("none", "time", "spawn")
SPACE_LIMITS = {
    "graph": {"yaw": (-180.0, 180.0), "pitch": (-90.0, 90.0), "zoom": (0.25, 4.0), "pan_x": (-2000.0, 2000.0), "pan_y": (-2000.0, 2000.0)},
    "sky": {"azimuth": (0.0, 360.0), "altitude": (-30.0, 85.0), "fov": (20.0, 240.0)},
}
MUTED_LIMIT = 200
LEGACY_CLASSES = {"direct": ("post", "call")}


def section(value: object, name: str, keys: tuple[str, ...]) -> dict:
    if not isinstance(value, dict):
        raise ToolError(f"{name} must be an object")
    try:
        expect(value, keys)
    except ToolError as error:
        raise ToolError(f"{name}: {error}") from None
    return value


def number_in(value: object, name: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not low <= value <= high:
        raise ToolError(f"{name} must be a number from {low} to {high}")
    return float(value)


def flag(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise ToolError(f"{name} must be true or false")
    return value


def color(value: object, name: str) -> str:
    if not isinstance(value, str) or not COLOR.fullmatch(value):
        raise ToolError(f"{name} must be a colour like #1a2b3c")
    return value


def stream_origin(url: object) -> str:
    if not isinstance(url, str) or not STREAM_URL.fullmatch(url):
        raise ToolError("a stream url must be an http or https URL without spaces or quotes")
    parts = urlsplit(url)
    try:
        port = parts.port
    except ValueError:
        raise ToolError("a stream url needs a valid port") from None
    host = parts.hostname or ""
    if parts.username is not None or parts.password is not None or not HOSTNAME.fullmatch(host):
        raise ToolError("a stream url needs a plain host name and no user info")
    return f"{parts.scheme}://{host}" if port in (None, DEFAULT_PORTS[parts.scheme]) else f"{parts.scheme}://{host}:{port}"


def via_origin(value: object, name: str) -> str:
    found = VIA.fullmatch(value) if isinstance(value, str) else None
    host = found is not None and HOSTNAME.fullmatch(found["host"]) is not None and (found["wild"] is None or "." in found["host"])
    port = found is not None and (found["port"] is None or (found["port"] != "443" and int(found["port"]) <= 65535))
    if not (host and port):
        raise ToolError(f"{name} must hold https origins like https://cdn.example or https://*.cdn.example, without the default port")
    return value


def via_list(value: object, name: str) -> list[str]:
    if not isinstance(value, list) or len(value) > VIA_LIMIT or len(set(map(str, value))) != len(value):
        raise ToolError(f"{name} must list at most {VIA_LIMIT} distinct origins")
    return [via_origin(origin, name) for origin in value]


def clock_minutes(value: object, name: str, end: bool) -> int:
    if end and value == MIDNIGHT:
        return 24 * 60
    if not isinstance(value, str) or not CLOCK.fullmatch(value):
        raise ToolError(f"{name} must be a time like 07:30")
    hours, minutes = value.split(":")
    return int(hours) * 60 + int(minutes)


def stream_fields(raw: object, name: str) -> dict:
    """Returns:
        The stream's fields with their names checked and its via valid; a
        missing via and None both mean not resolved yet.
    """
    entry = section({"via": None, **raw} if isinstance(raw, dict) else raw, name, ("name", "url", "from", "to", "days", "on", "via"))
    return {**entry, "via": None if entry["via"] is None else via_list(entry["via"], f"{name}.via")}


def stream_entry(raw: object, index: int) -> dict:
    name = f"streams[{index}]"
    entry = stream_fields(raw, name)
    label, days = entry["name"], entry["days"]
    if not isinstance(label, str) or not FIELDS["label"][0].fullmatch(label):
        raise ToolError(f"{name}.name must be one line of 1 to {NAME_LIMIT} characters")
    stream_origin(entry["url"])
    if clock_minutes(entry["from"], f"{name}.from", False) == clock_minutes(entry["to"], f"{name}.to", True):
        raise ToolError(f"{name} must end at another time than it starts")
    if not isinstance(days, list) or not days or len(set(map(str, days))) != len(days) or any(isinstance(day, bool) or not isinstance(day, int) or not 0 <= day <= 6 for day in days):
        raise ToolError(f"{name}.days must list distinct weekdays from 0 (Monday) to 6 (Sunday)")
    return {
        "name": label, "url": entry["url"], "from": entry["from"], "to": entry["to"], "days": sorted(days), "on": flag(entry["on"], f"{name}.on"),
        "via": entry["via"],
    }


def tone_setting(raw: object, kind_name: str) -> dict:
    entry = section(raw, f"sounds.{kind_name}", ("on", "volume"))
    return {"on": flag(entry["on"], f"sounds.{kind_name}.on"), "volume": number_in(entry["volume"], f"sounds.{kind_name}.volume", 0.0, 1.0)}


def distinct_texts(value: object, valid: Callable[[str], bool], limit: int) -> bool:
    if not isinstance(value, list) or len(value) > limit or not all(isinstance(item, str) and valid(item) for item in value):
        return False
    return len(set(value)) == len(value)


def speech_setting(raw: object) -> dict:
    entry = section(raw, "speech", ("on", "classes", "muted"))
    classes, muted = entry["classes"], entry["muted"]
    if not distinct_texts(classes, lambda name: name in CLASSES, len(CLASSES)):
        raise ToolError(f"speech.classes must list distinct classes of {', '.join(CLASSES)}")
    if "mayday" not in classes:
        raise ToolError("speech.classes must include mayday: a MAYDAY is never quieter than anything else")
    if not distinct_texts(muted, FIELDS["agent"][0].fullmatch, MUTED_LIMIT):
        raise ToolError(f"speech.muted must list at most {MUTED_LIMIT} distinct agent keys, each one line of 1 to 200 characters")
    return {"on": flag(entry["on"], "speech.on"), "classes": [name for name in CLASSES if name in classes], "muted": sorted(muted)}


def space_setting(raw: object) -> dict:
    entry = section(raw, "space", tuple(SETTINGS["space"]))
    graph = section(entry["graph"], "space.graph", tuple(SETTINGS["space"]["graph"]))
    sky = section(entry["sky"], "space.sky", tuple(SETTINGS["space"]["sky"]))
    if not isinstance(graph["axis"], str) or graph["axis"] not in SPACE_AXES:
        raise ToolError(f"space.graph.axis must be one of {', '.join(SPACE_AXES)}")
    views = {"graph": graph, "sky": sky}
    numbers = {view: {key: number_in(views[view][key], f"space.{view}.{key}", low, high) for key, (low, high) in limits.items()} for view, limits in SPACE_LIMITS.items()}
    return {"graph": {"axis": graph["axis"], **numbers["graph"]}, "sky": numbers["sky"]}


def valid_settings(raw: object) -> dict:
    data = section(raw, "settings", tuple(SETTINGS))
    colors = section(data["colors"], "colors", tuple(SETTINGS["colors"]))
    music = section(data["music"], "music", ("on", "volume"))
    sounds = section(data["sounds"], "sounds", TONES)
    if not isinstance(data["theme"], str) or data["theme"] not in THEMES:
        raise ToolError(f"theme must be one of {', '.join(THEMES)}")
    if not isinstance(data["streams"], list) or len(data["streams"]) > STREAMS_LIMIT:
        raise ToolError(f"streams must be a list of at most {STREAMS_LIMIT} entries")
    return {
        "latitude": number_in(data["latitude"], "latitude", -90.0, 90.0),
        "longitude": number_in(data["longitude"], "longitude", -180.0, 180.0),
        "theme": data["theme"],
        "colors": {key: color(colors[key], f"colors.{key}") for key in SETTINGS["colors"]},
        "music": {"on": flag(music["on"], "music.on"), "volume": number_in(music["volume"], "music.volume", 0.0, 1.0)},
        "sounds": {kind_name: tone_setting(sounds[kind_name], kind_name) for kind_name in TONES},
        "squelch": number_in(data["squelch"], "squelch", 0.0, 1.0),
        "notify": flag(data["notify"], "notify"),
        "streams": [stream_entry(entry, index) for index, entry in enumerate(data["streams"])],
        "speech": speech_setting(data["speech"]),
        "space": space_setting(data["space"]),
    }


def speech_renamed(stored: object) -> object:
    speech = stored.get("speech") if isinstance(stored, dict) else None
    classes = speech.get("classes") if isinstance(speech, dict) else None
    if not isinstance(classes, list) or not any(name in LEGACY_CLASSES for name in classes):
        return stored
    renamed = [new for name in classes for new in LEGACY_CLASSES.get(name, (name,))]
    return {**stored, "speech": {**speech, "classes": list(dict.fromkeys(renamed))}}


def migrated(stored: object) -> object:
    """Returns:
        The stored settings in the current shape: legacy speech classes
        renamed, and a stream saved before redirect resolution with via []:
        it may have been saved without the passkey, so the hub never dials
        it unsigned; re-adding it with the passkey resolves its redirects.
    """
    stored = speech_renamed(stored)
    streams = stored.get("streams") if isinstance(stored, dict) else None
    if not isinstance(streams, list):
        return stored
    return {**stored, "streams": [{**stream, "via": []} if isinstance(stream, dict) and "via" not in stream else stream for stream in streams]}


def station_origins(settings: dict) -> list[str]:
    return sorted({stream_origin(stream["url"]) for stream in settings["streams"]})


def media_origins(settings: dict) -> list[str]:
    return sorted({*station_origins(settings), *(origin for stream in settings["streams"] for origin in stream["via"] or ())})


class Settings:
    def __init__(self, file: Path) -> None:
        self.file = file
        self.lock = threading.Lock()
        stored = migrated(read_json(file))
        try:
            self.current = valid_settings({**SETTINGS, **stored} if isinstance(stored, dict) else stored)
        except ToolError:
            self.current = valid_settings(SETTINGS)

    def get(self) -> dict:
        with self.lock:
            return copy.deepcopy(self.current)

    def put(self, raw: object, expected: dict) -> dict:
        """Args:
            raw: the settings to save.
            expected: the settings the save was judged against; another save
                that landed meanwhile refuses this one.
        """
        settings = valid_settings(raw)
        with self.lock:
            if self.current != expected:
                raise ToolError("the settings changed while this save was checked; save again")
            write_atomic(self.file, json.dumps(settings, indent=1, sort_keys=True).encode("utf-8"))
            self.current = settings
            return copy.deepcopy(settings)
