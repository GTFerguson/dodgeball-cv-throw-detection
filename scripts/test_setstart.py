#!/usr/bin/env python
"""Checks on set-start detection.

The three signals are cheap to compute and easy to get subtly wrong in ways that
still produce a plausible time: a search band that misses the balls' pixels, a
whistle timed from its peak rather than its onset, or a sprint test that counts
referees. Each is covered here, and the clip itself is checked end to end when it
is present, because the thresholds are only meaningful against real footage.

Run with ``.venv/bin/python scripts/test_setstart.py``.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from court import CENTRE_LINE_M, Court  # noqa: E402
from pose import PoseRun  # noqa: E402
import setstart as ss  # noqa: E402

FITTED = REPO_ROOT / "data" / "court" / "wdbf2014_final_h2_set2.json"
CLIP = REPO_ROOT / "data" / "footage" / "wdbf2014_final_h2_set2.mp4"
TIMELINE = REPO_ROOT / "data" / "sets" / "wdbf2014_final_h2_set2.json"

# The rush this clip was cut around, timed by hand from the footage: the referee
# whistles at 17.3 s and the teams are across their baselines by 18.3 s.
KNOWN_START_S = 17.32
KNOWN_START_FRAME = 433
START_TOLERANCE_S = 0.4


def a_court() -> Court:
    if not FITTED.exists():
        raise unittest.SkipTest(f"no calibration at {FITTED}; run scripts/fit_court.py")
    return Court.load(FITTED)


def detection(cx, cy, court, conf=0.9):
    """A standing player at a court position, as the pose reader would report."""
    x, y = court.to_image(cx, cy)
    kpts = [[x, y - 100.0, 0.9] for _ in range(15)]
    kpts += [[x - 5.0, y, 0.95], [x + 5.0, y, 0.95]]
    return {"box": [x - 30, y - 200, x + 30, y], "conf": conf, "kpts": kpts}


class ArmedState(unittest.TestCase):
    def test_needs_enough_balls(self):
        few = [0.5, 4.5, 8.5][: ss.ARMED_MIN_BALLS - 1]
        self.assertFalse(ss.is_armed(few))

    def test_needs_them_spread_along_the_line(self):
        """Balls bunched at one end are a pile, not a layout."""
        clustered = [0.1 * i for i in range(ss.ARMED_MIN_BALLS + 2)]
        self.assertFalse(ss.is_armed(clustered))

    def test_accepts_a_laid_out_line(self):
        laid = [0.5, 1.2, 1.8, 7.2, 7.8, 8.5]
        self.assertTrue(ss.is_armed(laid))

    def test_a_hidden_ball_does_not_disarm(self):
        """A ball behind a waiting player is routine and must not end a window."""
        laid = [0.5, 1.2, 7.8, 8.5]
        self.assertGreaterEqual(len(laid), ss.ARMED_MIN_BALLS)
        self.assertTrue(ss.is_armed(laid))


class SearchBand(unittest.TestCase):
    def setUp(self):
        self.court = a_court()
        self.mask = ss.centre_line_mask(self.court, self.court.frame_size)

    def test_covers_the_line_itself(self):
        for cx in (0.5, 4.5, 8.5):
            x, y = self.court.to_image(cx, CENTRE_LINE_M)
            self.assertTrue(self.mask[int(round(y)), int(round(x))],
                            f"centre line at x={cx} m is outside the search band")

    def test_reaches_above_the_floor(self):
        """A ball is a solid object: its pixels sit above where it touches down.

        The band is grown towards the top of the image for exactly this reason,
        and growing it the other way leaves ball bodies outside the mask while
        still looking like a plausible band.
        """
        x, y = self.court.to_image(4.5, CENTRE_LINE_M)
        top = int(round(y - ss.BALL_DIAMETER_NORM[0] * self.court.scale_at(y)))
        self.assertTrue(self.mask[top, int(round(x))],
                        "band does not cover a ball standing on the centre line")

    def test_excludes_the_far_baseline(self):
        x, y = self.court.to_image(4.5, 17.5)
        self.assertFalse(self.mask[int(round(y)), int(round(x))])


class WhistlePicking(unittest.TestCase):
    def times(self, n=1000):
        return np.arange(n) * 0.01

    def test_reports_onset_not_peak(self):
        t = self.times()
        p = np.zeros_like(t)
        p[100:140] = np.linspace(ss.WHISTLE_MIN_PROMINENCE_DB + 2, 40, 40)
        found = ss.loudest_whistle(t, p, (0.0, 10.0))
        self.assertIsNotNone(found)
        onset, strength = found
        self.assertAlmostEqual(onset, 1.0, places=2)
        self.assertAlmostEqual(strength, 40.0, places=1)

    def test_ignores_the_crowd(self):
        t = self.times()
        p = np.full_like(t, ss.WHISTLE_MIN_PROMINENCE_DB - 5)
        self.assertIsNone(ss.loudest_whistle(t, p, (0.0, 10.0)))

    def test_ignores_a_single_loud_sample(self):
        """A click or a compression artefact is not a whistle."""
        t = self.times()
        p = np.zeros_like(t)
        p[500] = 60.0
        self.assertIsNone(ss.loudest_whistle(t, p, (0.0, 10.0)))

    def test_picks_the_strongest_inside_the_window(self):
        t = self.times()
        p = np.zeros_like(t)
        p[100:140] = 25.0
        p[300:340] = 35.0
        onset, strength = ss.loudest_whistle(t, p, (0.0, 10.0))
        self.assertAlmostEqual(onset, 3.0, places=2)
        self.assertAlmostEqual(strength, 35.0, places=1)

    def test_confines_itself_to_the_window(self):
        """The gate is the whole point: a whistle outside it is somebody else's."""
        t = self.times()
        p = np.zeros_like(t)
        p[700:740] = 40.0
        self.assertIsNone(ss.loudest_whistle(t, p, (0.0, 5.0)))


class SprintTest(unittest.TestCase):
    def setUp(self):
        self.court = a_court()

    def test_waiting_players_are_not_a_sprint(self):
        waiting = [detection(cx, 0.5, self.court) for cx in (1, 3, 5, 7)]
        waiting += [detection(cx, 17.5, self.court) for cx in (1, 3, 5, 7)]
        self.assertEqual(ss.mid_court_players(waiting, self.court), 0)

    def test_counts_players_who_have_broken_for_the_line(self):
        running = [detection(cx, 7.0, self.court) for cx in (2, 4, 6)]
        self.assertEqual(ss.mid_court_players(running, self.court), 3)

    def test_ignores_the_crowd_and_benches(self):
        """Detections off the court are numerous and must never count."""
        offcourt = [detection(-4.0, 9.0, self.court), detection(13.0, 9.0, self.court)]
        self.assertEqual(ss.mid_court_players(offcourt, self.court), 0)

    def test_ignores_low_confidence_detections(self):
        faint = [detection(4.0, 9.0, self.court, conf=ss.PLAYER_MIN_CONF - 0.1)]
        self.assertEqual(ss.mid_court_players(faint, self.court), 0)


def a_timeline(**overrides):
    """A written timeline, as scripts/detect_set_start.py produces one."""
    payload = {
        "schema_version": ss.SCHEMA_VERSION,
        "video": "clip.mp4",
        "clip_sha256": "abc",
        "fps": 25.0,
        "frame_count": 5000,
        "clip_offset_s": 0.0,
        "thresholds": {},
        "sets": [
            {"status": "confirmed", "start_frame": 100,
             "armed": {"start_frame": 20, "end_frame": 110}},
            {"status": "confirmed", "start_frame": 2100,
             "armed": {"start_frame": 2000, "end_frame": 2110}},
            {"status": "no_whistle", "start_frame": None,
             "armed": {"start_frame": 4800, "end_frame": 4990}},
        ],
    }
    payload.update(overrides)
    return payload


class TimelineReader(unittest.TestCase):
    def load(self, payload):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(payload, fh)
            path = Path(fh.name)
        self.addCleanup(path.unlink)
        return ss.SetTimeline.load(path)

    def test_rejects_a_future_schema(self):
        with self.assertRaises(ValueError):
            self.load(a_timeline(schema_version=ss.SCHEMA_VERSION + 1))

    def test_refuses_a_different_cut_of_the_footage(self):
        """Frame indices are all that tie the layers together."""
        timeline = self.load(a_timeline())
        timeline.check_clip("abc")
        with self.assertRaises(ValueError):
            timeline.check_clip("a different hash")

    def test_only_confirmed_sets_are_starts(self):
        self.assertEqual(self.load(a_timeline()).starts, [100, 2100])

    def test_a_set_is_bounded_by_the_next_ball_layout(self):
        """Play has stopped by the time the balls are being laid out again."""
        intervals = self.load(a_timeline()).live_play_intervals()
        self.assertEqual([(i.start_frame, i.end_frame) for i in intervals],
                         [(100, 2000), (2100, 4800)])

    def test_the_last_set_is_bounded_by_the_clip(self):
        payload = a_timeline()
        payload["sets"] = payload["sets"][:1]
        interval, = self.load(payload).live_play_intervals()
        self.assertEqual(interval.end_frame, payload["frame_count"] - 1)

    def test_every_end_is_declared_a_bound(self):
        """A set ends on its last elimination, which nothing here detects yet."""
        for interval in self.load(a_timeline()).live_play_intervals():
            self.assertTrue(interval.end_is_bound)

    def test_dead_time_belongs_to_no_set(self):
        timeline = self.load(a_timeline())
        self.assertIsNone(timeline.interval_for(50))
        self.assertIsNone(timeline.interval_for(2050))
        self.assertEqual(timeline.interval_for(500).start_frame, 100)

    def test_reads_what_the_script_wrote(self):
        if not TIMELINE.exists():
            self.skipTest(f"no timeline at {TIMELINE}; run scripts/detect_set_start.py")
        timeline = ss.SetTimeline.load(TIMELINE)
        self.assertEqual(timeline.starts, [KNOWN_START_FRAME])
        self.assertEqual(len(timeline.live_play_intervals()), 1)


class OnTheClip(unittest.TestCase):
    """The thresholds only mean anything against the footage they were set on."""

    @classmethod
    def setUpClass(cls):
        if not CLIP.exists():
            raise unittest.SkipTest(f"no clip at {CLIP}; run scripts/make_clip.sh")
        cls.court = a_court()
        try:
            cls.pose = PoseRun.for_video(CLIP)
        except (FileNotFoundError, ValueError) as exc:
            raise unittest.SkipTest(f"no usable pose run: {exc}")
        cls.results = ss.detect_set_starts(CLIP, cls.court, cls.pose)

    def test_finds_both_ball_layouts(self):
        """The clip was cut to hold one set: its own start and the next one's setup."""
        self.assertEqual(len(self.results), 2)

    def test_times_the_rush_from_the_whistle(self):
        first = self.results[0]
        self.assertEqual(first.status, "confirmed")
        found = first.start_frame / self.court.fps
        self.assertAlmostEqual(found, KNOWN_START_S, delta=START_TOLERANCE_S)

    def test_the_break_follows_the_whistle(self):
        """Players react to the whistle, so the sprint must never precede it."""
        first = self.results[0]
        self.assertIsNotNone(first.sprint_frame)
        self.assertGreater(first.sprint_frame, first.start_frame)

    def test_the_layout_breaks_after_the_whistle(self):
        first = self.results[0]
        self.assertGreater(first.first_ball_moves_frame, first.start_frame)

    def test_reports_a_layout_with_no_whistle_rather_than_inventing_one(self):
        """The clip ends during the next set's setup, before its whistle."""
        second = self.results[1]
        self.assertEqual(second.status, "no_whistle")
        self.assertIsNone(second.start_frame)

    def test_the_gate_is_what_makes_the_whistle_usable(self):
        """Ungated, this clip offers many whistles; only one is a set start."""
        times, prominence = ss.whistle_prominence(CLIP)
        whole_clip = ss.loudest_whistle(times, prominence, (0.0, times[-1]))
        loud = prominence >= ss.WHISTLE_MIN_PROMINENCE_DB
        events = np.split(np.flatnonzero(loud),
                          np.flatnonzero(np.diff(np.flatnonzero(loud)) > 1) + 1)
        self.assertGreater(len([e for e in events if len(e) >= 5]), 5)
        self.assertIsNotNone(whole_clip)


if __name__ == "__main__":
    unittest.main(verbosity=2)
