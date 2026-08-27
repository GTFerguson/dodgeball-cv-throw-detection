#!/usr/bin/env python3
"""The rebound witness: contact from the ball's path, the turn, the jump cut, and the seed check."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

import src.rebound as rb  # noqa: E402
from src.rebound import (DEFLECT_MIN_TURN_DEG, Contact, Rebound, at_the_feet, box_entries,  # noqa: E402
                         cut_at_jump, follow, on_chain, turn, velocity_into, window_for)


def straight(start: tuple[float, float], step: tuple[float, float], n: int, first_frame: int = 100):
    return [(first_frame + i, (start[0] + i * step[0], start[1] + i * step[1])) for i in range(n)]


class BoxEntries(unittest.TestCase):

    def setUp(self):
        self.players = lambda f: [("near", 1, "near-1", (0.0, 250.0, 60.0, 350.0)),
                                  ("far", 7, "far-7", (230.0, 250.0, 290.0, 350.0)),
                                  ("far", 8, "far-8", (330.0, 250.0, 390.0, 350.0))]

    def test_every_box_the_ball_enters_is_listed_at_the_index_it_enters(self):
        path = straight((100.0, 300.0), (20.0, 0.0), 15)   # x = 100 .. 380
        entries = box_entries(path, self.players, thrower=1, margin=0.0)
        self.assertEqual([(i, c.track_id) for i, c, _ in entries], [(7, 7), (12, 8)])
        self.assertEqual(entries[0][1], Contact(frame=107, team="far", track_id=7, participant_id="far-7"))

    def test_the_throwers_own_box_is_not_an_entry(self):
        path = straight((10.0, 300.0), (20.0, 0.0), 3)
        self.assertEqual(box_entries(path, self.players, thrower=1, margin=0.0), [])

    def test_a_turn_at_the_bottom_of_the_box_is_the_floor(self):
        box = (230.0, 250.0, 290.0, 350.0)
        self.assertTrue(at_the_feet((250.0, 345.0), box))
        self.assertFalse(at_the_feet((250.0, 300.0), box))


class Turn(unittest.TestCase):

    def test_a_ball_that_carries_on_turns_nothing(self):
        v = np.array([20.0, 0.0])
        self.assertAlmostEqual(turn(v, [(0.0, 0.0), (20.0, 0.0), (40.0, 0.0)], span=100.0), 0.0)

    def test_a_ball_that_comes_back_turns_round(self):
        v = np.array([20.0, 0.0])
        self.assertAlmostEqual(turn(v, [(0.0, 0.0), (-15.0, 5.0), (-30.0, 10.0)], span=100.0), 161.6, places=1)

    def test_the_turn_is_read_where_the_ball_leaves_the_box(self):
        # Through the box and on: at the exit it is still on line, whatever
        # it does at the next player.
        v = np.array([20.0, 0.0])
        box = (10.0, -50.0, 50.0, 50.0)
        points = [(12.0, 0.0), (32.0, 0.0), (52.0, 0.0), (40.0, -10.0), (20.0, -20.0)]
        self.assertLess(turn(v, points, span=1000.0, box=box), 1.0)

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
        self.assertEqual(cut_at_jump(positions, (0.0, 0.0), speed=20.0, slack=10.0),
                         [(101, (20.0, 0.0)), (102, (40.0, 0.0))])

    def test_the_seed_check_fails_when_the_tracker_left_the_ball_on_the_chain(self):
        chain = straight((0.0, 0.0), (20.0, 0.0), 5)
        on = dict(chain)
        self.assertTrue(on_chain(on, chain, tolerance=5.0))
        self.assertFalse(on_chain({**on, 103: (60.0, 90.0)}, chain, tolerance=5.0))
        self.assertFalse(on_chain({}, chain, tolerance=5.0))

    def test_velocity_into_is_the_median_step(self):
        v = velocity_into([(0.0, 0.0), (10.0, 0.0), (20.0, 0.0), (30.0, 0.0), (400.0, 0.0)])
        self.assertEqual(tuple(v), (10.0, 0.0))

    def test_the_window_starts_at_the_seed_lookback(self):
        chain = straight((0.0, 0.0), (20.0, 0.0), 8)   # frames 100..107
        first, last = window_for(chain, fps=25.0)
        self.assertEqual(first, 105)
        self.assertEqual(last, 105 + 12 + 8)


class Follow(unittest.TestCase):
    """End to end with a scripted tracker in place of SAM2.

    The chain ends at x=200, four frames short of the far player's box at
    x=280; the tracker carries the ball on to the player and past it.
    """

    def setUp(self):
        self.chain = straight((100.0, 300.0), (20.0, 0.0), 6, first_frame=100)   # 100..105, x 100..200
        self.box = (270.0, 250.0, 330.0, 350.0)
        self.players = lambda f: [("near", 1, "near-1", (0.0, 250.0, 60.0, 350.0)),
                                  ("far", 7, "far-7", self.box)]
        self.frames = {f: np.zeros((800, 800, 3), np.uint8) for f in range(90, 140)}
        self.contact_frame = 109   # x = 280 at 20 px a frame from x=200 at 105

    def run_follow(self, world):
        # The tracker answers in clip pixels and follow() maps them back
        # through the crop; pinning the crop to the whole (square) frame at
        # scale 1 puts its origin at 0 and lets the script speak in frame pixels. No blob is under any point on
        # a black frame, so the seed is the earliest looked-at chain point.
        old = rb.CROP_MIN_PX, rb.CROP_MAX_PX, rb.CROP_SIDE_PX
        rb.CROP_MIN_PX = rb.CROP_MAX_PX = rb.CROP_SIDE_PX = 800
        try:
            def scripted(clip, prompt):
                # each segment starts at the frame the prompt's point or box sits on:
                # the script finds it by matching the seed against the world
                seed = prompt["points"][0] if "points" in prompt else None
                starts = [f for f, p in world.items() if seed and abs(p[0] - seed[0]) < 1e-6 and abs(p[1] - seed[1]) < 1e-6]
                start = min(starts) if starts else window_for(self.chain, 25.0)[0]
                return [world.get(start + i) for i in range(len(clip))]
            return follow(self.chain, 1, self.players, 0.0, lambda y: 100.0, self.frames, scripted, fps=25.0)
        finally:
            rb.CROP_MIN_PX, rb.CROP_MAX_PX, rb.CROP_SIDE_PX = old

    def flight(self, after):
        world = dict(self.chain)
        for k in range(1, 5):
            world[105 + k] = (200.0 + 20.0 * k, 300.0)            # on to the player: 220..280
        for k in range(1, 9):
            world[self.contact_frame + k] = after(k)
        return world

    def test_a_ball_the_chain_lost_short_of_the_player_still_finds_its_contact(self):
        r = self.run_follow(self.flight(lambda k: (280.0 - 15.0 * k, 300.0 - 5.0 * k)))
        self.assertTrue(r.seeded)
        self.assertEqual(r.contact, Contact(frame=109, team="far", track_id=7, participant_id="far-7"))

    def test_a_box_the_ball_passes_straight_through_is_not_the_contact(self):
        # A bystander at x 230..260 stands in the ball's 2D path before the
        # player it turns at.
        players = self.players
        self.players = lambda f: players(f) + [("far", 9, "far-9", (230.0, 250.0, 260.0, 350.0))]
        r = self.run_follow(self.flight(lambda k: (280.0 - 15.0 * k, 300.0 - 5.0 * k)))
        self.assertEqual(r.contact.track_id, 7)
        self.assertEqual(r.passed, 1)
        self.assertTrue(r.deflected)

    def test_a_turn_at_the_feet_is_the_floor_not_the_player(self):
        # Ball into the bottom band of the box, then back up: a bounce beside the feet.
        world = dict(self.chain)
        for k in range(1, 5):
            world[105 + k] = (200.0 + 20.0 * k, 300.0 + 11.0 * k)   # arrives at (280, 344): in the band
        for k in range(1, 9):
            world[109 + k] = (280.0 - 15.0 * k, 344.0 - 10.0 * k)
        r = self.run_follow(world)
        self.assertFalse(r.deflected)

    def test_a_ball_that_comes_back_is_deflected(self):
        r = self.run_follow(self.flight(lambda k: (280.0 - 15.0 * k, 300.0 - 5.0 * k)))
        self.assertEqual(r.tracked, 8)
        self.assertGreater(r.turn_deg, DEFLECT_MIN_TURN_DEG)
        self.assertTrue(r.deflected)

    def test_a_ball_that_carries_on_is_not(self):
        r = self.run_follow(self.flight(lambda k: (280.0 + 20.0 * k, 300.0)))
        self.assertEqual(r.contact.track_id, 7)
        self.assertFalse(r.deflected)

    def test_a_tracker_that_left_the_ball_on_the_chain_has_no_answer(self):
        # ...whether what it followed turned or carried on.
        for after in (lambda k: (280.0 - 15.0 * k, 300.0), lambda k: (280.0 + 20.0 * k, 300.0)):
            world = self.flight(after)
            for f, p in self.chain:
                world[f] = (p[0], p[1] + 200.0)                      # nowhere near the chain
            r = self.run_follow(world)
            self.assertFalse(r.seeded)
            self.assertIsNone(r.deflected)

    def test_a_ball_that_reaches_nobody_has_no_answer(self):
        world = dict(self.chain)
        for k in range(1, 20):
            world[105 + k] = (200.0 + 20.0 * k, 100.0)               # over everyone's head
        r = self.run_follow(world)
        self.assertTrue(r.seeded)
        self.assertIsNone(r.contact)
        self.assertIsNone(r.deflected)

    def test_a_track_that_dies_at_the_contact_has_no_answer(self):
        world = dict(self.chain)
        for k in range(1, 5):
            world[105 + k] = (200.0 + 20.0 * k, 300.0)
        r = self.run_follow(world)
        self.assertEqual(r.contact.frame, 109)
        self.assertEqual(r.tracked, 0)
        self.assertIsNone(r.deflected)

    def test_frames_missing_from_the_window_is_no_answer_not_a_crash(self):
        r = follow(self.chain, 1, self.players, 0.0, lambda y: 100.0, {}, lambda c, p: [], fps=25.0)
        self.assertEqual(r, Rebound(seeded=False, contact=None, tracked=0, turn_deg=None))


if __name__ == "__main__":
    unittest.main()
