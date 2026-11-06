"""Open, read, lock, append, replace and unlink files below a trusted directory without following a symlink.

The council root is writable by every sandboxed agent of the same uid, while
its hooks run outside the sandbox: a symlink planted at any name or directory
below the root would turn a hook's read or write into one outside it, and a
FIFO planted at a name would hang every agent's hook. Every function here
opens the root and each directory below it with O_NOFOLLOW, relative to the
directory before, and the final name with O_NOFOLLOW and O_NONBLOCK; a planted
symlink, a `..` part, a path outside the root or anything but a regular file
raises OSError.
"""

from __future__ import annotations

import contextlib
import errno
import fcntl
import os
import stat
import time
from collections.abc import Iterator
from pathlib import Path
from typing import TextIO

DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
DIRECTORY_MODE = 0o700
READ_LIMIT = 1 << 26
LOCK_POLL = 0.05


def parts_below(root: Path, path: Path) -> tuple[str, ...]:
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        parts = ()
    if not parts or ".." in parts:
        raise OSError(errno.EINVAL, f"not a path below {root}", str(path))
    return parts


def directory(root: Path, parts: tuple[str, ...], create: bool) -> int:
    fd = os.open(root, DIRECTORY)
    try:
        for part in parts:
            if create:
                with contextlib.suppress(FileExistsError):
                    os.mkdir(part, DIRECTORY_MODE, dir_fd=fd)
            child = os.open(part, DIRECTORY, dir_fd=fd)
            os.close(fd)
            fd = child
    except BaseException:
        os.close(fd)
        raise
    return fd


def open_below(root: Path, path: Path, flags: int, mode: int) -> int:
    """Open a file below root.

    Args:
      root: the trusted directory; a symlink there is refused too.
      path: the file, below root; with O_CREAT in flags its missing
        directories are made with mode 0o700.
      flags: os.open flags; O_NOFOLLOW, O_NONBLOCK and O_CLOEXEC are added.
      mode: permission bits of a created file.

    Returns:
      The file descriptor of a regular file; the caller closes it.
    """
    *dirs, name = parts_below(root, path)
    fd = directory(root, tuple(dirs), bool(flags & os.O_CREAT))
    try:
        file = os.open(name, flags | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, mode, dir_fd=fd)
    finally:
        os.close(fd)
    if not stat.S_ISREG(os.fstat(file).st_mode):
        os.close(file)
        raise OSError(errno.EINVAL, "not a regular file", str(path))
    return file


def read_text(root: Path, path: Path) -> str:
    """Read a regular file below root.

    Args:
      root: the trusted directory.
      path: the file, below root; one over READ_LIMIT bytes raises OSError.

    Returns:
      Its content, UTF-8 decoded, undecodable bytes replaced.
    """
    with open(open_below(root, path, os.O_RDONLY, 0), "rb") as handle:
        data = handle.read(READ_LIMIT + 1)
    if len(data) > READ_LIMIT:
        raise OSError(errno.EFBIG, f"larger than {READ_LIMIT} bytes", str(path))
    return data.decode("utf-8", errors="replace")


@contextlib.contextmanager
def locked(root: Path, path: Path, mode: int, wait: float | None) -> Iterator[TextIO]:
    """Hold an exclusive flock on a lock file below root, created without truncation.

    Args:
      root: the trusted directory.
      path: the lock file, below root.
      mode: permission bits of a created lock file.
      wait: seconds to wait for the lock before TimeoutError, or None to wait
        as long as another holder keeps it.

    Yields:
      The open lock file.
    """
    with open(open_below(root, path, os.O_WRONLY | os.O_CREAT, mode), "w", encoding="utf-8") as handle:
        if wait is None:
            fcntl.flock(handle, fcntl.LOCK_EX)
        else:
            deadline = time.monotonic() + wait
            while not try_lock(handle):
                if time.monotonic() >= deadline:
                    raise TimeoutError(errno.ETIMEDOUT, f"lock held for over {wait} s", str(path))
                time.sleep(LOCK_POLL)
        yield handle


def try_lock(handle: TextIO) -> bool:
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    return True


def append(root: Path, path: Path, text: str, mode: int) -> None:
    """Append text to a file below root.

    Args:
      root: the trusted directory.
      path: the file, below root.
      text: what to append, UTF-8 encoded.
      mode: permission bits of a created file.
    """
    with open(open_below(root, path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, mode), "a", encoding="utf-8") as handle:
        handle.write(text)


def replace(root: Path, path: Path, text: str, mode: int) -> None:
    """Replace a file below root atomically through a fresh temp file beside it.

    Args:
      root: the trusted directory.
      path: the file, below root; a symlink there is replaced, never followed.
      text: the new content, UTF-8 encoded.
      mode: permission bits of the new file.
    """
    *dirs, name = parts_below(root, path)
    fd = directory(root, tuple(dirs), True)
    try:
        temp = f".{name}.{os.urandom(8).hex()}"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
        try:
            with open(os.open(temp, flags, mode, dir_fd=fd), "w", encoding="utf-8") as handle:
                handle.write(text)
            os.replace(temp, name, src_dir_fd=fd, dst_dir_fd=fd)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(temp, dir_fd=fd)
            raise
    finally:
        os.close(fd)


def unlink(root: Path, path: Path) -> None:
    """Remove a name below root; a symlink there is removed, never followed.

    Args:
      root: the trusted directory.
      path: the name, below root.
    """
    *dirs, name = parts_below(root, path)
    fd = directory(root, tuple(dirs), False)
    try:
        os.unlink(name, dir_fd=fd)
    finally:
        os.close(fd)
