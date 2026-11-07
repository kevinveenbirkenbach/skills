from __future__ import annotations

import re
from pathlib import Path

from markupsafe import Markup

from .errors import ToolError

SPRITE = Path("bootstrap-icons") / "bootstrap-icons.svg"
SYMBOL = re.compile(r'<symbol class="bi bi-[a-z0-9-]+" viewBox="0 0 16 16" id="([a-z0-9-]+)">(.*?)</symbol>', re.DOTALL)
NAME = re.compile(r'"#?bi-([a-z0-9]+(?:-[a-z0-9]+)*)"')
SOURCES = ("*.js", "*.j2")


def symbols(sprite: Path) -> dict[str, str]:
    return dict(SYMBOL.findall(sprite.read_text(encoding="utf-8")))


def used(templates: Path) -> list[str]:
    names: set[str] = set()
    for pattern in SOURCES:
        for path in sorted(templates.glob(pattern)):
            names.update(NAME.findall(path.read_text(encoding="utf-8")))
    return sorted(names)


def sheet(vendor: Path, templates: Path) -> Markup:
    """Args:
        vendor: the directory holding the vendored Bootstrap Icons sprite.
        templates: the page sources; every string literal "bi-<name>" or
            "#bi-<name>" in them names an icon the page shows.

    Returns:
        A hidden inline SVG holding exactly those symbols, each as
        bi-<name>, so the page draws them with <use href="#bi-<name>"> and
        loads nothing.
    """
    known = symbols(vendor / SPRITE)
    names = used(templates)
    missing = [name for name in names if name not in known]
    if missing:
        raise ToolError(f"icons missing from {vendor / SPRITE}: {', '.join(missing)}")
    body = "".join(f'<symbol id="bi-{name}" viewBox="0 0 16 16">{known[name]}</symbol>' for name in names)
    return Markup(f'<svg xmlns="http://www.w3.org/2000/svg" class="sprite" aria-hidden="true" focusable="false">{body}</svg>')
