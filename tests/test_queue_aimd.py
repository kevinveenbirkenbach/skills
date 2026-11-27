"""Exercise the self-tuning queue of requirement 083: the AIMD target, the settle window and the p95 footprints with their margin."""

from __future__ import annotations

import unittest

import test_queue as fixtures

AIMD = fixtures.REPO_ROOT / "skills" / "kvb-org-queue" / "scripts" / "aimd.py"
NOW = fixtures.NOW
BAND = {"low": {"ram": 70, "cpu": 70}, "high": {"ram": 90, "cpu": 90}}
CALM = {"psi_some": 0.2, "swap_out_mb_min": 0.0}
EVERY = 20


def peak(seq: int, ram: float, cpu: float, **fields: object) -> dict:
    return fixtures.history_row(seq, mem_before=20, mem_max=20 + ram, cpu_before=10, cpu_max=10 + cpu, end=NOW - 100 + seq, **fields)


class TestTarget(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.aimd = fixtures._load(AIMD)

    def poll(self, state: dict, at: float, load: dict[str, float], pressure: dict[str, float | None]) -> tuple[dict, dict]:
        state = self.aimd.stepped(state, BAND, load, pressure, 1.0, at, EVERY)
        return state, self.aimd.target(state, BAND)

    def test_a_fresh_target_starts_at_the_upper_limit_and_a_stored_one_stays_inside_the_band(self):
        self.assertEqual(self.aimd.target({}, BAND), {"ram": 90, "cpu": 90})
        self.assertEqual(self.aimd.target({"ram": 50, "cpu": 99}, BAND), {"ram": 70, "cpu": 90})
        self.assertEqual(self.aimd.target({"ram": "80", "cpu": True}, BAND), {"ram": 90, "cpu": 90})

    def test_below_the_lower_limit_the_target_rises_by_2_per_poll_up_to_the_upper_limit(self):
        state, seen = {"ram": 70, "cpu": 76}, []
        for n in range(12):
            state, aim = self.poll(state, NOW + n * EVERY, {"ram": 40, "cpu": 30}, CALM)
            seen.append(aim)
        self.assertEqual([aim["ram"] for aim in seen], [72, 74, 76, 78, 80, 82, 84, 86, 88, 90, 90, 90])
        self.assertEqual([aim["cpu"] for aim in seen[:8]], [78, 80, 82, 84, 86, 88, 90, 90])

    def test_a_pass_inside_the_step_interval_only_adds_its_sample(self):
        state, aim = self.poll({"ram": 70, "cpu": 70}, NOW, {"ram": 40, "cpu": 30}, CALM)
        self.assertEqual(aim, {"ram": 72, "cpu": 72})
        state, aim = self.poll(state, NOW + EVERY - 1, {"ram": 95, "cpu": 95}, {"psi_some": 50.0, "swap_out_mb_min": 900.0})
        self.assertEqual(aim, {"ram": 72, "cpu": 72})
        self.assertEqual((len(state["samples"]), state["stepped"]), (2, NOW))
        state, aim = self.poll(state, NOW + EVERY, {"ram": 40, "cpu": 30}, CALM)
        self.assertEqual(aim, {"ram": 74, "cpu": 74})

    def test_load_above_the_upper_limit_rising_psi_and_swap_out_drop_it_at_once_to_the_middle(self):
        state = {"ram": 90, "cpu": 90, "psi": 0.5, "stepped": NOW - EVERY}
        state, aim = self.poll(state, NOW, {"ram": 95, "cpu": 50}, CALM)
        self.assertEqual(aim, {"ram": 80, "cpu": 90})
        state, aim = self.poll(state, NOW + EVERY, {"ram": 50, "cpu": 50}, {"psi_some": 4.0, "swap_out_mb_min": 0.0})
        self.assertEqual(aim, {"ram": 75, "cpu": 80})
        state, aim = self.poll(state, NOW + 2 * EVERY, {"ram": 50, "cpu": 50}, {"psi_some": 4.0, "swap_out_mb_min": 0.0})
        self.assertEqual(aim, {"ram": 75, "cpu": 80})
        state, aim = self.poll(state, NOW + 3 * EVERY, {"ram": 50, "cpu": 50}, {"psi_some": 0.3, "swap_out_mb_min": 12.0})
        self.assertEqual(aim, {"ram": 72.5, "cpu": 75})
        state, aim = self.poll(state, NOW + 4 * EVERY, {"ram": 50, "cpu": 50}, {"psi_some": None, "swap_out_mb_min": None})
        self.assertEqual(aim, {"ram": 74.5, "cpu": 77})

    def test_the_rise_follows_the_10_minute_average_not_the_last_sample(self):
        busy = [[NOW - 500 + 20 * k, 80.0, 80.0] for k in range(25)]
        state = {"ram": 80, "cpu": 80, "stepped": NOW - EVERY, "samples": busy}
        state, aim = self.poll(state, NOW, {"ram": 40, "cpu": 40}, CALM)
        self.assertEqual(aim, {"ram": 80, "cpu": 80})
        state, aim = self.poll(state, NOW + self.aimd.WINDOW_SECONDS, {"ram": 40, "cpu": 40}, CALM)
        self.assertEqual(aim, {"ram": 82, "cpu": 82})
        self.assertEqual([row[0] for row in state["samples"]], [NOW, NOW + self.aimd.WINDOW_SECONDS])


class TestSelfTuningPass(fixtures.Passes, unittest.TestCase):
    def test_a_grant_is_refused_while_load_plus_footprint_passes_the_target_and_the_reason_names_it(self):
        running, waiting = fixtures.job(1, status="active"), fixtures.job(2, task="work/b", workdir="/b")
        shares = {"j1": {"ram": 0, "cpu": 0}, "j2": {"ram": 15, "cpu": 5}}
        load = {"ram": 58.0, "cpu": 30.0}
        aimed = {**BAND, "target": {"ram": 72.0, "cpu": 90.0}}
        self.assertEqual(self.decide([running, waiting], footprints=shares, band=aimed, load=load),
                         {"j2": "would reach 73 % RAM > target 72.0 %"})
        self.assertIsNone(self.decide([running, waiting], footprints=shares, band={**BAND, "target": {"ram": 73.0, "cpu": 90.0}},
                                      load=load)["j2"])
        self.assertIsNone(self.decide([running, waiting], footprints=shares, band=BAND, load=load)["j2"])

    def test_one_queue_pass_per_poll_over_a_load_series_grants_and_refuses_by_the_target(self):
        aimd = fixtures._load(AIMD)
        running, waiting = fixtures.job(1, status="active"), fixtures.job(2, task="work/b", workdir="/b")
        shares = {"j1": {"ram": 0, "cpu": 0}, "j2": {"ram": 15, "cpu": 5}}
        series = [
            ({"ram": 58.0, "cpu": 30.0}, CALM, "would reach 73 % RAM > target 72.0 %"),
            ({"ram": 58.0, "cpu": 30.0}, CALM, None),
            ({"ram": 58.0, "cpu": 30.0}, {"psi_some": 5.0, "swap_out_mb_min": 0.0}, "would reach 73 % RAM > target 72.0 %"),
            ({"ram": 92.0, "cpu": 30.0}, CALM, "load 92 % RAM >= 70 % band"),
        ]
        state = {"ram": 70, "cpu": 90}
        for n, (load, pressure, reason) in enumerate(series):
            with self.subTest(poll=n):
                state = aimd.stepped(state, BAND, load, pressure, 1.0, NOW + n * EVERY, EVERY)
                aimed = {**BAND, "target": aimd.target(state, BAND)}
                self.assertEqual(self.decide([running, waiting], footprints=shares, band=aimed, load=load), {"j2": reason})
        self.assertEqual(aimd.target(state, BAND)["ram"], 71)

    def test_at_most_one_grant_lands_per_settle_window_while_a_queue_job_runs(self):
        running, first, second = fixtures.job(1, status="active"), fixtures.job(2, task="work/b", workdir="/b"), fixtures.job(3, task="work/c", workdir="/c")
        settles = "settles: the last grant was 2 s ago, one grant per 5 s"
        self.assertEqual(self.decide([running, first], settle=(5, NOW - 2)), {"j2": settles})
        self.assertEqual(self.decide([running, first], settle=(5, NOW - 5)), {"j2": None})
        self.assertEqual(self.decide([running, first], settle=(5, None)), {"j2": None})
        self.assertEqual(self.decide([first], settle=(5, NOW - 2)), {"j2": None})
        granted = {**first, "status": "active"}
        self.assertEqual(self.decide([running, granted, second], settle=(5, NOW - 1)),
                         {"j3": "settles: the last grant was 1 s ago, one grant per 5 s"})
        self.assertEqual(self.decide([running, granted, second], settle=(5, NOW - 5)), {"j3": None})
        self.assertEqual(self.queue.settle_reason((5, NOW + 3), NOW), None)
        self.assertEqual(self.queue.settle_reason(None, NOW), None)


class TestLearnedSizes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.history = fixtures._load(fixtures.HISTORY)
        cls.queue = fixtures._load(fixtures.QUEUE)

    def learn(self, rows: list[dict]) -> tuple[dict, dict]:
        return self.history.learn(rows, NOW, {"load_limits": {"mem_percent": 80, "cpu_percent": 90}})

    def test_the_margin_grows_by_the_overshoot_shrinks_slowly_and_stays_between_1_and_2(self):
        margin, booked = self.history.margin, {"ram": 10, "cpu": 100}
        self.assertEqual(margin([peak(1, 12, 30, predicted=booked)]), 1.2)
        self.assertAlmostEqual(margin([peak(1, 12, 30, predicted=booked), peak(2, 5, 30, predicted=booked)]), 1.15)
        self.assertAlmostEqual(margin([peak(2, 5, 30, predicted=booked), peak(1, 12, 30, predicted=booked)]), 1.15)
        self.assertEqual(margin([peak(1, 40, 30, predicted=booked)]), 2.0)
        self.assertEqual(margin([peak(n, 5, 30, predicted=booked) for n in range(3)]), 1.0)
        self.assertEqual(margin([peak(1, 30, 30, predicted={"ram": 10, "cpu": 20})]), 2.0)
        self.assertEqual(margin([peak(1, 40, 30), peak(2, 40, 30, predicted={"ram": 0, "cpu": True})]), 1.0)
        shrunk = [peak(1, 20, 30, predicted=booked), *(peak(n + 2, 5, 30, predicted=booked) for n in range(4))]
        self.assertAlmostEqual(margin(shrunk), 1.8)

    def test_the_footprint_is_the_p95_of_the_peaks_times_the_learned_margin_and_the_band_refuses_it(self):
        shares = (5, 5, 10, 15, 15)
        plain = [peak(n, ram, 30) for n, ram in enumerate(shares)]
        signatures, kinds = self.learn(plain)
        self.assertEqual(self.history.footprint("test", ("make test",), signatures, kinds), {"ram": 15, "cpu": 30})
        predicted = [{"ram": 10, "cpu": 100}] * 4 + [{"ram": 15, "cpu": 100}]
        taught = [{**row, "predicted": booked} for row, booked in zip(plain, predicted)]
        signatures, kinds = self.learn(taught)
        self.assertAlmostEqual(signatures["test", "make test"]["margin"], 1.45)
        share = self.history.footprint("test", ("make test",), signatures, kinds)
        self.assertAlmostEqual(share["ram"], 21.75)
        self.assertAlmostEqual(share["cpu"], 43.5)
        running, waiting = fixtures.job(1, status="active"), fixtures.job(2, task="work/b", workdir="/b")
        rules = {**fixtures.BASE, "band": {**BAND, "target": {"ram": 70.0, "cpu": 90.0}}, "load": {"ram": 50.0, "cpu": 20.0}}
        verdicts = self.queue.evaluate([running, waiting], **{**rules, "footprints": {"j1": {"ram": 0, "cpu": 0}, "j2": share}})[0]
        self.assertEqual(verdicts, {"j2": "would reach 72 % RAM > target 70.0 %"})
        verdicts = self.queue.evaluate([running, waiting], **{**rules, "footprints": {"j1": {"ram": 0, "cpu": 0}, "j2": {"ram": 15, "cpu": 30}}})[0]
        self.assertEqual(verdicts, {"j2": None})

    def test_a_finished_job_records_the_footprint_its_grant_booked(self):
        entry = fixtures.job(1)
        self.assertEqual(self.queue.finished(entry, "make test", None, False, {"ram": 12.0, "cpu": 30.0})["predicted"],
                         {"ram": 12.0, "cpu": 30.0})
        self.assertNotIn("predicted", self.queue.finished(entry, "make test", None, False, None))


if __name__ == "__main__":
    unittest.main()
