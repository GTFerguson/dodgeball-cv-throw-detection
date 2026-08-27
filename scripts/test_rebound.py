#!/usr/bin/env python3
"""The rebound witness: contact frame, the turn, the jump cut, and the seed check."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from src.rebound import (DEFLECT_MIN_TURN_DEG, Rebound, after_contact, contact_frame,  # noqa: E402
                         follow, incoming_velocity, on_chain, turn)


def straight(start: tuple[float, float], step: tuple[float, float], n: int, first_frame: int = 100):
    return [(first_frame + i, (start[0] + i * step[0], start[1] + i * step[1])) for i in range(n)]


class ContactFrame(unittest.TestCase):

    def test_the_first_chain_point_inside_the_box_is_the_contact(self):
        chain = straight((0.0, 100.0), (20.0, 0.0), 8)
        box = (100.0, 50.0, 160.0, 150.0)
        self.assertEqual(contact_frame(chain, 7, lambda t, f: box, margin=0.0), 105)

    def test_no_box_on_any_frame_is_no_contact(self):
        chain = straight((0.0, 100.0), (20.0, 0.0), 8)
        self.assertIsNone(contact_frame(chain, 7, lambda t, f: None, margin=0.1))


class Turn(unittest.TestCase):

    def test_a_ball_that_carries_on_turns_nothing(self):
        v = np.array([20.0, 0.0])
        self.assertAlmostEqual(turn(v, [(0.0, 0.0), (20.0, 0.0), (40.0, 0.0)], span=100.0), 0.0)

    def test_a_ball_that_comes_back_turns_round(self):
        v = np.array([20.0, 0.0])
        self.assertAlmostEqual(turn(v, [(0.0, 0.0), (-15.0, 5.0), (-30.0, 10.0)], span=100.0), 161.6, places=1)

    def test_the_turn_is_read_before_the_ball_reaches_a_wall(self):
        # Straight on for three frames, then a wall sends it back: over the
        # first span it carried on, whatever it did later.
        v = np.array([30.0, 0.0])
        points = [(0.0, 0.0), (30.0, 0.0), (60.0, 0.0), (30.0, 0.0), (0.0, 0.0)]
        self.assertLess(turn(v, points, span=50.0), 5.0)

    def test_one_point_is_no_turn(self):
        self.assertIsNone(turn(np.array([1.0, 0.0]), [(0.0, 0.0)], span=10.0))


class Track(unittest.TestCase):

    def test_the_track_ends_at_a_jump_the_ball_could_not_make(self):
        positions = {101: (20.0, 0.0), 102: (40.0, 0.0), 103: (400.0, 300.0), 104: (420.0, 300.0)}
        self.assertEqual(after_contact(positions, 100, (0.0, 0.0), max_step=60.0),
                         [(20.0, 0.0), (40.0, 0.0)])

    def test_the_seed_check_fails_when_the_tracker_left_the_ball_before_the_contact(self):
        chain = straight((0.0, 0.0), (20.0, 0.0), 5)
        on = {f: p for f, p in chain}
        self.assertTrue(on_chain(on, chain, tolerance=5.0))
        off = {**on, 103: (60.0, 90.0)}
        self.assertFalse(on_chain(off, chain, tolerance=5.0))
        self.assertFalse(on_chain({}, chain, tolerance=5.0))

    def test_incoming_velocity_is_the_median_step(self):
        v = incoming_velocity([(0.0, 0.0), (10.0, 0.0), (20.0, 0.0), (30.0, 0.0), (400.0, 0.0)])
        self.assertEqual(tuple(v), (10.0, 0.0))


class Follow(unittest.TestCase):
    """End to end with a scripted tracker in place of SAM2."""

    def setUp(self):
        self.chain = straight((100.0, 300.0), (20.0, 0.0), 8, first_frame=100)   # 100..107, at x=240 by 107
        self.box = (230.0, 250.0, 290.0, 350.0)
        self.contact = 107
        self.frames = {f: np.zeros((600, 800, 3), np.uint8) for f in range(90, 130)}

    def run_follow(self, world_positions):
        # The tracker answers in clip pixels and follow() maps them back
        # through the crop; pinning the crop to the whole frame at scale 1
        # lets the script speak in frame pixels.
        import src.rebound as rb
        old = rb.CROP_MIN_PX, rb.CROP_MAX_PX, rb.CROP_SIDE_PX
        rb.CROP_MIN_PX = rb.CROP_MAX_PX = rb.CROP_SIDE_PX = 800
        seed_frame = self.contact - 3
        try:
            def scripted(clip, prompt):
                return [world_positions.get(seed_frame + i) for i in range(len(clip))]
            return follow(self.chain, self.contact, self.box, 100.0, self.frames, scripted, fps=25.0)
        finally:
            rb.CROP_MIN_PX, rb.CROP_MAX_PX, rb.CROP_SIDE_PX = old

    def test_a_ball_that_comes_back_is_deflected(self):
        world = {f: p for f, p in self.chain}
        for k in range(1, 9):
            world[self.contact + k] = (240.0 - 15.0 * k, 300.0 - 5.0 * k)
        r = self.run_follow(world)
        self.assertTrue(r.seeded)
        self.assertEqual(r.tracked, 8)
        self.assertGreater(r.turn_deg, DEFLECT_MIN_TURN_DEG)
        self.assertTrue(r.deflected)

    def test_a_ball_that_carries_on_is_not(self):
        world = {f: p for f, p in self.chain}
        for k in range(1, 9):
            world[self.contact + k] = (240.0 + 20.0 * k, 300.0)
        r = self.run_follow(world)
        self.assertTrue(r.seeded)
        self.assertFalse(r.deflected)

    def test_a_tracker_that_left_the_ball_before_the_contact_has_no_answer(self):
        world = {f: (p[0], p[1] + 200.0) for f, p in self.chain}   # nowhere near the chain
        for k in range(1, 9):
            world[self.contact + k] = (240.0 - 15.0 * k, 300.0)
        r = self.run_follow(world)
        self.assertFalse(r.seeded)
        self.assertIsNone(r.deflected)

    def test_a_track_that_dies_at_the_contact_has_no_answer(self):
        world = {f: p for f, p in self.chain}
        r = self.run_follow(world)
        self.assertTrue(r.seeded)
        self.assertEqual(r.tracked, 0)
        self.assertIsNone(r.deflected)

    def test_frames_missing_from_the_window_is_no_answer_not_a_crash(self):
        r = follow(self.chain, self.contact, self.box, 100.0, {}, lambda c, p: [], fps=25.0)
        self.assertEqual(r, Rebound(contact_frame=107, seeded=False, tracked=0, turn_deg=None))


if __name__ == "__main__":
    unittest.main()
