from __future__ import annotations

import copy
import json
import re
import threading
from pathlib import Path
from urllib.parse import urlsplit

from .errors import ToolError
from .fields import FIELDS, NAME_LIMIT, expect
from .records import read_json, write_atomic

THEMES = ("sky", "light", "dark", "custom")
ESTIMATIONS = ("none", "points")
TRENDS = ("off", "regression", "velocity")
TREND_DAYS = (1, 365)
THRESHOLDS = tuple(range(30, 91, 10))
RADIO_MOVED = ("sounds", "squelch")
SPEECH_MOVED = ("on", "classes", "muted")
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
    "notify": True,
    "streams": [],
    "speech": {"threshold": 50},
    "space": {
        "graph": {"axis": "none", "yaw": 30.0, "pitch": 20.0, "zoom": 1.0, "pan_x": 0.0, "pan_y": 0.0},
        "sky": {"azimuth": 180.0, "altitude": 0.0, "fov": 180.0},
    },
    "estimation": "none",
    "trend": {"mode": "off", "days": 7},
    "bubbles": False,
}
SPACE_AXES = ("none", "time", "spawn")
SPACE_LIMITS = {
    "graph": {"yaw": (-180.0, 180.0), "pitch": (-90.0, 90.0), "zoom": (0.25, 4.0), "pan_x": (-2000.0, 2000.0), "pan_y": (-2000.0, 2000.0)},
    "sky": {"azimuth": (0.0, 360.0), "altitude": (-30.0, 85.0), "fov": (20.0, 240.0)},
}


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


def speech_setting(raw: object) -> dict:
    entry = section(raw, "speech", tuple(SETTINGS["speech"]))
    threshold = entry["threshold"]
    if isinstance(threshold, bool) or not isinstance(threshold, int) or threshold not in THRESHOLDS:
        raise ToolError(f"speech.threshold must be one of {', '.join(map(str, THRESHOLDS))} percent")
    return {"threshold": threshold}


def space_setting(raw: object) -> dict:
    entry = section(raw, "space", tuple(SETTINGS["space"]))
    graph = section(entry["graph"], "space.graph", tuple(SETTINGS["space"]["graph"]))
    sky = section(entry["sky"], "space.sky", tuple(SETTINGS["space"]["sky"]))
    if not isinstance(graph["axis"], str) or graph["axis"] not in SPACE_AXES:
        raise ToolError(f"space.graph.axis must be one of {', '.join(SPACE_AXES)}")
    views = {"graph": graph, "sky": sky}
    numbers = {view: {key: number_in(views[view][key], f"space.{view}.{key}", low, high) for key, (low, high) in limits.items()} for view, limits in SPACE_LIMITS.items()}
    return {"graph": {"axis": graph["axis"], **numbers["graph"]}, "sky": numbers["sky"]}


def trend_setting(raw: object) -> dict:
    entry = section(raw, "trend", tuple(SETTINGS["trend"]))
    low, high = TREND_DAYS
    if not isinstance(entry["mode"], str) or entry["mode"] not in TRENDS:
        raise ToolError(f"trend.mode must be one of {', '.join(TRENDS)}")
    if isinstance(entry["days"], bool) or not isinstance(entry["days"], int) or not low <= entry["days"] <= high:
        raise ToolError(f"trend.days must be a whole number from {low} to {high}")
    return {"mode": entry["mode"], "days": entry["days"]}


def valid_settings(raw: object) -> dict:
    data = section(raw, "settings", tuple(SETTINGS))
    colors = section(data["colors"], "colors", tuple(SETTINGS["colors"]))
    music = section(data["music"], "music", ("on", "volume"))
    if not isinstance(data["theme"], str) or data["theme"] not in THEMES:
        raise ToolError(f"theme must be one of {', '.join(THEMES)}")
    if not isinstance(data["streams"], list) or len(data["streams"]) > STREAMS_LIMIT:
        raise ToolError(f"streams must be a list of at most {STREAMS_LIMIT} entries")
    if not isinstance(data["estimation"], str) or data["estimation"] not in ESTIMATIONS:
        raise ToolError(f"estimation must be one of {', '.join(ESTIMATIONS)}")
    return {
        "latitude": number_in(data["latitude"], "latitude", -90.0, 90.0),
        "longitude": number_in(data["longitude"], "longitude", -180.0, 180.0),
        "theme": data["theme"],
        "colors": {key: color(colors[key], f"colors.{key}") for key in SETTINGS["colors"]},
        "music": {"on": flag(music["on"], "music.on"), "volume": number_in(music["volume"], "music.volume", 0.0, 1.0)},
        "notify": flag(data["notify"], "notify"),
        "streams": [stream_entry(entry, index) for index, entry in enumerate(data["streams"])],
        "speech": speech_setting(data["speech"]),
        "space": space_setting(data["space"]),
        "estimation": data["estimation"],
        "trend": trend_setting(data["trend"]),
        "bubbles": flag(data["bubbles"], "bubbles"),
    }


def radio_moved(stored: object) -> object:
    """Returns:
        The stored settings without the tones, the squelch and the read-aloud
        filters, which each browser keeps for itself since requirement 004;
        a speech section left empty is dropped so the default threshold
        fills it.
    """
    if not isinstance(stored, dict):
        return stored
    kept = {key: value for key, value in stored.items() if key not in RADIO_MOVED}
    speech = stored.get("speech")
    if not isinstance(speech, dict):
        return kept
    rest = {key: value for key, value in speech.items() if key not in SPEECH_MOVED}
    others = {key: value for key, value in kept.items() if key != "speech"}
    return {**others, "speech": rest} if rest else others


def migrated(stored: object) -> object:
    """Returns:
        The stored settings in the current shape: the radio set moved to the
        browser, and a stream saved before redirect resolution with via []:
        it may have been saved without the passkey, so the hub never dials
        it unsigned; re-adding it with the passkey resolves its redirects.
    """
    stored = radio_moved(stored)
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
