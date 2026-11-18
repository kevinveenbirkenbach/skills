from __future__ import annotations

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
        self.built: dict[object, tuple[int, float, dict]] = {}
        self.generation = 0

    def invalidate(self) -> None:
        with self.guard:
            self.generation += 1

    def shared(self, key: object, build: Callable[[], dict]) -> dict:
        """Returns:
            build()'s result; callers arriving while it runs wait for it and
            share it, and so do callers within ttl after it, until
            invalidate() is called.
        """
        with self.guard:
            lock = self.locks.setdefault(key, threading.Lock())
        with lock:
            with self.guard:
                generation = self.generation
                hit = self.built.get(key)
            if hit is not None and hit[0] == generation and time.monotonic() - hit[1] < self.ttl:
                return hit[2]
            value = build()
            with self.guard:
                self.built[key] = (generation, time.monotonic(), value)
            return value
