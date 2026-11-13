from __future__ import annotations

import io
import os
import re
import secrets
import struct
import subprocess
import threading
import time
import wave
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .council import HUMAN
from .errors import EngineError, ToolError, Unavailable
from .fields import TEXT_LIMIT, bounded, decode, expect
from .phrasing import PROCEDURE_LINES, SPEECH_LIMIT, SPOKEN_LINE, phrase
from .records import digest, read_json
from .skill_scripts import SAFE_PATH
from .speechservice import Service

MODEL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
SPEAKER_LIMIT = 10000
TTS_TIMEOUT = 120
TTS_KEEP = 200
WORD_CACHE = "word-"
STT_RATE = 16000
STT_SECONDS = 120
STT_LIMIT = 44 + STT_RATE * 2 * STT_SECONDS
STT_TIMEOUT = 120
HEARING_WINDOW = 60
HEARING_RATE = 6
HEARING_HOUR = 3600
HEARING_BUDGET = 5 * STT_SECONDS
NOISE = re.compile(r"\[[^\]\n]{0,40}\]")
PLACEHOLDERS = frozenset({0, 0xFFFFFFFF})


def voice_models(folder: Path) -> list[Path]:
    try:
        return sorted(folder.glob("*.onnx"))
    except OSError:
        return []


def installed_voices(folder: Path) -> dict[str, tuple[str, int | None]]:
    """Args:
        folder: directory holding <model>.onnx files with <model>.onnx.json.

    Returns:
        voice id <model>:<speaker> -> (model, speaker id or None for a model
        with one speaker), in model and speaker order; a model without a
        readable config or with an unsafe name is left out.
    """
    found: dict[str, tuple[str, int | None]] = {}
    for model in voice_models(folder):
        data = read_json(model.with_name(f"{model.name}.json"))
        count = data.get("num_speakers") if isinstance(data, dict) else None
        if not MODEL_NAME.fullmatch(model.stem) or isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= SPEAKER_LIMIT:
            continue
        for speaker in range(count):
            found[f"{model.stem}:{speaker}"] = (model.stem, speaker if count > 1 else None)
    return found


def unreachable(path: Path, part: str, mode: int, ability: str) -> str:
    """Args:
        path: a file or directory an engine needs.
        part: what path is, such as "the Piper executable".
        mode: the os.access mode the hub needs on path.
        ability: what path must be for that mode, such as "executable".

    Returns:
        "" when the hub may use path, otherwise a message naming path and
        the first directory above it the hub may not search, if any.
    """
    if os.access(path, mode):
        return ""
    closed = next((folder for folder in reversed(path.parents) if not os.access(folder, os.X_OK)), None)
    if closed is not None:
        return f"{part} {path} lies under {closed}, which the hub may not search"
    return f"{part} {path} is missing or not {ability}"


def voice_of(key: str, pool: list[str], operator: str) -> str:
    """Args:
        key: the speaker's session id or directory key; HUMAN is the operator.
        pool: the installed voice ids other than the operator's, in their
            fixed order.
        operator: the operator's voice; empty when no voice is installed.

    Returns:
        operator for HUMAN or when the pool is empty, otherwise the voice
        sha256(key) picks from the pool.
    """
    if key == HUMAN or not pool:
        return operator
    return pool[int(digest(key), 16) % len(pool)]


def wav_seconds(body: bytes) -> float:
    try:
        with wave.open(io.BytesIO(body), "rb") as reader:
            shape = (reader.getnchannels(), reader.getsampwidth(), reader.getframerate(), reader.getcomptype())
            frames = reader.getnframes()
    except (wave.Error, EOFError):
        raise ToolError("the recording must be a WAV file") from None
    if shape != (1, 2, STT_RATE, "NONE"):
        raise ToolError(f"the recording must be {STT_RATE} Hz mono 16-bit PCM")
    if not 0 < frames <= STT_RATE * STT_SECONDS:
        raise ToolError(f"the recording must last more than 0 and at most {STT_SECONDS} seconds")
    return frames / STT_RATE


def whole_wav(body: bytes) -> bytes | None:
    """Returns:
        body if it is a RIFF WAVE whose RIFF size matches the bytes received
        and whose chunks, a non-empty data chunk among them, all end within
        those bytes; a streamed WAVE, whose RIFF size is a placeholder in
        PLACEHOLDERS, only if its data chunk is the last chunk and runs to the
        end of the body, returned with both sizes set to the bytes received;
        None for every other body.
    """
    if len(body) < 12 or body[:4] != b"RIFF" or body[8:12] != b"WAVE":
        return None
    riff = struct.unpack_from("<I", body, 4)[0]
    streamed = riff in PLACEHOLDERS
    if not streamed and riff + 8 != len(body):
        return None
    offset, data = 12, False
    while offset + 8 <= len(body):
        name, size = body[offset : offset + 4], struct.unpack_from("<I", body, offset + 4)[0]
        start = offset + 8
        if streamed and name == b"data":
            if start == len(body) or (size not in PLACEHOLDERS and start + size != len(body)):
                return None
            return b"RIFF" + struct.pack("<I", len(body) - 8) + body[8 : offset + 4] + struct.pack("<I", len(body) - start) + body[start:]
        if start + size > len(body):
            return None
        data = data or (name == b"data" and size > 0)
        offset = start + size + (size & 1)
    return body if data and not streamed and offset in (len(body), len(body) + 1) else None


def playable(path: Path) -> bool:
    try:
        with wave.open(str(path), "rb") as reader:
            return reader.getnframes() > 0
    except (OSError, wave.Error, EOFError):
        return False


def heard(output: str) -> str:
    return " ".join(NOISE.sub(" ", output).split())[:TEXT_LIMIT]


@dataclass(frozen=True)
class Engines:
    piper: Path
    voices: Path
    operator_voice: str
    whisper: Path
    whisper_model: Path
    scratch: Path
    service: Service


class Speech:
    def __init__(self, engines: Engines, cache: Path) -> None:
        self.engines = engines
        self.cache = cache
        cache.mkdir(exist_ok=True)
        self.voices = installed_voices(engines.voices)
        if self.voices and engines.operator_voice not in self.voices:
            raise ToolError(f"the operator voice {engines.operator_voice!r} is not installed in {engines.voices}")
        self.operator = engines.operator_voice if self.voices else ""
        self.pool = [voice for voice in self.voices if voice != self.operator]
        self.handed = {self.operator} if self.operator else set()
        self.speaking = threading.Lock()
        self.hearing = threading.Lock()
        self.metering = threading.Lock()
        self.admitted: list[tuple[float, float]] = []

    def env(self) -> dict[str, str]:
        scratch = str(self.engines.scratch)
        return {"PATH": SAFE_PATH, "HOME": scratch, "TMPDIR": scratch, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"}

    def output_gap(self) -> str:
        """Returns:
            "" when speech output works, otherwise why not, naming the Piper
            executable, the voice directory or a voice config with its path;
            with the speech service the voices still come from the voice
            directory, and no Piper runs here.
        """
        folder = self.engines.voices
        piper = "" if self.engines.service.enabled() else unreachable(self.engines.piper, "the Piper executable", os.X_OK, "executable")
        gap = piper or unreachable(folder, "the voice directory", os.R_OK | os.X_OK, "searchable")
        if gap or self.voices:
            return gap
        models = voice_models(folder)
        if not models:
            return f"the voice directory {folder} holds no <model>.onnx voice"
        return f"the voice config {models[0]}.json is missing, unreadable or names no 1 to {SPEAKER_LIMIT} speakers"

    def input_gap(self) -> str:
        """Returns:
            "" when speech input works, otherwise why not, naming the
            whisper.cpp executable or model with its path; always "" with the
            speech service.
        """
        if self.engines.service.enabled():
            return ""
        model = self.engines.whisper_model
        gap = unreachable(self.engines.whisper, "the whisper.cpp executable", os.X_OK, "executable") or unreachable(model, "the whisper.cpp model", os.R_OK, "readable")
        return gap or ("" if os.path.isfile(model) else f"the whisper.cpp model {model} is not a file")

    def voice_of(self, key: str) -> str:
        """Args:
            key: the speaker's session id or directory key.

        Returns:
            The speaker's voice, which /api/tts accepts from then on.
        """
        voice = voice_of(key, self.pool, self.operator)
        self.handed.add(voice)
        return voice

    def describe(self) -> dict:
        operator = self.voice_of(HUMAN)
        sample = phrase("broadcast", HUMAN, [], "radio check")
        silent, deaf = self.output_gap(), self.input_gap()
        return {
            "tts": not silent, "stt": not deaf, "tts_off": silent, "stt_off": deaf, "voices": len(self.voices), "operator": operator, "sample": sample,
            "limit": SPEECH_LIMIT, "rate": STT_RATE, "seconds": STT_SECONDS,
        }

    def synthesize(self, body: bytes, admit: Callable[[str], None]) -> bytes:
        """Args:
            body: {"text", "voice"} as JSON.
            admit: called with a line before it renders and not for a cached
                one; it raises to hold the render back.

        Returns:
            The WAV of the line, from the cache when rendered before.
        """
        gap = self.output_gap()
        if gap:
            raise Unavailable(f"speech output is off: {gap}")
        payload = decode(body)
        expect(payload, ("text", "voice"))
        voice = payload["voice"]
        if not isinstance(voice, str) or voice not in self.voices:
            raise ToolError("voice must be one of the installed voices")
        if voice not in self.handed:
            raise ToolError("voice must be one the hub hands out to a speaker")
        line = " ".join(bounded(payload, "text", SPEECH_LIMIT).split())
        if not SPOKEN_LINE.fullmatch(line):
            raise ToolError(f"text must be 1 to {SPEECH_LIMIT} printable characters")
        key = digest(f"{voice}\n{line}")
        target = self.cache / f"{WORD_CACHE if line in PROCEDURE_LINES else ''}{key}.wav"
        with self.speaking:
            if not target.is_file():
                admit(line)
                self.render(voice, line, target)
                self.trim()
            os.utime(target)
            return target.read_bytes()

    def render(self, voice: str, line: str, target: Path) -> None:
        partial = self.cache / f".{target.stem}-{secrets.token_hex(4)}.wav"
        try:
            if self.engines.service.enabled():
                spoken = whole_wav(self.engines.service.speak(voice, line))
                if spoken is None:
                    raise EngineError("the speech service answered no complete WAV")
                partial.write_bytes(spoken)
                if not playable(partial):
                    raise EngineError("the speech service answered no playable WAV")
            else:
                self.piper(voice, line, partial)
            os.replace(partial, target)
        finally:
            partial.unlink(missing_ok=True)

    def piper(self, voice: str, line: str, partial: Path) -> None:
        model, speaker = self.voices[voice]
        onnx = self.engines.voices / f"{model}.onnx"
        command = [str(self.engines.piper), "--model", str(onnx), "--config", f"{onnx}.json", "--output-file", str(partial)]
        command += [] if speaker is None else ["--speaker", str(speaker)]
        try:
            done = subprocess.run(
                command,
                input=f"{line}\n",
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=TTS_TIMEOUT,
                env=self.env(),
                cwd=self.engines.scratch,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise EngineError(f"piper took longer than {TTS_TIMEOUT} seconds") from None
        except OSError as error:
            raise EngineError(f"piper did not start: {error.strerror}") from None
        if done.returncode != 0 or not playable(partial):
            raise EngineError(f"piper failed with exit code {done.returncode}: {done.stderr.strip()[-300:]}")

    def trim(self) -> None:
        spoken = (path for path in self.cache.glob("*.wav") if not path.name.startswith(WORD_CACHE))
        kept = sorted(spoken, key=lambda path: path.stat().st_mtime, reverse=True)
        for path in kept[TTS_KEEP:]:
            path.unlink(missing_ok=True)

    def admit(self, seconds: float) -> None:
        """Raises:
            Unavailable when HEARING_RATE recordings were admitted in the last
            HEARING_WINDOW seconds, or when this one would take the audio
            admitted in the last hour past HEARING_BUDGET seconds.
        """
        now = time.monotonic()
        with self.metering:
            recent = [(at, length) for at, length in self.admitted if at > now - HEARING_HOUR]
            if sum(1 for at, _ in recent if at > now - HEARING_WINDOW) >= HEARING_RATE:
                raise Unavailable(f"the hub transcribes at most {HEARING_RATE} recordings per {HEARING_WINDOW} s: try again in a minute")
            if sum(length for _, length in recent) + seconds > HEARING_BUDGET:
                raise Unavailable(f"the hub transcribes at most {HEARING_BUDGET} s of audio per hour; the budget refills as the hour passes")
            self.admitted = [*recent, (now, seconds)]

    def transcribe(self, body: bytes) -> dict:
        gap = self.input_gap()
        if gap:
            raise Unavailable(f"speech input is off: {gap}")
        self.admit(wav_seconds(body))
        return self.whisper(body)

    def whisper(self, body: bytes) -> dict:
        if self.engines.service.enabled():
            with self.hearing:
                return {"text": heard(self.engines.service.hear(body))}
        command = [str(self.engines.whisper), "--model", str(self.engines.whisper_model), "--file", "-", "--output-txt", "--language", "auto", "--no-prints", "--suppress-nst"]
        with self.hearing:
            try:
                done = subprocess.run(command, input=body, capture_output=True, timeout=STT_TIMEOUT, env=self.env(), cwd=self.engines.scratch, check=False)
            except subprocess.TimeoutExpired:
                raise EngineError(f"whisper.cpp took longer than {STT_TIMEOUT} seconds") from None
            except OSError as error:
                raise EngineError(f"whisper.cpp did not start: {error.strerror}") from None
        if done.returncode != 0:
            raise EngineError(f"whisper.cpp failed with exit code {done.returncode}: {done.stderr.decode('utf-8', errors='replace').strip()[-300:]}")
        return {"text": heard(done.stdout.decode("utf-8", errors="replace"))}
