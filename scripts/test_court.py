#!/usr/bin/env python
"""Checks on the court reader.

The fit is validated by held-out markings; these cover the reader, where the
failures are quieter. A transform that loses precision, a boundary test that
flickers on the line, or a foot point taken from the wrong place all produce
plausible court positions rather than errors, and the only symptom downstream is
an elimination that never happened.

Run with ``.venv/bin/python scripts/test_court.py``.
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

from court import (  # noqa: E402
    CENTRE_LINE_M, COURT_LENGTH_M, COURT_WIDTH_M,
    LEFT_ANKLE, RIGHT_ANKLE, MARGIN_M, MAX_BOUNDARY_SLACK_M, SCHEMA_VERSION, Court, foot_point,
)

FITTED = REPO_ROOT / "data" / "court" / "wdbf2014_final_h2_set2.json"


def a_court() -> Court:
    if not FITTED.exists():
        raise unittest.SkipTest(f"no calibration at {FITTED}; run scripts/fit_court.py")
    return Court.load(FITTED)


def detection(box, ankle_conf=(0.9, 0.9), ankle_xy=((900.0, 700.0), (940.0, 704.0))):
    kpts = [[0.0, 0.0, 0.0] for _ in range(17)]
    for i, xy, c in zip((LEFT_ANKLE, RIGHT_ANKLE), ankle_xy, ankle_conf):
        kpts[i] = [xy[0], xy[1], c]
    return {"box": list(box), "conf": 0.9, "kpts": kpts}


class Transforms(unittest.TestCase):
    def setUp(self):
        self.court = a_court()

    def test_round_trip_is_lossless(self):
        for cx, cy in [(0, 0), (COURT_WIDTH_M, 0), (4.5, 9.0),
                       (0, COURT_LENGTH_M), (COURT_WIDTH_M, COURT_LENGTH_M)]:
            x, y = self.court.to_image(cx, cy)
            bx, by = self.court.to_court(x, y)
            self.assertAlmostEqual(bx, cx, places=6)
            self.assertAlmostEqual(by, cy, places=6)

    def test_corners_map_to_court_corners(self):
        truth = [(0, 0), (COURT_WIDTH_M, 0), (COURT_WIDTH_M, COURT_LENGTH_M), (0, COURT_LENGTH_M)]
        for (x, y), (cx, cy) in zip(self.court.corners_image, truth):
            gx, gy = self.court.to_court(x, y)
            self.assertAlmostEqual(gx, cx, places=3)
            self.assertAlmostEqual(gy, cy, places=3)

    def test_vectorises(self):
        xs = np.array([100.0, 500.0, 900.0])
        ys = np.array([900.0, 700.0, 400.0])
        cx, cy = self.court.to_court(xs, ys)
        self.assertEqual(cx.shape, xs.shape)
        for i in range(len(xs)):
            sx, sy = self.court.to_court(float(xs[i]), float(ys[i]))
            self.assertAlmostEqual(float(cx[i]), sx, places=9)
            self.assertAlmostEqual(float(cy[i]), sy, places=9)

    def test_held_out_markings_are_within_tolerance(self):
        for marking, error in self.court.held_out_error_m.items():
            self.assertLess(abs(error), 0.25, f"{marking} m off by {error}")


class Zones(unittest.TestCase):
    def setUp(self):
        self.court = a_court()

    def test_inside_is_on_court_and_not_in_margin(self):
        self.assertTrue(self.court.on_court(4.5, 9.0))
        self.assertFalse(self.court.in_margin(4.5, 9.0))

    def test_margin_is_outside_the_court_but_adjacent(self):
        just_out = COURT_WIDTH_M + MARGIN_M / 2
        self.assertFalse(self.court.on_court(just_out, 9.0))
        self.assertTrue(self.court.in_margin(just_out, 9.0))

    def test_beyond_the_margin_is_neither(self):
        far = COURT_WIDTH_M + MARGIN_M * 3
        self.assertFalse(self.court.on_court(far, 9.0))
        self.assertFalse(self.court.in_margin(far, 9.0))

    def test_a_player_on_the_line_stays_on_court(self):
        # Detection noise around an exact boundary would otherwise read as a
        # player leaving and returning, and a crossing is an elimination.
        slack = float(self.court.slack_at(0.0, 9.0))
        self.assertTrue(self.court.on_court(-slack / 2, 9.0))
        self.assertTrue(self.court.on_court(COURT_WIDTH_M + slack / 2, 9.0))

    def test_the_slack_is_wider_where_a_pixel_is_worth_more_court(self):
        # The camera is end-on, so the same ankle wobble spans several times more
        # court at the far baseline than at the near one. A slack fixed in metres
        # is therefore either loose near the camera or useless far from it.
        near = float(self.court.slack_at(COURT_WIDTH_M / 2, 0.0))
        far = float(self.court.slack_at(COURT_WIDTH_M / 2, COURT_LENGTH_M))
        self.assertGreater(far, near * 2)
        self.assertLess(far, MAX_BOUNDARY_SLACK_M)

    def test_the_slack_never_reaches_the_crossing_band(self):
        # on_court and in_margin have to stay disjoint, or the eliminated queue
        # standing in the band joins the roster.
        self.assertLess(MAX_BOUNDARY_SLACK_M, MARGIN_M)

    def test_half_splits_on_the_centre_line(self):
        self.assertEqual(str(self.court.half(CENTRE_LINE_M - 0.1)), "near")
        self.assertEqual(str(self.court.half(CENTRE_LINE_M + 0.1)), "far")


class Scale(unittest.TestCase):
    def setUp(self):
        self.court = a_court()

    def test_far_players_scale_smaller_than_near(self):
        near, far = self.court.to_image(4.5, 1.0), self.court.to_image(4.5, 17.0)
        self.assertGreater(self.court.scale_at(near[1]), self.court.scale_at(far[1]))

    def test_normalising_makes_two_ends_comparable(self):
        # A player of one real height at each end: pixel heights differ by ~2x,
        # normalised heights must not.
        near_y, far_y = 980.0, 300.0
        k = 0.2313
        near_px = k * self.court.scale_at(near_y)
        far_px = k * self.court.scale_at(far_y)
        self.assertGreater(near_px / far_px, 1.5)
        self.assertAlmostEqual(float(self.court.normalise(near_px, near_y)),
                               float(self.court.normalise(far_px, far_y)), places=9)


class FootPoint(unittest.TestCase):
    def test_prefers_both_ankles(self):
        x, y, source = foot_point(detection((800, 400, 1000, 720)))
        self.assertEqual(source, "ankles")
        self.assertAlmostEqual(x, 920.0)
        self.assertAlmostEqual(y, 702.0)

    def test_uses_a_single_visible_ankle(self):
        x, y, source = foot_point(detection((800, 400, 1000, 720), ankle_conf=(0.9, 0.01)))
        self.assertEqual(source, "ankle")
        self.assertAlmostEqual(x, 900.0)

    def test_falls_back_to_the_box_when_ankles_are_guesses(self):
        x, y, source = foot_point(detection((800, 400, 1000, 720), ankle_conf=(0.01, 0.02)))
        self.assertEqual(source, "box")
        self.assertAlmostEqual(x, 900.0)
        self.assertAlmostEqual(y, 720.0)

    def test_a_prone_player_is_placed_at_the_ankles_not_the_box_edge(self):
        # A dive leaves a wide, short box whose bottom edge is the torso, metres
        # from where the player actually touches the floor.
        prone = detection((900, 640, 1140, 700), ankle_xy=((915.0, 660.0), (925.0, 664.0)))
        x, y, source = foot_point(prone)
        self.assertEqual(source, "ankles")
        self.assertLess(y, prone["box"][3])
        self.assertLess(x, 0.5 * (prone["box"][0] + prone["box"][2]))

    def test_missing_keypoints_do_not_raise(self):
        x, y, source = foot_point({"box": [10, 20, 30, 40], "conf": 0.5})
        self.assertEqual((x, y, source), (20.0, 40.0, "box"))


class Loading(unittest.TestCase):
    def test_rejects_a_future_schema(self):
        data = json.loads(FITTED.read_text()) if FITTED.exists() else {}
        data["schema_version"] = SCHEMA_VERSION + 1
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(data, fh)
            path = fh.name
        try:
            with self.assertRaises(ValueError):
                Court.load(path)
        finally:
            Path(path).unlink()


if __name__ == "__main__":
    unittest.main(verbosity=2)
