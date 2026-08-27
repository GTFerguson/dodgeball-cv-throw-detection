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

from src.ball import (BALL_FAINT_SAT_MIN, BALL_HSV_HI, BALL_HSV_LO, BLOB_DIAMETER_NORM,  # noqa: E402
                      DISC_RADIUS_NORM, ball_mask, ball_masks, blobs_in, disc_count,
                      wrist_frame, wrist_height)


def canvas(h: int = 300, w: int = 400) -> np.ndarray:
    return np.full((h, w, 3), (90, 90, 90), np.uint8)


def paint(img: np.ndarray, centre, radius, hsv) -> None:
    bgr = cv2.cvtColor(np.uint8([[hsv]]), cv2.COLOR_HSV2BGR)[0][0]
    cv2.circle(img, centre, radius, tuple(int(v) for v in bgr), -1)


BALL_HSV = (11, 200, 240)
JERSEY_HSV = (5, 200, 180)
# The ball as a motion-blurred streak: the same hue at the saturation the
# evaluation clip's final throw measured on the frames after release.
STREAK_HSV = (11, 75, 160)


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


    def test_a_blurred_ball_is_faint_not_strict(self):
        img = canvas()
        paint(img, (200, 150), 10, STREAK_HSV)
        strict, faint = ball_masks(img)
        self.assertEqual(strict.sum(), 0)
        self.assertGreater(faint.sum(), 0)
        self.assertLess(BALL_FAINT_SAT_MIN, STREAK_HSV[1])

    def test_the_faint_mask_still_refuses_the_jersey(self):
        img = canvas()
        paint(img, (200, 150), 40, JERSEY_HSV)
        self.assertEqual(ball_masks(img)[1].sum(), 0)


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

    def test_a_faint_blob_is_kept_apart_from_the_strict_ones(self):
        # A clean ball and a blurred one near the wrist: the blurred one is
        # recorded as faint, and the clean one is not recorded twice for
        # also appearing under the faint mask.
        img = canvas()
        paint(img, (220, 150), 8, BALL_HSV)
        paint(img, (260, 150), 8, STREAK_HSV)
        strict, faint = ball_masks(img)
        wf = wrist_frame(strict, *blobs_in(strict), (200.0, 150.0), True, 500.0,
                         faint_components=blobs_in(faint)[0])
        self.assertEqual([(int(b.x), b.faint) for b in wf.blobs], [(220, False)])
        self.assertEqual([(int(b.x), b.faint) for b in wf.faint], [(260, True)])
        self.assertGreater(wf.disc, 0.0)

    def test_an_unseen_wrist_records_nothing(self):
        m = ball_mask(canvas())
        wf = wrist_frame(m, *blobs_in(m), None, False, scale=500.0)
        self.assertIsNone(wf.wrist)
        self.assertEqual(wf.disc, 0.0)
        self.assertEqual(DISC_RADIUS_NORM * 500.0, 25.0)


class Height(unittest.TestCase):

    def person(self, shoulder_y=100.0, hip_y=160.0):
        kpts = [[0.0, 0.0, 0.0] for _ in range(17)]
        kpts[5] = [90.0, shoulder_y, 0.9]
        kpts[6] = [110.0, shoulder_y, 0.9]
        kpts[11] = [92.0, hip_y, 0.9]
        kpts[12] = [108.0, hip_y, 0.9]
        return {"box": [80.0, 80.0, 120.0, 250.0], "conf": 0.9, "kpts": kpts}

    def test_a_wrist_a_torso_above_the_shoulder_is_at_height_one(self):
        self.assertAlmostEqual(wrist_height(self.person(), (100.0, 40.0)), 1.0)

    def test_a_wrist_at_the_hip_is_at_minus_one(self):
        self.assertAlmostEqual(wrist_height(self.person(), (100.0, 160.0)), -1.0)

    def test_up_is_along_the_body_not_the_image(self):
        # Lying head towards the camera: shoulders below the hips in the image.
        prone = self.person(shoulder_y=200.0, hip_y=150.0)
        self.assertAlmostEqual(wrist_height(prone, (100.0, 250.0)), 1.0)

    def test_no_body_no_height(self):
        self.assertIsNone(wrist_height(None, (1.0, 1.0)))
        self.assertIsNone(wrist_height(self.person(), None))


if __name__ == "__main__":
    unittest.main(verbosity=2)
