#!/usr/bin/env python
"""Checks on joining the tracks of one player by their number.

Run with ``.venv/bin/python scripts/test_players.py``.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.players import (CLAIM_MIN_READINGS, JOIN_MAX_OVERLAP,  # noqa: E402
                         MAX_WEARERS, Player, clash, join, worn_at_once)


class Joining(unittest.TestCase):
    # On the evaluation clip SARAULT 44 is tracks 2, 227 and 270 in sequence,
    # with gaps of three and six frames where the huddle hid him.

    def test_fragments_of_one_number_in_sequence_are_one_player(self):
        spans = {2: (0, 2932), 227: (2935, 3394), 270: (3400, 4967)}
        numbers = {2: "44", 227: "44", 270: "44"}
        self.assertEqual(join(spans, numbers, {2: "near", 227: "near", 270: "near"}), [
            Player(team="near", number="44", track_ids=(2, 227, 270), start=0, end=4967),
        ])

    def test_tracks_are_ordered_by_when_they_were_worn_not_by_id(self):
        spans = {9: (3000, 4000), 3: (0, 2900)}
        self.assertEqual(join(spans, {9: "6", 3: "6"})[0].track_ids, (3, 9))

    def test_a_brief_overlap_is_a_hand_over_and_still_joins(self):
        # 56 (CHALMERS' own track) lingered 24 frames after 422 took his body.
        spans = {56: (129, 2905), 422: (2881, 3671)}
        self.assertEqual(len(join(spans, {56: "7", 422: "7"})), 1)

    def test_two_tracks_wearing_a_number_at_once_are_two_people(self):
        spans = {1: (0, 3000), 2: (1000, 4000)}
        self.assertEqual(clash(spans, [1, 2]), (1, 2))
        self.assertEqual(len(join(spans, {1: "44", 2: "44"})), 2)

    def test_a_clash_leaves_every_track_of_that_number_unjoined(self):
        # A third fragment that overlaps neither could belong to either of
        # them, and the number cannot say which.
        spans = {1: (0, 3000), 2: (1000, 4000), 3: (4100, 5000)}
        players = join(spans, {1: "44", 2: "44", 3: "44"})
        self.assertEqual([p.track_ids for p in players], [(1,), (2,), (3,)])

    def test_the_overlap_allowed_is_exactly_the_tolerance(self):
        spans = {1: (0, 100), 2: (101 - JOIN_MAX_OVERLAP, 300)}
        self.assertIsNone(clash(spans, [1, 2]))
        spans[2] = (100 - JOIN_MAX_OVERLAP, 300)
        self.assertEqual(clash(spans, [1, 2]), (1, 2))

    def test_unnamed_tracks_are_nobody(self):
        spans = {1: (0, 100), 2: (200, 300)}
        self.assertEqual(join(spans, {1: "10"}), [
            Player(team=None, number="10", track_ids=(1,), start=0, end=100),
        ])

    def test_the_same_number_on_the_other_side_is_another_player(self):
        # Numbers are per team: a USA 44 after SARAULT 44 leaves the court is
        # not his next fragment, whatever the gap.
        spans = {1: (0, 1000), 2: (2000, 3000)}
        players = join(spans, {1: 44, 2: 44}, {1: "near", 2: "far"})
        self.assertEqual([(p.team, p.track_ids) for p in players],
                         [("far", (2,)), ("near", (1,))])

    def test_players_come_out_by_number(self):
        spans = {1: (0, 100), 2: (0, 100), 3: (0, 100)}
        players = join(spans, {1: 44, 2: 6, 3: 18})
        self.assertEqual([p.number for p in players], [6, 18, 44])


class WornAtOnce(unittest.TestCase):
    # Before letters were read, the far side's `USA` print came back as `54` and
    # four of its tracks claimed it in the same frames.

    def test_a_number_several_players_wear_at_once_is_not_a_number(self):
        spans = {17: (0, 5123), 73: (209, 4050), 12: (0, 2039), 167: (2039, 3948)}
        counts = {17: {"27": 9, "54": 4}, 73: {"55": 10, "54": 4},
                  12: {"1": 3, "54": 3}, 167: {"1": 3, "54": 3}}
        self.assertEqual(worn_at_once(spans, counts), {"54"})

    def test_the_real_numbers_on_those_tracks_survive(self):
        spans = {17: (0, 5123), 73: (209, 4050), 12: (0, 2039), 167: (2039, 3948)}
        counts = {17: {"27": 9, "54": 4}, 73: {"55": 10, "54": 4},
                  12: {"1": 3, "54": 3}, 167: {"1": 3, "54": 3}}
        worn = worn_at_once(spans, counts)
        self.assertNotIn("27", worn)
        self.assertNotIn("1", worn)

    def test_one_number_per_team_at_once_is_allowed(self):
        # A near 2 and a far 2 are two players, and both are real.
        spans = {1: (0, 3000), 2: (0, 3000)}
        self.assertEqual(worn_at_once(spans, {1: {"2": 8}, 2: {"2": 8}}), set())

    def test_fragments_in_sequence_are_not_wearers_at_once(self):
        # SARAULT 44 is three tracks in sequence, never on court together.
        spans = {2: (0, 2932), 227: (2935, 3394), 270: (3400, 4967)}
        counts = {2: {"44": 9}, 227: {"44": 5}, 270: {"44": 12}}
        self.assertEqual(worn_at_once(spans, counts), set())

    def test_a_stray_misread_is_not_a_claim(self):
        # `6` is read once or twice on tracks not wearing it; counting those as
        # claims would condemn a number two players really do wear.
        spans = {18: (0, 3313), 2: (0, 2932), 82: (287, 3088)}
        counts = {18: {"6": 8}, 2: {"44": 9, "6": 2}, 82: {"10": 9, "6": 1}}
        self.assertEqual(worn_at_once(spans, counts), set())

    def test_a_claim_needs_exactly_the_minimum_readings(self):
        spans = {1: (0, 100), 2: (0, 100), 3: (0, 100)}
        below = {i: {"7": CLAIM_MIN_READINGS - 1} for i in (1, 2, 3)}
        at = {i: {"7": CLAIM_MIN_READINGS} for i in (1, 2, 3)}
        self.assertEqual(worn_at_once(spans, below), set())
        self.assertEqual(worn_at_once(spans, at), {"7"})

    def test_more_claimants_than_teams_but_never_concurrent_is_allowed(self):
        spans = {1: (0, 100), 2: (200, 300), 3: (400, 500)}
        self.assertEqual(worn_at_once(spans, {i: {"7": 5} for i in (1, 2, 3)}), set())

    def test_the_wearers_allowed_is_exactly_the_number_of_teams(self):
        spans = {i: (0, 100) for i in range(1, MAX_WEARERS + 2)}
        counts = {i: {"7": 5} for i in spans}
        self.assertEqual(worn_at_once(spans, counts), {"7"})
        del spans[MAX_WEARERS + 1], counts[MAX_WEARERS + 1]
        self.assertEqual(worn_at_once(spans, counts), set())

    def test_a_track_with_no_span_is_not_a_claimant(self):
        spans = {1: (0, 100), 2: (0, 100)}
        counts = {1: {"7": 5}, 2: {"7": 5}, 99: {"7": 5}}
        self.assertEqual(worn_at_once(spans, counts), set())


if __name__ == "__main__":
    unittest.main(verbosity=2)
