from __future__ import annotations

import copy
import json
import re
import threading
from collections.abc import Callable
from pathlib import Path

from .errors import Conflict, ToolError
from .fields import decode
from .records import read_json, write_atomic
from .settings import flag, section

VIEW_LIMIT = 64 << 10
CHANGE_LIMIT = 2 * VIEW_LIMIT + (1 << 10)
VIEW = {
    "resources": {"hidden": [], "tokens": "interval", "combined": False, "combinedHidden": []},
    "burn": {"overlays": []},
    "home": {"pins": []},
    "kanban": {"hidden": []},
    "legend": {"views": {}, "tiles": {}},
    "approval": {"mode": "direct"},
}
APPROVAL_MODES = ("direct", "select")
LEGEND_PANELS = (
    "agents/orbit", "agents/chord", "agents/swimlane", "artifacts/orbit", "artifacts/chord", "artifacts/swimlane",
    "tasks/rasci", "tasks/gantt", "tasks/burn", "resources-hardware", "resources-tokens", "resources-combined",
)
PIN_KEY = re.compile(r"[A-Za-z0-9:_./-]{1,32}:[A-Za-z0-9:_./-]{1,200}")
VIEW_PATH = re.compile(r"[A-Za-z]{1,32}(?:\.[A-Za-z]{1,32})?")
SERIES_ID = re.compile(r"[A-Za-z0-9:_./-]{1,200}")
PIN_KIND = re.compile(r"[A-Za-z0-9:_./-]{1,32}")
IDS_LIMIT = 500
TOKEN_MODES = ("interval", "accumulated")
OVERLAYS = ("fix", "break", "tokens", "velocity", "security", "score")
KANBAN_LAYERS = ("line", "jobs")
PINS_LIMIT = 64
SPAN = (1, 12)
METRIC = "metric"
CHARTS = ("hardware", "tokens", "combined")
SHOWN_LIMIT = 100
FNV_PRIME = 0x01000193
FNV_SEEDS = (0x811C9DC5, 0x01000193)


def series_ids(value: object, name: str) -> list[str]:
    if not isinstance(value, list) or len(value) > IDS_LIMIT or not all(isinstance(item, str) and SERIES_ID.fullmatch(item) for item in value):
        raise ToolError(f"{name} must list at most {IDS_LIMIT} ids of 1 to 200 characters from A-Z, a-z, 0-9 and :_./-")
    if len(set(value)) != len(value):
        raise ToolError(f"{name} must not repeat an id")
    return list(value)


def members(value: object, name: str, what: str, allowed: tuple[str, ...]) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item in allowed for item in value) or len(set(value)) != len(value):
        raise ToolError(f"{name} must list distinct {what} of {', '.join(allowed)}")
    return list(value)


def span(value: object, name: str) -> int:
    low, high = SPAN
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ToolError(f"{name} must be a whole number from {low} to {high}")
    return value


def fnv(text: str, seed: int) -> str:
    value = seed
    for char in text:
        value = ((value ^ ord(char)) * FNV_PRIME) & 0xFFFFFFFF
    return f"{value:08x}"


def digest(text: str) -> str:
    """Args:
        text: any text, such as the series ids of a metric pin joined by
            newlines.

    Returns:
        The 16 hex characters Panels.digest gives for the same text: FNV-1a
        over its code points from FNV_SEEDS, one hash per seed.
    """
    return "".join(fnv(text, seed) for seed in FNV_SEEDS)


def metric_id(view: dict) -> str:
    """Args:
        view: a metric pin's view as metric_view returns it.

    Returns:
        The only id resourcePin gives a pin of that view: the chart, the
        token mode unless the chart is hardware, and all or the digest of the
        series switched on.
    """
    shown = "all" if view["shown"] is None else digest("\n".join(view["shown"]))
    return "/".join([view["chart"], shown] if view["chart"] == "hardware" else [view["chart"], view["tokens"], shown])


def metric_view(raw: object, name: str) -> dict:
    """Args:
        raw: the view a metric pin stores: the chart, its token mode and the
            series switched on when it was starred, null for all of them.
        name: where the view sits, for the error message.

    Returns:
        The view; a chart outside CHARTS, a hardware chart with a token mode
        other than interval, or a series list that is not a sorted list of
        at most SHOWN_LIMIT distinct series ids raises ToolError.
    """
    view = section(raw, name, ("chart", "tokens", "shown"))
    if not isinstance(view["chart"], str) or view["chart"] not in CHARTS:
        raise ToolError(f"{name}.chart must be one of {', '.join(CHARTS)}")
    if not isinstance(view["tokens"], str) or view["tokens"] not in TOKEN_MODES or (view["chart"] == "hardware" and view["tokens"] != "interval"):
        raise ToolError(f"{name}.tokens must be one of {', '.join(TOKEN_MODES)}, interval for the hardware chart")
    shown = view["shown"]
    if shown is not None and (len(series_ids(shown, f"{name}.shown")) > SHOWN_LIMIT or shown != sorted(shown)):
        raise ToolError(f"{name}.shown must be null or a sorted list of at most {SHOWN_LIMIT} series ids")
    return {"chart": view["chart"], "tokens": view["tokens"], "shown": None if shown is None else list(shown)}


def pin_entry(raw: object, index: int) -> dict:
    name = f"home.pins[{index}]"
    metric = isinstance(raw, dict) and raw.get("kind") == METRIC
    entry = section(raw, name, ("kind", "id", "w", "h", "view") if metric else ("kind", "id", "w", "h"))
    if not isinstance(entry["kind"], str) or not PIN_KIND.fullmatch(entry["kind"]):
        raise ToolError(f"{name}.kind must be 1 to 32 characters from A-Z, a-z, 0-9 and :_./-")
    if not isinstance(entry["id"], str) or not SERIES_ID.fullmatch(entry["id"]):
        raise ToolError(f"{name}.id must be 1 to 200 characters from A-Z, a-z, 0-9 and :_./-")
    pin = {"kind": entry["kind"], "id": entry["id"], "w": span(entry["w"], f"{name}.w"), "h": span(entry["h"], f"{name}.h")}
    if not metric:
        return pin
    view = metric_view(entry["view"], f"{name}.view")
    if entry["id"] != metric_id(view):
        raise ToolError(f"{name}.id must be {metric_id(view)}, the chart, token mode and series of its view")
    return {**pin, "view": view}


def pins(value: object) -> list[dict]:
    if not isinstance(value, list) or len(value) > PINS_LIMIT:
        raise ToolError(f"home.pins must be a list of at most {PINS_LIMIT} pins")
    found = [pin_entry(raw, index) for index, raw in enumerate(value)]
    if len({(pin["kind"], pin["id"]) for pin in found}) != len(found):
        raise ToolError("home.pins must not pin the same kind and id twice")
    return found


def legend_flags(value: object, name: str, known: Callable[[str], object], what: str) -> dict[str, bool]:
    """Args:
        value: a map of legend owners to whether their legend shows.
        name: where the map sits, for the error message.
        known: true for a key that may own a legend.
        what: the keys known accepts, for the error message.

    Returns:
        The map; a key known refuses or a value other than true or false
        raises ToolError.
    """
    if not isinstance(value, dict) or not all(isinstance(key, str) and known(key) for key in value):
        raise ToolError(f"{name} must map {what} to true or false")
    return {key: flag(shown, f"{name}.{key}") for key, shown in value.items()}


def valid_view(raw: object) -> dict:
    """Args:
        raw: the whole view document as the page sent it.

    Returns:
        The document with every key of VIEW and nothing else; any other
        key, a missing one or a malformed value raises ToolError. The
        legend state of a tile whose pin left Home is dropped.
    """
    data = section(raw, "view", tuple(VIEW))
    resources = section(data["resources"], "resources", tuple(VIEW["resources"]))
    burn = section(data["burn"], "burn", tuple(VIEW["burn"]))
    home = section(data["home"], "home", tuple(VIEW["home"]))
    kanban = section(data["kanban"], "kanban", tuple(VIEW["kanban"]))
    legend = section(data["legend"], "legend", tuple(VIEW["legend"]))
    approval = section(data["approval"], "approval", tuple(VIEW["approval"]))
    if not isinstance(resources["tokens"], str) or resources["tokens"] not in TOKEN_MODES:
        raise ToolError(f"resources.tokens must be one of {', '.join(TOKEN_MODES)}")
    if not isinstance(approval["mode"], str) or approval["mode"] not in APPROVAL_MODES:
        raise ToolError(f"approval.mode must be one of {', '.join(APPROVAL_MODES)}")
    pinned = pins(home["pins"])
    keys = {f"{pin['kind']}:{pin['id']}" for pin in pinned}
    tiles = legend_flags(legend["tiles"], "legend.tiles", PIN_KEY.fullmatch, "pin keys kind:id")
    return {
        "resources": {
            "hidden": series_ids(resources["hidden"], "resources.hidden"),
            "tokens": resources["tokens"],
            "combined": flag(resources["combined"], "resources.combined"),
            "combinedHidden": series_ids(resources["combinedHidden"], "resources.combinedHidden"),
        },
        "burn": {"overlays": members(burn["overlays"], "burn.overlays", "metrics", OVERLAYS)},
        "home": {"pins": pinned},
        "kanban": {"hidden": members(kanban["hidden"], "kanban.hidden", "layers", KANBAN_LAYERS)},
        "legend": {
            "views": legend_flags(legend["views"], "legend.views", LEGEND_PANELS.__contains__, f"panels of {', '.join(LEGEND_PANELS)}"),
            "tiles": {key: shown for key, shown in tiles.items() if key in keys},
        },
        "approval": {"mode": approval["mode"]},
    }


def upgraded(raw: object) -> object:
    """Returns:
        A stored document of an older hub with each VIEW section it lacks
        at its default; anything else as it is.
    """
    return {**copy.deepcopy(VIEW), **raw} if isinstance(raw, dict) else raw


def slot(view: dict, path: object) -> tuple[dict, str]:
    """Args:
        view: a document of the shape of VIEW.
        path: a section or section.key of VIEW, such as resources.hidden.

    Returns:
        The object holding the path's value and its key there.
    """
    if not isinstance(path, str) or not VIEW_PATH.fullmatch(path):
        raise ToolError("a view path must be a section or section.key, such as resources.hidden")
    keys = path.split(".")
    shape, node = VIEW, view
    for key in keys[:-1]:
        if key not in shape:
            raise ToolError(f"unknown view path {path}")
        shape, node = shape[key], node[key]
    if keys[-1] not in shape:
        raise ToolError(f"unknown view path {path}")
    return node, keys[-1]


def value_at(view: dict, path: object) -> object:
    node, key = slot(view, path)
    return node[key]


class ViewStore:
    def __init__(self, file: Path) -> None:
        self.file = file
        self.lock = threading.Lock()
        try:
            self.current = valid_view(upgraded(read_json(file)))
        except ToolError:
            self.current = copy.deepcopy(VIEW)

    def get(self) -> dict:
        with self.lock:
            return copy.deepcopy(self.current)

    def patch(self, body: bytes) -> dict:
        """Args:
            body: {"set": {path: value}, "expect": {path: value}} as JSON, at
                most CHANGE_LIMIT bytes, so that a document at VIEW_LIMIT can
                still send both values of a path; expect names the same paths
                with the values the page last saw stored there, and every
                other path keeps its stored value.

        Returns:
            The whole stored document. A path whose stored value differs
            from its expected one raises Conflict with {"view", "paths"}: the
            stored document and those paths. A refused change, or one that
            would grow the document past VIEW_LIMIT bytes, leaves the file
            and the served document as they were.
        """
        if len(body) > CHANGE_LIMIT:
            raise ToolError(f"a view change must not exceed {CHANGE_LIMIT} bytes")
        change = section(decode(body), "change", ("set", "expect"))
        values, expected = change["set"], change["expect"]
        if not isinstance(values, dict) or not values or not isinstance(expected, dict) or set(expected) != set(values):
            raise ToolError("set must map at least one view path to its new value and expect the same paths to their stored values")
        with self.lock:
            moved = [path for path in values if value_at(self.current, path) != expected[path]]
            if moved:
                raise Conflict({"view": copy.deepcopy(self.current), "paths": moved})
            draft = copy.deepcopy(self.current)
            for path, value in values.items():
                node, key = slot(draft, path)
                node[key] = value
            view = valid_view(draft)
            data = json.dumps(view, separators=(",", ":")).encode("utf-8")
            if len(data) > VIEW_LIMIT:
                raise ToolError(f"the view document must not exceed {VIEW_LIMIT} bytes")
            write_atomic(self.file, data)
            self.current = view
            return copy.deepcopy(view)
