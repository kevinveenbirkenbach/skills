from __future__ import annotations

import concurrent.futures
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import review_scope

SKILLS = Path(__file__).resolve().parents[2]
SKILL = Path(__file__).resolve().parents[1] / "SKILL.md"
SECURITY = SKILLS / "kvb-check-security" / "scripts" / "security.py"
PRINCIPLES = SKILLS / "kvb-check-principles" / "scripts" / "principles.py"
MEASURE = SKILLS / "kvb-check-efficiency" / "scripts" / "measure.py"
QUEUE = SKILLS / "kvb-org-queue" / "scripts" / "queue.py"
LEGAL = SKILLS / "kvb-check-legal" / "checks.md"
PRINCIPLE_LIMITS = ("--ccn", "10", "--nloc", "50", "--params", "5", "--min-tokens", "50")
SEVERITIES = ("critical", "high", "medium", "low", "info")
BLOCKING = ("critical", "high")
LIMIT = 100
LENS_SECONDS = 3600
TAIL = 2000
STANDARD_FILES = ("AGENTS.md", "CONTRIBUTING.md")
STANDARD_DIRS = ("docs/contributing/",)
ROLE = re.compile(r"^roles/([^/]+)/")
HEADING = re.compile(r"^#{1,6}\s+\S")
HARNESS = "harness:"
QUEUE_KIND = "test"


@dataclass(frozen=True)
class Lens:
    """Args:
        name: the lens name findings carry.
        scope: "file" for a lens keyed per file, "diff" for one keyed by the
            whole change's patch id.
        script: whether review.py runs it as a process; else a subagent or
            a harness skill judges and review.py records its answer.
        heavy: whether it runs through queue.py hold when a task is given.
        standards: whether its key carries the standards digest.
    """

    name: str
    scope: str
    script: bool
    heavy: bool
    standards: bool


LENSES = (
    Lens("quality", "diff", True, True, False),
    Lens("security", "diff", True, True, False),
    Lens("principles", "diff", True, False, False),
    Lens("performance", "diff", True, True, False),
    Lens("standards", "file", False, False, True),
    Lens("legal", "file", False, False, False),
)
SOURCES = {"security": SECURITY, "principles": PRINCIPLES, "performance": MEASURE, "standards": SKILL, "legal": LEGAL}
CHECKS = {"security": "kvb-check-security", "principles": "kvb-check-principles", "performance": "kvb-check-efficiency", "legal": "kvb-check-legal"}
SCORE_BLOCK = ("kvb-check-break-risk", "kvb-check-confidence", "kvb-check-score")


def every(harness: list[str]) -> list[Lens]:
    return [*LENSES, *(Lens(f"{HARNESS}{name}", "diff", False, False, False) for name in harness)]


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16] if path.is_file() else "absent"


def version(lens: Lens) -> str:
    if lens.name == "quality":
        binary = shutil.which("quality")
        if binary is None:
            return "absent"
        done = subprocess.run([binary, "--version"], capture_output=True, text=True, check=False)
        return " ".join(done.stdout.split()) or f"exit {done.returncode}"
    if lens.name.startswith(HARNESS):
        return file_digest(SKILL)
    return file_digest(SOURCES[lens.name])


def quality_command(scope: review_scope.Scope) -> list[str] | str:
    binary = shutil.which("quality")
    if binary is None:
        return "quality is not installed; quality 003 brings it with kvb-quality-review"
    return [binary, "check", *(["--staged"] if scope.head is None else ["--base", scope.base]), "--json"]


def principles_command(repo: Path, scope: review_scope.Scope, files: list[str]) -> list[str] | str:
    chosen = ["--staged"] if scope.head is None else [item for path in files for item in ("--file", path)]
    if not chosen:
        return "no changed file"
    return [sys.executable, "-I", str(PRINCIPLES), "--repo", str(repo), *chosen, *PRINCIPLE_LIMITS, "--json"]


def performance_command(scope: review_scope.Scope, measure: list[str]) -> list[str] | str:
    if not measure:
        return "no runnable code to measure: pass --measure <command> for a change to runnable code"
    return [sys.executable, "-I", str(MEASURE), "--base", scope.base, "--json", "--", *measure]


def command(lens: Lens, repo: Path, scope: review_scope.Scope, files: list[str], measure: list[str]) -> list[str] | str:
    """Returns:
        The argv of a script lens for this change, or the reason it cannot
        run, which the review lists in place of its findings.
    """
    if lens.name == "quality":
        return quality_command(scope)
    if lens.name == "security":
        return [sys.executable, "-I", str(SECURITY), "--repo", str(repo), "--base", scope.base, "--json"]
    if lens.name == "principles":
        return principles_command(repo, scope, files)
    return performance_command(scope, measure)


def queued(argv: list[str], task: str) -> list[str]:
    return [sys.executable, "-I", str(QUEUE), "hold", "--kind", QUEUE_KIND, "--task", task, "--", *argv]


def run_one(repo: Path, item: tuple[Lens, list[str]]) -> tuple[str, dict]:
    lens, argv = item
    started = time.time()
    try:
        done = subprocess.run(argv, cwd=repo, capture_output=True, text=True, check=False, timeout=LENS_SECONDS)
    except (OSError, subprocess.TimeoutExpired) as error:
        return lens.name, {"started": started, "problem": str(error)}
    return lens.name, {"started": started, "code": done.returncode, "stdout": done.stdout, "stderr": done.stderr[-TAIL:]}


def run_all(repo: Path, jobs: list[tuple[Lens, list[str]]]) -> dict[str, dict]:
    """Returns:
        Per lens name its start time and exit code, stdout and stderr tail,
        or the problem that kept it from running; every job starts at once.
    """
    if not jobs:
        return {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        return dict(pool.map(lambda job: run_one(repo, job), jobs))


def finding(lens: str, entry: dict, severity: str, rule: str, message: str) -> dict:
    line = entry.get("line")
    return {
        "lens": lens, "rule": rule, "severity": severity if severity in SEVERITIES else "medium",
        "path": str(entry.get("path") or entry.get("file") or "-"), "line": line if isinstance(line, int) else None,
        "message": message, "evidence": "",
    }


def security_findings(data: object) -> tuple[list[dict], str | None]:
    if not isinstance(data, dict):
        return [], "unreadable report"
    if data.get("security") is None:
        return [], str(data.get("problem"))
    return [finding("security", entry, entry["severity"], entry.get("rule") or "", f"MEDUSA {entry.get('rule') or 'finding'}") for entry in data.get("findings", [])], None


def principle_findings(data: list[dict]) -> tuple[list[dict], str | None]:
    return [finding("principles", entry, "medium", f"{entry['tool']}:{entry['lens']}", entry["message"]) for entry in data], None


def performance_findings(data: dict) -> tuple[list[dict], str | None]:
    return [finding("performance", {}, "medium", key, f"{key} {data[key]} % of the base") for key in ("efficiency", "speed") if data.get(key, 0) > LIMIT], None


def quality_findings(data: object) -> tuple[list[dict], str | None]:
    entries = data.get("findings", []) if isinstance(data, dict) else data if isinstance(data, list) else []
    return [finding("quality", entry, str(entry.get("severity", "")).lower(), str(entry.get("rule") or entry.get("rule_id") or ""), str(entry.get("message") or "")) for entry in entries if isinstance(entry, dict)], None


PARSERS = {"quality": quality_findings, "security": security_findings, "principles": principle_findings, "performance": performance_findings}


def parsed(lens: str, result: dict) -> tuple[list[dict], str | None]:
    """Returns:
        The findings a script lens printed, or the problem that makes its
        output unusable.
    """
    if "problem" in result:
        return [], result["problem"]
    try:
        data = json.loads(result["stdout"])
    except ValueError:
        return [], f"exit {result['code']} without JSON: {result['stderr'].strip()[-300:]}"
    return PARSERS[lens](data)


def standards(repo: Path, paths: list[str]) -> list[str]:
    tracked = set(review_scope.git(repo, "ls-files", "-z").split("\0"))
    picked = {name for name in tracked if name in STANDARD_FILES or name.startswith(STANDARD_DIRS)}
    roles = {match.group(1) for path in paths if (match := ROLE.match(path))}
    picked |= {f"roles/{role}/AGENTS.md" for role in roles} & tracked
    return sorted(picked)


def standards_digest(repo: Path, names: list[str]) -> str:
    return hashlib.sha256("\0".join(f"{name}\0{file_digest(repo / name)}" for name in names).encode()).hexdigest()


def index(root: Path, names: list[str]) -> str:
    rows = []
    for name in names:
        path = root / name
        if path.is_file():
            rows += [f"{name}:{number} {text.strip()}" for number, text in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1) if HEADING.match(text)]
    return "\n".join(rows)


def brief(lens: Lens, repo: Path, scope: review_scope.Scope, paths: list[str], names: list[str]) -> str:
    """Args:
        paths: the files this subagent reviews, the ones the memory lacks.
        names: the standards files of the change.

    Returns:
        The subagent's brief: only the hunks of its files and the index of
        the sections it may cite, never a whole standards document.
    """
    sections = index(LEGAL.parent, [LEGAL.name]) if lens.name == "legal" else index(repo, names)
    source = f"{LEGAL}" if lens.name == "legal" else str(repo)
    return "\n".join([
        "task-class: judgement",
        f"Lens {lens.name} of kvb-code-review on {scope.spec}; read-only: never edit, stage, commit or push.",
        f"Files: {', '.join(paths) or 'none'}",
        f"Sections you may cite (read only those a hunk touches, by file:line under {source}):",
        sections or "none",
        "Hunks:",
        review_scope.hunks(repo, scope, paths) or "none",
        ('Answer one JSON array and nothing else: per finding {"rule": "<file:line of the cited rule>", "severity": "critical|high|medium|low", '
         '"path": "<file>", "line": <number>, "message": "<one line>", "evidence": "<quote or command>"}; [] when nothing holds.'),
    ])
