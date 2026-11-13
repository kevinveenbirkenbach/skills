from __future__ import annotations

import functools
import importlib.util
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Protocol

SCRIPT_TIMEOUT = 60
OUTPUT_LIMIT = 4000
FIRST_LINE_LIMIT = 200
ELIDED = "..."
SAFE_PATH = "/usr/local/bin:/usr/bin:/bin"
RADIO = "kvb-org-radio/scripts/radio.py"
RASCI = "kvb-org-rasci/scripts/rasci.py"
NIGHT = "kvb-org-suspend/scripts/night.py"
OPERATOR_SCRIPT = "kvb-org-operator/scripts/operator.py"
ESTIMATE = "kvb-org-queue-estimate/scripts/estimate.py"


def bounded(stdout: str) -> str:
    """Returns:
        stdout when it fits OUTPUT_LIMIT, else its first line, whole or not
        at all once over FIRST_LINE_LIMIT, ELIDED and the last OUTPUT_LIMIT
        characters of the rest: the first line a caller parses, like the ts
        radio.py prints, outlives a long output.
    """
    if len(stdout) <= OUTPUT_LIMIT:
        return stdout
    first, _, rest = stdout.partition("\n")
    return "\n".join([first if len(first) <= FIRST_LINE_LIMIT else "", ELIDED, rest[-OUTPUT_LIMIT:]])


def script_module(script: Path) -> ModuleType | None:
    """Returns:
        The installed script as a module, loaded again after an install
        changed it, None when it is missing or does not load.
    """
    try:
        changed = script.stat().st_mtime_ns
    except OSError:
        return None
    return loaded(script, changed)


@functools.cache
def loaded(script: Path, changed: int) -> ModuleType | None:
    spec = importlib.util.spec_from_file_location(f"kvb_orchestrator_{script.stem}_{changed}", script)
    if spec is None:
        return None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except (OSError, ImportError, RuntimeError, SyntaxError):
        return None
    return module


class Runner(Protocol):
    skills: Path

    def run(self, script: str, args: list[str]) -> dict: ...


@dataclass(frozen=True)
class Scripts:
    skills: Path
    council: Path
    home: Path

    def run(self, script: str, args: list[str]) -> dict:
        command = " ".join([Path(script).name, *args])
        env = {"PATH": SAFE_PATH, "HOME": str(self.home), "AGENTS_COUNCIL_ROOT": str(self.council), "PYTHONDONTWRITEBYTECODE": "1"}
        try:
            done = subprocess.run(
                [sys.executable, str(self.skills / script), *args],
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=SCRIPT_TIMEOUT,
                env=env,
                stdin=subprocess.DEVNULL,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            partial = error.stdout.decode("utf-8", errors="replace") if isinstance(error.stdout, bytes) else error.stdout or ""
            return {"command": command, "code": -1, "stdout": bounded(partial), "stderr": str(error)}
        except OSError as error:
            return {"command": command, "code": -1, "stdout": "", "stderr": str(error)}
        return {"command": command, "code": done.returncode, "stdout": bounded(done.stdout), "stderr": done.stderr[-OUTPUT_LIMIT:]}
