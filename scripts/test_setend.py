#!/usr/bin/env python
"""Checks on set-end detection.

The floor's signals are easy to over-read: a side above six flickers mid-set
when a tracker fragment doubles a player, and one player on a side is not
the end until the floor fills behind it. Each rule is covered on synthetic
counts, and the clip is checked end to end against the truth set's own end.

Run with ``.venv/bin/python scripts/test_setend.py``.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from src.evaluate import TruthSet  # noqa: E402
from src.roster import ROSTER_ROOT, Roster  # noqa: E402
from src.setend import (FLOOD_MIN_RISE, LAST_STAND_MIN_S, Hit, SetEnd, detect_set_end,  # noqa: E402
                        end_from_counts, flood_after, last_stands, trace_back)
from setstart import SETS_ROOT, SetTimeline  # noqa: E402

CLIP = "wdbf2014_final_h2_set2"
FPS = 25.0
STAND = int(LAST_STAND_MIN_S * FPS)


def counts(*runs: tuple[int, int, int]) -> list[tuple[int, int, int]]:
    """(length, near, far) runs laid end to end from frame 0."""
    out, f = [], 0
    for length, near, far in runs:
        out += [(f + i, near, far) for i in range(length)]
        f += length
    return out


class Stands(unittest.TestCase):

    def test_one_on_a_side_that_holds_is_a_stand(self):
        stands = last_stands(counts((100, 6, 3), (STAND, 6, 1), (20, 6, 2)), FPS)
        self.assertEqual([(s.side, s.start_frame, s.end_frame, s.total) for s in stands],
                         [("far", 100, 100 + STAND - 1, 7)])

    def test_a_moment_at_one_is_not(self):
        self.assertEqual(last_stands(counts((100, 6, 3), (STAND - 1, 6, 1), (20, 6, 2)), FPS), [])

    def test_either_side_may_stand(self):
        stands = last_stands(counts((10, 1, 4), (STAND, 1, 4)), FPS)
        self.assertEqual([s.side for s in stands], ["near"])

    def test_one_against_one_is_a_stand_for_both(self):
        self.assertEqual({s.side for s in last_stands(counts((STAND, 1, 1)), FPS)}, {"near", "far"})


class Floods(unittest.TestCase):

    def test_two_extra_bodies_that_stay_are_a_flood(self):
        seq = counts((STAND, 6, 1), (30, 6, 2), (20, 7, 3))
        stand, = last_stands(seq, FPS)
        self.assertEqual(flood_after(seq, stand, FPS), STAND + 30)

    def test_one_body_back_is_a_catch_not_a_flood(self):
        seq = counts((STAND, 6, 1), (300, 6, 2))
        stand, = last_stands(seq, FPS)
        self.assertIsNone(flood_after(seq, stand, FPS))

    def test_a_flood_must_hold(self):
        seq = counts((STAND, 6, 1), (3, 7, 3), (300, 6, 1))
        stand = last_stands(seq, FPS)[0]
        self.assertIsNone(flood_after(seq, stand, FPS))

    def test_a_flood_must_follow_soon(self):
        seq = counts((STAND, 6, 1), (300, 6, 2), (50, 8, 4))
        stand, = last_stands(seq, FPS)
        self.assertIsNone(flood_after(seq, stand, FPS))


class Ends(unittest.TestCase):

    def test_the_floor_ends_a_set_where_the_stand_ends(self):
        end = end_from_counts(counts((100, 6, 3), (STAND, 6, 1), (30, 6, 2), (20, 7, 3)), FPS)
        self.assertEqual((end.frame, end.source, end.stand.side), (100 + STAND - 1, "floor", "far"))
        self.assertEqual(end.hit_window, (100, 100 + STAND + 30))

    def test_a_stand_a_catch_reversed_is_not_the_end(self):
        seq = counts((STAND, 6, 1), (300, 5, 2), (STAND, 5, 1), (30, 5, 2), (20, 7, 4))
        end = end_from_counts(seq, FPS)
        self.assertEqual(end.stand.start_frame, STAND + 300)

    def test_no_stand_no_end(self):
        self.assertIsNone(end_from_counts(counts((500, 6, 3), (50, 8, 4)), FPS))

    def test_a_hit_on_the_last_player_makes_the_end_exact(self):
        seq = counts((100, 6, 3), (STAND, 6, 1), (30, 6, 2), (20, 7, 3))
        end = end_from_counts(seq, FPS, [Hit(frame=120, side="far")])
        self.assertEqual((end.frame, end.source), (120, "hit"))

    def test_a_hit_on_the_other_side_or_before_the_stand_is_not_it(self):
        seq = counts((100, 6, 3), (STAND, 6, 1), (30, 6, 2), (20, 7, 3))
        end = end_from_counts(seq, FPS, [Hit(frame=120, side="near"), Hit(frame=50, side="far")])
        self.assertEqual(end.source, "floor")

    def test_the_last_throw_at_the_stand_inside_the_window_is_traced_back(self):
        seq = counts((100, 6, 3), (STAND, 6, 1), (30, 6, 2), (20, 7, 3))
        end = end_from_counts(seq, FPS)
        throws = [(1, 90, "near"), (2, 110, "near"), (3, 130, "far"), (4, 140, "near"), (5, 400, "near")]
        self.assertEqual(trace_back(throws, end), 4)
        self.assertIsNone(trace_back([(3, 130, "far")], end))


@unittest.skipUnless((ROSTER_ROOT / f"{CLIP}.json").exists()
                     and (SETS_ROOT / f"{CLIP}.json").exists(), "roster or sets not built")
class OnTheClip(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.roster = Roster.for_video(CLIP)
        cls.timeline = SetTimeline.for_video(CLIP)
        cls.truth = TruthSet.for_video(CLIP)
        cls.start = cls.timeline.starts[0]
        # The truth's own end: the frame the ball went dead after the last elimination.
        (_, cls.truth_end), = cls.truth.set_intervals()

    def test_the_floor_ends_the_set_within_a_second_of_the_truth(self):
        end = detect_set_end(self.roster, self.start, self.timeline.frame_count - 1, FPS)
        self.assertEqual((end.source, end.stand.side), ("floor", "far"))
        self.assertLessEqual(abs(end.frame - self.truth_end), FPS)

    def test_the_truths_last_hit_lies_in_the_hit_window(self):
        end = detect_set_end(self.roster, self.start, self.timeline.frame_count - 1, FPS)
        hits = [Hit(frame=t.end_frame or t.release_frame,
                    side=("far" if t.team == "near" else "near") if t.outcome == "hit" else t.team)
                for t in self.truth.events if t.wins_elimination]
        a, b = end.hit_window
        self.assertTrue(a <= self.truth_end <= b)
        exact = detect_set_end(self.roster, self.start, self.timeline.frame_count - 1, FPS, hits)
        self.assertEqual((exact.frame, exact.source), (self.truth_end, "hit"))

    def test_the_written_end_is_what_the_timeline_reads(self):
        # Exact when the outcome stage's hits were there to be read (the
        # pipeline runs set end after events), a floor bound when they were
        # not; either way within a second of the truth and marked for what it is.
        interval, = self.timeline.live_play_intervals()
        self.assertIn(interval.end_source, ("hit", "floor"))
        self.assertEqual(interval.end_is_bound, interval.end_source != "hit")
        self.assertLessEqual(abs(interval.end_frame - self.truth_end), FPS)
        self.assertIsNotNone(self.timeline.detected_end(interval))


if __name__ == "__main__":
    unittest.main(verbosity=2)
