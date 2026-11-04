#!/usr/bin/env python3
"""Report the default values a change adds, each with the explicit form to use instead.

Python is parsed with ast; a node counts when it starts on an added line.
Every other language is matched by regular expressions over the whole file
with its comments masked (and its strings, where they cannot hold a default),
and a match counts when it starts on an added line. The file name picks the
language; a .j2 or .jinja suffix adds the Jinja rules to the inner type.

Args:
    --repo: a directory inside the git work tree to scan.
    --staged: scan only the staged changes (git diff --cached) against the
        index version of each file. Without it: every change against HEAD,
        staged and unstaged, against the working tree file.
    --file: scan this whole file, every line counted as added; repeatable,
        relative to --repo or absolute. Untracked files are in no diff.
    --json: print the hits as a JSON list instead of tab-separated lines.

Output:
    One line per hit: file:line, language, construct, instead, and a fifth
    column when a mark applies: `candidate` for `??`, `||` and Python `or`,
    which are often logic rather than a default, and `justified?` when a
    comment sits on the line or directly above it, for the agent to judge.

Permitted, never reported: None, null, nil, undefined, false and the empty
string, which denote absence, and empty containers ([], {}, (), list(),
Vec::new() and the like), which denote it as "" does. A Python parameter
defaulting to a list, dict or set is still reported: every call shares that
one mutable object.

Not detected: Go zero values (no syntax marks them), Helm values.yaml (every
key there is a default by design), Docker ENV placeholders and Java overloads
standing in for optional parameters (both need judgement), and `||` with a
non-literal right operand (mostly logic).

Exit codes:
    0 no hits, 1 hits, 2 usage error, git failure, or a file that cannot be
    read or, for Python, parsed.
"""

from __future__ import annotations

import argparse
import ast
import bisect
import io
import json
import re
import subprocess
import sys
import tokenize
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath

WIDTH = 80
WINDOW = 200
FREE = frozenset(
    {
        "", "''", '""', "``", "false", "none", "null", "nil", "undefined", "[]", "{}", "()",
        "string.empty", "string::new()", "vec::new()", "vec![]",
    }
)
EMPTY_CALLS = frozenset({"list", "dict", "set", "tuple", "frozenset", "str", "bytes"})
MUTABLE_CALLS = frozenset({"list", "dict", "set"})
LITERALS = (ast.Constant, ast.List, ast.Tuple, ast.Set, ast.Dict, ast.JoinedStr)
QUOTES = "'\"`"
OPENERS = "([{"
CLOSERS = ")]}"
KEYWORDS = frozenset(
    {
        "if", "for", "foreach", "while", "switch", "catch", "using", "lock", "fixed", "return",
        "typeof", "sizeof", "nameof", "await", "new", "do", "else", "with", "void", "delete", "in",
        "of", "yield", "case", "throw", "super", "base", "this", "default", "when", "checked",
        "unchecked",
    }
)
NULL_CHECK = {
    "js": "`if (a === undefined) throw`",
    "ts": "`if (a === undefined) throw`",
    "csharp": "an explicit null check that throws",
}

HASH = r"(?:^|(?<=[ \t]))#[^\n]*"
LINE_HASH = r"^[ \t]*#[^\n]*"
SLASH = r"//[^\n]*|/\*.*?\*/"
JINJA_COMMENT = r"\{#.*?#\}"
SQL_COMMENT = r"--[^\n]*|/\*.*?\*/"
DQ = r'"(?:\\.|[^"\\\n])*"'
SQ = r"'(?:\\.|[^'\\\n])*'"
BACKTICK = r"`(?:\\.|[^`\\])*`"
CHAR = r"'(?:\\.|[^'\\\n])'"
SQL_STRING = r"'(?:''|[^'])*'"

HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
JINJA_SUFFIX = re.compile(r"\.(?:j2|jinja2?)$")
DOCKERFILE = re.compile(
    r"^(?:Dockerfile|Containerfile)(?:\..+)?$|\.(?:dockerfile|containerfile)$", re.IGNORECASE
)
COMPOSE = re.compile(r"^(?:docker-)?compose(?:[.-][\w.-]+)?\.ya?ml$")
MAKEFILES = frozenset({"Makefile", "makefile", "GNUmakefile"})
SUFFIXES = {
    ".py": "python",
    ".sh": "shell", ".bash": "shell", ".zsh": "shell",
    ".mk": "make", ".make": "make",
    ".yml": "yaml", ".yaml": "yaml",
    ".js": "js", ".jsx": "js", ".mjs": "js", ".cjs": "js",
    ".ts": "ts", ".tsx": "ts", ".mts": "ts", ".cts": "ts",
    ".cs": "csharp",
    ".java": "java",
    ".rs": "rust",
    ".sql": "sql",
    ".tf": "terraform",
}

SHELL_DEFAULT = re.compile(r"\$\{([A-Za-z_]\w*|\d+)(:?[-=])([^}\n]*)\}")
MAKE_DEFAULT = re.compile(
    r"^[ \t]*(?:override[ \t]+|export[ \t]+)?([A-Za-z_][\w.-]*)[ \t]*\?=[ \t]*([^\n]*)$", re.MULTILINE
)
JINJA_DEFAULT = re.compile(r"\|\s*(?:default|d)\s*\(")
ENV_LOOKUP = re.compile(r"lookup\(\s*['\"]env['\"]")
FUNCTION_BEFORE = re.compile(r"\bfunction\b[\s*]*[\w$]*\s*(?:<[^<>()]*>)?\s*\Z")
METHOD_BEFORE = re.compile(r"(?<![\w$.])([\w$]+)\s*(?:<[^<>()]*>)?\s*\Z")
METHOD_AFTER = re.compile(r"\s*(?::[^;{}]*)?(?:\{|=>|where\b)")
ARROW_AFTER = re.compile(r"\s*(?::[^=;{}()]*)?=>")
DECLARE = re.compile(r"\b(?:const|let|var)\s+([{\[])")
NULLISH = re.compile(r"\?\?=?")
OR_OPERATOR = re.compile(r"\|\|=?")
LITERAL = re.compile(r"""['"`\[{]|-?\.?\d|true\b""")
OPERAND_HEAD = re.compile(r"\s*((?:new\s+|await\s+)?-?)")
GET_OR_DEFAULT = re.compile(r"\b(?:getOrDefault|GetValueOrDefault)\s*\(")
UNWRAP_OR = re.compile(r"\.unwrap_or(_default)?\s*\(")
SERDE_DEFAULT = re.compile(r"#\[serde\([^\]]*\bdefault\b[^\]]*\]")
SQL_DEFAULT = re.compile(
    r"\bDEFAULT\b(?!\s+(?:VALUES|CHARSET|CHARACTER|COLLATE|PRIVILEGES)\b)", re.IGNORECASE
)
SQL_EXEMPT = re.compile(r"\b(?:DROP|ON\s+(?:DELETE|UPDATE)\s+SET)\s+\Z", re.IGNORECASE)
SQL_VALUE = re.compile(r"\s+('(?:''|[^'])*'|[^\s,;)]+(?:\([^)]*\))?)")
TF_VARIABLE = re.compile(r"\bvariable\s+\"[^\"\n]*\"\s*\{")
TF_DEFAULT = re.compile(r"\bdefault[ \t]*=(?!=)[ \t]*")


class ScanError(Exception):
    pass


@dataclass(frozen=True)
class Hit:
    file: str
    line: int
    language: str
    construct: str
    instead: str
    candidate: bool
    justified: bool


def free(value: str) -> bool:
    value = value.strip()
    if value[:1] in ("[", "{", "("):
        value = re.sub(r"\s+", "", value)
    return value.lower() in FREE


def short(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= WIDTH else f"{flat[: WIDTH - 3]}..."


def chars(text: str, start: int, end: int):
    depth, quote, escaped = 0, "", False
    for index in range(start, end):
        char = text[index]
        if char == "\n":
            quote, escaped = "", False
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
        elif char in QUOTES:
            quote = char
        elif char in OPENERS:
            yield index, char, depth
            depth += 1
        elif char in CLOSERS:
            depth -= 1
            yield index, char, depth
        else:
            yield index, char, depth


def pairs(masked: str) -> dict[int, int]:
    found: dict[int, int] = {}
    stack: list[int] = []
    for index, char, _ in chars(masked, 0, len(masked)):
        if char in OPENERS:
            stack.append(index)
        elif char in CLOSERS and stack:
            found[stack.pop()] = index
    return found


def closing(text: str, opener: int) -> int:
    for index, char, depth in chars(text, opener, len(text)):
        if char in CLOSERS and depth == 0:
            return index
    return -1


def segments(text: str, start: int, end: int) -> list[tuple[int, int]]:
    parts, begin = [], start
    for index, char, depth in chars(text, start, end):
        if char == "," and depth == 0:
            parts.append((begin, index))
            begin = index + 1
    parts.append((begin, end))
    return parts


def equals(masked: str, start: int, end: int) -> int:
    for index, char, depth in chars(masked, start, end):
        if char == "=" and depth == 0 and masked[index - 1] not in "=!<>" and masked[index + 1] not in "=>":
            return index
    return -1


def arguments(text: str, match: dict[int, int], opener: int) -> list[str] | None:
    if opener not in match:
        return None
    return [text[begin:end].strip() for begin, end in segments(text, opener + 1, match[opener])]


def operand(masked: str, at: int, match: dict[int, int]) -> tuple[int, int]:
    head = OPERAND_HEAD.match(masked, at)
    begin, end = head.start(1), head.end()
    while end < len(masked):
        char = masked[end]
        if char in OPENERS and end in match:
            end = match[end] + 1
        elif char in QUOTES and masked.find(char, end + 1) > 0:
            end = masked.find(char, end + 1) + 1
        elif char.isalnum() or char in "_$.:":
            end += 1
        else:
            break
    return begin, end


def pattern_defaults(masked: str, text: str, match: dict[int, int], start: int, end: int, instead: str):
    found = []
    for begin, finish in segments(masked, start, end):
        eq = equals(masked, begin, finish)
        if eq >= 0:
            value = text[eq + 1 : finish].strip()
            if not free(value):
                found.append((eq, short(f"{text[begin:eq].strip()} = {value}"), instead, False))
        for index, char, depth in chars(masked, begin, finish if eq < 0 else eq):
            if char in "{[" and depth == 0 and index in match:
                found += pattern_defaults(masked, text, match, index + 1, match[index], instead)
    return found


def shell_expansion(masked: str, text: str, match: dict[int, int], lang: str):
    found = []
    for hit in SHELL_DEFAULT.finditer(masked):
        name = hit.group(1)
        if free(hit.group(3)):
            continue
        if lang == "shell":
            instead = f': "${{{name}:?set {name} in <file>}}"'
        else:
            instead = f"${{{name}:?{name} is required}}"
        found.append((hit.start(), short(text[hit.start() : hit.end()]), instead, False))
    return found


def make_conditional(masked: str, text: str, match: dict[int, int], lang: str):
    return [
        (
            hit.start(1),
            short(f"{hit.group(1)} ?= {hit.group(2)}"),
            f"{hit.group(1)} := $(or $({hit.group(1)}),$(error {hit.group(1)} is required))",
            False,
        )
        for hit in MAKE_DEFAULT.finditer(masked)
        if not free(hit.group(2))
    ]


def expression_start(masked: str, at: int) -> int:
    opened = max(masked.rfind("{{", 0, at), masked.rfind("{%", 0, at))
    closed = max(masked.rfind("}}", 0, at), masked.rfind("%}", 0, at))
    return opened if opened > closed else masked.rfind("\n", 0, at) + 1


def jinja_default(masked: str, text: str, match: dict[int, int], lang: str):
    found = []
    for hit in JINJA_DEFAULT.finditer(masked):
        opener = hit.end() - 1
        closer = closing(masked, opener)
        argument = text[slice(*segments(masked, opener + 1, closer)[0])].strip() if closer > 0 else "..."
        env = ENV_LOOKUP.search(masked, expression_start(masked, hit.start()), hit.start())
        if free(argument) and not env:
            continue
        construct = f"lookup('env', ...) | default({argument})" if env else f"| default({argument})"
        found.append((hit.start(), short(construct), "| mandatory, or an assert on the variable", False))
    return found


def parameters(masked: str, text: str, match: dict[int, int], lang: str):
    found = []
    for opener, closer in match.items():
        if masked[opener] != "(":
            continue
        low = max(0, opener - WINDOW)
        name = METHOD_BEFORE.search(masked, low, opener)
        if (
            FUNCTION_BEFORE.search(masked, low, opener)
            or ARROW_AFTER.match(masked, closer + 1)
            or (name and name.group(1) not in KEYWORDS and METHOD_AFTER.match(masked, closer + 1))
        ):
            found += pattern_defaults(masked, text, match, opener + 1, closer, "a required parameter")
    return found


def destructuring(masked: str, text: str, match: dict[int, int], lang: str):
    found = []
    for hit in DECLARE.finditer(masked):
        opener = hit.start(1)
        if opener in match:
            found += pattern_defaults(
                masked, text, match, opener + 1, match[opener], f"no default; {NULL_CHECK[lang]}"
            )
    return found


def nullish(masked: str, text: str, match: dict[int, int], lang: str):
    found = []
    for hit in NULLISH.finditer(masked):
        value = text[slice(*operand(masked, hit.end(), match))]
        if not free(value) and value != "throw":
            found.append((hit.start(), short(f"{hit.group()} {value}"), NULL_CHECK[lang], True))
    return found


def or_literal(masked: str, text: str, match: dict[int, int], lang: str):
    found = []
    for hit in OR_OPERATOR.finditer(masked):
        value = text[slice(*operand(masked, hit.end(), match))]
        if LITERAL.match(value) and not free(value):
            found.append((hit.start(), short(f"{hit.group()} {value}"), NULL_CHECK[lang], True))
    return found


def get_or_default(masked: str, text: str, match: dict[int, int], lang: str):
    found = []
    for hit in GET_OR_DEFAULT.finditer(masked):
        opener = hit.end() - 1
        args = arguments(text, match, opener)
        if args is not None and len(args) == 2 and free(args[1]):
            continue
        end = match[opener] + 1 if args is not None else hit.end()
        found.append((hit.start(), short(text[hit.start() : end]), "an explicit null check that throws", False))
    return found


def unwrap_or(masked: str, text: str, match: dict[int, int], lang: str):
    found = []
    for hit in UNWRAP_OR.finditer(masked):
        opener = hit.end() - 1
        args = arguments(text, match, opener)
        if not hit.group(1) and args is not None and len(args) == 1 and free(args[0]):
            continue
        end = match[opener] + 1 if args is not None else hit.end()
        found.append((hit.start(), short(text[hit.start() : end]), "ok_or(Error::MissingX)?", False))
    return found


def serde_default(masked: str, text: str, match: dict[int, int], lang: str):
    return [
        (hit.start(), short(text[hit.start() : hit.end()]), "a required field, #[serde(deny_unknown_fields)]", False)
        for hit in SERDE_DEFAULT.finditer(masked)
    ]


def sql_default(masked: str, text: str, match: dict[int, int], lang: str):
    found = []
    for hit in SQL_DEFAULT.finditer(masked):
        if SQL_EXEMPT.search(masked, max(0, hit.start() - WINDOW), hit.start()):
            continue
        value = SQL_VALUE.match(text, hit.end())
        if value and not free(value.group(1)):
            found.append(
                (hit.start(), short(f"DEFAULT {value.group(1)}"), "NOT NULL, and supply it in every insert", False)
            )
    return found


def terraform_default(masked: str, text: str, match: dict[int, int], lang: str):
    found = []
    for block in TF_VARIABLE.finditer(masked):
        opener = block.end() - 1
        if opener not in match:
            continue
        closer = match[opener]
        for hit in TF_DEFAULT.finditer(masked, opener + 1, closer):
            start = hit.end()
            value = text[start : match[start] + 1] if start in match else text[start:closer].split("\n", 1)[0]
            if not free(value):
                found.append(
                    (hit.start(), short(f"default = {value}"), "no default; fail on the missing input", False)
                )
    return found


JS = (f"{DQ}|{SQ}|{BACKTICK}", SLASH, (parameters, destructuring, nullish, or_literal))
LANGS = {
    "shell": ("", HASH, (shell_expansion,)),
    "env": ("", LINE_HASH, (shell_expansion,)),
    "make": ("", HASH, (make_conditional, shell_expansion)),
    "dockerfile": ("", LINE_HASH, (shell_expansion,)),
    "compose": ("", HASH, (shell_expansion,)),
    "yaml": ("", HASH, (jinja_default, shell_expansion)),
    "jinja": ("", JINJA_COMMENT, (jinja_default,)),
    "js": JS,
    "ts": JS,
    "csharp": (f"{DQ}|{CHAR}", SLASH, (parameters, nullish, get_or_default)),
    "java": (f"{DQ}|{CHAR}", SLASH, (get_or_default,)),
    "rust": (f"{DQ}|{CHAR}", SLASH, (unwrap_or, serde_default)),
    "sql": (SQL_STRING, SQL_COMMENT, (sql_default,)),
    "terraform": (DQ, f"{HASH}|{SLASH}", (terraform_default,)),
}


def language(name: str) -> str:
    if DOCKERFILE.search(name):
        return "dockerfile"
    if COMPOSE.match(name):
        return "compose"
    if name in MAKEFILES:
        return "make"
    if name == ".env" or name.startswith(".env.") or name.endswith(".env"):
        return "env"
    return SUFFIXES.get(PurePosixPath(name).suffix, "")


def languages(path: str) -> list[str]:
    name = PurePosixPath(path).name
    stem = JINJA_SUFFIX.sub("", name)
    inner = language(stem)
    if stem == name:
        return [inner] if inner else []
    return ["jinja"] + ([inner] if inner and inner != "python" else [])


def mask(text: str, pattern: re.Pattern[str]) -> tuple[str, list[tuple[int, int]]]:
    comments: list[tuple[int, int]] = []

    def blank(match: re.Match[str]) -> str:
        body = re.sub(r"[^\n]", " ", match.group())
        if match.lastgroup == "comment":
            comments.append(match.span())
            return body
        return match.group()[0] + body[1:-1] + match.group()[-1]

    return pattern.sub(blank, text), comments


def scan_masked(path: str, text: str, langs: list[str], wanted: set[int] | None) -> list[Hit]:
    strings = "|".join(LANGS[lang][0] for lang in langs if LANGS[lang][0])
    source = "(?P<comment>" + "|".join(LANGS[lang][1] for lang in langs) + ")"
    if strings:
        source += f"|(?P<string>{strings})"
    masked, spans = mask(text, re.compile(source, re.MULTILINE | re.DOTALL))
    starts = [0] + [newline.end() for newline in re.finditer("\n", text)]
    commented: set[int] = set()
    for begin, end in spans:
        commented.update(
            range(bisect.bisect_right(starts, begin), bisect.bisect_right(starts, max(begin, end - 1)) + 1)
        )
    rows = masked.split("\n")
    comment_only = {line for line in commented if not rows[line - 1].strip()}
    match = pairs(masked)
    hits, seen = [], set()
    for lang in langs:
        for rule in LANGS[lang][2]:
            if rule in seen:
                continue
            seen.add(rule)
            for offset, construct, instead, candidate in rule(masked, text, match, lang):
                line = bisect.bisect_right(starts, offset)
                if wanted is None or line in wanted:
                    justified = line in commented or line - 1 in comment_only
                    hits.append(Hit(path, line, lang, construct, instead, candidate, justified))
    return hits


def absent(node: ast.expr) -> bool:
    if isinstance(node, ast.Constant):
        value = node.value
        return value is None or value is False or (isinstance(value, (str, bytes)) and not value)
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return not node.elts
    if isinstance(node, ast.Dict):
        return not node.keys
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in EMPTY_CALLS
        and not node.args
        and not node.keywords
    )


def mutable(node: ast.expr) -> bool:
    if isinstance(node, (ast.List, ast.Dict, ast.Set)):
        return True
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in MUTABLE_CALLS


def parameter_defaults(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
    args = node.args
    positional = args.posonlyargs + args.args
    paired = list(zip(positional[len(positional) - len(args.defaults) :], args.defaults))
    paired += [(arg, value) for arg, value in zip(args.kwonlyargs, args.kw_defaults) if value is not None]
    owner = "lambda" if isinstance(node, ast.Lambda) else node.name
    found = []
    for arg, value in paired:
        construct = short(f"{owner}({arg.arg}={ast.unparse(value)})")
        if mutable(value):
            instead = "None, and a branch that builds a fresh object: every call shares a mutable default"
            found.append((value.lineno, construct, instead, False))
        elif not absent(value):
            found.append((value.lineno, construct, "a required parameter", False))
    return found


def call_default(node: ast.Call):
    func = node.func
    keywords = {keyword.arg: keyword.value for keyword in node.keywords if keyword.arg}
    attribute = func.attr if isinstance(func, ast.Attribute) else ""
    name = func.id if isinstance(func, ast.Name) else ""
    if attribute == "add_argument":
        fallback, instead = keywords.get("default"), "add_argument(..., required=True)"
    elif name == "getattr" and len(node.args) == 3:
        fallback = node.args[2]
        instead = f"getattr({ast.unparse(node.args[0])}, {ast.unparse(node.args[1])})"
    elif "getenv" in (attribute, name) or attribute == "get":
        fallback = node.args[1] if len(node.args) == 2 else keywords.get("default")
        owner = ast.unparse(func.value) if attribute == "get" else "os.environ"
        instead = "os.environ[name]" if owner.endswith("environ") else f"{owner}[name]"
    else:
        return []
    if fallback is None or absent(fallback):
        return []
    if attribute == "add_argument":
        construct = f"add_argument(default={ast.unparse(fallback)})"
    else:
        construct = ast.unparse(node)
    return [(fallback.lineno, short(construct), instead, False)]


def python_rules(node: ast.AST):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        return parameter_defaults(node)
    if isinstance(node, ast.Call):
        return call_default(node)
    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
        last = node.values[-1]
        if isinstance(last, LITERALS) and not absent(last):
            construct = short(f"or {ast.unparse(last)}")
            return [(last.lineno, construct, "a check that raises on the missing value", True)]
    return []


def scan_python(path: str, text: str, wanted: set[int] | None) -> list[Hit]:
    try:
        tree = ast.parse(text, filename=path)
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (SyntaxError, ValueError, tokenize.TokenError) as error:
        raise ScanError(f"{path}: unparseable Python: {error}") from error
    commented = {token.start[0] for token in tokens if token.type == tokenize.COMMENT}
    comment_only = {line for line, row in enumerate(text.split("\n"), 1) if row.lstrip().startswith("#")}
    hits = []
    for node in ast.walk(tree):
        for line, construct, instead, candidate in python_rules(node):
            if wanted is None or line in wanted:
                justified = line in commented or line - 1 in comment_only
                hits.append(Hit(path, line, "python", construct, instead, candidate, justified))
    return hits


def scan(path: str, text: str, wanted: set[int] | None) -> list[Hit]:
    langs = languages(path)
    if langs == ["python"]:
        return scan_python(path, text, wanted)
    return scan_masked(path, text, langs, wanted)


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, check=False)
    if result.returncode != 0:
        raise ScanError(f"git {args[0]}: {result.stderr.decode('utf-8', 'replace').strip()}")
    return result.stdout.decode("utf-8", "replace")


def unquote(name: str) -> str:
    if name.startswith('"'):
        return ast.literal_eval(f"b{name}").decode("utf-8", "replace")
    return name


def added_lines(root: Path, staged: bool) -> dict[str, set[int]]:
    diff = git(
        root, "diff", "--cached" if staged else "HEAD", "--no-color", "--no-ext-diff", "--no-textconv",
        "--find-renames", "--unified=0", "--src-prefix=a/", "--dst-prefix=b/",
    )
    added: dict[str, set[int]] = {}
    path, line, header = None, 0, False
    for row in diff.split("\n"):
        if row.startswith("diff "):
            path, header = None, True
        elif header and row.startswith("+++ "):
            target = unquote(row[4:].removesuffix("\t"))
            path = target[2:] if target.startswith("b/") else None
        elif row.startswith("@@"):
            header = False
            hunk = HUNK.match(row)
            if hunk:
                line = int(hunk.group(1))
            else:
                path = None
        elif path and not header and row.startswith("+"):
            added.setdefault(path, set()).add(line)
            line += 1
    return added


def read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        raise ScanError(f"{path}: {error.strerror}") from error


def collect(repo: Path, staged: bool, files: list[str]) -> list[Hit]:
    if not repo.is_dir():
        raise ScanError(f"{repo} is not a directory")
    root = Path(git(repo, "rev-parse", "--show-toplevel").strip()).resolve()
    targets: dict[str, tuple[str, set[int] | None]] = {}
    for path, lines in added_lines(root, staged).items():
        if languages(path):
            text = git(root, "cat-file", "blob", f":{path}") if staged else read(root / path)
            targets[path] = (text, lines)
    for name in files:
        target = (repo / name).resolve()
        if not target.is_file():
            raise ScanError(f"{name}: no such file")
        shown = target.relative_to(root).as_posix() if target.is_relative_to(root) else str(target)
        if not languages(shown):
            print(f"defaults: {shown}: no rules for this file type", file=sys.stderr)
            continue
        targets[shown] = (read(target), None)
    hits = []
    for path, (text, wanted) in targets.items():
        hits += scan(path, text, wanted)
    return sorted(hits, key=lambda hit: (hit.file, hit.line, hit.language, hit.construct))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", required=True)
    parser.add_argument("--staged", action="store_true")
    parser.add_argument("--file", action="append", default=[])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        hits = collect(Path(args.repo), args.staged, args.file)
    except ScanError as error:
        print(f"defaults: {error}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps([asdict(hit) for hit in hits], indent=1))
        return 1 if hits else 0
    for hit in hits:
        marks = ",".join(mark for mark, on in (("candidate", hit.candidate), ("justified?", hit.justified)) if on)
        print("\t".join([f"{hit.file}:{hit.line}", hit.language, hit.construct, hit.instead] + ([marks] if marks else [])))
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
