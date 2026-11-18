from __future__ import annotations

import json
import threading
import time
import unittest

import hub_support  # noqa: F401
from hub_case import HubCase
from kvb_orchestrator.livestate import LiveState


def counting(pause: float) -> tuple[list[int], object]:
    calls: list[int] = []

    def build() -> dict:
        calls.append(1)
        time.sleep(pause)
        return {"build": len(calls)}

    return calls, build


class TestLiveState(unittest.TestCase):
    def test_callers_arriving_during_a_build_wait_for_it_and_share_it(self):
        live = LiveState(60.0)
        calls, build = counting(0.3)
        results: list[dict] = []
        threads = [threading.Thread(target=lambda: results.append(live.shared("live", build))) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(5)
        self.assertEqual((len(calls), len(results)), (1, 4))
        self.assertTrue(all(result is results[0] for result in results))

    def test_a_zero_ttl_rebuilds_and_other_keys_build_on_their_own(self):
        live = LiveState(0.0)
        calls, build = counting(0.0)
        live.shared("live", build)
        live.shared("live", build)
        live.shared("track", build)
        self.assertEqual(len(calls), 3)

    def test_invalidate_ends_the_shared_build_at_once(self):
        live = LiveState(60.0)
        _, build = counting(0.0)
        first = live.shared("live", build)
        self.assertIs(live.shared("live", build), first)
        live.invalidate()
        self.assertEqual(live.shared("live", build), {"build": 2})

    def test_a_build_overtaken_by_invalidate_is_not_served_again(self):
        live = LiveState(60.0)
        started = threading.Event()

        def slow() -> dict:
            started.set()
            time.sleep(0.2)
            return {"stale": True}

        thread = threading.Thread(target=lambda: live.shared("live", slow))
        thread.start()
        started.wait(5)
        live.invalidate()
        thread.join(5)
        self.assertEqual(live.shared("live", lambda: {"stale": False}), {"stale": False})


class TestLiveStateRoute(HubCase):
    def live_ttl(self) -> float:
        return 60.0

    def test_polls_share_one_state_until_a_post_or_a_window_query(self):
        first = self.snapshot()
        self.assertEqual(self.snapshot()["now"], first["now"])
        status, _, body = self.get(f"/api/state?to={first['now']}")
        self.assertEqual(status, 200, body)
        self.assertGreater(json.loads(body)["now"], first["now"])
        self.post_json("/api/inbox/mark", {}, self.guard(self.host))
        self.assertGreater(self.snapshot()["now"], first["now"])


if __name__ == "__main__":
    unittest.main()
