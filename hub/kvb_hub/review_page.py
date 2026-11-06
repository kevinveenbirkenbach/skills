from __future__ import annotations

import re
from html.parser import HTMLParser

DIGITS = re.compile(r"[0-9]+")
TEXTS = ("path", "old", "add", "del", "tag", "placeholder")


class ReviewPage(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.files: list[dict] = []
        self.section = ""
        self.details: list[str] = []
        self.spans: list[str] = []
        self.file: dict | None = None
        self.texts: dict[str, list[str]] = {}
        self.row = ""
        self.cells: list[str] | None = None
        self.cell: list[str] | None = None
        self.detail = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        classes = (values.get("class") or "").split()
        first = classes[0] if classes else ""
        if tag == "section":
            self.section = values.get("id") or ""
        elif tag == "details":
            if first == "file" and "commit" not in self.details:
                self.file = {"section": self.section, "status": "", "tags": [], "lines": []}
                self.texts = {name: [] for name in TEXTS}
                self.spans = []
            self.details.append(first)
        elif self.file is None:
            return
        elif tag == "span":
            self.spans.append(first)
            if first == "badge":
                self.file["status"] = values.get("title") or ""
        elif tag == "p" and first == "placeholder":
            self.detail = True
        elif tag == "tr":
            self.row, self.cells = first, []
        elif tag == "td" and self.cells is not None:
            self.cell = []

    def handle_data(self, data: str) -> None:
        if self.file is None:
            return
        if self.cell is not None:
            self.cell.append(data)
        elif self.detail:
            self.texts["placeholder"].append(data)
        elif self.spans and self.spans[-1] in self.texts:
            self.texts[self.spans[-1]].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "section":
            self.section = ""
        elif tag == "details" and self.details:
            if self.details.pop() == "file" and self.file is not None:
                self.files.append(self.finish(self.file))
                self.file = None
        elif self.file is None:
            return
        elif tag == "span" and self.spans:
            if self.spans.pop() == "tag":
                self.file["tags"].append("".join(self.texts["tag"]).strip())
                self.texts["tag"] = []
        elif tag == "p":
            self.detail = False
        elif tag == "td" and self.cell is not None and self.cells is not None:
            self.cells.append("".join(self.cell))
            self.cell = None
        elif tag == "tr" and self.cells is not None:
            self.file["lines"].append(diff_line(self.row, self.cells))
            self.cells = None

    def finish(self, file: dict) -> dict:
        text = {name: "".join(parts).strip() for name, parts in self.texts.items()}
        counts = {name: DIGITS.search(text[name]) for name in ("add", "del")}
        numbers = {name: int(match.group()) if match else 0 for name, match in counts.items()}
        return {**file, "path": text["path"], "old": text["old"], "added": numbers["add"], "removed": numbers["del"], "detail": text["placeholder"]}


def diff_line(kind_name: str, cells: list[str]) -> dict:
    if len(cells) >= 4:
        return {"kind": kind_name, "old": cells[0].strip(), "new": cells[1].strip(), "text": cells[3]}
    return {"kind": kind_name, "old": "", "new": "", "text": cells[-1].strip() if cells else ""}


def review_files(page: bytes) -> list[dict]:
    parser = ReviewPage()
    parser.feed(page.decode("utf-8", errors="replace"))
    parser.close()
    return parser.files
