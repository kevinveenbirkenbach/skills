from __future__ import annotations

import io
import os
import re
import secrets
import subprocess
import threading
import wave
from dataclasses import dataclass
from pathlib import Path

from .council import HUMAN
from .errors import EngineError, ToolError, Unavailable
from .fields import TEXT_LIMIT, bounded, decode, expect
from .phrasing import SPEECH_LIMIT, SPOKEN_LINE, phrase
from .records import digest, read_json
from .skill_scripts import SAFE_PATH

MODEL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
SPEAKER_LIMIT = 10000
TTS_TIMEOUT = 60
TTS_KEEP = 200
STT_RATE = 16000
STT_SECONDS = 120
STT_LIMIT = 44 + STT_RATE * 2 * STT_SECONDS
STT_TIMEOUT = 120
NOISE = re.compile(r"\[[^\]\n]{0,40}\]")


def installed_voices(folder: Path) -> dict[str, tuple[str, int | None]]:
    """Args:
        folder: directory holding <model>.onnx files with <model>.onnx.json.

    Returns:
        voice id <model>:<speaker> -> (model, speaker id or None for a model
        with one speaker), in model and speaker order; a model without a
        readable config or with an unsafe name is left out.
    """
    try:
        models = sorted(folder.glob("*.onnx"))
    except OSError:
        return {}
    found: dict[str, tuple[str, int | None]] = {}
    for model in models:
        data = read_json(model.with_name(f"{model.name}.json"))
        count = data.get("num_speakers") if isinstance(data, dict) else None
        if not MODEL_NAME.fullmatch(model.stem) or isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= SPEAKER_LIMIT:
            continue
        for speaker in range(count):
            found[f"{model.stem}:{speaker}"] = (model.stem, speaker if count > 1 else None)
    return found


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
        self.speaking = threading.Lock()
        self.hearing = threading.Lock()

    def env(self) -> dict[str, str]:
        scratch = str(self.engines.scratch)
        return {"PATH": SAFE_PATH, "HOME": scratch, "TMPDIR": scratch, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"}

    def speaks(self) -> bool:
        return bool(self.voices) and os.access(self.engines.piper, os.X_OK)

    def hears(self) -> bool:
        return os.access(self.engines.whisper, os.X_OK) and self.engines.whisper_model.is_file()

    def voice_of(self, key: str) -> str:
        return voice_of(key, self.pool, self.operator)

    def describe(self) -> dict:
        operator = self.voice_of(HUMAN)
        sample = phrase("broadcast", HUMAN, [], "radio check")
        return {"tts": self.speaks(), "stt": self.hears(), "voices": len(self.voices), "operator": operator, "sample": sample, "limit": SPEECH_LIMIT, "rate": STT_RATE, "seconds": STT_SECONDS}

    def synthesize(self, body: bytes) -> bytes:
        if not self.speaks():
            raise Unavailable("speech output is off: no Piper voice or executable is installed")
        payload = decode(body)
        expect(payload, ("text", "voice"))
        voice = payload["voice"]
        if not isinstance(voice, str) or voice not in self.voices:
            raise ToolError("voice must be one of the installed voices")
        line = " ".join(bounded(payload, "text", SPEECH_LIMIT).split())
        if not SPOKEN_LINE.fullmatch(line):
            raise ToolError(f"text must be 1 to {SPEECH_LIMIT} printable characters")
        key = digest(f"{voice}\n{line}")
        target = self.cache / f"{key}.wav"
        with self.speaking:
            if not target.is_file():
                self.render(voice, line, target)
                self.trim()
            os.utime(target)
            return target.read_bytes()

    def render(self, voice: str, line: str, target: Path) -> None:
        model, speaker = self.voices[voice]
        onnx = self.engines.voices / f"{model}.onnx"
        partial = self.cache / f".{target.stem}-{secrets.token_hex(4)}.wav"
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
            if done.returncode != 0 or not playable(partial):
                raise EngineError(f"piper failed with exit code {done.returncode}: {done.stderr.strip()[-300:]}")
            os.replace(partial, target)
        except subprocess.TimeoutExpired:
            raise EngineError(f"piper took longer than {TTS_TIMEOUT} seconds") from None
        except OSError as error:
            raise EngineError(f"piper did not start: {error.strerror}") from None
        finally:
            partial.unlink(missing_ok=True)

    def trim(self) -> None:
        kept = sorted(self.cache.glob("*.wav"), key=lambda path: path.stat().st_mtime, reverse=True)
        for path in kept[TTS_KEEP:]:
            path.unlink(missing_ok=True)

    def transcribe(self, body: bytes) -> dict:
        if not self.hears():
            raise Unavailable("speech input is off: whisper.cpp or its model is missing")
        wav_seconds(body)
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
