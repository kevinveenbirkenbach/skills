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
LAST_HOUR = NOW - NOW % HOUR
NOTHING = {"value": None, "approx": False, "covered": None}


def token(t: int, given: int, cached: int) -> dict:
    return {"t": t, "agent": "Skills", "model": "claude-opus-5-5", "input": given, "output": 0, "cache_read": cached, "cache_write": 0}


def sample(t: float, cpu: float, span: int | None = None, vram: tuple[int, int] | None = None, boot: int = 50) -> dict:
    gpus = [{"name": "0000:01:00.0", "util": 10.0, "vram_used": vram[0] * GIB, "vram_total": vram[1] * GIB}, {"name": "0000:02:00.0", "asleep": True}] if vram else [{"name": "0000:01:00.0", "util": None, "vram_used": None, "vram_total": None}]
    row = {"t": t, "cpu": cpu, "ram": cpu + 1, "swap": 2.0, "disks": [{"mount": "/", "used": 50, "total": 100}, {"mount": "/boot", "used": boot, "total": 100}], "gpus": gpus}
    return row if span is None else {**row, "span": span}


def per_unit(amount: float, covered: float, approx: bool) -> dict[str, dict]:
    return {name: {"value": rates.precise(amount if seconds is None else amount * seconds / covered), "approx": approx and seconds is not None, "covered": covered} for name, seconds in rates.PERIODS}


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

    def rated(self, begin: float, end: float) -> dict:
        return rates.rated(self.council, self.folder.parent, NOW, (begin, end))

    def column(self, metric: str, begin: float, end: float) -> dict:
        found = self.rated(begin, end)
        return {period: found["rates"][period][metric] for period in rates.PERIOD_NAMES}

    def test_a_week_of_seven_million_tokens_gives_a_million_a_day_seven_a_week_and_seven_in_all(self):
        self.lines(self.folder / "tokens.jsonl", [token(LAST_HOUR - 10 * DAY, 5, 0), token(LAST_HOUR - 2 * DAY, 6_000_000, 1_000_000)])
        tokens = self.column("tokens", NOW - 7 * DAY, NOW)
        self.assertEqual(tokens, per_unit(7_000_000, 7 * DAY, False))
        self.assertEqual((tokens["day"]["value"], tokens["week"]["value"], tokens["total"]["value"], tokens["month"]["value"]), (1_000_000.0, 7_000_000.0, 7_000_000.0, 30_000_000.0))

    def test_done_tasks_key_results_and_commits_count_inside_the_window_and_scale_per_unit(self):
        ends = [NOW - 30, NOW - 1800, NOW - 2 * DAY, NOW - 20 * DAY]
        tasks = {f"work/t{index}": {"status": "done", "end": iso(end)} for index, end in enumerate(ends)}
        others = {"status": "done", "end": iso(NOW - 10)}
        results = [{"text": "met", "met": True, "met_at": iso(NOW - 600)}, {"text": "old", "met": True}, {"text": "open", "met": False}]
        self.register({**tasks, "work/legacy": {"status": "done"}, "work/open": {**others, "status": "running", "key_results": results}, "work/halted": {**others, "status": "stopped"}, "operator/run": others})
        commit = {"time": NOW - 5 * HOUR, "remote": "example.org/repo", "sha": "a" * 40, "values": {}}
        self.lines(self.council / "scores.jsonl", [commit, commit, {**commit, "sha": None, "time": NOW - 60}, {**commit, "sha": "b" * 40, "time": NOW - 3 * DAY}])
        day = self.rated(NOW - DAY, NOW)["rates"]
        self.assertEqual({period: day[period]["tasks"] for period in rates.PERIOD_NAMES}, per_unit(2, DAY, False))
        self.assertEqual({period: day[period]["krs"] for period in rates.PERIOD_NAMES}, per_unit(1, DAY, False))
        self.assertEqual({period: day[period]["commits"] for period in rates.PERIOD_NAMES}, per_unit(1, DAY, False))
        past = self.rated(NOW - 3 * DAY, NOW - DAY)["rates"]
        self.assertEqual((past["total"]["tasks"]["value"], past["total"]["commits"]["value"], past["day"]["tasks"]["value"]), (1.0, 1.0, 0.5))

    def test_a_window_reaching_before_the_first_token_row_divides_by_the_covered_part_and_marks_the_rates_approx(self):
        self.register({"work/old": {"status": "done", "end": iso(NOW - 30 * DAY)}})
        self.lines(self.folder / "tokens.jsonl", [token(LAST_HOUR - 2 * DAY, 4000, 800)])
        tokens = self.column("tokens", NOW - 7 * DAY, NOW)
        covered = NOW - (LAST_HOUR - 2 * DAY)
        self.assertEqual(tokens, per_unit(4800, covered, True))
        self.assertEqual(tokens["total"], {"value": 4800.0, "approx": False, "covered": covered})
        self.assertEqual(self.column("tasks", NOW - 7 * DAY, NOW)["day"], {"value": 0.0, "approx": False, "covered": 7 * DAY})

    def test_a_window_before_every_record_holds_no_value(self):
        self.register({"work/a": {"status": "done", "end": iso(NOW - DAY)}})
        self.lines(self.folder / "tokens.jsonl", [token(LAST_HOUR - DAY, 100, 0)])
        self.lines(self.folder / "samples.jsonl", [sample(NOW - DAY, 40.0)])
        found = self.rated(NOW - 9 * DAY, NOW - 8 * DAY)
        self.assertEqual({found["rates"][period][kind] == NOTHING for period in rates.PERIOD_NAMES for kind in rates.COUNTS}, {True})
        self.assertIsNone(found["rates"]["day"]["cpu"]["value"])
        self.assertEqual((found["from"], found["to"], found["since"]), (NOW - 9 * DAY, NOW - 8 * DAY, LAST_HOUR - DAY))

    def test_a_window_shorter_than_an_hour_shares_the_token_hour_and_marks_every_token_rate_approx(self):
        self.lines(self.folder / "tokens.jsonl", [token(LAST_HOUR, 1000, 800)])
        tokens = self.column("tokens", NOW - 600, NOW)
        self.assertEqual(tokens["minute"], {"value": 60.0, "approx": True, "covered": 600})
        self.assertEqual(tokens["total"], {"value": 600.0, "approx": True, "covered": 600})

    def test_gauges_average_the_window_weighting_each_row_by_its_sampled_seconds_inside_on_both_ends(self):
        start = NOW - 10 * DAY - (NOW - 10 * DAY) % DAY
        self.lines(self.folder / "samples.jsonl", [
            {**sample(start, 40.0), "span": 3600, "width": DAY},
            {**sample(NOW - 2 * DAY - 300, 70.0, boot=80), "span": 600, "width": 900},
            sample(NOW - 30, 10.0, boot=20),
        ])
        found = self.rated(start + DAY / 2, NOW - 2 * DAY)["rates"]
        self.assertEqual({found[period]["cpu"]["value"] for period in rates.PERIOD_NAMES}, {round((1800 * 40 + 200 * 70) / 2000, 1)})
        self.assertEqual(found["hour"]["disk"], {"value": round((1800 * 50 + 200 * 80) / 2000, 1), "mount": "/boot", "used": 53, "total": 100, "approx": False})
        self.assertEqual(found["week"]["vram"], {"value": None, "used": None, "approx": False})

    def test_gauges_of_the_last_minutes_read_vram_and_the_fullest_disk(self):
        self.lines(self.folder / "samples.jsonl", [sample(NOW - 90, 30.0, vram=(4, 8), boot=70), sample(NOW - 30, 10.0, vram=(2, 8), boot=90)])
        last = self.rated(NOW - 60, NOW)["rates"]["minute"]
        self.assertEqual((last["cpu"]["value"], last["ram"]["value"]), (10.0, 11.0))
        self.assertEqual(last["vram"], {"value": 25.0, "used": 2 * GIB, "approx": False})
        self.assertEqual(last["disk"], {"value": 90.0, "mount": "/boot", "used": 90, "total": 100, "approx": False})
        both = self.rated(NOW - 120, NOW)["rates"]["hour"]
        self.assertEqual((both["cpu"]["value"], both["vram"]["value"], both["vram"]["used"], both["disk"]["value"]), (20.0, 37.5, 3 * GIB, 80.0))

    def test_a_window_without_a_sample_shows_no_gauge_and_kinds_with_records_but_none_inside_count_an_exact_zero(self):
        self.lines(self.folder / "samples.jsonl", [sample(NOW - 2 * HOUR, 40.0)])
        found = self.rated(NOW - HOUR, NOW)["rates"]
        self.assertIsNone(found["day"]["cpu"]["value"])
        self.assertEqual(found["minute"]["disk"], {"value": None, "mount": None, "used": None, "total": None, "approx": False})
        self.assertEqual({found[period][kind]["value"] for period in rates.PERIOD_NAMES for kind in ("tasks", "commits", "krs")}, {0.0})
        self.assertEqual(found["day"]["tokens"], NOTHING)

    def test_folded_sampler_rows_feed_the_window_with_the_seconds_they_sampled(self):
        old = NOW - NOW % DAY - 100 * DAY
        raw = [sample(old + 3600 + index * 60, 20.0) for index in range(30)] + [sample(NOW - 9 * DAY + index * 60, 60.0) for index in range(30)] + [sample(NOW - 59, 10.0)]
        kept = sampler.retain(sorted(raw, key=lambda row: row["t"]), NOW)
        self.assertEqual([(row["t"], row["span"], row["width"]) for row in kept[:1]], [(old, 1800, DAY)])
        self.assertEqual(sum(row["span"] for row in kept[1:-1]), 1800)
        self.assertEqual({row["width"] for row in kept[1:-1]}, {900})
        self.assertNotIn("span", kept[-1])
        self.lines(self.folder / "samples.jsonl", kept)
        month = round((10 * 60 + 60 * 1800) / (60 + 1800), 1)
        year = round((10 * 60 + 60 * 1800 + 20 * 1800) / (60 + 1800 * 2), 1)
        cpu = [self.rated(NOW - seconds, NOW)["rates"]["day"]["cpu"]["value"] for seconds in (60, 7 * DAY, 30 * DAY, 365 * DAY)]
        self.assertEqual(cpu, [10.0, 10.0, month, year])

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
        self.assertEqual(self.rated(NOW - 365 * DAY, NOW)["rates"]["year"]["cpu"]["value"], 50.0)

    def test_token_rows_older_than_ninety_days_fold_into_one_row_per_day_agent_and_model_kept_forever(self):
        day, hour = NOW - NOW % DAY - 100 * DAY, NOW - NOW % HOUR
        rows = [token(day + HOUR, 10, 0), token(day + 5 * HOUR, 20, 5), {**token(day + 2 * HOUR, 1, 0), "model": "other"}, token(hour - HOUR, 7, 0)]
        kept = sampler.compact(rows, NOW)
        daily = [{**token(day, 30, 5), "width": DAY}, {**token(day, 1, 0), "model": "other", "width": DAY}]
        self.assertEqual(kept, [*daily, token(hour - HOUR, 7, 0)])
        self.assertEqual(sampler.compact(kept, NOW + 400 * DAY)[:2], daily)

    def test_a_daily_token_row_counts_by_the_share_of_its_day_inside_the_window(self):
        year = NOW - 365 * DAY
        self.lines(self.folder / "tokens.jsonl", [{**token(year - year % DAY, 8640, 0), "width": DAY}])
        total = self.column("tokens", year, NOW)["total"]
        self.assertEqual(total, {"value": rates.precise((year - year % DAY + DAY - year) / DAY * 8640), "approx": False, "covered": NOW - year})

    def test_counts_shorten_to_thousands_millions_billions_and_trillions(self):
        probe = "const R = require(process.argv[1]); console.log(JSON.stringify(JSON.parse(process.argv[2]).map(R.compact)));"
        values = [999, 1000, 999_949, 999_950, 14_370_239_246.104, 999_960_000_000, 2.5e12, 3e15]
        done = subprocess.run(["node", "-e", probe, str(HUB / "templates" / "resources.js"), json.dumps(values)], capture_output=True, text=True, timeout=60, check=True)
        self.assertEqual(json.loads(done.stdout), ["999", "1.0k", "999.9k", "1.0M", "14.4B", "1.0T", "2.5T", "3000.0T"])


class TestHubRates(HubCase):
    def test_the_hub_serves_the_rates_of_the_window_from_the_register_the_journal_and_the_sampler(self):
        done = 1_700_000_000
        self.write_council({"rasci.json": {"work/a": {"status": "done", "end": iso(done), "key_results": [{"text": "a", "met": True, "met_at": iso(done)}]}}})
        (self.council / "scores.jsonl").write_text(json.dumps({"time": done, "remote": "example.org/repo", "sha": "c" * 40, "values": {}}) + "\n", encoding="utf-8")
        status, headers, body = self.get(f"/api/rates?from={done - DAY}&to={done + DAY}")
        self.assertEqual((status, headers["content-type"]), (200, "application/json"), body)
        found = json.loads(body)
        self.assertEqual([entry["name"] for entry in found["periods"]], list(rates.PERIOD_NAMES))
        self.assertEqual({kind: found["rates"]["total"][kind]["value"] for kind in rates.COUNTS}, {"tasks": 1.0, "commits": 1.0, "krs": 1.0, "tokens": None})
        self.assertEqual({kind: found["rates"]["day"][kind]["approx"] for kind in ("tasks", "commits", "krs")}, {"tasks": True, "commits": True, "krs": True})
        self.assertEqual(set(found["rates"]["hour"]), set(rates.METRICS))
        self.assertEqual((found["since"], found["from"], found["to"]), (done, done - DAY, done + DAY))
        self.assertEqual(self.get(f"/api/rates?from={done}&to={done - 1}")[0], 400)


if __name__ == "__main__":
    unittest.main()
