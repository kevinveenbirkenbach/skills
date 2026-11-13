from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from .errors import ToolError

KEY_LIMIT = 4096
LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})


def bearer(key: str) -> bool:
    """Returns:
        Whether key is printable ASCII without whitespace, the only shape an
        Authorization header carries.
    """
    return key.isascii() and key.isprintable() and not any(character.isspace() for character in key)


def sealed(url: str) -> bool:
    """Returns:
        Whether a bearer key sent to url stays off the open network: an https
        URL or one whose host is 127.0.0.1, localhost or ::1; False for a URL
        that does not parse.
    """
    try:
        parts = urlsplit(url)
        return parts.scheme == "https" or parts.hostname in LOOPBACK
    except ValueError:
        return False


def key_from(path: Path, owner: str) -> str:
    """Args:
        path: a bearer key file; an empty file such as /dev/null means no key.
        owner: what the key is for, such as "speech service", named in the
            message.

    Returns:
        The key without the whitespace around it.

    Raises:
        ToolError naming the path, never its content, when the file cannot be
        read as UTF-8 text or holds more than KEY_LIMIT bytes; at most
        KEY_LIMIT + 1 bytes are read, so /dev/zero fails at once.
    """
    try:
        with path.open("rb") as handle:
            data = handle.read(KEY_LIMIT + 1)
        if len(data) > KEY_LIMIT:
            raise ToolError(f"the {owner} key file {path} holds more than {KEY_LIMIT} bytes")
        return data.decode("utf-8").strip()
    except (OSError, ValueError):
        raise ToolError(f"the {owner} key file {path} is unreadable") from None
