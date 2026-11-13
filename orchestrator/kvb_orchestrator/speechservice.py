from __future__ import annotations

import json
import secrets
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from . import transport
from .errors import EngineError, ToolError
from .keys import bearer, sealed

SPEECH_PATH = "/audio/speech"
HEARING_PATH = "/audio/transcriptions"
SPEECH_MODEL = "tts-1"
HEARING_MODEL = "whisper-1"
SERVICE_TIMEOUT = 120
SPOKEN_REPLY = 32 << 20
HEARD_REPLY = 1 << 20
SCHEMES = frozenset({"http", "https"})


def service_base(url: str) -> bool:
    """Returns:
        Whether url is a printable ASCII http or https URL with a host and a
        port from 1 to 65535 if any, without whitespace, userinfo, query,
        fragment or percent escape, so no credential travels in it.
    """
    if not (url.isascii() and url.isprintable()) or any(mark in url for mark in " @?#%"):
        return False
    try:
        parts = urlsplit(url)
        port_valid = parts.port != 0
    except ValueError:
        return False
    return port_valid and parts.scheme in SCHEMES and bool(parts.hostname)


def form(fields: dict[str, str], name: str, wav: bytes) -> tuple[bytes, str]:
    """Args:
        fields: the plain form fields.
        name: the field the WAV file travels in.
        wav: the recording.

    Returns:
        The multipart/form-data body and its content type.
    """
    boundary = secrets.token_hex(16)
    while boundary.encode() in wav:
        boundary = secrets.token_hex(16)
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode() for key, value in fields.items()]
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="recording.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode() + wav + b"\r\n")
    return b"".join(parts) + f"--{boundary}--\r\n".encode(), f"multipart/form-data; boundary={boundary}"


@dataclass(frozen=True)
class Service:
    """Args:
        url: base URL of an OpenAI-compatible audio API with its /v1, such as
            svc-ai-speech or the LiteLLM route to it; empty keeps the
            in-container engines.
        key: the bearer key the service expects; empty sends none. It never
            shows in the repr or in any message.
    """

    url: str
    key: str = field(repr=False)

    def __post_init__(self) -> None:
        if self.url and not service_base(self.url):
            raise ToolError("the speech service URL must be http or https with a host and without userinfo, query or fragment")
        if self.key and not bearer(self.key):
            raise ToolError("the speech service key must be printable ASCII without whitespace: check KVB_ORCHESTRATOR_SPEECH_KEY_FILE")
        if self.url and self.key and not sealed(self.url):
            raise ToolError("the speech service key travels only over https or to 127.0.0.1, localhost or ::1: set an https KVB_ORCHESTRATOR_SPEECH_URL or empty KVB_ORCHESTRATOR_SPEECH_KEY_FILE")

    def enabled(self) -> bool:
        return bool(self.url)

    def post(self, path: str, body: bytes, kind: str, limit: int) -> bytes:
        """Returns:
            The body of a 200 answer, within SERVICE_TIMEOUT seconds of wall
            clock for the whole call.

        Raises:
            EngineError for every failure, naming a status, a limit or an
            exception type only.
        """
        headers = {"Content-Type": kind, "Accept": "*/*"}
        if self.key:
            headers["Authorization"] = f"Bearer {self.key}"
        try:
            return transport.post(f"{self.url.rstrip('/')}{path}", body, headers, limit, SERVICE_TIMEOUT)
        except transport.Failure as failure:
            raise EngineError(f"the speech service {failure}") from None

    def speak(self, voice: str, line: str) -> bytes:
        """Returns:
            The WAV the service renders of line in voice, unchecked.
        """
        body = json.dumps({"model": SPEECH_MODEL, "input": line, "voice": voice, "response_format": "wav"}).encode()
        return self.post(SPEECH_PATH, body, "application/json", SPOKEN_REPLY)

    def hear(self, wav: bytes) -> str:
        """Returns:
            The transcript the service hears in the recording.
        """
        body, kind = form({"model": HEARING_MODEL, "response_format": "json"}, "file", wav)
        reply = self.post(HEARING_PATH, body, kind, HEARD_REPLY)
        try:
            text = json.loads(reply)["text"]
        except (ValueError, RecursionError, KeyError, IndexError, TypeError):
            raise EngineError("the speech service answered no transcript") from None
        if not isinstance(text, str):
            raise EngineError("the speech service answered no transcript")
        return text
