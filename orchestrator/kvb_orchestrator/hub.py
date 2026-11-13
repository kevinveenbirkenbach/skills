from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

import jinja2
from markupsafe import Markup

from .approving import Approving
from .artifacts import Touched
from .asking import Asking
from .batches import Pending
from .choosing import Choosing
from .cleanup import Cleaning, Spool
from .denying import Denying
from .engines import Engines, Speech
from .events import Log, Watch
from .gating import Gating
from .icons import sheet
from .inbox import Inbox
from .jobs import Jobs
from .language import Language, Model
from .ledger import Ledger, Marks, Reviews
from .mcp import Mcp
from .messaging import Messaging
from .names import Names
from .offices import Offices
from .presence import SNAPSHOT
from .redirects import Redirects
from .requesting import Requesting
from .reviewing import Reviewing
from .rules import Rules
from .settings import Settings
from .signed import signing
from .skill_scripts import Runner
from .sources import Sources
from .tasking import Tasking
from .timeline import Timeline
from .transcripts import Transcripts
from .tree import TREE_HEARTBEAT, Tree
from .view import View
from .viewstore import ViewStore
from .voicenotes import VoiceNotes


@dataclass(frozen=True)
class Places:
    tree_file: Path
    timers: Path
    vendor: Path
    cleanup: Path
    offices: Path
    kept: Path


def environment(templates: Path) -> jinja2.Environment:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(templates),
        autoescape=True,
        undefined=jinja2.StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.policies["json.dumps_kwargs"] = {"sort_keys": False}
    return env


@dataclass(frozen=True)
class Hub(Mcp, Reviewing, Asking, Messaging, Choosing, Approving, Denying, Requesting, Cleaning, Offices, Tasking, Gating, Inbox, Rules, Jobs, Sources, Timeline, View, Language):
    council: Path
    pages: Path
    public_port: int
    reviews: Reviews
    asks: Ledger
    decisions: Ledger
    messages: Ledger
    rule_requests: Ledger
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
    agent_sessions: Path
    model: Model
    timers: Path
    kept: Path
    settings: Settings
    redirects: Redirects
    speech: Speech
    approvers: Path
    vendor: Path
    icons: Markup
    spool: Spool
    office_spool: Spool
    touched: Touched
    voice_notes: VoiceNotes
    replay: Path
    view_store: ViewStore

    def hosts(self) -> tuple[str, str]:
        return f"127.0.0.1:{self.public_port}", f"localhost:{self.public_port}"

    def url(self) -> str:
        return f"{signing.origin_of(self.public_port)}/"


def open_hub(council: Path, pages: Path, public_port: int, state: Path, host_state: Path, transcripts: Path, scripts: Runner, templates: Path, places: Places, model: Model, engines: Engines, approvers: Path, redirects: Redirects) -> Hub:
    uploads = state / "uploads"
    uploads.mkdir(exist_ok=True)
    reviews = Reviews(state)
    speech = Speech(engines, state / "tts")
    messages = Ledger(state / "messages.json")
    return Hub(
        vendor=places.vendor,
        icons=sheet(places.vendor, templates),
        spool=Spool(places.cleanup).ready(),
        office_spool=Spool(places.offices).ready(),
        touched=Touched(reviews.stored),
        approvers=approvers,
        speech=speech,
        voice_notes=VoiceNotes(state / "voice", host_state / "voice", speech, lambda: {message["voice"] for message in messages.listed() if message.get("voice")}),
        replay=state / "replay" / "messages.json",
        view_store=ViewStore(state / "view.json"),
        rules=Ledger(state / "rules.json"),
        jobs=Ledger(state / "jobs.json"),
        marks=Marks(state / "marks.json"),
        log=Log(state / "log.jsonl"),
        batches=Pending(),
        names=Names(state / "names.json"),
        settings=Settings(state / "settings.json"),
        redirects=redirects,
        watch=Watch(),
        tree=Tree(file=places.tree_file, heartbeat=state / TREE_HEARTBEAT, lock=threading.Lock(), cached=None, stamp=None),
        agent_sessions=state / SNAPSHOT,
        model=model,
        timers=places.timers,
        kept=places.kept,
        council=council,
        pages=pages,
        public_port=public_port,
        reviews=reviews,
        asks=Ledger(state / "asks.json"),
        decisions=Ledger(state / "decisions.json"),
        messages=messages,
        rule_requests=Ledger(state / "rule-requests.json"),
        uploads=uploads,
        host_state=host_state,
        transcripts=Transcripts(transcripts),
        scripts=scripts,
        templates=environment(templates),
    )
