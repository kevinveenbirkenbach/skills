#!/usr/bin/env python3
"""Args:
    sample: append one row to <state>/samples.jsonl: {t, disks: [{mount,
        used, total}], cpu, ram, swap, load, gpus: [{name, util, vram_used,
        vram_total} | {name, asleep: true}], queue: {waiting, active},
        psi_some, psi_full, swap_out_mb_min}; t in epoch seconds, used, total
        and vram in bytes, cpu, ram, swap and util in percent, load the
        1-minute load average, a GPU named by its PCI address. cpu is the
        busy share of the /proc/stat ticks since those the run before kept in
        <state>/cpu.json as [t, idle, total], None on the first run and after
        a gap of more than 15 minutes. psi_some and psi_full are the avg10 of
        /proc/pressure/memory, None without PSI; swap_out_mb_min the MB per
        minute swapped out (pswpout of /proc/vmstat) since the count the run
        before kept in <state>/swap.json as [t, pswpout], None like cpu and
        after a counter reset. An NVIDIA GPU
        whose PCI runtime_status is not active is recorded asleep, and
        nvidia-smi is not run for it; an awake one nvidia-smi gives no
        reading for (no driver, a driver mismatch) keeps its name with util
        and vram None. In the first minute of a 15-minute bucket, rows older
        than 7 days fold into 15-minute means and means older than 90 days
        into one mean per day, kept forever, each row weighted by the seconds
        it sampled; a folded row carries span, the seconds its rows sampled
        (60 per raw row), and width, the seconds of its bucket.
    tokens: add the input, output, cache-read and cache-write tokens of the
        usage fields in the Claude Code transcripts under --transcripts since
        each file's byte offset to <state>/tokens.jsonl as {t, agent, model,
        input, output, cache_read, cache_write}, t the hour; agent is the
        name the council claim of the session carries, else the session id's
        first 8 characters. A message counts once by its message id and
        request id, also when written over several lines or copied into a
        fork's transcript. <state>/offsets.json holds {files: {path: offset},
        seen: {hour: [key digest]}}, seen keeping the hours this run read and
        the last two, and is replaced only when it changes. In the first
        minute of an hour, rows of the same hour, agent and model merge and
        the rows of a day that ended more than 90 days ago fold into one row
        per day, agent and model with width: 86400, kept forever.
    --state: the directory of these files, the unit passes
        ~/.local/state/agents-council/resources.
    --council: the council directory with queue.json and the claims.
    --transcripts (tokens): Claude Code's projects directory.
    --proc, --sys (sample): where /proc and /sys are mounted.

Returns:
    Runs on the host every minute through kvb-orchestrator-resources.timer,
    because the hub's container sees neither the host's disks, memory and
    GPUs nor its transcripts' offsets; nothing here calls a language model.
    The exit code is 0.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import datetime
import errno
import functools
import hashlib
import json
import os
import shutil
import stat
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

import queue_live

INTERVAL = 60
BUCKET = 900
HOUR = 3600
DAY = 86400
FINE = 7 * DAY
COARSE = 90 * DAY
COMMAND_SECONDS = 10
KEY_BYTES = 9
KIB = 1 << 10
MIB = 1 << 20
JSON_BYTES = 1 << 24
BUDGET = 64 << 20
NVIDIA = "0x10de"
DISPLAY = "0x03"
NVIDIA_QUERY = "pci.bus_id,utilization.gpu,memory.used,memory.total"
UNREAD = {"util": None, "vram_used": None, "vram_total": None}
COUNTS = (("input", "input_tokens"), ("output", "output_tokens"), ("cache_read", "cache_read_input_tokens"), ("cache_write", "cache_creation_input_tokens"))
NAMES = tuple(name for name, _ in COUNTS)
HOST_DIGITS = (("cpu", 1), ("ram", 1), ("swap", 1), ("load", 2), ("psi_some", 2), ("psi_full", 2), ("swap_out_mb_min", 1))
CLAIMS = ("*/claim.json", "*/*/claim.json")
SAMPLES = "samples.jsonl"
TOKENS = "tokens.jsonl"
OFFSETS = "offsets.json"
TICKS = "cpu.json"
SWAPPED = "swap.json"
PAGE_BYTES = os.sysconf("SC_PAGE_SIZE")
MB = 1_000_000


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def read_json(path: Path) -> object:
    """Returns:
        The parsed JSON of path, read without following a symlink and only
        from a regular file of at most JSON_BYTES; None when that fails.
    """
    try:
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                return None
            data = handle.read(JSON_BYTES + 1)
        return None if len(data) > JSON_BYTES else json.loads(data.decode("utf-8"))
    except (OSError, ValueError, RecursionError):
        return None


def number(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return None


def percent(part: float, whole: float | None) -> float | None:
    return round(100 * part / whole, 1) if whole else None


def command(argv: list[str]) -> str | None:
    if shutil.which(argv[0]) is None:
        return None
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=COMMAND_SECONDS, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def parse_df(text: str) -> list[dict]:
    """Returns:
        One {mount, used, total} in bytes per block device in the output of
        df -P -k, at the first mount df lists for it; loop devices and
        filesystems without a device are left out.
    """
    found, seen = [], set()
    for line in text.splitlines()[1:]:
        parts = line.split(None, 5)
        if len(parts) < 6 or not parts[0].startswith("/dev/") or parts[0].startswith("/dev/loop") or parts[0] in seen:
            continue
        total, used = number(parts[1]), number(parts[2])
        if total is None or used is None:
            continue
        seen.add(parts[0])
        found.append({"mount": parts[5], "used": int(used) * KIB, "total": int(total) * KIB})
    return found


def parse_meminfo(text: str) -> dict[str, int]:
    values = {}
    for line in text.splitlines():
        key, _, rest = line.partition(":")
        fields = rest.split()
        if fields and fields[0].isdigit():
            values[key.strip()] = int(fields[0])
    return values


def memory(values: dict[str, int]) -> tuple[float | None, float | None]:
    """Returns:
        RAM in use ((MemTotal - MemAvailable) / MemTotal) and swap in use in
        percent; swap is 0 without a swap device, None when unknown.
    """
    total, available = values.get("MemTotal"), values.get("MemAvailable")
    ram = percent(total - available, total) if total and available is not None else None
    swap_total, swap_free = values.get("SwapTotal"), values.get("SwapFree")
    if swap_total == 0:
        return ram, 0.0
    return ram, percent(swap_total - swap_free, swap_total) if swap_total and swap_free is not None else None


def cpu_ticks(text: str) -> tuple[int, int] | None:
    """Returns:
        (idle, total) ticks of the summary line of /proc/stat: idle counts
        idle and iowait, total the first eight fields, which already hold
        guest time.
    """
    fields = text.split("\n", 1)[0].split()
    if len(fields) < 6 or fields[0] != "cpu" or not all(field.isdigit() for field in fields[1:9]):
        return None
    values = [int(field) for field in fields[1:9]]
    return values[3] + values[4], sum(values)


def cpu_percent(before: tuple[int, int] | None, after: tuple[int, int] | None) -> float | None:
    if before is None or after is None:
        return None
    idle, total = after[0] - before[0], after[1] - before[1]
    return percent(total - idle, total) if total > 0 else None


def parse_loadavg(text: str) -> float | None:
    fields = text.split()
    return number(fields[0]) if fields else None


def parse_nvidia(text: str) -> dict[str, dict]:
    """Returns:
        Per PCI address (domain of 4 hex digits) {util, vram_used,
        vram_total} from the CSV nvidia-smi prints for NVIDIA_QUERY with
        noheader,nounits; vram in bytes, an unknown value None.
    """
    found = {}
    for line in text.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != 4:
            continue
        util, used, total = (number(part) for part in parts[1:])
        found[parts[0].lower()[-12:]] = {"util": util, "vram_used": None if used is None else int(used * MIB), "vram_total": None if total is None else int(total * MIB)}
    return found


def nvidia_gpus(sys_root: Path) -> list[tuple[str, bool]]:
    """Returns:
        The PCI address of every NVIDIA display controller under sys_root and
        whether its runtime_status reads active.
    """
    found = []
    for device in sorted((sys_root / "bus" / "pci" / "devices").glob("*")):
        if read_text(device / "vendor").strip() == NVIDIA and read_text(device / "class").strip().startswith(DISPLAY):
            found.append((device.name, read_text(device / "power" / "runtime_status").strip() == "active"))
    return found


def gpus(sys_root: Path, run: Callable[[list[str]], str | None]) -> list[dict]:
    devices = nvidia_gpus(sys_root)
    awake = [address for address, active in devices if active]
    readings = parse_nvidia(run(["nvidia-smi", f"--id={','.join(awake)}", f"--query-gpu={NVIDIA_QUERY}", "--format=csv,noheader,nounits"]) or "") if awake else {}
    return [{"name": address, **readings.get(address, UNREAD)} if active else {"name": address, "asleep": True} for address, active in devices]


def queue(council: Path) -> dict:
    """Returns:
        {waiting, active}: the queue.json entries with an enqueue time that
        queue_live.settled() keeps without an outcome, as the hub counts them.
    """
    data = read_json(council / "queue.json")
    entries = data.get("entries") if isinstance(data, dict) else None
    found = []
    for entry in entries if isinstance(entries, list) else []:
        created = queue_live.moment(entry.get("enqueued")) if isinstance(entry, dict) else None
        if created is not None:
            found.append((entry, created))
    history = functools.partial(queue_live.read_history, council / queue_live.HISTORY)
    statuses = [entry.get("status") for entry, _, result in queue_live.settled(council, found, history) if result is None]
    return {"waiting": statuses.count("waiting"), "active": statuses.count("active")}


def integers(value: object, size: int) -> bool:
    return isinstance(value, list) and len(value) == size and all(isinstance(item, int) and not isinstance(item, bool) for item in value)


def cpu_since(proc: Path, state: Path, t: int) -> float | None:
    """Returns:
        The busy share of the ticks in proc's stat since those the run
        before kept in <state>/cpu.json at most BUCKET seconds before t,
        else None; this run's ticks replace them.
    """
    ticks = cpu_ticks(read_text(proc / "stat"))
    stored = read_json(state / TICKS)
    before = (stored[1], stored[2]) if integers(stored, 3) and t - BUCKET <= stored[0] <= t else None
    if ticks is not None:
        replace(state / TICKS, json.dumps([t, *ticks]))
    return cpu_percent(before, ticks)


def psi_avg10(text: str, kind: str) -> float | None:
    for line in text.splitlines():
        fields = line.split()
        if fields[:1] == [kind]:
            values = dict(field.split("=", 1) for field in fields[1:] if "=" in field)
            return number(values.get("avg10", ""))
    return None


def swapped_pages(text: str) -> int | None:
    for line in text.splitlines():
        fields = line.split()
        if len(fields) == 2 and fields[0] == "pswpout" and fields[1].isdigit():
            return int(fields[1])
    return None


def swap_out_since(proc: Path, state: Path, t: int) -> float | None:
    """Returns:
        The MB per minute swapped out since the pswpout count the run before
        kept in <state>/swap.json at most BUCKET seconds before t, else None,
        also after a counter reset; this run's count replaces it.
    """
    pages = swapped_pages(read_text(proc / "vmstat"))
    if pages is None:
        return None
    stored = read_json(state / SWAPPED)
    replace(state / SWAPPED, json.dumps([t, pages]))
    if not integers(stored, 2) or not t - BUCKET <= stored[0] < t or stored[1] > pages:
        return None
    return round((pages - stored[1]) * PAGE_BYTES / MB * 60 / (t - stored[0]), 1)


def sample(proc: Path, sys_root: Path, council: Path, run: Callable[[list[str]], str | None], state: Path) -> dict:
    t = int(time.time())
    ram, swap = memory(parse_meminfo(read_text(proc / "meminfo")))
    pressure = read_text(proc / "pressure" / "memory")
    return {
        "t": t,
        "disks": parse_df(run(["df", "-P", "-k", "-l"]) or ""),
        "cpu": cpu_since(proc, state, t),
        "ram": ram,
        "swap": swap,
        "load": parse_loadavg(read_text(proc / "loadavg")),
        "gpus": gpus(sys_root, run),
        "queue": queue(council),
        "psi_some": psi_avg10(pressure, "some"),
        "psi_full": psi_avg10(pressure, "full"),
        "swap_out_mb_min": swap_out_since(proc, state, t),
    }


def is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def weight(row: dict) -> int | float:
    """Returns:
        The seconds row sampled: its span, INTERVAL for a raw row.
    """
    span = row.get("span")
    return span if is_number(span) and span > 0 else INTERVAL


def average(pairs: list[tuple[int | float, object]], digits: int) -> float | None:
    """Args:
        pairs: (weight, value) per reading; a value that is no number is
            left out.
    """
    found = [(part, value) for part, value in pairs if is_number(value)]
    total = sum(part for part, _ in found)
    return round(sum(part * value for part, value in found) / total, digits) if total else None


def whole(pairs: list[tuple[int | float, object]]) -> int | None:
    found = average(pairs, 0)
    return None if found is None else int(found)


def listed(rows: list[dict], key: str) -> list[tuple[int | float, dict]]:
    return [(weight(row), item) for row in rows if isinstance(row.get(key), list) for item in row[key] if isinstance(item, dict)]


def grouped(items: list[tuple[int | float, dict]], key: str) -> dict[object, list[tuple[int | float, dict]]]:
    found: dict[object, list[tuple[int | float, dict]]] = {}
    for part, item in items:
        found.setdefault(item.get(key), []).append((part, item))
    return found


def means(readings: list[tuple[int | float, dict]], key: str) -> list[tuple[int | float, object]]:
    return [(part, reading.get(key)) for part, reading in readings]


def gpu_mean(name: object, readings: list[tuple[int | float, dict]]) -> dict:
    awake = [(part, reading) for part, reading in readings if reading.get("asleep") is not True]
    if not awake:
        return {"name": name, "asleep": True}
    return {"name": name, "util": average(means(awake, "util"), 1), "vram_used": whole(means(awake, "vram_used")), "vram_total": whole(means(awake, "vram_total"))}


def disk_means(rows: list[dict]) -> list[dict]:
    return [{"mount": mount, "used": whole(means(disks, "used")), "total": whole(means(disks, "total"))} for mount, disks in grouped(listed(rows, "disks"), "mount").items()]


def queue_mean(rows: list[dict]) -> dict:
    queues = [(weight(row), row["queue"]) for row in rows if isinstance(row.get("queue"), dict)]
    return {key: average(means(queues, key), 2) for key in ("waiting", "active")}


def mean_row(start: int, width: int, rows: list[dict]) -> dict:
    """Returns:
        The mean of rows in the bucket of width seconds at start, each row
        weighted by weight(): per mount and per GPU the mean of the rows that
        list it, a GPU asleep in every row stays asleep; span the seconds the
        rows sampled together, width the bucket's.
    """
    host = {key: average([(weight(row), row.get(key)) for row in rows], digits) for key, digits in HOST_DIGITS}
    gpu_rows = [gpu_mean(name, readings) for name, readings in grouped(listed(rows, "gpus"), "name").items()]
    return {"t": start, "disks": disk_means(rows), **host, "gpus": gpu_rows, "queue": queue_mean(rows), "span": sum(weight(row) for row in rows), "width": width}


def folded(start: int, width: int, rows: list[dict]) -> dict:
    """Returns:
        The one row the bucket of width seconds at start keeps: a lone row
        at start already folded to width or wider unchanged; a lone row at
        start without span, a 15-minute mean written before folded rows
        carried span, with span and width the whole bucket; else mean_row().
    """
    if len(rows) == 1 and rows[0]["t"] == start:
        kept = rows[0].get("width")
        if is_number(kept) and kept >= width:
            return rows[0]
        if "span" not in rows[0]:
            return {**rows[0], "span": width, "width": width}
    return mean_row(start, width, rows)


def timed(row: object) -> bool:
    return isinstance(row, dict) and is_number(row.get("t"))


def fold(rows: list[dict], width: int, line: float) -> list[dict]:
    """Returns:
        rows with every bucket of width seconds that ended by line folded()
        into one row at its start, the other rows following unchanged and in
        order.
    """
    buckets: dict[int, list[dict]] = {}
    rest = []
    for row in rows:
        start = int(row["t"] // width * width)
        if start + width <= line:
            buckets.setdefault(start, []).append(row)
        else:
            rest.append(row)
    return [folded(start, width, buckets[start]) for start in sorted(buckets)] + rest


def retain(rows: list[dict], now: float) -> list[dict]:
    """Returns:
        rows with every 15-minute bucket that ended more than 7 days ago
        folded into one mean at its start, every day (UTC) that ended more
        than 90 days ago folded into one mean of those, kept forever, and the
        newer rows unchanged and in order; a folded row carries span, the
        seconds its rows sampled, and width, its bucket's seconds.
    """
    return fold(fold([row for row in rows if timed(row)], BUCKET, now - FINE), DAY, now - COARSE)


def read_rows(path: Path) -> list[dict]:
    rows = []
    for line in read_text(path).splitlines():
        try:
            row = json.loads(line)
        except (ValueError, RecursionError):
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def encoded(rows: list[dict]) -> str:
    return "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows)


def folder(path: Path) -> int:
    return os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)


def append_rows(path: Path, rows: list[dict]) -> None:
    """Args:
        path: the file; a link at it or its directory, or a file that is not
            regular with a single link, raises OSError.
        rows: appended as JSON lines.
    """
    if rows:
        parent = folder(path)
        try:
            fd = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, 0o600, dir_fd=parent)
        finally:
            os.close(parent)
        with open(fd, "a", encoding="utf-8") as handle:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise OSError(errno.EINVAL, "not a regular file with a single link", str(path))
            handle.write(encoded(rows))


def replace(path: Path, text: str) -> None:
    """Args:
        path: the file, replaced through a fresh temp file beside it; a link
            at its directory raises OSError, one at path is replaced.
        text: the new content.
    """
    parent = folder(path)
    temp = f".{path.name}.{os.urandom(8).hex()}"
    try:
        with open(os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=parent), "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(temp, path.name, src_dir_fd=parent, dst_dir_fd=parent)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temp, dir_fd=parent)
        raise
    finally:
        os.close(parent)


def rewrite(path: Path, keep: Callable[[list[dict], float], list[dict]], now: float) -> None:
    rows = read_rows(path)
    kept = keep(rows, now)
    if kept != rows:
        replace(path, encoded(kept))


def record(state: Path, row: dict, now: float) -> None:
    path = state / SAMPLES
    append_rows(path, [row])
    if now % BUCKET < INTERVAL:
        rewrite(path, retain, now)


def claim_names(council: Path) -> dict[str, str]:
    names = {}
    for pattern in CLAIMS:
        for path in sorted(council.glob(pattern)):
            data = read_json(path)
            if isinstance(data, dict) and isinstance(data.get("session"), str) and isinstance(data.get("name"), str) and data["name"].strip():
                names[data["session"]] = data["name"].strip()
    return names


def epoch(value: object) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.datetime.fromisoformat(value)
    except ValueError:
        return None
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=datetime.UTC)).timestamp()


def count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def assistant(raw: bytes) -> tuple[dict, dict, dict] | None:
    """Returns:
        (row, message, usage) of an assistant transcript line whose message
        carries a usage map and whose row a session id, else None.
    """
    try:
        row = json.loads(raw)
    except (ValueError, RecursionError):
        return None
    message = row.get("message") if isinstance(row, dict) and row.get("type") == "assistant" else None
    fields = message.get("usage") if isinstance(message, dict) else None
    return (row, message, fields) if isinstance(fields, dict) and isinstance(row.get("sessionId"), str) else None


def message_key(ident: object, request: object) -> str:
    """Returns:
        A short digest of (message id, request id), "" without a message id.
    """
    if not isinstance(ident, str) or not ident:
        return ""
    text = f"{ident}\0{request if isinstance(request, str) else ''}"
    return base64.urlsafe_b64encode(hashlib.blake2b(text.encode("utf-8"), digest_size=KEY_BYTES).digest()).decode("ascii")


def usage(raw: bytes) -> tuple[str, float, str, str, tuple[int, ...]] | None:
    """Returns:
        (message key, time, session, model, counts in COUNTS order) of an
        assistant transcript line with a usage field, a time and a model,
        else None.
    """
    found = assistant(raw)
    if found is None:
        return None
    row, message, fields = found
    ts, model = epoch(row.get("timestamp")), message.get("model")
    if ts is None or not isinstance(model, str):
        return None
    return message_key(message.get("id"), row.get("requestId")), ts, row["sessionId"], model, tuple(count(fields.get(field)) for _, field in COUNTS)


def first_sight(key: str, ts: float, seen: dict[int, set[str]], keys: dict[int, set[str]]) -> bool:
    """Returns:
        Whether the message key at ts is in neither seen nor keys at its hour
        or a neighbouring one, then files it in keys at its hour; a line
        without a key is always a first sight. The neighbours catch a copy a
        fork wrote seconds after the original across the hour.
    """
    if not key:
        return True
    hour = int(ts // HOUR * HOUR)
    known = any(key in found.get(near, ()) for found in (seen, keys) for near in (hour - HOUR, hour, hour + HOUR))
    keys.setdefault(hour, set()).add(key)
    return not known


def scan(path: Path, start: int, budget: int, seen: dict[int, set[str]]) -> tuple[int, list[tuple[float, str, str, tuple[int, ...]]], dict[int, set[str]]]:
    """Returns:
        The offset after the last complete line read from start, at most
        about budget bytes on, the usage of every message seen holds no key
        of, and per hour the keys of every message read.
    """
    found = []
    keys: dict[int, set[str]] = {}
    position = start
    with path.open("rb") as handle:
        handle.seek(start)
        for raw in handle:
            if not raw.endswith(b"\n") or position - start >= budget:
                break
            position += len(raw)
            read = usage(raw) if b'"usage"' in raw else None
            if read is not None and first_sight(read[0], read[1], seen, keys) and any(read[4]):
                found.append(read[1:])
    return position, found, keys


def token_rows(sums: dict[tuple, list[int]]) -> list[dict]:
    """Args:
        sums: per (t, agent, model, width) the counts in COUNTS order.

    Returns:
        One token row per key in key order; a row other than hourly names
        its width.
    """
    return [{"t": t, "agent": agent, "model": model, **dict(zip(NAMES, counts, strict=True)), **({} if width == HOUR else {"width": width})} for (t, agent, model, width), counts in sorted(sums.items())]


def token_key(row: dict, line: float) -> tuple:
    """Returns:
        (t, agent, model, width) of the row a token row merges into: its day
        (UTC) when the row is daily or the day ended by line, else its hour.
    """
    day = int(row["t"] // DAY * DAY)
    if row.get("width") == DAY or day + DAY <= line:
        return day, row["agent"], row["model"], DAY
    return row["t"], row["agent"], row["model"], HOUR


def add(sums: dict[tuple, list[int]], key: tuple, counts: tuple[int, ...]) -> None:
    total = sums.setdefault(key, [0] * len(COUNTS))
    for index, value in enumerate(counts):
        total[index] += value


def compact(rows: list[dict], now: float) -> list[dict]:
    """Returns:
        The token rows merged per token_key(), every day that ended more than
        90 days ago one row per agent and model, kept forever.
    """
    sums: dict[tuple, list[int]] = {}
    for row in rows:
        if timed(row) and isinstance(row.get("agent"), str) and isinstance(row.get("model"), str):
            add(sums, token_key(row, now - COARSE), tuple(count(row.get(name)) for name in NAMES))
    return token_rows(sums)


def start_of(entry: object, info: os.stat_result, now: float) -> int:
    if isinstance(entry, int) and not isinstance(entry, bool) and entry >= 0:
        return entry if entry <= info.st_size else 0
    return info.st_size if info.st_mtime < now - COARSE else 0


def read_transcript(path: Path, entry: object, budget: int, now: float, seen: dict[int, set[str]]) -> tuple[int, int, list, dict[int, set[str]]]:
    """Returns:
        (start, end, usages, keys per hour) of path read from the offset
        entry records, without reading once budget is spent.
    """
    info = path.stat()
    start = start_of(entry, info, now)
    if budget <= 0 or start >= info.st_size:
        return start, start, [], {}
    return start, *scan(path, start, budget, seen)


def seen_of(value: object) -> dict[int, set[str]]:
    if not isinstance(value, dict):
        return {}
    return {int(hour): {key for key in keys if isinstance(key, str)} for hour, keys in value.items() if hour.isdigit() and isinstance(keys, list)}


def kept_seen(seen: dict[int, set[str]], touched: set[int], now: float) -> dict[str, list[str]]:
    floor = now // HOUR * HOUR - HOUR
    return {str(hour): sorted(keys) for hour, keys in sorted(seen.items()) if hour in touched or hour >= floor}


def count_tokens(transcripts: Path, council: Path, state: Path, now: float, budget: int) -> list[dict]:
    """Returns:
        The rows appended to <state>/tokens.jsonl by this run.
    """
    stored = read_json(state / OFFSETS)
    offsets = stored.get("files") if isinstance(stored, dict) and isinstance(stored.get("files"), dict) else {}
    seen = seen_of(stored.get("seen") if isinstance(stored, dict) else None)
    names = claim_names(council)
    sums: dict[tuple, list[int]] = {}
    files, touched = {}, set()
    for path in sorted(transcripts.rglob("*.jsonl")):
        key = path.relative_to(transcripts).as_posix()
        try:
            start, end, found, keys = read_transcript(path, offsets.get(key), budget, now, seen)
        except OSError:
            if key in offsets:
                files[key] = offsets[key]
            continue
        files[key] = end
        budget -= end - start
        for hour, read in keys.items():
            seen.setdefault(hour, set()).update(read)
            touched.add(hour)
        for ts, session, model, counts in found:
            add(sums, (int(ts // HOUR * HOUR), names.get(session) or session[:8], model, HOUR), counts)
    rows = token_rows(sums)
    append_rows(state / TOKENS, rows)
    kept = {"files": files, "seen": kept_seen(seen, touched, now)}
    if kept != stored:
        replace(state / OFFSETS, json.dumps(kept, sort_keys=True, separators=(",", ":")))
    if now % HOUR < INTERVAL:
        rewrite(state / TOKENS, compact, now)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Sample the host's resources and count the transcripts' tokens for the Agent Orchestrator.")
    commands = parser.add_subparsers(dest="command", required=True)
    sampling, counting = commands.add_parser("sample"), commands.add_parser("tokens")
    for sub in (sampling, counting):
        sub.add_argument("--state", type=Path, required=True)
        sub.add_argument("--council", type=Path, required=True)
    sampling.add_argument("--proc", type=Path, required=True)
    sampling.add_argument("--sys", type=Path, required=True)
    counting.add_argument("--transcripts", type=Path, required=True)
    args = parser.parse_args()
    args.state.mkdir(parents=True, exist_ok=True)
    if args.command == "sample":
        row = sample(args.proc, args.sys, args.council, command, args.state)
        record(args.state, row, row["t"])
    else:
        count_tokens(args.transcripts, args.council, args.state, time.time(), BUDGET)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
