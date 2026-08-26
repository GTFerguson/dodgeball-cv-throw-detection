#!/usr/bin/env python
"""Checks on seeing the ball around a wrist.

Run with ``.venv/bin/python scripts/test_ball.py``.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from src.ball import (BALL_HSV_HI, BALL_HSV_LO, BLOB_DIAMETER_NORM, DISC_RADIUS_NORM,  # noqa: E402
                      ball_mask, blobs_in, disc_count, wrist_frame)


def canvas(h: int = 300, w: int = 400) -> np.ndarray:
    return np.full((h, w, 3), (90, 90, 90), np.uint8)


def paint(img: np.ndarray, centre, radius, hsv) -> None:
    bgr = cv2.cvtColor(np.uint8([[hsv]]), cv2.COLOR_HSV2BGR)[0][0]
    cv2.circle(img, centre, radius, tuple(int(v) for v in bgr), -1)


BALL_HSV = (11, 200, 240)
JERSEY_HSV = (5, 200, 180)


class Mask(unittest.TestCase):

    def test_a_ball_is_orange(self):
        img = canvas()
        paint(img, (200, 150), 10, BALL_HSV)
        self.assertGreater(ball_mask(img).sum(), 0)

    def test_the_red_jersey_is_not(self):
        # The set-start mask admitted the near team's red; this one must not.
        img = canvas()
        paint(img, (200, 150), 40, JERSEY_HSV)
        self.assertEqual(ball_mask(img).sum(), 0)
        self.assertGreater(BALL_HSV_LO[0], JERSEY_HSV[0])
        self.assertLessEqual(BALL_HSV[0], BALL_HSV_HI[0])


class Disc(unittest.TestCase):

    def test_the_disc_counts_only_inside_the_radius(self):
        img = canvas()
        paint(img, (200, 150), 10, BALL_HSV)
        m = ball_mask(img)
        self.assertGreater(disc_count(m, 200, 150, 15), 250)
        self.assertEqual(disc_count(m, 300, 150, 15), 0)

    def test_the_disc_survives_the_image_edge(self):
        img = canvas()
        paint(img, (5, 5), 4, BALL_HSV)
        self.assertGreater(disc_count(ball_mask(img), 2, 2, 10), 0)


class Blobs(unittest.TestCase):

    def test_a_blob_near_the_wrist_is_recorded_with_its_distance(self):
        img = canvas()
        paint(img, (220, 150), 8, BALL_HSV)
        m = ball_mask(img)
        wf = wrist_frame(m, *blobs_in(m), (200.0, 150.0), True, scale=500.0)
        self.assertEqual(len(wf.blobs), 1)
        self.assertAlmostEqual(wf.blobs[0].distance_norm(200.0, 150.0, 500.0), 0.04, places=2)
        self.assertGreater(wf.disc, 0.0)

    def test_a_speck_and_a_wall_are_not_balls(self):
        img = canvas()
        paint(img, (220, 150), 1, BALL_HSV)
        cv2.rectangle(img, (0, 250), (399, 299),
                      tuple(int(v) for v in cv2.cvtColor(np.uint8([[BALL_HSV]]), cv2.COLOR_HSV2BGR)[0][0]), -1)
        m = ball_mask(img)
        wf = wrist_frame(m, *blobs_in(m), (200.0, 150.0), True, scale=500.0)
        self.assertEqual([b.diameter_norm for b in wf.blobs
                          if not BLOB_DIAMETER_NORM[0] <= b.diameter_norm <= BLOB_DIAMETER_NORM[1]], [])
        self.assertEqual(len(wf.blobs), 0)

    def test_the_disc_counts_only_ball_sized_orange(self):
        # A speck of skin colour at the wrist is not a ball in hand; a ball is.
        img = canvas()
        paint(img, (200, 150), 1, BALL_HSV)
        m = ball_mask(img)
        self.assertEqual(wrist_frame(m, *blobs_in(m), (200.0, 150.0), True, 500.0).disc, 0.0)
        paint(img, (200, 150), 8, BALL_HSV)
        m = ball_mask(img)
        self.assertGreater(wrist_frame(m, *blobs_in(m), (200.0, 150.0), True, 500.0).disc, 0.0)

    def test_an_unseen_wrist_records_nothing(self):
        m = ball_mask(canvas())
        wf = wrist_frame(m, *blobs_in(m), None, False, scale=500.0)
        self.assertIsNone(wf.wrist)
        self.assertEqual(wf.disc, 0.0)
        self.assertEqual(DISC_RADIUS_NORM * 500.0, 25.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
