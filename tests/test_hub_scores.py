from __future__ import annotations

import json
import unittest

from hub_case import HubCase
from score_fixture import REPO_ROOT, Fixture, backfill

LABELS = REPO_ROOT / "skills" / "kvb-check-score" / "labels.json"
T = 1_760_000_000


class TestHubScores(HubCase):
    def fetch(self, query: str) -> tuple[int, bytes]:
        status, _, body = self.get(f"/api/scores?{query}")
        return status, body

    def test_the_hub_serves_the_backfilled_journal_rows_of_a_window(self):
        fixture = Fixture(self.council.parent / "fixture")
        done = backfill(self.council, "--repo", str(fixture.a))
        self.assertEqual(done.returncode, 0, done.stderr)
        begin, end = fixture.time_of(fixture.new), fixture.time_of(fixture.estimated)
        status, body = self.fetch(f"from={begin}&to={end}")
        self.assertEqual(status, 200, body)
        found = json.loads(body)
        self.assertEqual((found["since"], found["until"]), (begin, end))
        self.assertEqual(found["labels"], json.loads(LABELS.read_text(encoding="utf-8")))
        self.assertEqual([(row["sha"], row["branch"]) for row in found["rows"]], [(fixture.new, "feature/two"), (fixture.estimated, "main")])
        self.assertEqual([row["values"]["score"] for row in found["rows"]], [81, 52])

    def test_broken_lines_and_rows_without_values_are_left_out_in_time_order(self):
        self.council.mkdir(exist_ok=True)
        late = {"time": T, "branch": "feature/a", "values": {"score": 90}}
        early = {"time": T - 10, "branch": "feature/a", "values": {"score": 80}}
        lines = [json.dumps(late), "{broken", json.dumps({"time": T}), json.dumps({"time": "x", "values": {}}), json.dumps(early), json.dumps({**late, "time": T + 500})]
        (self.council / "scores.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
        status, body = self.fetch(f"from={T - 100}&to={T + 100}")
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)["rows"], [early, late])
        self.assertEqual(self.fetch(f"from={T + 10}&to={T}")[0], 400)

    def test_a_label_file_of_another_shape_is_served_as_null(self):
        skills = self.council.parent / "skills"
        labels = skills / "kvb-check-score" / "labels.json"
        labels.parent.mkdir(parents=True)
        self.scripts.skills = skills
        good = {"metrics": {"fix": {"emoji": "🎯", "label": "Fix", "former": []}}}
        for text, served in (("{}", None), ('{"metrics": []}', None), ('{"metrics": {}}', None), ('{"metrics": {"fix": {"emoji": 1, "label": "Fix"}}}', None), ("{broken", None), (json.dumps(good), good)):
            with self.subTest(labels=text):
                labels.write_text(text, encoding="utf-8")
                status, body = self.fetch(f"from={T}&to={T + 1}")
                self.assertEqual((status, json.loads(body)["labels"]), (200, served))

    def test_a_missing_journal_answers_no_rows(self):
        status, body = self.fetch(f"from={T}&to={T + 1}")
        self.assertEqual((status, json.loads(body)["rows"]), (200, []))


if __name__ == "__main__":
    unittest.main()
