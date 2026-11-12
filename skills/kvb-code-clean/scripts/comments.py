#!/usr/bin/env python3
"""Report every comment and docstring a change adds, for the agent to delete or keep.

Args:
    --repo: a directory inside the git work tree to scan.
    --staged: scan only the staged changes (git diff --cached) against the
        index version of each file. Without it: every change against HEAD,
        staged and unstaged, against the working tree file.
    --file: scan this whole file, every line counted as added; repeatable,
        relative to --repo or absolute. Untracked files are in no diff.
    --json: print the hits as a JSON list instead of tab-separated lines.

Output:
    One line per hit: file:line, language, kind (comment or docstring), the
    text, and `directive` for a tool directive (noqa, nocheck, shellcheck, ...).

Exit codes:
    0 no hits but directives, 1 hits, 2 usage error, git failure, or a file
    that cannot be read or, for Python, parsed.
"""

from __future__ import annotations

import argparse
import ast
import bisect
import io
import json
import re
import sys
import tokenize
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath

import defaults

EXTRA = {
    ".py": ("python", defaults.DQ + "|" + defaults.SQ, defaults.HASH),
    ".rb": ("ruby", defaults.DQ + "|" + defaults.SQ, defaults.HASH),
    ".php": ("php", defaults.DQ + "|" + defaults.SQ, defaults.HASH + "|" + defaults.SLASH),
    ".css": ("css", defaults.DQ + "|" + defaults.SQ, r"/\*.*?\*/"),
    ".scss": ("css", defaults.DQ + "|" + defaults.SQ, defaults.SLASH),
    ".html": ("html", "", r"<!--.*?-->"),
    ".xml": ("html", "", r"<!--.*?-->"),
    ".lua": ("lua", defaults.DQ + "|" + defaults.SQ, r"--\[\[.*?\]\]|--[^\n]*"),
}
DIRECTIVE = re.compile(
    r"\b(?:noqa|nocheck|nosec|type:\s*ignore|pragma|pylint|mypy|ruff|pyright|isort|fmt:\s*(?:on|off)"
    r"|coding[:=]|shellcheck|yamllint|hadolint|ansible-lint|markdownlint|eslint|stylelint|prettier"
    r"|rubocop|frozen_string_literal|phpcs|phpstan|psalm|jscpd|checkov|tflint)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Hit:
    file: str
    line: int
    language: str
    kind: str
    text: str
    directive: bool


def patterns(path: str) -> list[tuple[str, str, str]]:
    found = [(lang, *defaults.LANGS[lang][:2]) for lang in defaults.languages(path) if lang != "python"]
    stem = defaults.JINJA_SUFFIX.sub("", PurePosixPath(path).name)
    extra = EXTRA.get(PurePosixPath(stem).suffix)
    return found + ([extra] if extra else [])


def python_lang(path: str) -> bool:
    return defaults.languages(path) == ["python"]


def known(path: str) -> bool:
    return python_lang(path) or bool(patterns(path))


def touched(lines: set[int], wanted: set[int] | None) -> bool:
    return wanted is None or bool(lines & wanted)


def python_comments(path: str, tokens: list[tokenize.TokenInfo], wanted: set[int] | None) -> list[Hit]:
    return [
        Hit(path, token.start[0], "python", "comment", defaults.short(token.string), bool(DIRECTIVE.search(token.string)))
        for token in tokens
        if token.type == tokenize.COMMENT
        and not (token.start[0] == 1 and token.string.startswith("#!"))
        and touched({token.start[0]}, wanted)
    ]


def python_docstrings(path: str, tree: ast.AST, wanted: set[int] | None) -> list[Hit]:
    nodes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
    ]
    return [
        Hit(path, node.lineno, "python", "docstring", defaults.short(node.value.value), False)
        for node in nodes
        if touched(set(range(node.lineno, (node.end_lineno or node.lineno) + 1)), wanted)
    ]


def scan_python(path: str, text: str, wanted: set[int] | None) -> list[Hit]:
    try:
        tree = ast.parse(text, filename=path)
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (SyntaxError, ValueError, tokenize.TokenError) as error:
        raise defaults.ScanError(f"{path}: unparseable Python: {error}") from error
    return python_comments(path, tokens, wanted) + python_docstrings(path, tree, wanted)


def masked_pattern(langs: list[tuple[str, str, str]]) -> re.Pattern[str]:
    strings = "|".join(pattern for _, pattern, _ in langs if pattern)
    source = "(?P<comment>" + "|".join(pattern for _, _, pattern in langs) + ")"
    return re.compile(source + (f"|(?P<string>{strings})" if strings else ""), re.MULTILINE | re.DOTALL)


def scan_masked(path: str, text: str, langs: list[tuple[str, str, str]], wanted: set[int] | None) -> list[Hit]:
    _, spans = defaults.mask(text, masked_pattern(langs))
    starts = [0] + [newline.end() for newline in re.finditer("\n", text)]
    language = "+".join(lang for lang, _, _ in langs)
    hits = []
    for begin, end in spans:
        body = text[begin:end]
        if begin == 0 and body.startswith("#!"):
            continue
        first = bisect.bisect_right(starts, begin)
        lines = set(range(first, bisect.bisect_right(starts, max(begin, end - 1)) + 1))
        if touched(lines, wanted):
            hits.append(Hit(path, first, language, "comment", defaults.short(body), bool(DIRECTIVE.search(body))))
    return hits


def scan(path: str, text: str, wanted: set[int] | None) -> list[Hit]:
    if python_lang(path):
        return scan_python(path, text, wanted)
    langs = patterns(path)
    return scan_masked(path, text, langs, wanted) if langs else []


def changed_targets(root: Path, staged: bool) -> dict[str, tuple[str, set[int] | None]]:
    targets: dict[str, tuple[str, set[int] | None]] = {}
    for path, lines in defaults.added_lines(root, staged).items():
        if known(path):
            text = defaults.git(root, "cat-file", "blob", f":{path}") if staged else defaults.read(root / path)
            targets[path] = (text, lines)
    return targets


def file_targets(repo: Path, root: Path, files: list[str]) -> dict[str, tuple[str, set[int] | None]]:
    targets: dict[str, tuple[str, set[int] | None]] = {}
    for name in files:
        target = (repo / name).resolve()
        if not target.is_file():
            raise defaults.ScanError(f"{name}: no such file")
        shown = target.relative_to(root).as_posix() if target.is_relative_to(root) else str(target)
        if known(shown):
            targets[shown] = (defaults.read(target), None)
        else:
            print(f"comments: {shown}: no comment syntax known for this file type", file=sys.stderr)
    return targets


def collect(repo: Path, staged: bool, files: list[str]) -> list[Hit]:
    if not repo.is_dir():
        raise defaults.ScanError(f"{repo} is not a directory")
    root = Path(defaults.git(repo, "rev-parse", "--show-toplevel").strip()).resolve()
    targets = changed_targets(root, staged) | file_targets(repo, root, files)
    hits = [hit for path, (text, wanted) in targets.items() for hit in scan(path, text, wanted)]
    return sorted(hits, key=lambda hit: (hit.file, hit.line, hit.kind))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", required=True)
    parser.add_argument("--staged", action="store_true")
    parser.add_argument("--file", action="append", default=[])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        hits = collect(Path(args.repo), args.staged, args.file)
    except defaults.ScanError as error:
        print(f"comments: {error}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps([asdict(hit) for hit in hits], indent=1))
    else:
        for hit in hits:
            row = [f"{hit.file}:{hit.line}", hit.language, hit.kind, hit.text] + (["directive"] if hit.directive else [])
            print("\t".join(row))
    return 1 if any(not hit.directive for hit in hits) else 0


if __name__ == "__main__":
    sys.exit(main())
