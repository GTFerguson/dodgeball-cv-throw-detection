#!/usr/bin/env python
"""Checks on the court fit.

The fit is validated in production by held-out floor markings, which only works
when the floor really is a regulation court. These tests pin the two things that
claim cannot cover: that the geometry is recovered exactly on a court whose truth
is known by construction, and that a floor which is *not* a regulation court is
rejected rather than silently calibrated wrong.

Run with ``.venv/bin/python scripts/test_fit_court.py``.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fit_court import (  # noqa: E402
    COURT_LENGTH_M,
    COURT_WIDTH_M,
    HELD_OUT_MARKINGS_M,
    _fit_robust,
    _runs,
    fit_plate,
)

FLOOR_BGR = (110, 116, 116)
TAPE_BGR = (140, 238, 186)
MARKING_BGR = (235, 240, 238)

# Chosen to resemble the real camera - an elevated end-on view with the near
# edge close to full frame width - so the test exercises real perspective rather
# than a near-orthographic case where every fit looks good.
CORNERS_IMAGE = np.float32([[80, 1050], [1790, 1050], [1360, 262], [624, 262]])


def synthetic_plate(marking_positions_m) -> np.ndarray:
    """A blank court rendered through a known homography."""
    corners_court = np.float32([[0, 0], [COURT_WIDTH_M, 0],
                                [COURT_WIDTH_M, COURT_LENGTH_M], [0, COURT_LENGTH_M]])
    court_to_image = cv2.getPerspectiveTransform(corners_court, CORNERS_IMAGE)

    def px(cx, cy):
        v = court_to_image @ np.array([cx, cy, 1.0])
        return (int(round(v[0] / v[2])), int(round(v[1] / v[2])))

    img = np.zeros((1080, 1920, 3), np.uint8)
    apron = np.array([px(x, y) for x, y in [
        (-2, -2), (COURT_WIDTH_M + 2, -2),
        (COURT_WIDTH_M + 2, COURT_LENGTH_M + 2), (-2, COURT_LENGTH_M + 2)]], np.int32)
    cv2.fillPoly(img, [apron], FLOOR_BGR)
    for cx in (0, COURT_WIDTH_M):
        cv2.line(img, px(cx, 0), px(cx, COURT_LENGTH_M), TAPE_BGR, 5)
    for cy in [0, COURT_LENGTH_M, *marking_positions_m]:
        cv2.line(img, px(0, cy), px(COURT_WIDTH_M, cy), MARKING_BGR, 4)
    return img


class RunSplitting(unittest.TestCase):
    def test_separates_runs_across_a_gap(self):
        xs = np.array([10, 11, 12, 40, 41, 90])
        self.assertEqual(_runs(xs), [(10, 12), (40, 41), (90, 90)])

    def test_single_run_when_contiguous(self):
        self.assertEqual(_runs(np.array([5, 6, 7, 8])), [(5, 8)])

    def test_empty_input(self):
        self.assertEqual(_runs(np.array([], int)), [])


class RobustLineFit(unittest.TestCase):
    def test_recovers_line_despite_outliers(self):
        ys = np.arange(200, 1000, dtype=float)
        xs = -0.7 * ys + 800
        xs[::40] += 300                      # a minority of grossly wrong rows
        a, b, keep = _fit_robust(np.stack([xs, ys], axis=1))
        self.assertAlmostEqual(a, -0.7, places=3)
        self.assertAlmostEqual(b, 800, places=1)
        self.assertLess(keep.sum(), len(ys))


class SyntheticCourt(unittest.TestCase):
    def test_recovers_known_geometry(self):
        result = fit_plate(synthetic_plate(HELD_OUT_MARKINGS_M))
        for expected, error in result["held_out_error_m"].items():
            self.assertLess(abs(error), 0.10, f"marking at {expected} m off by {error} m")

    def test_corners_land_on_the_rendered_corners(self):
        result = fit_plate(synthetic_plate(HELD_OUT_MARKINGS_M))
        # Row order differs from the rendering order; compare as point sets.
        found = sorted(map(tuple, np.round(result["corners_image"], 0).tolist()))
        truth = sorted(map(tuple, CORNERS_IMAGE.round(0).tolist()))
        for (fx, fy), (tx, ty) in zip(found, truth, strict=True):
            self.assertLess(abs(fx - tx), 4.0)
            self.assertLess(abs(fy - ty), 4.0)

    def test_rejects_a_floor_that_is_not_a_regulation_court(self):
        # Markings at the right spacing for a shorter court. Every line is still
        # found and the homography still fits; only the held-out check catches it.
        wrong = [m * 13.4 / COURT_LENGTH_M for m in HELD_OUT_MARKINGS_M]
        with self.assertRaises(SystemExit):
            fit_plate(synthetic_plate(wrong))


if __name__ == "__main__":
    unittest.main(verbosity=2)
