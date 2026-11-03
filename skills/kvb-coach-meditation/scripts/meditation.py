#!/usr/bin/env python3
"""Keep the kvb-coach-meditation settings and write the session page.

Args:
    --state: path of the settings JSON file.
    set <key>=<value> ...: change settings; every value is validated.
    show: print the settings.
    session --page <meditation.html> --out <file>: write the page with the
        settings embedded and print its path; fails while a setting is missing.

Exit codes:
    0 done, 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PLACEHOLDER = "const SETTINGS = null;"
RANGES = {
    "minutes": (int, 1, 30),
    "beat": (float, 8.0, 13.0),
    "base": (float, 100.0, 400.0),
    "volume": (float, 0.05, 1.0),
}
CHOICES = {
    "mode": ("binaural", "isochronic"),
    "palette": ("aurora", "ocean", "ember", "forest"),
    "breathing": ("box", "478", "none"),
}
KEYS = (*RANGES, *CHOICES)


def fail(message: str) -> None:
    print(f"meditation: {message}", file=sys.stderr)
    sys.exit(2)


def parse(pair: str) -> tuple[str, int | float | str]:
    key, sep, raw = pair.partition("=")
    if not sep or key not in KEYS:
        fail(f"{pair}: expected <key>=<value> with key in {', '.join(KEYS)}")
    if key in CHOICES:
        if raw not in CHOICES[key]:
            fail(f"{key} must be one of {', '.join(CHOICES[key])}")
        return key, raw
    kind, low, high = RANGES[key]
    try:
        value = kind(raw)
    except ValueError:
        fail(f"{key} must be a number")
    if not low <= value <= high:
        fail(f"{key} must lie between {low} and {high}")
    return key, value


def load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except ValueError:
        fail(f"{path} is not valid JSON")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--state", required=True)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("set").add_argument("pairs", nargs="+")
    sub.add_parser("show")
    p = sub.add_parser("session")
    p.add_argument("--page", required=True)
    p.add_argument("--out", required=True)
    args = parser.parse_args()

    path = Path(args.state)
    settings = load(path)
    if args.cmd == "set":
        settings.update(parse(pair) for pair in args.pairs)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(settings, indent=1, sort_keys=True), encoding="utf-8")
        tmp.replace(path)
    if args.cmd in ("set", "show"):
        for key in KEYS:
            print(f"{key}={settings.get(key, '-')}")
        return 0
    missing = [key for key in KEYS if key not in settings]
    if missing:
        fail(f"missing settings: {', '.join(missing)}")
    page = Path(args.page)
    if not page.is_file():
        fail(f"{page} does not exist")
    template = page.read_text(encoding="utf-8")
    if template.count(PLACEHOLDER) != 1:
        fail(f"{page} lacks the line {PLACEHOLDER}")
    embedded = json.dumps({key: settings[key] for key in KEYS})
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(template.replace(PLACEHOLDER, f"const SETTINGS = {embedded};"), encoding="utf-8")
    print(out.resolve())
    return 0


if __name__ == "__main__":
    sys.exit(main())
