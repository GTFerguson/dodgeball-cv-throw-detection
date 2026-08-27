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
                         MAX_WEARERS, Player, Swap, clash, fold_by_occupancy, join, swaps_between,
                         worn_at_once)


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


class Folding(unittest.TestCase):
    """The pieces no number was read on, named by who is missing from the six."""

    # A near side of six, all on court 0-1000 except where a test says otherwise.
    def side(self, gaps: dict[str, tuple[int, int]] | None = None):
        gaps = gaps or {}
        spans, teams, core, players = {}, {}, {}, []
        for k, number in enumerate(("1", "2", "3", "4", "5", "6")):
            tid = 10 + k
            if number in gaps:
                a, b = gaps[number]
                spans[tid] = (0, a)
                spans[100 + tid] = (b, 1000)
                for t in (tid, 100 + tid):
                    teams[t], core[t] = "near", {0: 30}
                ids = (tid, 100 + tid)
            else:
                spans[tid], teams[tid], core[tid] = (0, 1000), "near", {0: 30}
                ids = (tid,)
            players.append(Player(team="near", number=number, track_ids=ids, start=0, end=1000))
        return spans, teams, core, players

    def fold(self, players, pieces, spans, teams, core, **kw):
        return fold_by_occupancy(players, pieces, spans, teams, core, min_core_frames=25, **kw)

    def test_a_piece_in_the_one_gap_is_that_player(self):
        spans, teams, core, players = self.side({"4": (300, 600)})
        spans[50], teams[50], core[50] = (310, 590), "near", {0: 200}
        fold = self.fold(players, [50], spans, teams, core)
        self.assertEqual(fold.folded[50].number, "4")
        self.assertEqual(fold.folded[50].track_ids, (13, 50, 113))
        self.assertEqual(fold.folded[50].start, 0)
        self.assertEqual((fold.excess, fold.unsure), (frozenset(), frozenset()))

    def test_a_piece_with_nobody_missing_is_a_seventh_body(self):
        spans, teams, core, players = self.side()
        spans[50], teams[50], core[50] = (310, 590), "near", {0: 200}
        fold = self.fold(players, [50], spans, teams, core)
        self.assertEqual(fold.excess, frozenset({50}))
        self.assertEqual(fold.folded, {})

    def test_two_players_missing_at_once_names_nobody(self):
        spans, teams, core, players = self.side({"4": (300, 600), "5": (300, 600)})
        spans[50], teams[50], core[50] = (310, 590), "near", {0: 200}
        fold = self.fold(players, [50], spans, teams, core)
        self.assertEqual(fold.unsure, frozenset({50}))

    def test_naming_one_piece_can_make_the_next_one_certain(self):
        # 4 is missing 300-450 and 5 is missing 300-600; two pieces overlap
        # across 380-440. The later piece runs past 4's return, so it can only
        # be 5 - and once it is, 5 is on court with the earlier piece, which
        # can then only be 4.
        spans, teams, core, players = self.side({"4": (300, 450), "5": (300, 600)})
        spans[50], teams[50], core[50] = (310, 440), "near", {0: 100}
        spans[51], teams[51], core[51] = (380, 590), "near", {0: 100}
        fold = self.fold(players, [50, 51], spans, teams, core)
        self.assertEqual({p: q.number for p, q in fold.folded.items()}, {51: "5", 50: "4"})

    def test_two_pieces_on_court_together_with_one_candidate_are_left_alone(self):
        spans, teams, core, players = self.side({"4": (300, 600)})
        spans[50], teams[50], core[50] = (310, 590), "near", {0: 200}
        spans[51], teams[51], core[51] = (320, 580), "near", {0: 200}
        fold = self.fold(players, [50, 51], spans, teams, core)
        self.assertEqual(fold.folded, {})
        self.assertEqual(fold.unsure, frozenset({50, 51}))

    def test_a_side_with_fewer_than_six_known_keeps_silent(self):
        spans, teams, core, players = self.side({"4": (300, 600)})
        players = players[:5]
        spans[50], teams[50], core[50] = (310, 590), "near", {0: 200}
        fold = self.fold(players, [50], spans, teams, core)
        self.assertEqual(fold.unsure, frozenset({50}))
        self.assertEqual(fold.excess, frozenset())

    def test_a_player_who_sat_this_set_out_is_not_among_the_six(self):
        # 4 played only set 1; in set 0 the side is five known players.
        spans, teams, core, players = self.side({"4": (300, 600)})
        for t in (13, 113):
            core[t] = {1: 30}
        spans[50], teams[50], core[50] = (310, 590), "near", {0: 200}
        fold = self.fold(players, [50], spans, teams, core)
        self.assertEqual(fold.unsure, frozenset({50}))

    def test_a_hand_over_overlap_does_not_make_a_player_present(self):
        spans, teams, core, players = self.side({"4": (300, 600)})
        spans[50], teams[50], core[50] = (300 - JOIN_MAX_OVERLAP + 1, 590), "near", {0: 200}
        self.assertEqual(self.fold(players, [50], spans, teams, core).folded[50].number, "4")
        spans[50] = (300 - JOIN_MAX_OVERLAP, 590)
        self.assertEqual(self.fold(players, [50], spans, teams, core).excess, frozenset({50}))

    def test_position_tells_a_hand_over_from_two_players_at_once(self):
        # 4's track lingers 20 frames into the piece. On one body that is 4
        # handed over to the piece; on two bodies it is 4 still on court, and
        # the piece is whoever else is missing.
        spans, teams, core, players = self.side({"4": (320, 600), "5": (300, 700)})
        spans[50], teams[50], core[50] = (301, 590), "near", {0: 200}
        one_body = self.fold(players, [50], spans, teams, core, together=lambda a, b: True)
        self.assertEqual(one_body.unsure, frozenset({50}))  # 4 or 5: both handed over or absent
        two_bodies = self.fold(players, [50], spans, teams, core, together=lambda a, b: False)
        self.assertEqual(two_bodies.folded[50].number, "5")

    def test_the_player_just_lost_where_the_piece_starts_is_the_piece(self):
        # 4 and 5 are both missing; 4's track ended a few frames before the
        # piece began, in the same place. That seam names the piece.
        spans, teams, core, players = self.side({"4": (300, 600), "5": (200, 700)})
        spans[50], teams[50], core[50] = (310, 590), "near", {0: 200}
        seam = lambda a, b: (a, b) == (13, 50)  # noqa: E731
        self.assertEqual(self.fold(players, [50], spans, teams, core, continues=seam).folded[50].number, "4")
        # With both lost there, the seam says nothing.
        both = lambda a, b: b == 50 and a in (13, 14)  # noqa: E731
        self.assertEqual(self.fold(players, [50], spans, teams, core, continues=both).unsure, frozenset({50}))

    def test_the_reader_is_never_overruled_by_the_count(self):
        # 4 is the one missing, but the piece read 5's number: it is not 4, and
        # 5 is on court, so it is nobody the count can name.
        spans, teams, core, players = self.side({"4": (300, 600)})
        spans[50], teams[50], core[50] = (310, 590), "near", {0: 200}
        fold = self.fold(players, [50], spans, teams, core, claims={50: {"5"}})
        self.assertEqual((fold.folded, fold.unsure, fold.excess), ({}, frozenset({50}), frozenset()))
        # A seventh body is a seventh body whatever it read.
        spans, teams, core, players = self.side()
        spans[50], teams[50], core[50] = (310, 590), "near", {0: 200}
        self.assertEqual(self.fold(players, [50], spans, teams, core, claims={50: {"17"}}).excess, frozenset({50}))
        # And a claim that agrees with the count settles a choice of two.
        spans, teams, core, players = self.side({"4": (300, 600), "5": (300, 600)})
        spans[50], teams[50], core[50] = (310, 590), "near", {0: 200}
        self.assertEqual(self.fold(players, [50], spans, teams, core, claims={50: {"5"}}).folded[50].number, "5")

    def test_a_piece_with_no_side_or_no_core_frames_is_unsure(self):
        spans, teams, core, players = self.side({"4": (300, 600)})
        spans[50], teams[50], core[50] = (310, 590), None, {0: 200}
        spans[51], teams[51], core[51] = (310, 590), "near", {}
        fold = self.fold(players, [50, 51], spans, teams, core)
        self.assertEqual(fold.unsure, frozenset({50, 51}))


class Swapping(unittest.TestCase):
    """Two tracks on court together that read one number one after the other."""

    def test_a_number_that_moves_between_concurrent_tracks_is_a_swap(self):
        spans = {2: (0, 2900), 49: (100, 740)}
        windows = {2: {"44": (450, 2800)}, 49: {"44": (280, 360)}}
        self.assertEqual(swaps_between(spans, windows), [Swap(a=49, b=2, number="44", last_a=360, first_b=450)])

    def test_the_order_of_the_windows_says_who_had_it_first(self):
        spans = {2: (0, 2900), 49: (100, 740)}
        windows = {2: {"44": (120, 200)}, 49: {"44": (400, 700)}}
        self.assertEqual(swaps_between(spans, windows)[0], Swap(a=2, b=49, number="44", last_a=200, first_b=400))

    def test_tracks_in_sequence_are_a_join_not_a_swap(self):
        spans = {2: (0, 2932), 227: (2935, 3394)}
        windows = {2: {"44": (100, 2800)}, 227: {"44": (3000, 3300)}}
        self.assertEqual(swaps_between(spans, windows), [])

    def test_a_number_two_tracks_read_at_once_is_not_a_swap(self):
        spans = {2: (0, 2900), 49: (100, 740)}
        windows = {2: {"44": (200, 600)}, 49: {"44": (300, 500)}}
        self.assertEqual(swaps_between(spans, windows), [])

    def test_different_numbers_do_not_swap(self):
        spans = {2: (0, 2900), 49: (100, 740)}
        windows = {2: {"44": (450, 2800)}, 49: {"18": (280, 360)}}
        self.assertEqual(swaps_between(spans, windows), [])
