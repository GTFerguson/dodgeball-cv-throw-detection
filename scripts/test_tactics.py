#!/usr/bin/env python
"""Checks on splitting efficiency by set-up.

Run with ``.venv/bin/python scripts/test_tactics.py``.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.tactics import (  # noqa: E402
    COORDINATION_S,
    FAKE_WINDOW_S,
    Event,
    attacks,
    coordinated,
    fakes_before,
    split,
)

FPS = 25.0


def throw(frame, team="near", won=False):
    return Event(frame, team, "throw", won)


def fake(frame, team="near"):
    return Event(frame, team, "fake", False)


class Coordination(unittest.TestCase):

    def test_two_same_team_throws_inside_the_window_are_coordinated(self):
        a, b = throw(100), throw(100 + round(COORDINATION_S * FPS))
        self.assertTrue(coordinated([a, b], a, FPS))
        self.assertTrue(coordinated([a, b], b, FPS))

    def test_one_frame_past_the_window_is_solo(self):
        a, b = throw(100), throw(101 + round(COORDINATION_S * FPS))
        self.assertFalse(coordinated([a, b], a, FPS))

    def test_the_other_team_and_a_pass_do_not_count(self):
        a = throw(100)
        self.assertFalse(coordinated([a, throw(102, team="far"), Event(103, "near", "pass", False)],
                                     a, FPS))

    def test_the_window_is_a_duration(self):
        a, b = throw(100), throw(104)
        self.assertTrue(coordinated([a, b], a, 12.5))
        self.assertFalse(coordinated([a, throw(108)], a, 12.5))

    def test_an_attack_chains_releases_however_many_balls(self):
        a, b, c, d = throw(100), throw(106), throw(112), throw(200)
        groups = attacks([a, b, c, d, throw(103, team="far")], FPS)
        self.assertEqual([[e.frame for e in g] for g in groups], [[100, 106, 112], [103], [200]])


class Fakes(unittest.TestCase):

    def test_same_team_fakes_in_the_trailing_window_are_counted(self):
        t = throw(1000)
        events = [fake(1000 - int(FAKE_WINDOW_S * FPS)), fake(990), fake(1001),
                  fake(995, team="far"), t]
        self.assertEqual(fakes_before(events, t, FPS), 2)

    def test_a_fake_just_outside_the_window_is_not(self):
        t = throw(1000)
        self.assertEqual(fakes_before([fake(1000 - int(FAKE_WINDOW_S * FPS) - 1), t], t, FPS), 0)


class Split(unittest.TestCase):

    def test_each_throw_lands_in_one_coordination_cell_and_one_fake_bin(self):
        events = [fake(80), throw(100, won=True), throw(105), throw(400, team="far", won=False),
                  fake(380, team="far"), fake(390, team="far"), fake(395, team="far")]
        r = split(events, [(0, None)], FPS)
        near, far = r[0]["near"], r[0]["far"]
        self.assertEqual(near["all"], [1, 2])
        # One attack of two balls that put one player out: 1 for 1, not 1 for 2.
        self.assertEqual(near["coordinated"], [1, 1])
        self.assertEqual(near["solo"], [0, 0])
        self.assertEqual(near["fakes"]["1"], [1, 2])
        self.assertEqual(far["solo"], [0, 1])
        self.assertEqual(far["fakes"]["2+"], [0, 1])
        self.assertEqual(r["total"]["near"]["all"], [1, 2])

    def test_sets_are_split_and_summed(self):
        events = [throw(100, won=True), throw(2000), throw(2005)]
        r = split(events, [(0, 1000), (1500, None)], FPS)
        self.assertEqual(r[0]["near"]["all"], [1, 1])
        self.assertEqual(r[1]["near"]["all"], [0, 2])
        self.assertEqual(r[1]["near"]["coordinated"], [0, 1])
        self.assertEqual(r["total"]["near"]["all"], [1, 3])

    def test_a_throw_outside_every_set_is_not_counted(self):
        r = split([throw(100)], [(200, 300)], FPS)
        self.assertNotIn("near", r[0])
        self.assertEqual(r["total"], {})


if __name__ == "__main__":
    unittest.main()
