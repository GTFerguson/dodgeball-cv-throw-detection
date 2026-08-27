#!/usr/bin/env python
"""Checks on resolving outcomes from the game state.

Run with ``.venv/bin/python scripts/test_outcome.py``.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.outcome import (ELIMINATION_WINDOW_S, HOLD_S, HOLD_SLACK_S, Step,  # noqa: E402
                         Thrown, count_steps, fold, resolve)
from src.timing import frames  # noqa: E402

HOLD_FRAMES = frames(HOLD_S)
HOLD_SLACK_FRAMES = frames(HOLD_SLACK_S)
ELIMINATION_WINDOW = frames(ELIMINATION_WINDOW_S)


def series(levels: list[tuple[int, int]]) -> list[int]:
    """A count series from (value, length) runs."""
    out = []
    for v, n in levels:
        out += [v] * n
    return out


class Steps(unittest.TestCase):

    def test_a_drop_that_holds_is_a_step(self):
        counts = {"far": series([(6, 100), (5, 100)]), "near": series([(6, 200)])}
        self.assertEqual(count_steps(counts, 0), [Step(100, "far", 6, 5)])

    def test_a_blip_is_not(self):
        counts = {"far": series([(6, 100), (5, 10), (6, 100)]), "near": []}
        self.assertEqual(count_steps(counts, 0), [])

    def test_a_flicker_inside_the_hold_is_forgiven(self):
        seq = series([(6, 100), (5, 20), (6, 2), (5, 100)])
        self.assertEqual(count_steps({"far": seq, "near": []}, 0), [Step(100, "far", 6, 5)])

    def test_a_rise_is_a_step_too(self):
        counts = {"near": series([(5, 100), (6, 100)]), "far": []}
        self.assertEqual(count_steps(counts, 433), [Step(533, "near", 5, 6)])

    def test_a_drop_shorter_than_the_hold_less_its_slack_is_not_a_step(self):
        seq = series([(6, 100), (5, HOLD_FRAMES - HOLD_SLACK_FRAMES - 1), (6, 100)])
        self.assertEqual(count_steps({"far": seq, "near": []}, 0), [])
        seq = series([(6, 100), (5, HOLD_FRAMES - HOLD_SLACK_FRAMES), (6, 100)])
        self.assertEqual(len(count_steps({"far": seq, "near": []}, 0)), 2)


class AtAnotherRate(unittest.TestCase):

    def test_the_hold_is_a_duration(self):
        # Half the rate: a drop that holds 25 frames is the same two seconds.
        counts = {"far": series([(6, 50), (5, 50)]), "near": []}
        self.assertEqual(count_steps(counts, 0, fps=12.5), [Step(50, "far", 6, 5)])
        short = {"far": series([(6, 50), (5, HOLD_FRAMES // 2 - HOLD_SLACK_FRAMES // 2 - 1), (6, 50)]),
                 "near": []}
        self.assertEqual(count_steps(short, 0, fps=12.5), [])

    def test_the_elimination_window_is_a_duration(self):
        throws = [Thrown(1, 100, "near")]
        late = 100 + ELIMINATION_WINDOW // 2 + 1
        self.assertNotIn(1, resolve(throws, [Step(late, "far", 6, 5)], fps=12.5)[0])
        self.assertIn(1, resolve(throws, [Step(late - 1, "far", 6, 5)], fps=12.5)[0])


class Resolve(unittest.TestCase):

    def test_a_drop_is_a_hit_by_the_last_throw_at_that_side(self):
        throws = [Thrown(1, 1000, "near"), Thrown(2, 1040, "near"), Thrown(3, 1060, "far")]
        out, orphans = resolve(throws, [Step(1100, "far", 6, 5)])
        self.assertEqual(out[2].outcome, "hit")
        self.assertNotIn(1, out)
        self.assertEqual(orphans, [])

    def test_a_drop_with_a_return_opposite_is_a_catch_of_that_sides_throw(self):
        throws = [Thrown(1, 1000, "far"), Thrown(2, 1010, "near")]
        out, _ = resolve(throws, [Step(1080, "far", 6, 5), Step(1120, "near", 5, 6)])
        self.assertEqual(out[1].outcome, "catch")
        self.assertEqual(out[1].return_frame, 1120)
        self.assertNotIn(2, out)

    def test_the_return_may_come_first(self):
        throws = [Thrown(1, 1000, "far")]
        out, _ = resolve(throws, [Step(1050, "near", 5, 6), Step(1100, "far", 6, 5)])
        self.assertEqual(out[1].outcome, "catch")

    def test_a_drop_too_long_after_any_throw_is_unexplained(self):
        throws = [Thrown(1, 100, "near")]
        out, orphans = resolve(throws, [Step(100 + ELIMINATION_WINDOW + 1, "far", 6, 5)])
        self.assertEqual(out, {})
        self.assertEqual(len(orphans), 1)

    def test_a_throw_resolves_once(self):
        throws = [Thrown(1, 1000, "near")]
        out, orphans = resolve(throws, [Step(1050, "far", 6, 5), Step(1150, "far", 5, 4)])
        self.assertEqual(out[1].outcome, "hit")
        self.assertEqual(len(orphans), 1)

    def test_a_two_player_return_explains_two_catches(self):
        # Far catches twice; the two thrown-out near players leave in one
        # step and the two returning far players walk on in one step. One
        # rise, two catches - not one catch and a hit invented for the second.
        throws = [Thrown(1, 1000, "far"), Thrown(2, 1030, "far")]
        out, orphans = resolve(throws, [Step(1060, "far", 6, 5), Step(1080, "far", 5, 4),
                                        Step(1120, "near", 4, 6)])
        self.assertEqual((out[1].outcome, out[2].outcome), ("catch", "catch"))
        self.assertEqual(orphans, [])

    def test_a_two_player_drop_claims_two_throws(self):
        throws = [Thrown(1, 1000, "near"), Thrown(2, 1010, "near")]
        out, _ = resolve(throws, [Step(1100, "far", 6, 4)])
        self.assertEqual({out[1].outcome, out[2].outcome}, {"hit"})


class Fold(unittest.TestCase):

    def test_the_fold_tracks_hits_and_catches(self):
        throws = [Thrown(1, 100, "near"), Thrown(2, 200, "far")]
        trail = fold(throws, {1: "hit", 2: "catch"}, {"near": 6, "far": 6})
        self.assertEqual(trail, [(100, {"near": 6, "far": 5}), (200, {"near": 7, "far": 4})])


if __name__ == "__main__":
    unittest.main(verbosity=2)
