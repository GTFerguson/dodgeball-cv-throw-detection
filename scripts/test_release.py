#!/usr/bin/env python
"""Checks on the release gate: event or not, released or not.

Run with ``.venv/bin/python scripts/test_release.py``. Traces are built by
hand from blob positions; the clip-level checks run only when the timeline
has been written for the evaluation clip.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from src.ball import Blob, Trace, WristFrame  # noqa: E402
from src.candidates import Candidate  # noqa: E402
from src.release import (BALL_BEFORE_MIN, DEPART_MIN_NORM, RUSH_S, TIMELINE_ROOT,  # noqa: E402
                         ball_before, decide, departure)

CLIP = "wdbf2014_final_h2_set2"
SCALE = 500.0
WRIST = (1000.0, 500.0)


def candidate(frame: int = 1000) -> Candidate:
    return Candidate(frame=frame, track_id=1, participant_id="near-7", team="near",
                     score=50.0, detection_index=0, box=(900.0, 300.0, 1100.0, 700.0))


def trace(ball_path: dict[int, tuple[float, float] | None] | None = None,
          held: float = 0.001, frame: int = 1000) -> Trace:
    """A trace where the right wrist holds `held` orange before the peak and
    the ball, if a path is given, sits at those positions by offset."""
    t = Trace(candidate(frame), SCALE)
    for offset in range(-12, 17):
        blobs = ()
        pos = (ball_path or {}).get(offset)
        if pos is not None:
            blobs = (Blob(pos[0], pos[1], 0.03, 200),)
        disc = held if offset < 0 else 0.0
        t.frames[offset] = {
            "L": WristFrame((800.0, 500.0), True, 0.0, ()),
            "R": WristFrame(WRIST, True, disc, blobs),
        }
    return t


def flight(start: int, step: float, frames: int = 8, missing: int | None = None) -> dict:
    """The ball leaving the wrist rightwards at `step` px a frame from offset `start`;
    unseen on offset `missing` if given."""
    path = {o: WRIST for o in range(-8, start)}
    for k in range(frames + 1):
        path[start + k] = (WRIST[0] + step * k, WRIST[1])
    if missing is not None:
        path[missing] = None
    return path


class BallBefore(unittest.TestCase):

    def test_the_fuller_wrist_counts(self):
        self.assertAlmostEqual(ball_before(trace(held=0.004)), 0.004)

    def test_an_empty_hand_is_nothing(self):
        self.assertEqual(ball_before(trace(held=0.0)), 0.0)


class Departure(unittest.TestCase):

    def test_a_ball_flying_off_the_hand_is_a_release(self):
        d = departure(trace(flight(start=0, step=0.15 * SCALE)))
        self.assertTrue(d.released, d)
        self.assertEqual(d.wrist, "R")
        self.assertGreaterEqual(d.distance, DEPART_MIN_NORM)

    def test_a_release_before_the_peak_is_still_found(self):
        d = departure(trace(flight(start=-6, step=0.15 * SCALE)))
        self.assertTrue(d.released, d)
        self.assertLessEqual(d.seed_offset, -6)

    def test_a_frame_the_ball_is_not_seen_on_is_bridged(self):
        # The whip drops the ball from the mask for a frame; the chain steps over it.
        d = departure(trace(flight(start=0, step=0.1 * SCALE, missing=1)))
        self.assertTrue(d.released, d)
        d = departure(trace(flight(start=0, step=0.1 * SCALE, missing=1)))
        self.assertGreaterEqual(d.links, 2)

    def test_two_missing_frames_break_the_chain(self):
        path = flight(start=0, step=0.1 * SCALE, missing=1)
        path[2] = None
        self.assertFalse(departure(trace(path)).released)

    def test_a_step_longer_than_a_throw_is_not_taken(self):
        # Half the scale in a frame is beyond any throw, even read as two
        # frames across a bridged gap.
        d = departure(trace(flight(start=0, step=0.5 * SCALE)))
        self.assertFalse(d.released, d)

    def test_a_chain_through_standing_orange_is_not_a_release(self):
        # A ball on the floor and a sock lie along a line from the hand; each
        # was there the frame before, so neither is the ball leaving.
        t = trace({o: WRIST for o in range(-8, 12)})
        floor = (WRIST[0] + 0.12 * SCALE, WRIST[1])
        sock = (WRIST[0] + 0.26 * SCALE, WRIST[1])
        for o in range(-8, 12):
            r = t.frames[o]["R"]
            t.frames[o]["R"] = WristFrame(r.wrist, True, r.disc, r.blobs + (
                Blob(floor[0], floor[1], 0.03, 200), Blob(sock[0], sock[1], 0.015, 60)))
        self.assertFalse(departure(t).released)

    def test_a_ball_kept_in_the_hand_is_not(self):
        path = {o: WRIST for o in range(-8, 12)}
        self.assertFalse(departure(trace(path)).released)

    def test_a_ball_that_moves_a_little_and_stops_is_not(self):
        # Pumped forward a hand's length and held: a fake.
        path = {o: WRIST for o in range(-8, 0)}
        path.update({o: (WRIST[0] + 0.04 * SCALE, WRIST[1]) for o in range(0, 12)})
        self.assertFalse(departure(trace(path)).released)

    def test_a_chain_that_turns_back_is_not_followed(self):
        # Out and back: the second step reverses, so the chain is one link.
        path = {o: WRIST for o in range(-8, 0)}
        path[0] = (WRIST[0] + 0.15 * SCALE, WRIST[1])
        path[1] = WRIST
        path[2] = (WRIST[0] + 0.15 * SCALE, WRIST[1])
        d = departure(trace(path))
        self.assertLess(d.links, 2)

    def test_a_ball_never_at_the_hand_is_no_departure(self):
        far = (WRIST[0] + 0.5 * SCALE, WRIST[1])
        path = {o: (far[0] + 0.1 * SCALE * (o + 8), far[1]) for o in range(-8, 12)}
        self.assertEqual(departure(trace(path)).links, 0)


class Decide(unittest.TestCase):

    def test_a_proposal_inside_the_rush_is_dropped(self):
        d = decide(trace(frame=440), set_start_frame=433, fps=25.0)
        self.assertEqual(d.dropped, "rush")
        self.assertIsNone(d.released)

    def test_the_rush_ends_after_rush_s(self):
        d = decide(trace(frame=433 + int(RUSH_S * 25) + 1), set_start_frame=433, fps=25.0)
        self.assertNotEqual(d.dropped, "rush")

    def test_no_ball_in_hand_is_not_an_event(self):
        d = decide(trace(held=BALL_BEFORE_MIN / 2), None, 25.0)
        self.assertEqual(d.dropped, "no ball in hand")
        self.assertIsNone(d.kind)

    def test_a_held_ball_that_never_leaves_is_a_fake(self):
        d = decide(trace({o: WRIST for o in range(-8, 12)}), None, 25.0)
        self.assertTrue(d.is_event)
        self.assertEqual(d.kind, "fake")

    def test_a_held_ball_that_leaves_is_a_throw(self):
        d = decide(trace(flight(0, 0.15 * SCALE)), None, 25.0)
        self.assertEqual(d.kind, "throw")
        self.assertTrue(d.released)


@unittest.skipUnless((TIMELINE_ROOT / f"{CLIP}.json").exists(), "no timeline for the clip")
class OnTheClip(unittest.TestCase):

    def setUp(self):
        self.data = json.loads((TIMELINE_ROOT / f"{CLIP}.json").read_text())

    def test_every_proposal_is_accounted_for(self):
        self.assertEqual(len(self.data["events"]) + len(self.data["dropped"]), 105)

    def test_nothing_is_kept_inside_the_rush(self):
        first = min(e["frame"] for e in self.data["events"])
        self.assertGreaterEqual(first, 433 + RUSH_S * 25)

    def test_every_event_carries_its_evidence(self):
        for e in self.data["events"]:
            self.assertIn(e["kind"], ("fake", "throw"))
            self.assertEqual(e["kind"] == "throw", e["released"])
            self.assertGreaterEqual(e["evidence"]["ball_before"], BALL_BEFORE_MIN * 1e3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
