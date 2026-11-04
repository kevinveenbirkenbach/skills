#!/usr/bin/env python3
"""Report the principle-lens hits of ruff, lizard and jscpd on the lines a change touches.

Args:
    --repo: a directory inside the git work tree to scan.
    --staged: scan only the staged changes (git diff --cached); the tools
        read a snapshot of the index. Without it: every change against HEAD,
        staged and unstaged, in the working tree.
    --file: count every line of this file as changed; repeatable, relative
        to --repo or absolute. Untracked files are in no diff.
    --ccn: a function above this cyclomatic complexity is a hit (ruff C901,
        lizard).
    --nloc: a function above this many lines of code, blank and comment
        lines excluded, is a hit (lizard).
    --params: a function above this many parameters is a hit (ruff PLR0913,
        lizard).
    --min-tokens: a clone of at least this many tokens is a hit (jscpd).
    --json: print the hits as a JSON list instead of tab-separated lines.

Output:
    One line per hit: file:line, lens, tool, message. ruff C901 and PLR0913
    and lizard map to SRP; ruff BLE001, S110, B006 and B008 to fail fast;
    ruff ARG to KISS/YAGNI; jscpd to DRY. A ruff hit counts when its range
    touches a changed line, a lizard function when its span does, a jscpd
    clone when either side does. ruff reads Python files, lizard the
    languages it has a reader for, jscpd the whole tree for clone partners.
    A tool missing from PATH writes `skip: <tool> missing` to stderr instead
    of hits.

Exit codes:
    0 no hits, 1 hits, 2 usage error, git failure, a failed tool or
    unreadable tool output, or a missing kvb-code-clean/scripts/defaults.py,
    which parses the diff.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from types import ModuleType

DEFAULTS = Path(__file__).resolve().parents[2] / "kvb-code-clean" / "scripts" / "defaults.py"
RUFF_LENSES = {
    "C901": "SRP",
    "PLR0913": "SRP",
    "BLE001": "fail fast",
    "S110": "fail fast",
    "B006": "fail fast",
    "B008": "fail fast",
    "ARG": "KISS/YAGNI",
}
PYTHON = frozenset({".py", ".pyi"})
LIZARD = frozenset(
    {
        ".c", ".cc", ".cpp", ".cxx", ".h", ".hpp", ".cs", ".java", ".js", ".cjs", ".mjs", ".jsx", ".ts",
        ".tsx", ".vue", ".py", ".rb", ".php", ".go", ".rs", ".swift", ".kt", ".kts", ".scala", ".lua",
        ".m", ".mm", ".pl", ".pm", ".r", ".erl", ".hrl", ".es", ".escript", ".sol", ".sql", ".pks",
        ".pkb", ".pls", ".plb", ".pck", ".gd", ".zig", ".st", ".sdl", ".ttcn", ".ttcnpp", ".f", ".f70",
        ".f90", ".f95", ".f03", ".f08", ".for", ".ftn", ".fpp",
    }
)
LIZARD_WARNING = re.compile(
    r"^(?P<path>.+?):(?P<line>\d+): warning: "
    r"(?P<message>.+? has \d+ NLOC, \d+ CCN, \d+ token, \d+ PARAM, (?P<length>\d+) length\b.*)$"
)
REPORT = "jscpd-report.json"
BLOBS = frozenset({b"100644", b"100755"})


def load(path: Path) -> ModuleType:
    if not path.is_file():
        print(f"principles: {path} is missing; it parses the diff", file=sys.stderr)
        sys.exit(2)
    spec = importlib.util.spec_from_file_location("kvb_code_clean_defaults", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


defaults = load(DEFAULTS)
ScanError = defaults.ScanError


@dataclass(frozen=True, order=True)
class Hit:
    file: str
    line: int
    lens: str
    tool: str
    message: str


@dataclass(frozen=True)
class Target:
    path: Path
    lines: frozenset[int] | None

    def overlaps(self, start: int, end: int) -> bool:
        return self.lines is None or not self.lines.isdisjoint(range(start, end + 1))


@dataclass(frozen=True)
class Scan:
    base: Path
    scratch: Path
    targets: dict[str, Target]
    shown: dict[str, str]
    limits: argparse.Namespace

    def name(self, raw: str) -> str:
        path = (self.base / raw).resolve()
        if str(path) in self.shown:
            return self.shown[str(path)]
        return path.relative_to(self.base).as_posix() if path.is_relative_to(self.base) else str(path)

    def touched(self, raw: str, start: int, end: int) -> str | None:
        name = self.name(raw)
        target = self.targets.get(name)
        return name if target is not None and target.overlaps(start, end) else None

    def files(self, suffixes: frozenset[str]) -> list[str]:
        return [str(target.path) for target in self.targets.values() if target.path.suffix.lower() in suffixes]


def available(tool: str) -> bool:
    if shutil.which(tool):
        return True
    print(f"skip: {tool} missing", file=sys.stderr)
    return False


def run(command: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        command, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False
    )


def failed(result: subprocess.CompletedProcess) -> ScanError:
    return ScanError(f"{result.args[0]} exited {result.returncode}: {result.stderr.strip()}")


def ruff_lens(code: str | None) -> str | None:
    if code is None:
        return None
    return next((lens for prefix, lens in RUFF_LENSES.items() if code.startswith(prefix)), None)


def ruff(scan: Scan) -> list[Hit]:
    paths = scan.files(PYTHON)
    if not paths or not available("ruff"):
        return []
    result = run(
        [
            "ruff", "check", "--isolated", "--no-cache", "--exit-zero", "--output-format", "json",
            "--select", ",".join(RUFF_LENSES),
            "--config", f"lint.mccabe.max-complexity = {scan.limits.ccn}",
            "--config", f"lint.pylint.max-args = {scan.limits.params}",
            *paths,
        ],
        scan.base,
    )
    if result.returncode != 0:
        raise failed(result)
    hits = []
    for row in json.loads(result.stdout):
        lens = ruff_lens(row["code"])
        start = row["location"]["row"]
        name = scan.touched(row["filename"], start, row["end_location"]["row"])
        if lens and name:
            hits.append(Hit(name, start, lens, "ruff", f"{row['code']} {row['message']}"))
    return hits


def parse_lizard(text: str) -> list[tuple[str, int, int, str]]:
    found = []
    for row in text.splitlines():
        match = LIZARD_WARNING.match(row)
        if match:
            line = int(match["line"])
            found.append((match["path"], line, line + int(match["length"]) - 1, match["message"]))
    return found


def lizard(scan: Scan) -> list[Hit]:
    paths = scan.files(LIZARD)
    if not paths or not available("lizard"):
        return []
    limits = scan.limits
    result = run(
        [
            "lizard", "--warnings_only", "--CCN", str(limits.ccn), "--arguments", str(limits.params),
            "--Threshold", f"nloc={limits.nloc}", *paths,
        ],
        scan.base,
    )
    if result.returncode not in (0, 1):
        raise failed(result)
    return [
        Hit(name, start, "SRP", "lizard", message)
        for path, start, end, message in parse_lizard(result.stdout)
        if (name := scan.touched(path, start, end))
    ]


def side(part: dict) -> tuple[str, int, int]:
    return part["name"], part["start"], part["end"]


def parse_jscpd(report: dict) -> list[tuple[tuple[str, int, int], tuple[str, int, int], int]]:
    return [(side(clone["firstFile"]), side(clone["secondFile"]), clone["tokens"]) for clone in report["duplicates"]]


def jscpd(scan: Scan) -> list[Hit]:
    if not scan.targets or not available("jscpd"):
        return []
    extra = [str(target.path) for target in scan.targets.values() if not target.path.is_relative_to(scan.base)]
    output = scan.scratch / "jscpd"
    output.mkdir()
    result = run(
        [
            "jscpd", "--min-tokens", str(scan.limits.min_tokens), "--reporters", "json", "--output", str(output),
            "--absolute", "--silent", str(scan.base), *extra,
        ],
        scan.base,
    )
    report = output / REPORT
    if not report.is_file():
        raise failed(result)
    hits = []
    for first, second, tokens in parse_jscpd(json.loads(report.read_text(encoding="utf-8"))):
        for (path, start, end), (other, other_start, other_end) in ((first, second), (second, first)):
            name = scan.touched(path, start, end)
            if name:
                clone = f"clone of {scan.name(other)}:{other_start}-{other_end}, {tokens} tokens"
                hits.append(Hit(name, start, "DRY", "jscpd", clone))
                break
    return hits


def git_bytes(root: Path, *args: str, stdin: bytes) -> bytes:
    result = subprocess.run(["git", *args], cwd=root, input=stdin, capture_output=True, check=False)
    if result.returncode != 0:
        raise ScanError(f"git {args[0]}: {result.stderr.decode('utf-8', 'replace').strip()}")
    return result.stdout


def snapshot(root: Path, target: Path) -> None:
    entries = []
    for record in git_bytes(root, "ls-files", "--stage", "-z", stdin=b"").split(b"\0"):
        meta, _, path = record.partition(b"\t")
        fields = meta.split()
        if len(fields) == 3 and fields[0] in BLOBS and fields[2] == b"0":
            entries.append((fields[1], os.fsdecode(path)))
    data = git_bytes(root, "cat-file", "--batch", stdin=b"".join(oid + b"\n" for oid, _ in entries))
    offset = 0
    for _, path in entries:
        newline = data.index(b"\n", offset)
        size = int(data[offset:newline].split()[2])
        file = target / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(data[newline + 1 : newline + 1 + size])
        offset = newline + 2 + size


def collect(repo: Path, staged: bool, names: list[str], limits: argparse.Namespace) -> list[Hit]:
    if not repo.is_dir():
        raise ScanError(f"{repo} is not a directory")
    root = Path(defaults.git(repo, "rev-parse", "--show-toplevel").strip()).resolve()
    changed = defaults.added_lines(root, staged)
    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp).resolve()
        base = root
        if staged:
            base = scratch / "index"
            base.mkdir()
            snapshot(root, base)
        targets = {
            path: Target(base / path, frozenset(lines)) for path, lines in changed.items() if (base / path).is_file()
        }
        for name in names:
            source = (repo / name).resolve()
            if not source.is_file():
                raise ScanError(f"{name}: no such file")
            if not source.is_relative_to(root):
                targets[str(source)] = Target(source, None)
                continue
            shown = source.relative_to(root).as_posix()
            if staged:
                (base / shown).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, base / shown)
            targets[shown] = Target(base / shown, None)
        shown = {str(target.path.resolve()): name for name, target in targets.items()}
        scan = Scan(base, scratch, targets, shown, limits)
        return sorted(hit for probe in (ruff, lizard, jscpd) for hit in probe(scan))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", required=True)
    parser.add_argument("--staged", action="store_true")
    parser.add_argument("--file", action="append", default=[])
    parser.add_argument("--ccn", type=int, required=True)
    parser.add_argument("--nloc", type=int, required=True)
    parser.add_argument("--params", type=int, required=True)
    parser.add_argument("--min-tokens", type=int, required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        hits = collect(Path(args.repo), args.staged, args.file, args)
    except ScanError as error:
        print(f"principles: {error}", file=sys.stderr)
        return 2
    except (KeyError, ValueError) as error:
        print(f"principles: unreadable tool output: {error!r}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps([asdict(hit) for hit in hits], indent=1))
        return 1 if hits else 0
    for hit in hits:
        print("\t".join([f"{hit.file}:{hit.line}", hit.lens, hit.tool, hit.message]))
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
