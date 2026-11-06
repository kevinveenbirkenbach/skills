from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from pathlib import Path

import jinja2

from .approving import Approving
from .asking import Asking
from .batches import Pending
from .engines import Engines, Speech
from .events import Log, Watch
from .inbox import Inbox
from .jobs import Jobs
from .language import Language, Model
from .ledger import Ledger, Marks, Reviews
from .mcp import Mcp
from .messaging import Messaging
from .names import Names
from .reviewing import Reviewing
from .rules import Rules
from .settings import Settings
from .signed import signing
from .skill_scripts import Runner
from .sources import Sources
from .timeline import Timeline
from .transcripts import Transcripts
from .tree import Tree
from .view import View


@dataclass(frozen=True)
class Places:
    repos: Path
    worktrees: Path
    timers: Path


def environment(templates: Path) -> jinja2.Environment:
    return jinja2.Environment(
        loader=jinja2.FileSystemLoader(templates),
        autoescape=True,
        undefined=jinja2.StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )


@dataclass(frozen=True)
class Hub(Mcp, Reviewing, Asking, Messaging, Approving, Inbox, Rules, Jobs, Sources, Timeline, View, Language):
    council: Path
    pages: Path
    public_port: int
    reviews: Reviews
    asks: Ledger
    decisions: Ledger
    messages: Ledger
    uploads: Path
    host_state: Path
    transcripts: Transcripts
    scripts: Runner
    templates: jinja2.Environment
    rules: Ledger
    jobs: Ledger
    marks: Marks
    log: Log
    batches: Pending
    names: Names
    watch: Watch
    tree: Tree
    model: Model
    timers: Path
    settings: Settings
    speech: Speech
    approvers: Path

    def hosts(self) -> tuple[str, str]:
        return f"127.0.0.1:{self.public_port}", f"localhost:{self.public_port}"

    def url(self) -> str:
        return f"{signing.origin_of(self.public_port)}/"


def open_hub(council: Path, pages: Path, public_port: int, state: Path, host_state: Path, transcripts: Path, scripts: Runner, templates: Path, places: Places, model: Model, engines: Engines, approvers: Path) -> Hub:
    uploads = state / "uploads"
    uploads.mkdir(exist_ok=True)
    return Hub(
        approvers=approvers,
        speech=Speech(engines, state / "tts"),
        rules=Ledger(state / "rules.json"),
        jobs=Ledger(state / "jobs.json"),
        marks=Marks(state / "marks.json"),
        log=Log(state / "log.jsonl"),
        batches=Pending(),
        names=Names(state / "names.json"),
        settings=Settings(state / "settings.json"),
        watch=Watch(),
        tree=Tree(repos=places.repos, worktrees=places.worktrees, home=state, lock=threading.Lock(), cached=None, scanned=-math.inf),
        model=model,
        timers=places.timers,
        council=council,
        pages=pages,
        public_port=public_port,
        reviews=Reviews(state),
        asks=Ledger(state / "asks.json"),
        decisions=Ledger(state / "decisions.json"),
        messages=Ledger(state / "messages.json"),
        uploads=uploads,
        host_state=host_state,
        transcripts=Transcripts(transcripts),
        scripts=scripts,
        templates=environment(templates),
    )
