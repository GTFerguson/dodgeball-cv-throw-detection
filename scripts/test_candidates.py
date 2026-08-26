#!/usr/bin/env python
"""Checks on proposing throw candidates from the pose run.

Run with ``.venv/bin/python scripts/test_candidates.py``. The clip-level checks
run only when the roster and candidates have been built for the evaluation
clip, because the thresholds are only meaningful against real footage.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from src.candidates import (CANDIDATES_ROOT, MIN_SCORE, MIN_SEPARATION_FRAMES,  # noqa: E402
                            Candidate, CandidateSet, detect, peaks,
                            relative_wrist_speed, wound_up)

CLIP = "wdbf2014_final_h2_set2"


def person(shoulder=(100.0, 100.0), hip=(100.0, 160.0), wrist=(100.0, 130.0),
           wrist_conf=0.9) -> dict:
    """A skeleton with both shoulders, both hips and one (right) wrist placed."""
    kpts = [[0.0, 0.0, 0.0] for _ in range(17)]
    kpts[5] = [shoulder[0] - 10, shoulder[1], 0.9]
    kpts[6] = [shoulder[0] + 10, shoulder[1], 0.9]
    kpts[11] = [hip[0] - 8, hip[1], 0.9]
    kpts[12] = [hip[0] + 8, hip[1], 0.9]
    kpts[10] = [wrist[0], wrist[1], wrist_conf]
    kpts[15] = [hip[0] - 8, hip[1] + 80, 0.9]
    kpts[16] = [hip[0] + 8, hip[1] + 80, 0.9]
    return {"box": [80.0, 80.0, 120.0, 250.0], "conf": 0.9, "kpts": kpts}


class WindUp(unittest.TestCase):
    # "Up" is along the body, from the hips to the shoulders, so that a player
    # lying on the floor does not have every wrist above the shoulder.

    def test_a_wrist_past_the_shoulder_on_a_standing_player_is_wound_up(self):
        self.assertTrue(wound_up(person(wrist=(120.0, 80.0))))

    def test_a_wrist_at_the_hip_is_not(self):
        self.assertFalse(wound_up(person(wrist=(100.0, 150.0))))

    def test_a_prone_player_with_the_wrist_above_in_the_image_is_not(self):
        # Lying with the head towards the camera: shoulders below the hips in
        # the image. A wrist higher in the image than the shoulder is towards
        # the feet, which is down the body.
        prone = person(shoulder=(100.0, 200.0), hip=(100.0, 150.0), wrist=(100.0, 170.0))
        self.assertFalse(wound_up(prone))

    def test_a_prone_player_reaching_past_the_head_is(self):
        prone = person(shoulder=(100.0, 200.0), hip=(100.0, 150.0), wrist=(100.0, 230.0))
        self.assertTrue(wound_up(prone))

    def test_an_unseen_wrist_cannot_be_wound_up(self):
        self.assertFalse(wound_up(person(wrist=(120.0, 80.0), wrist_conf=0.1)))


class WristSpeed(unittest.TestCase):
    # The body's own motion is subtracted so a sprinting or diving player's arm
    # is not a throw; the scale divides so near and far players compare.

    def test_a_wrist_moving_with_the_body_has_no_speed(self):
        a = person(shoulder=(100.0, 100.0), hip=(100.0, 160.0), wrist=(100.0, 130.0))
        b = person(shoulder=(130.0, 100.0), hip=(130.0, 160.0), wrist=(130.0, 130.0))
        self.assertEqual(relative_wrist_speed(a, b, scale=100.0), 0.0)

    def test_a_wrist_moving_against_a_still_body_has_speed(self):
        a = person(wrist=(100.0, 130.0))
        b = person(wrist=(140.0, 130.0))
        self.assertAlmostEqual(relative_wrist_speed(a, b, scale=100.0), 400.0)

    def test_the_same_motion_further_away_scores_the_same(self):
        a, b = person(wrist=(100.0, 130.0)), person(wrist=(140.0, 130.0))
        near = relative_wrist_speed(a, b, scale=200.0)
        a2, b2 = person(wrist=(100.0, 130.0)), person(wrist=(120.0, 130.0))
        far = relative_wrist_speed(a2, b2, scale=100.0)
        self.assertAlmostEqual(near, far)

    def test_missing_keypoints_score_nothing(self):
        self.assertEqual(relative_wrist_speed(person(wrist_conf=0.1), person(), 100.0), 0.0)
        self.assertEqual(relative_wrist_speed({"kpts": []}, person(), 100.0), 0.0)


class Peaks(unittest.TestCase):

    def test_peaks_are_the_strongest_frames_at_least_a_motion_apart(self):
        scores = [0, 50, 60, 55, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 45, 0]
        self.assertEqual(peaks(scores, min_score=30.0, min_separation=12), [2, 14])

    def test_a_second_peak_inside_the_separation_is_the_same_motion(self):
        scores = [0, 50, 0, 0, 0, 40, 0]
        self.assertEqual(peaks(scores, min_score=30.0, min_separation=12), [1])

    def test_nothing_below_the_score_is_a_peak(self):
        self.assertEqual(peaks([10.0, 20.0, 29.9], min_score=30.0), [])


class FakeInterval:
    def __init__(self, a, b):
        self.start_frame, self.end_frame = a, b

    def contains(self, f):
        return self.start_frame <= f <= self.end_frame


class FakeTimeline:
    def live_play_intervals(self):
        return [FakeInterval(0, 100)]


class FakeCourt:
    # At this scale a 3 px/frame drift scores 3 and a 60 px whip scores 60.
    def scale_at(self, foot_y):
        return 1000.0


class FakePose:
    def __init__(self, frames):
        self._frames = frames

    def frame(self, f):
        return self._frames.get(f, [])


class FakeTrack:
    def __init__(self, id, role, team, detections, in_play):
        self.id, self.role, self.team = id, role, team
        self.participant_id = f"{role}-t{id}"
        self.detections, self._in_play = detections, in_play

    def is_in_play(self, f):
        return self._in_play(f)


class FakeRoster:
    def __init__(self, tracks):
        self._tracks = tracks

    def player_tracks(self, team=None):
        return [t for t in self._tracks if t.role == "player"]


def throw_sequence(frames: range, at: int) -> dict[int, list[dict]]:
    """A standing player whose wrist rises slowly, then whips forward at `at`."""
    out = {}
    for f in frames:
        if at - 11 <= f < at - 6:
            wrist = (100.0, 130.0 - 10.0 * (f - (at - 12)))   # raised 10 px a frame
        elif at - 6 <= f < at:
            wrist = (100.0, 80.0)               # wound up, above the shoulder
        elif f >= at:
            wrist = (160.0, 90.0)               # the whip: 60 px in one frame, then held
        else:
            wrist = (100.0, 130.0)
        out[f] = [person(wrist=wrist)]
    return out


class Detecting(unittest.TestCase):

    def test_a_wound_up_whip_on_a_player_in_play_is_proposed(self):
        pose = FakePose(throw_sequence(range(0, 40), at=20))
        track = FakeTrack(1, "player", "near", [(f, 0) for f in range(40)], lambda f: True)
        found = detect(FakeRoster([track]), pose, FakeCourt(), FakeTimeline())
        self.assertEqual([(c.frame, c.track_id, c.team) for c in found], [(20, 1, "near")])
        self.assertGreater(found[0].score, MIN_SCORE)

    def test_the_same_motion_on_an_official_is_not(self):
        pose = FakePose(throw_sequence(range(0, 40), at=20))
        track = FakeTrack(1, "official", None, [(f, 0) for f in range(40)], lambda f: True)
        self.assertEqual(detect(FakeRoster([track]), pose, FakeCourt(), FakeTimeline()), [])

    def test_a_whip_while_out_of_play_is_not(self):
        pose = FakePose(throw_sequence(range(0, 40), at=20))
        track = FakeTrack(1, "player", "near", [(f, 0) for f in range(40)], lambda f: f < 10)
        self.assertEqual(detect(FakeRoster([track]), pose, FakeCourt(), FakeTimeline()), [])

    def test_a_whip_outside_live_play_is_not(self):
        pose = FakePose(throw_sequence(range(100, 140), at=120))
        track = FakeTrack(1, "player", "near", [(f, 0) for f in range(100, 140)], lambda f: True)
        self.assertEqual(detect(FakeRoster([track]), pose, FakeCourt(), FakeTimeline()), [])

    def test_a_whip_with_no_wind_up_before_it_is_not(self):
        frames = throw_sequence(range(0, 40), at=20)
        for f in range(9, 20):
            frames[f] = [person(wrist=(100.0, 130.0))]
        for f in range(20, 40):
            frames[f] = [person(wrist=(160.0, 130.0))]   # the whip ends below the shoulder
        track = FakeTrack(1, "player", "near", [(f, 0) for f in range(40)], lambda f: True)
        self.assertEqual(detect(FakeRoster([track]), FakePose(frames), FakeCourt(), FakeTimeline()), [])

    def test_a_gap_in_the_track_does_not_read_as_motion(self):
        frames = throw_sequence(range(0, 40), at=20)
        del frames[19]                          # the whip now spans a missing frame
        track = FakeTrack(1, "player", "near", [(f, 0) for f in sorted(frames)], lambda f: True)
        self.assertEqual(detect(FakeRoster([track]), FakePose(frames), FakeCourt(), FakeTimeline()), [])


class TheFile(unittest.TestCase):

    def test_round_trip(self):
        cs = CandidateSet(video="clip.mp4", clip_sha256="abc", pose_run="run", fps=25.0,
                          thresholds={"min_score": MIN_SCORE},
                          candidates=[Candidate(20, 1, "near-7", "near", 55.5, 0, (1.0, 2.0, 3.0, 4.0))])
        with tempfile.TemporaryDirectory() as d:
            back = CandidateSet.load(cs.write(Path(d) / "c.json"))
        self.assertEqual(back.candidates, cs.candidates)
        self.assertEqual(back.near(24, 6), cs.candidates)
        self.assertEqual(back.near(30, 6), [])
        with self.assertRaises(ValueError):
            back.check_clip("other")


def clip_loadable() -> bool:
    try:
        from src.roster import Roster
        Roster.for_video(CLIP)
        return (CANDIDATES_ROOT / f"{CLIP}.json").exists()
    except Exception:
        return False


@unittest.skipUnless(clip_loadable(), "roster or candidates not built for the clip")
class OnTheClip(unittest.TestCase):
    # Throws found by eye on the clip's contact sheets, at their release frame.
    KNOWN_THROWS = (535, 1027, 1168, 1411, 1465, 1479, 1902, 1989, 2568, 3209, 3482, 4650)
    TOLERANCE = 6

    @classmethod
    def setUpClass(cls):
        from src.roster import Roster
        from setstart import SetTimeline
        cls.roster = Roster.for_video(CLIP)
        cls.found = CandidateSet.for_video(CLIP)
        cls.found.check_clip(cls.roster.clip_sha256)
        cls.timeline = SetTimeline.for_video(CLIP)

    def test_every_known_throw_is_proposed(self):
        for frame in self.KNOWN_THROWS:
            self.assertTrue(self.found.near(frame, self.TOLERANCE), frame)

    def test_only_players_are_proposed(self):
        for c in self.found.candidates:
            self.assertEqual(self.roster.track(c.track_id).role, "player", c)

    def test_nothing_is_proposed_outside_live_play(self):
        for c in self.found.candidates:
            self.assertIsNotNone(self.timeline.interval_for(c.frame), c)

    def test_proposals_are_loose_but_not_a_flood(self):
        # About one per expected event: the plan expects 80-100 events in the set.
        self.assertTrue(60 <= len(self.found.candidates) <= 160, len(self.found.candidates))

    def test_one_track_never_proposes_twice_in_one_motion(self):
        by_track: dict[int, list[int]] = {}
        for c in self.found.candidates:
            by_track.setdefault(c.track_id, []).append(c.frame)
        for track, frames in by_track.items():
            gaps = [b - a for a, b in zip(sorted(frames), sorted(frames)[1:])]
            self.assertTrue(all(g >= MIN_SEPARATION_FRAMES for g in gaps), (track, gaps))


if __name__ == "__main__":
    unittest.main(verbosity=2)
