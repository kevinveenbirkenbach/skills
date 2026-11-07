from __future__ import annotations

import contextlib
import hashlib
import re
import secrets
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterator
from pathlib import Path

from .engines import Speech, wav_seconds
from .errors import EngineError, Missing, ToolError, Unavailable
from .records import write_atomic

VOICE_KEEP = 50
HEARING_LIMIT = 4
NOTE_ID = re.compile(r"[0-9a-f]{16}")


class VoiceNotes:
    """Args:
        folder: the hub's own directory for the recordings, <id>.wav each.
        host_folder: the same directory as the host names it, for the radio
            text that points an agent at a recording.
        speech: transcribes a recording with whisper.cpp.
        referenced: the ids of the recordings stored messages carry; trim
            never deletes them.
    """

    def __init__(self, folder: Path, host_folder: Path, speech: Speech, referenced: Callable[[], set[str]]) -> None:
        self.folder = folder
        self.host_folder = host_folder
        self.speech = speech
        self.referenced = referenced
        self.lock = threading.Lock()
        self.notes: dict[str, dict] = {}
        self.sending: Counter[str] = Counter()
        folder.mkdir(exist_ok=True)
        self.trim()

    def submit(self, body: bytes) -> dict:
        gap = self.speech.input_gap()
        if gap:
            raise Unavailable(f"speech input is off: {gap}")
        seconds = wav_seconds(body)
        with self.lock:
            if sum(1 for note in self.notes.values() if note["status"] == "pending") >= HEARING_LIMIT:
                raise Unavailable(f"{HEARING_LIMIT} recordings are already waiting for their transcript")
            self.speech.admit(seconds)
            note_id = secrets.token_hex(8)
            write_atomic(self.folder / f"{note_id}.wav", body)
            note = {"id": note_id, "status": "pending", "text": "", "error": "", "seconds": round(seconds, 2), "created_ts": time.time()}
            self.notes[note_id] = note
        self.trim()
        threading.Thread(target=self.hear, args=(note_id, body), daemon=True).start()
        return dict(note)

    def hear(self, note_id: str, body: bytes) -> None:
        try:
            outcome = {"status": "done", "text": self.speech.whisper(body)["text"]}
        except (EngineError, Unavailable, ToolError, OSError) as error:
            outcome = {"status": "failed", "error": str(error)}
        with self.lock:
            if note_id in self.notes:
                self.notes[note_id] = {**self.notes[note_id], **outcome}

    def file(self, note_id: str) -> Path:
        if not NOTE_ID.fullmatch(note_id):
            raise Missing(note_id)
        path = self.folder / f"{note_id}.wav"
        if not path.is_file():
            raise Missing(note_id)
        return path

    def get(self, note_id: str) -> dict:
        self.file(note_id)
        with self.lock:
            note = self.notes.get(note_id)
        return dict(note) if note else {"id": note_id, "status": "done", "text": "", "error": "", "seconds": None, "created_ts": None}

    def audio(self, note_id: str) -> bytes:
        return self.file(note_id).read_bytes()

    def attached(self, note_id: object) -> tuple[str, str]:
        """Returns:
            ("", "") for no recording, else the id of a recording the hub
            keeps and the sha256 of its bytes.
        """
        if note_id == "":
            return "", ""
        if not isinstance(note_id, str):
            raise ToolError("voice must be a recording id or empty")
        try:
            wav = self.audio(note_id)
        except Missing:
            raise ToolError(f"no recording {note_id:.40}: it was never uploaded or is past the {VOICE_KEEP} kept") from None
        return note_id, hashlib.sha256(wav).hexdigest()

    @contextlib.contextmanager
    def held(self, note_id: object) -> Iterator[None]:
        """Args:
            note_id: a recording a message is about to carry; trim keeps it
                until the message is stored.
        """
        kept = isinstance(note_id, str) and NOTE_ID.fullmatch(note_id) is not None
        if kept:
            with self.lock:
                self.sending[note_id] += 1
        try:
            yield
        finally:
            if kept:
                with self.lock:
                    self.sending[note_id] -= 1
                    if not self.sending[note_id]:
                        del self.sending[note_id]

    def host_path(self, note_id: str) -> str:
        return str(self.host_folder / f"{note_id}.wav")

    def trim(self) -> None:
        with self.lock:
            spared = self.referenced() | set(self.sending)
            loose = [path for path in self.folder.glob("*.wav") if path.stem not in spared]
            for path in sorted(loose, key=lambda path: path.stat().st_mtime, reverse=True)[VOICE_KEEP:]:
                path.unlink(missing_ok=True)
                self.notes.pop(path.stem, None)
