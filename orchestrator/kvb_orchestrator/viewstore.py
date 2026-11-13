from __future__ import annotations

import copy
import json
import re
import threading
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
}
VIEW_PATH = re.compile(r"[A-Za-z]{1,32}(?:\.[A-Za-z]{1,32})?")
SERIES_ID = re.compile(r"[A-Za-z0-9:_./-]{1,200}")
PIN_KIND = re.compile(r"[A-Za-z0-9:_./-]{1,32}")
IDS_LIMIT = 500
TOKEN_MODES = ("interval", "accumulated")
OVERLAYS = ("fix", "break", "tokens", "velocity", "security", "score")
PINS_LIMIT = 64
SPAN = (1, 12)


def series_ids(value: object, name: str) -> list[str]:
    if not isinstance(value, list) or len(value) > IDS_LIMIT or not all(isinstance(item, str) and SERIES_ID.fullmatch(item) for item in value):
        raise ToolError(f"{name} must list at most {IDS_LIMIT} ids of 1 to 200 characters from A-Z, a-z, 0-9 and :_./-")
    if len(set(value)) != len(value):
        raise ToolError(f"{name} must not repeat an id")
    return list(value)


def span(value: object, name: str) -> int:
    low, high = SPAN
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ToolError(f"{name} must be a whole number from {low} to {high}")
    return value


def pin_entry(raw: object, index: int) -> dict:
    name = f"home.pins[{index}]"
    entry = section(raw, name, ("kind", "id", "w", "h"))
    if not isinstance(entry["kind"], str) or not PIN_KIND.fullmatch(entry["kind"]):
        raise ToolError(f"{name}.kind must be 1 to 32 characters from A-Z, a-z, 0-9 and :_./-")
    if not isinstance(entry["id"], str) or not SERIES_ID.fullmatch(entry["id"]):
        raise ToolError(f"{name}.id must be 1 to 200 characters from A-Z, a-z, 0-9 and :_./-")
    return {"kind": entry["kind"], "id": entry["id"], "w": span(entry["w"], f"{name}.w"), "h": span(entry["h"], f"{name}.h")}


def pins(value: object) -> list[dict]:
    if not isinstance(value, list) or len(value) > PINS_LIMIT:
        raise ToolError(f"home.pins must be a list of at most {PINS_LIMIT} pins")
    found = [pin_entry(raw, index) for index, raw in enumerate(value)]
    if len({(pin["kind"], pin["id"]) for pin in found}) != len(found):
        raise ToolError("home.pins must not pin the same kind and id twice")
    return found


def valid_view(raw: object) -> dict:
    """Args:
        raw: the whole view document as the page sent it.

    Returns:
        The document with every key of VIEW and nothing else; any other
        key, a missing one or a malformed value raises ToolError.
    """
    data = section(raw, "view", tuple(VIEW))
    resources = section(data["resources"], "resources", tuple(VIEW["resources"]))
    burn = section(data["burn"], "burn", tuple(VIEW["burn"]))
    home = section(data["home"], "home", tuple(VIEW["home"]))
    if not isinstance(resources["tokens"], str) or resources["tokens"] not in TOKEN_MODES:
        raise ToolError(f"resources.tokens must be one of {', '.join(TOKEN_MODES)}")
    overlays = burn["overlays"]
    if not isinstance(overlays, list) or not all(isinstance(item, str) and item in OVERLAYS for item in overlays) or len(set(overlays)) != len(overlays):
        raise ToolError(f"burn.overlays must list distinct metrics of {', '.join(OVERLAYS)}")
    return {
        "resources": {
            "hidden": series_ids(resources["hidden"], "resources.hidden"),
            "tokens": resources["tokens"],
            "combined": flag(resources["combined"], "resources.combined"),
            "combinedHidden": series_ids(resources["combinedHidden"], "resources.combinedHidden"),
        },
        "burn": {"overlays": list(overlays)},
        "home": {"pins": pins(home["pins"])},
    }


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
            self.current = valid_view(read_json(file))
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
