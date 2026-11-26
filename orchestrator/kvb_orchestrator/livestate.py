from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable

LIVE_TTL = 2.0


class LiveState:
    def __init__(self, ttl: float) -> None:
        """Args:
            ttl: seconds a finished build serves later callers of the same
                key; 0 rebuilds every time but still one build at a time.
        """
        self.ttl = ttl
        self.guard = threading.Lock()
        self.locks: dict[object, threading.Lock] = {}
        self.built: dict[object, tuple[int, float, dict, bytes]] = {}
        self.generation = 0

    def invalidate(self) -> None:
        with self.guard:
            self.generation += 1

    def slot(self, moment: float) -> float:
        """Returns:
            moment rounded down to a multiple of ttl, so polls whose window
            starts within one ttl share a key; moment itself for a zero ttl.
        """
        return moment - moment % self.ttl if self.ttl > 0 else moment

    def shared(self, key: object, build: Callable[[], dict]) -> dict:
        """Returns:
            build()'s result; callers arriving while it runs wait for it and
            share it, and so do callers within ttl after it, until
            invalidate() is called.
        """
        return self.entry(key, build)[0]

    def encoded(self, key: object, build: Callable[[], dict]) -> bytes:
        """Returns:
            The JSON bytes of shared(key, build), encoded once per build.
        """
        return self.entry(key, build)[1]

    def entry(self, key: object, build: Callable[[], dict]) -> tuple[dict, bytes]:
        with self.guard:
            lock = self.locks.setdefault(key, threading.Lock())
        with lock:
            with self.guard:
                generation = self.generation
                hit = self.built.get(key)
            if hit is not None and hit[0] == generation and time.monotonic() - hit[1] < self.ttl:
                return hit[2], hit[3]
            value = build()
            body = json.dumps(value).encode()
            with self.guard:
                at = time.monotonic()
                self.built = {old: found for old, found in self.built.items() if at - found[1] < self.ttl}
                self.built[key] = (generation, at, value, body)
                self.locks = {old: held for old, held in self.locks.items() if old in self.built}
            return value, body
