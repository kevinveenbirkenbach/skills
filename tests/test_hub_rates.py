from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import hub_support
import resources as sampler
from hub_case import HubCase
from kvb_orchestrator import rates

iso = hub_support.iso
HUB = hub_support.HUB

HOUR = 3600
DAY = 86400
GIB = 1 << 30
NOW = 1_800_000_000 + 1800
EXACT_ZERO = {"value": 0.0, "approx": False, "source": None}


def token(t: int, given: int, cached: int) -> dict:
    return {"t": t, "agent": "Skills", "model": "claude-opus-5-5", "input": given, "output": 0, "cache_read": cached, "cache_write": 0}


def sample(t: float, cpu: float, span: int | None = None, vram: tuple[int, int] | None = None, boot: int = 50) -> dict:
    gpus = [{"name": "0000:01:00.0", "util": 10.0, "vram_used": vram[0] * GIB, "vram_total": vram[1] * GIB}, {"name": "0000:02:00.0", "asleep": True}] if vram else [{"name": "0000:01:00.0", "util": None, "vram_used": None, "vram_total": None}]
    row = {"t": t, "cpu": cpu, "ram": cpu + 1, "swap": 2.0, "disks": [{"mount": "/", "used": 50, "total": 100}, {"mount": "/boot", "used": boot, "total": 100}], "gpus": gpus}
    return row if span is None else {**row, "span": span}


class TestRates(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.council = Path(tmp.name) / "council"
        self.folder = Path(tmp.name) / "kept" / "resources"
        self.council.mkdir()
        self.folder.mkdir(parents=True)

    def register(self, tasks: dict) -> None:
        (self.council / "rasci.json").write_text(json.dumps(tasks), encoding="utf-8")

    def lines(self, path: Path, rows: list[dict]) -> None:
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    def rated(self) -> dict:
        return rates.rated(self.council, self.folder.parent, NOW)

    def column(self, metric: str) -> dict:
        found = self.rated()
        return {period: found["rates"][period][metric] for period in rates.PERIOD_NAMES}

    def test_done_tasks_count_in_every_window_their_end_lies_in_and_total_counts_each_done_task(self):
        ends = [NOW - 30, NOW - 1800, NOW - 2 * DAY, NOW - 20 * DAY, NOW - 200 * DAY, NOW - 800 * DAY]
        tasks = {f"work/t{index}": {"status": "done", "end": iso(end)} for index, end in enumerate(ends)}
        others = {"status": "done", "end": iso(NOW - 10)}
        self.register({**tasks, "work/legacy": {"status": "done"}, "work/open": {**others, "status": "running"}, "work/halted": {**others, "status": "stopped"}, "operator/run": others})
        counts = dict(zip(rates.PERIOD_NAMES, (1.0, 2.0, 2.0, 3.0, 4.0, 5.0, 7.0), strict=True))
        self.assertEqual(self.column("tasks"), {period: {"value": value, "approx": False, "source": None} for period, value in counts.items()})

    def test_an_empty_window_takes_the_shortest_longer_window_with_events_scaled_down_and_marked_approx(self):
        results = [{"text": "met", "met": True, "met_at": iso(NOW - 1800)}, {"text": "open", "met": False}]
        self.register({"work/a": {"status": "running", "key_results": results}})
        commit = {"time": NOW - 5 * HOUR, "remote": "example.org/repo", "sha": "a" * 40, "values": {}}
        self.lines(self.council / "scores.jsonl", [commit, commit, {**commit, "sha": None, "time": NOW - 60}, {**commit, "sha": "b" * 40, "values": None}])
        krs = self.column("krs")
        self.assertEqual(krs["minute"], {"value": 0.01667, "approx": True, "source": "hour"})
        self.assertEqual([krs[period] for period in rates.PERIOD_NAMES[1:]], [{"value": 1.0, "approx": False, "source": None}] * 6)
        commits = self.column("commits")
        self.assertEqual(commits["minute"], {"value": 0.0006944, "approx": True, "source": "day"})
        self.assertEqual(commits["hour"], {"value": 0.04167, "approx": True, "source": "day"})
        self.assertEqual([commits[period] for period in rates.PERIOD_NAMES[2:]], [{"value": 1.0, "approx": False, "source": None}] * 5)

    def test_key_results_met_before_met_at_existed_count_only_in_total_and_scale_from_there(self):
        self.register({"work/a": {"status": "running", "key_results": [{"text": "a", "met": True}]}})
        self.lines(self.folder / "samples.jsonl", [sample(NOW - 10 * DAY, 5.0)])
        krs = self.column("krs")
        self.assertEqual(krs["total"], {"value": 1.0, "approx": False, "source": None})
        self.assertEqual(krs["year"], {"value": 1.0, "approx": True, "source": "total"})
        self.assertEqual(krs["week"], {"value": 0.7, "approx": True, "source": "total"})
        self.assertEqual(krs["minute"], {"value": 6.944e-05, "approx": True, "source": "total"})

    def test_tokens_share_their_hour_by_overlap_and_the_minute_always_takes_a_longer_window(self):
        hour = NOW - NOW % HOUR
        self.lines(self.folder / "tokens.jsonl", [token(hour, 1000, 800), token(hour - HOUR, 3000, 600), token(hour - 20 * DAY, 7, 0)])
        tokens = self.column("tokens")
        self.assertEqual(tokens["minute"], {"value": 60.0, "approx": True, "source": "hour"})
        self.assertEqual(tokens["hour"], {"value": 3600.0, "approx": False, "source": None})
        self.assertEqual((tokens["day"]["value"], tokens["month"]["value"], tokens["total"]["value"]), (5400.0, 5407.0, 5407.0))

    def test_an_empty_hour_takes_the_day_for_tokens_and_so_does_the_minute(self):
        hour = NOW - NOW % HOUR
        self.lines(self.folder / "tokens.jsonl", [token(hour - 5 * HOUR, 8000, 640)])
        tokens = self.column("tokens")
        self.assertEqual(tokens["minute"], {"value": 6.0, "approx": True, "source": "day"})
        self.assertEqual(tokens["hour"], {"value": 360.0, "approx": True, "source": "day"})
        self.assertEqual(tokens["day"], {"value": 8640.0, "approx": False, "source": None})

    def test_gauges_average_each_window_weighting_raw_rows_fifteen_minute_means_and_daily_means_by_their_span(self):
        self.lines(self.folder / "samples.jsonl", [
            sample(NOW - 500 * DAY, 0.0, span=DAY),
            sample(NOW - 200 * DAY, 90.0, span=DAY),
            sample(NOW - 10 * DAY, 50.0, span=900),
            sample(NOW - 90, 30.0, vram=(4, 8), boot=70),
            sample(NOW - 30, 10.0, vram=(2, 8), boot=90),
        ])
        found = self.rated()["rates"]
        self.assertEqual([found[period]["cpu"]["value"] for period in rates.PERIOD_NAMES], [10.0, 20.0, 20.0, 20.0, 46.5, 89.5, 45.0])
        self.assertEqual([found[period]["ram"]["value"] for period in ("minute", "hour")], [11.0, 21.0])
        self.assertEqual(found["minute"]["vram"], {"value": 25.0, "used": 2 * GIB, "approx": False, "source": None})
        self.assertEqual((found["hour"]["vram"]["value"], found["hour"]["vram"]["used"], found["month"]["vram"]["value"]), (37.5, 3 * GIB, 37.5))
        self.assertEqual(found["minute"]["disk"], {"value": 90.0, "mount": "/boot", "used": 90, "total": 100, "approx": False, "source": None})
        self.assertEqual((found["hour"]["disk"]["value"], found["month"]["disk"]["value"], found["month"]["disk"]["used"]), (80.0, 53.5, 54))
        self.assertEqual(self.rated()["since"], NOW - 500 * DAY)

    def test_a_window_without_a_sample_shows_no_gauge_and_kinds_without_any_event_count_an_exact_zero(self):
        self.lines(self.folder / "samples.jsonl", [sample(NOW - 2 * HOUR, 40.0)])
        found = self.rated()
        self.assertEqual([found["rates"][period]["cpu"]["value"] for period in rates.PERIOD_NAMES], [None, None, 40.0, 40.0, 40.0, 40.0, 40.0])
        self.assertEqual(found["rates"]["hour"]["vram"], {"value": None, "used": None, "approx": False, "source": None})
        self.assertEqual(found["rates"]["minute"]["disk"], {"value": None, "mount": None, "used": None, "total": None, "approx": False, "source": None})
        self.assertEqual({found["rates"][period][kind] == EXACT_ZERO for period in rates.PERIOD_NAMES for kind in rates.COUNTS}, {True})
        self.assertEqual((found["now"], found["since"], [entry["name"] for entry in found["periods"]]), (NOW, NOW - 2 * HOUR, list(rates.PERIOD_NAMES)))

    def test_folded_sampler_rows_feed_the_windows_with_the_seconds_they_sampled(self):
        old = NOW - NOW % DAY - 100 * DAY
        raw = [sample(old + 3600 + index * 60, 20.0) for index in range(30)] + [sample(NOW - 9 * DAY + index * 60, 60.0) for index in range(30)] + [sample(NOW - 59, 10.0)]
        kept = sampler.retain(sorted(raw, key=lambda row: row["t"]), NOW)
        self.assertEqual([(row["t"], row["span"], row["width"]) for row in kept[:1]], [(old, 1800, DAY)])
        self.assertEqual(sum(row["span"] for row in kept[1:-1]), 1800)
        self.assertEqual({row["width"] for row in kept[1:-1]}, {900})
        self.assertNotIn("span", kept[-1])
        self.lines(self.folder / "samples.jsonl", kept)
        found = self.rated()["rates"]
        month = round((10 * 60 + 60 * 1800) / (60 + 1800), 1)
        year = round((10 * 60 + 60 * 1800 + 20 * 1800) / (60 + 1800 * 2), 1)
        self.assertEqual([found[period]["cpu"]["value"] for period in ("minute", "week", "month", "year")], [10.0, 10.0, month, year])

    def test_a_lone_fifteen_minute_bucket_weighs_its_sampled_seconds_wherever_it_lies_in_its_day(self):
        day = NOW - NOW % DAY - 200 * DAY
        raw = [sample(day + 60 * index, 50.0) for index in range(15)] + [sample(day + DAY + 900 + 60 * index, 50.0) for index in range(15)]
        kept = sampler.retain(raw, NOW)
        self.assertEqual([(row["t"], row["span"], row["width"]) for row in kept], [(day, 900, DAY), (day + DAY, 900, DAY)])
        self.assertEqual(sampler.retain(kept, NOW), kept)

    def test_a_fifteen_minute_mean_written_before_rows_carried_span_stands_for_its_whole_bucket(self):
        start = NOW - NOW % 900 - 20 * DAY
        legacy = {**sample(start, 30.0), "queue": {"waiting": 0.0, "active": 1.0}}
        kept = sampler.retain([legacy, sample(start + 900 + 60, 90.0)], NOW)
        self.assertEqual([(row["t"], row["span"], row["width"]) for row in kept], [(start, 900, 900), (start + 900, 60, 900)])

    def test_the_year_weighs_every_tier_by_the_seconds_it_sampled(self):
        old, recent = NOW - NOW % DAY - 100 * DAY, NOW - NOW % DAY - 8 * DAY
        raw = [sample(old + 60 * index, 90.0) for index in range(60)] + [sample(recent + 60 * index, 10.0) for index in range(60)]
        self.lines(self.folder / "samples.jsonl", sampler.retain(raw, NOW))
        self.assertEqual(self.rated()["rates"]["year"]["cpu"]["value"], 50.0)

    def test_a_folded_row_straddling_a_window_start_counts_by_its_share_inside(self):
        week, year = NOW - 7 * DAY, NOW - 365 * DAY
        self.lines(self.folder / "samples.jsonl", [
            {**sample(year - year % DAY, 40.0), "span": 3600, "width": DAY},
            {**sample(week - 300, 70.0, boot=80), "span": 600, "width": 900},
            sample(NOW - 30, 10.0, boot=20),
        ])
        found = self.rated()["rates"]
        inside = (year - year % DAY + DAY - year) / DAY * 3600
        self.assertEqual(found["week"]["cpu"]["value"], round((400 * 70 + 60 * 10) / 460, 1))
        self.assertEqual(found["month"]["cpu"]["value"], round((600 * 70 + 60 * 10) / 660, 1))
        self.assertEqual(found["year"]["cpu"]["value"], round((inside * 40 + 600 * 70 + 60 * 10) / (inside + 660), 1))
        self.assertEqual(found["total"]["cpu"]["value"], round((3600 * 40 + 600 * 70 + 60 * 10) / 4260, 1))
        self.assertEqual(found["week"]["disk"]["value"], round((400 * 80 + 60 * 20) / 460, 1))

    def test_token_rows_older_than_ninety_days_fold_into_one_row_per_day_agent_and_model_kept_forever(self):
        day, hour = NOW - NOW % DAY - 100 * DAY, NOW - NOW % HOUR
        rows = [token(day + HOUR, 10, 0), token(day + 5 * HOUR, 20, 5), {**token(day + 2 * HOUR, 1, 0), "model": "other"}, token(hour - HOUR, 7, 0)]
        kept = sampler.compact(rows, NOW)
        daily = [{**token(day, 30, 5), "width": DAY}, {**token(day, 1, 0), "model": "other", "width": DAY}]
        self.assertEqual(kept, [*daily, token(hour - HOUR, 7, 0)])
        self.assertEqual(sampler.compact(kept, NOW + 400 * DAY)[:2], daily)

    def test_a_daily_token_row_counts_by_the_share_of_its_day_inside_a_window(self):
        year = NOW - 365 * DAY
        self.lines(self.folder / "tokens.jsonl", [{**token(year - year % DAY, 8640, 0), "width": DAY}])
        tokens = self.column("tokens")
        self.assertEqual(tokens["year"], {"value": rates.precise((year - year % DAY + DAY - year) / DAY * 8640), "approx": False, "source": None})
        self.assertEqual(tokens["total"], {"value": 8640.0, "approx": False, "source": None})

    def test_token_windows_reaching_before_the_first_token_row_are_scaled_estimates_from_the_rows_there_are(self):
        hour = NOW - NOW % HOUR
        begins = hour - 10 * DAY
        self.register({"work/old": {"status": "done", "end": iso(NOW - 400 * DAY)}})
        self.lines(self.folder / "tokens.jsonl", [token(begins, 1000, 0), token(hour - HOUR, 500, 0)])
        tokens = self.column("tokens")
        covered = NOW - begins
        self.assertEqual(tokens["minute"], {"value": rates.precise(250 / 60), "approx": True, "source": "hour"})
        self.assertEqual([tokens[period] for period in ("hour", "day", "week")], [{"value": value, "approx": False, "source": None} for value in (250.0, 500.0, 500.0)])
        for period, seconds in (("month", 30 * DAY), ("year", 365 * DAY), ("total", 400 * DAY)):
            with self.subTest(period=period):
                self.assertEqual(tokens[period], {"value": rates.precise(1500 * seconds / covered), "approx": True, "source": "total"})

    def test_counts_shorten_to_thousands_millions_billions_and_trillions(self):
        probe = "const R = require(process.argv[1]); console.log(JSON.stringify(JSON.parse(process.argv[2]).map(R.compact)));"
        values = [999, 1000, 999_949, 999_950, 14_370_239_246.104, 999_960_000_000, 2.5e12, 3e15]
        done = subprocess.run(["node", "-e", probe, str(HUB / "templates" / "resources.js"), json.dumps(values)], capture_output=True, text=True, timeout=60, check=True)
        self.assertEqual(json.loads(done.stdout), ["999", "1.0k", "999.9k", "1.0M", "14.4B", "1.0T", "2.5T", "3000.0T"])


class TestHubRates(HubCase):
    def test_the_hub_serves_the_rates_of_the_register_the_journal_and_the_sampler(self):
        self.write_council({"rasci.json": {"work/a": {"status": "done", "end": iso(1_700_000_000), "key_results": [{"text": "a", "met": True, "met_at": iso(1_700_000_000)}]}}})
        (self.council / "scores.jsonl").write_text(json.dumps({"time": 1_700_000_000, "remote": "example.org/repo", "sha": "c" * 40, "values": {}}) + "\n", encoding="utf-8")
        status, headers, body = self.get("/api/rates")
        self.assertEqual((status, headers["content-type"]), (200, "application/json"), body)
        found = json.loads(body)
        self.assertEqual([entry["name"] for entry in found["periods"]], list(rates.PERIOD_NAMES))
        self.assertEqual({kind: found["rates"]["total"][kind]["value"] for kind in rates.COUNTS}, {"tasks": 1.0, "commits": 1.0, "krs": 1.0, "tokens": 0.0})
        self.assertEqual(set(found["rates"]["hour"]), set(rates.METRICS))
        self.assertEqual(found["since"], 1_700_000_000)


if __name__ == "__main__":
    unittest.main()
