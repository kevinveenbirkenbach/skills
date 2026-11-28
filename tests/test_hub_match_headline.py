"""Exercise requirement 099: a Match card's headline is cut to 120 characters, its command and hash stay whole."""

from __future__ import annotations

import unittest

from kvb_orchestrator import payloads
from kvb_orchestrator.matching import HEADLINE, headline
from test_hub_match import MatchCase

LONG = "gh workflow run entry-manual-steer.yml --repo kevinveenbirkenbach/infinito-nexus-core " + " ".join(f"-f priority{index}=drv-intel#0@host+clearnet%debian:amd64" for index in range(15))


class TestHeadline(unittest.TestCase):
    def test_a_title_that_fits_stays_unchanged(self):
        card = {"title": "x" * HEADLINE}
        self.assertIs(headline(card), card)

    def test_a_long_title_is_cut_at_the_last_word_boundary_and_keeps_its_full_text(self):
        cut = headline({"title": LONG})
        self.assertLessEqual(len(cut["title"]), HEADLINE)
        self.assertTrue(cut["title"].endswith("…"))
        self.assertTrue(LONG.startswith(cut["title"][:-1]))
        self.assertEqual(LONG[len(cut["title"]) - 1], " ")
        self.assertEqual(cut["title_full"], LONG)

    def test_a_single_word_longer_than_the_limit_is_cut_inside_the_word(self):
        cut = headline({"title": "a" * 500})
        self.assertEqual(cut["title"], "a" * (HEADLINE - 1) + "…")


class TestHeadlineCard(MatchCase):
    def test_a_long_command_card_carries_the_cut_title_the_full_command_and_the_uncut_hash(self):
        self.operator_row("operator/steer", LONG, str(self.work))
        card = self.card("operator:operator/steer")
        self.assertLessEqual(len(card["title"]), HEADLINE)
        self.assertEqual((card["command"], card["title_full"]), (LONG, LONG))
        self.assertEqual(card["hash"], payloads.payload_hash(LONG, str(self.work), card["files"]))


if __name__ == "__main__":
    unittest.main()
