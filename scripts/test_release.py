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
from src.candidates import Candidate, CandidateSet  # noqa: E402
from src.release import (  # noqa: E402
    BALL_BEFORE_MIN,
    DEPART_MIN_NORM,
    PASS_MIN_ANGLE_DEG,
    RUSH_S,
    TIMELINE_ROOT,
    WINDUP_MIN_HEIGHT,
    ball_before,
    decide,
    departure,
    wound_up_with_ball,
)

CLIP = "wdbf2014_final_h2_set2"
SCALE = 500.0
WRIST = (1000.0, 500.0)


def candidate(frame: int = 1000) -> Candidate:
    return Candidate(frame=frame, track_id=1, participant_id="near-7", team="near",
                     score=50.0, detection_index=0, box=(900.0, 300.0, 1100.0, 700.0))


def trace(ball_path: dict[int, tuple[float, float] | None] | None = None,
          held: float = 0.001, frame: int = 1000, height=None,
          faint: set[int] = frozenset()) -> Trace:
    """A trace where the right wrist holds `held` orange before the peak and
    the ball, if a path is given, sits at those positions by offset. The
    right wrist's height along the torso is `height` - a number for every
    frame, or a dict by offset - and defaults to a wind-up past the shoulder."""
    t = Trace(candidate(frame), SCALE)
    for offset in range(-12, 17):
        blobs, dim = (), ()
        pos = (ball_path or {}).get(offset)
        if pos is not None and offset in faint:
            dim = (Blob(pos[0], pos[1], 0.03, 200, faint=True),)
        elif pos is not None:
            blobs = (Blob(pos[0], pos[1], 0.03, 200),)
        disc = held if offset < 0 else 0.0
        if isinstance(height, dict):
            h = height.get(offset, -0.5)
        else:
            h = height if height is not None else (0.4 if -8 <= offset <= -3 else -0.5)
        t.frames[offset] = {
            "L": WristFrame((800.0, 500.0), True, 0.0, (), -0.8),
            "R": WristFrame(WRIST, True, disc, blobs, h, dim),
        }
    return t


def flight(start: int, step: float, frames: int = 8, missing: int | None = None,
           direction=(1.0, 0.0)) -> dict:
    """The ball leaving the wrist at `step` px a frame along `direction` from
    offset `start`; unseen on offset `missing` if given."""
    path = {o: WRIST for o in range(-8, start)}
    for k in range(frames + 1):
        path[start + k] = (WRIST[0] + step * k * direction[0], WRIST[1] + step * k * direction[1])
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

    def test_a_streak_the_strict_mask_loses_carries_the_chain(self):
        # The final throw on the evaluation clip: the ball is in the hand at
        # frame 4650, a blurred streak the strict mask cannot see on 4651 and
        # 4652, and a ball again from 4653. Two unseen frames broke the chain;
        # the faint mask sees the streak and the chain runs through it.
        path = flight(start=0, step=0.1 * SCALE)
        self.assertFalse(departure(trace({**path, 1: None, 2: None})).released)
        d = departure(trace(path, faint={1, 2}))
        self.assertTrue(d.released, d)
        self.assertGreaterEqual(d.links, 3)

    def test_a_faint_blob_does_not_stop_the_chain_bridging_to_the_ball(self):
        # The ball is unseen for a frame, and a dull patch off the flight line
        # is faintly visible on that frame. The chain must still bridge the
        # frame to the ball rather than stop at the patch.
        t = trace(flight(start=0, step=0.1 * SCALE, missing=1))
        r = t.frames[1]["R"]
        decoy = Blob(WRIST[0], WRIST[1] + 0.1 * SCALE, 0.03, 200, faint=True)
        t.frames[1]["R"] = WristFrame(r.wrist, True, r.disc, r.blobs, r.height, (decoy,))
        d = departure(t)
        self.assertTrue(d.released, d)
        self.assertEqual(d.path[1][1], WRIST[1])

    def test_a_faint_blob_at_the_hand_does_not_seed_a_chain(self):
        # Only the strict mask says a ball was in the hand: dull orange there
        # is a sleeve or the floor, and a chain from it would be a fake released.
        path = flight(start=0, step=0.1 * SCALE)
        held = {o for o in path if o <= 0}
        self.assertFalse(departure(trace(path, faint=held)).released)

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


class WindUp(unittest.TestCase):

    def test_a_ball_carried_past_the_shoulder_is_a_wind_up(self):
        self.assertTrue(wound_up_with_ball(trace(height=WINDUP_MIN_HEIGHT + 0.1)))

    def test_a_ball_kept_below_the_shoulder_is_not(self):
        # A block or a raised catch: high, but never past the line.
        self.assertFalse(wound_up_with_ball(trace(height=WINDUP_MIN_HEIGHT - 0.1)))

    def test_an_empty_hand_past_the_shoulder_is_not(self):
        self.assertFalse(wound_up_with_ball(trace(held=0.0, height=0.5)))


class Direction(unittest.TestCase):
    # The near team's opponent is up the image; the far team's is down.

    def test_a_ball_going_up_the_image_from_a_near_player_is_a_throw(self):
        d = decide(trace(flight(0, 0.15 * SCALE, direction=(0.0, -1.0))), None, 25.0)
        self.assertEqual(d.kind, "throw")
        self.assertAlmostEqual(d.angle, 0.0)

    def test_the_same_ball_from_a_far_player_goes_backwards(self):
        t = trace(flight(0, 0.15 * SCALE, direction=(0.0, -1.0)))
        t.candidate = Candidate(**{**t.candidate.__dict__, "team": "far"})
        d = decide(t, None, 25.0)
        self.assertAlmostEqual(d.angle, 180.0)
        self.assertEqual(d.kind, "pass")

    def test_a_sideways_ball_is_a_pass(self):
        d = decide(trace(flight(0, 0.15 * SCALE, direction=(1.0, 0.0))), None, 25.0)
        self.assertGreaterEqual(d.angle, PASS_MIN_ANGLE_DEG)
        self.assertEqual(d.kind, "pass")

    def test_a_diagonal_towards_the_opponent_is_a_throw(self):
        d = decide(trace(flight(0, 0.15 * SCALE, direction=(0.7, -0.7))), None, 25.0)
        self.assertAlmostEqual(d.angle, 45.0, places=0)
        self.assertEqual(d.kind, "throw")

    def test_a_sideways_ball_on_too_short_a_chain_is_still_a_throw(self):
        # Two links: one hop's jitter is not a direction.
        d = decide(trace(flight(0, 0.15 * SCALE, frames=2, direction=(1.0, 0.0))), None, 25.0)
        self.assertTrue(d.released, d)
        self.assertEqual(d.kind, "throw")

    def test_no_team_no_angle_and_a_throw_by_default(self):
        t = trace(flight(0, 0.15 * SCALE, direction=(1.0, 0.0)))
        t.candidate = Candidate(**{**t.candidate.__dict__, "team": None})
        d = decide(t, None, 25.0)
        self.assertIsNone(d.angle)
        self.assertEqual(d.kind, "throw")

    def test_a_fake_has_no_angle(self):
        d = decide(trace({o: WRIST for o in range(-8, 12)}), None, 25.0)
        self.assertIsNone(d.angle)


class ContactDecides(unittest.TestCase):
    # The ball flies right and lands in a box at +8; whose box it is decides.

    def players(self, team):
        end = (WRIST[0] + 0.15 * SCALE * 8, WRIST[1])
        box = (end[0] - 30.0, end[1] - 80.0, end[0] + 30.0, end[1] + 80.0)
        return lambda frame: [(team, 99, f"{team}-9", box)]

    def test_a_ball_that_reaches_an_opponent_is_a_throw_whatever_its_direction(self):
        d = decide(trace(flight(0, 0.15 * SCALE)), None, 25.0, self.players("far"))
        self.assertEqual(d.kind, "throw")
        self.assertEqual(d.destination_source, "contact")
        self.assertEqual(d.contact.participant_id, "far-9")
        self.assertFalse(d.destination_agreed)  # direction said sideways

    def test_a_ball_that_reaches_a_teammate_is_a_pass(self):
        d = decide(trace(flight(0, 0.15 * SCALE)), None, 25.0, self.players("near"))
        self.assertEqual(d.kind, "pass")
        self.assertTrue(d.destination_agreed)

    def test_the_thrower_is_not_a_contact(self):
        end = (WRIST[0] + 0.15 * SCALE * 8, WRIST[1])
        box = (end[0] - 30.0, end[1] - 80.0, end[0] + 30.0, end[1] + 80.0)
        d = decide(trace(flight(0, 0.15 * SCALE)), None, 25.0, lambda f: [("near", 1, "near-7", box)])
        self.assertIsNone(d.contact)
        self.assertEqual(d.destination_source, "direction")

    def test_nobody_there_falls_back_to_direction(self):
        d = decide(trace(flight(0, 0.15 * SCALE)), None, 25.0, lambda f: [])
        self.assertIsNone(d.contact)
        self.assertEqual(d.destination_source, "direction")
        self.assertEqual(d.kind, "pass")


class Decide(unittest.TestCase):

    def test_a_held_ball_never_past_the_shoulder_is_not_an_event(self):
        d = decide(trace(height=-0.3), None, 25.0)
        self.assertEqual(d.dropped, "no wind-up with the ball")

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

    def test_a_held_ball_that_leaves_towards_the_opponent_is_a_throw(self):
        d = decide(trace(flight(0, 0.15 * SCALE, direction=(0.0, -1.0))), None, 25.0)
        self.assertEqual(d.kind, "throw")
        self.assertTrue(d.released)


@unittest.skipUnless((TIMELINE_ROOT / f"{CLIP}.json").exists(), "no timeline for the clip")
class OnTheClip(unittest.TestCase):

    def setUp(self):
        self.data = json.loads((TIMELINE_ROOT / f"{CLIP}.json").read_text())

    def test_every_proposal_is_accounted_for(self):
        proposals = len(CandidateSet.for_video(CLIP).candidates)
        self.assertEqual(len(self.data["events"]) + len(self.data["dropped"]), proposals)

    def test_nothing_is_kept_inside_the_rush(self):
        first = min(e["frame"] for e in self.data["events"])
        self.assertGreaterEqual(first, 433 + RUSH_S * 25)

    def test_every_event_carries_its_evidence(self):
        for e in self.data["events"]:
            self.assertIn(e["kind"], ("fake", "pass", "throw"))
            self.assertEqual(e["kind"] != "fake", e["released"])
            self.assertEqual(e["evidence"]["angle"] is not None, e["released"])
            self.assertIn(e["evidence"]["destination_source"],
                          ("contact", "direction", "default", None))
            self.assertGreaterEqual(e["evidence"]["ball_before"], BALL_BEFORE_MIN * 1e3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
