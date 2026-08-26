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

from src.players import JOIN_MAX_OVERLAP, Player, clash, join  # noqa: E402


class Joining(unittest.TestCase):
    # On the evaluation clip SARAULT 44 is tracks 2, 227 and 270 in sequence,
    # with gaps of three and six frames where the huddle hid him.

    def test_fragments_of_one_number_in_sequence_are_one_player(self):
        spans = {2: (0, 2932), 227: (2935, 3394), 270: (3400, 4967)}
        numbers = {2: 44, 227: 44, 270: 44}
        self.assertEqual(join(spans, numbers, {2: "near", 227: "near", 270: "near"}), [
            Player(team="near", number=44, track_ids=(2, 227, 270), start=0, end=4967),
        ])

    def test_tracks_are_ordered_by_when_they_were_worn_not_by_id(self):
        spans = {9: (3000, 4000), 3: (0, 2900)}
        self.assertEqual(join(spans, {9: 6, 3: 6})[0].track_ids, (3, 9))

    def test_a_brief_overlap_is_a_hand_over_and_still_joins(self):
        # 56 (CHALMERS' own track) lingered 24 frames after 422 took his body.
        spans = {56: (129, 2905), 422: (2881, 3671)}
        self.assertEqual(len(join(spans, {56: 7, 422: 7})), 1)

    def test_two_tracks_wearing_a_number_at_once_are_two_people(self):
        spans = {1: (0, 3000), 2: (1000, 4000)}
        self.assertEqual(clash(spans, [1, 2]), (1, 2))
        self.assertEqual(len(join(spans, {1: 44, 2: 44})), 2)

    def test_a_clash_leaves_every_track_of_that_number_unjoined(self):
        # A third fragment that overlaps neither could belong to either of
        # them, and the number cannot say which.
        spans = {1: (0, 3000), 2: (1000, 4000), 3: (4100, 5000)}
        players = join(spans, {1: 44, 2: 44, 3: 44})
        self.assertEqual([p.track_ids for p in players], [(1,), (2,), (3,)])

    def test_the_overlap_allowed_is_exactly_the_tolerance(self):
        spans = {1: (0, 100), 2: (101 - JOIN_MAX_OVERLAP, 300)}
        self.assertIsNone(clash(spans, [1, 2]))
        spans[2] = (100 - JOIN_MAX_OVERLAP, 300)
        self.assertEqual(clash(spans, [1, 2]), (1, 2))

    def test_unnamed_tracks_are_nobody(self):
        spans = {1: (0, 100), 2: (200, 300)}
        self.assertEqual(join(spans, {1: 10}), [
            Player(team=None, number=10, track_ids=(1,), start=0, end=100),
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
