from __future__ import annotations

import functools
import threading
import time
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
from .crons import History, queue_live
from .denying import Denying
from .engines import Engines, Speech
from .events import Log, Watch
from .firewall import Firewall
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
from .receipts import (
    NAMES,
    READS,
    SIGHTING,
    ReceiptNames,
    ReceiptReads,
    sight,
    sighting_pass,
)
from .redirects import Redirects
from .requesting import Requesting
from .resources import RESOURCES, SAMPLES
from .reviewing import Reviewing
from .rules import Offers, Rules
from .settings import Settings
from .signed import signing
from .skill_scripts import Runner
from .sources import Sources
from .speechgate import CpuGate
from .tasking import Tasking
from .timeline import Timeline
from .transcripts import Transcripts
from .tree import TREE_HEARTBEAT, Tree
from .view import RADIO_WINDOW, View
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
class Hub(Mcp, Reviewing, Asking, Messaging, Choosing, Approving, Denying, Requesting, Cleaning, Offices, Tasking, Gating, Firewall, Inbox, Rules, Jobs, Sources, Timeline, View, Language):
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
    offers: Offers
    jobs: Ledger
    marks: Marks
    log: Log
    batches: Pending
    names: Names
    receipt_names: ReceiptNames
    receipt_reads: ReceiptReads
    watch: Watch
    tree: Tree
    agent_sessions: Path
    model: Model
    timers: Path
    kept: Path
    settings: Settings
    redirects: Redirects
    speech: Speech
    speech_gate: CpuGate
    approvers: Path
    vendor: Path
    icons: Markup
    spool: Spool
    office_spool: Spool
    firewall_spool: Spool
    groups: Ledger
    rule_sets: Ledger
    touched: Touched
    voice_notes: VoiceNotes
    replay: Path
    history: History
    view_store: ViewStore

    def hosts(self) -> tuple[str, str]:
        return f"127.0.0.1:{self.public_port}", f"localhost:{self.public_port}"

    def url(self) -> str:
        return f"{signing.origin_of(self.public_port)}/"


def sighting(hub: Hub, stop: threading.Event) -> threading.Thread:
    """Args:
        hub: the hub whose receipt stores record the host snapshot's names
            and the first sighting of each read row.
        stop: ends the thread once set.

    Returns:
        The started daemon thread that runs sighting_pass() every SIGHTING
        seconds, whether or not a page builds the state.
    """
    step = functools.partial(sighting_pass, hub.scripts.skills, hub.council, hub.receipt_names, hub.receipt_reads, hub.agent_sessions, RADIO_WINDOW)
    thread = threading.Thread(target=sight, args=(step, hub.receipt_reads, stop, SIGHTING), name="receipt names", daemon=True)
    thread.start()
    return thread


def open_hub(council: Path, pages: Path, public_port: int, state: Path, host_state: Path, transcripts: Path, scripts: Runner, templates: Path, places: Places, model: Model, engines: Engines, approvers: Path, redirects: Redirects) -> Hub:
    uploads = state / "uploads"
    uploads.mkdir(exist_ok=True)
    reviews = Reviews(state)
    speech = Speech(engines, state / "tts")
    messages = Ledger(state / "messages.json")
    settings = Settings(state / "settings.json")
    return Hub(
        speech_gate=CpuGate(samples=places.kept / RESOURCES / SAMPLES, threshold=lambda: settings.get()["speech"]["threshold"], clock=time.time),
        vendor=places.vendor,
        icons=sheet(places.vendor, templates),
        spool=Spool(places.cleanup).ready(),
        office_spool=Spool(places.offices).ready(),
        firewall_spool=Spool(state / "firewall").ready(),
        groups=Ledger(state / "groups.json"),
        rule_sets=Ledger(state / "rule-sets.json"),
        touched=Touched(reviews.stored),
        approvers=approvers,
        speech=speech,
        voice_notes=VoiceNotes(state / "voice", host_state / "voice", speech, lambda: {message["voice"] for message in messages.listed() if message.get("voice")}),
        replay=state / "replay" / "messages.json",
        view_store=ViewStore(state / "view.json"),
        rules=Ledger(state / "rules.json"),
        offers=Offers(),
        jobs=Ledger(state / "jobs.json"),
        marks=Marks(state / "marks.json"),
        log=Log(state / "log.jsonl"),
        batches=Pending(),
        names=Names(state / "names.json"),
        receipt_names=ReceiptNames(state / NAMES),
        receipt_reads=ReceiptReads(state / READS),
        settings=settings,
        redirects=redirects,
        watch=Watch(),
        tree=Tree(file=places.tree_file, heartbeat=state / TREE_HEARTBEAT, lock=threading.Lock(), cached=None, stamp=None),
        agent_sessions=state / SNAPSHOT,
        model=model,
        timers=places.timers,
        kept=places.kept,
        council=council,
        history=History(council / queue_live.HISTORY),
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
