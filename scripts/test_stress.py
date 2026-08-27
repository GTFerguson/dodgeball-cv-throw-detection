#!/usr/bin/env python
"""Checks on deriving a stress condition's inputs from the source clip's.

Run with ``.venv/bin/python scripts/test_stress.py``.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.court import Court  # noqa: E402
from src.evaluate import TOLERANCE_FRAMES  # noqa: E402
from src.stress import (CONDITIONS, Condition, derive_court, derive_labels,  # noqa: E402
                        derive_sets, read_json, remap, tolerance_for)

SOURCE_STEM = "wdbf2014_final_h2_set2"
HALF = CONDITIONS["480p"]
DROP = CONDITIONS["drop2"]
CRF = CONDITIONS["crf40"]


class Frames(unittest.TestCase):

    def test_a_dropped_frame_maps_to_the_kept_frame_before_it(self):
        m = DROP.frame_map()
        self.assertEqual([m(f) for f in (0, 1, 2, 3, 433)], [0, 0, 1, 1, 216])

    def test_an_unchanged_rate_keeps_every_index(self):
        self.assertEqual(HALF.frame_map()(433), 433)
        self.assertEqual(CRF.frame_map()(433), 433)

    def test_the_tolerance_is_a_duration_not_a_frame_count(self):
        self.assertEqual(tolerance_for(TOLERANCE_FRAMES, DROP), TOLERANCE_FRAMES // 2)
        self.assertEqual(tolerance_for(TOLERANCE_FRAMES, HALF), TOLERANCE_FRAMES)

    def test_the_encoder_keeps_the_width_even(self):
        self.assertEqual(HALF.frame_size((1920, 1080)), (854, 480))
        self.assertEqual(DROP.frame_size((1920, 1080)), (1920, 1080))


class Remap(unittest.TestCase):

    def test_frames_and_boxes_are_found_at_any_depth(self):
        data = {"frame": 10, "release_frame": 11, "end_frame": None, "fps": 25,
                "thrower": {"frame": 12, "box": {"x1": 100, "y1": 50, "x2": 200, "y2": 150},
                            "pose_run": {"imgsz": 1920}},
                "live_play": [{"start_frame": 4, "detected_start_frame": 4}],
                "uncertain": False}
        out = remap(data, lambda f: f // 2, (0.5, 0.25))
        self.assertEqual(out["frame"], 5)
        self.assertEqual(out["release_frame"], 5)
        self.assertIsNone(out["end_frame"])
        self.assertEqual(out["fps"], 25)  # not a frame index
        self.assertEqual(out["thrower"]["frame"], 6)
        self.assertEqual(out["thrower"]["box"], {"x1": 50, "y1": 12.5, "x2": 100, "y2": 37.5})
        self.assertEqual(out["thrower"]["pose_run"]["imgsz"], 1920)
        self.assertEqual(out["live_play"][0], {"start_frame": 2, "detected_start_frame": 2})
        self.assertIs(out["uncertain"], False)

    def test_the_source_is_left_alone(self):
        data = {"frame": 10, "box": {"x1": 1, "y1": 1, "x2": 2, "y2": 2}}
        remap(data, lambda f: 0, (0.0, 0.0))
        self.assertEqual(data["frame"], 10)
        self.assertEqual(data["box"]["x2"], 2)


class OnTheClip(unittest.TestCase):
    """Against the committed inputs, where they exist."""

    @classmethod
    def setUpClass(cls):
        cls.court = read_json(REPO_ROOT / "data" / "court" / f"{SOURCE_STEM}.json")
        cls.labels = read_json(REPO_ROOT / "data" / "labels" / f"{SOURCE_STEM}.json")
        cls.sets = read_json(REPO_ROOT / "data" / "sets" / f"{SOURCE_STEM}.json")

    def test_the_scaled_court_maps_the_scaled_pixel_to_the_same_metre(self):
        derived = derive_court(self.court, HALF, HALF.stem_for(SOURCE_STEM), "x" * 64)
        src = Court(video="", clip_sha256="", frame_size=(1920, 1080), fps=25.0,
                    image_to_court=np.array(self.court["image_to_court"]),
                    court_to_image=np.array(self.court["court_to_image"]),
                    horizon_y=self.court["horizon_y"],
                    corners_image=np.array(self.court["corners_image"]),
                    cross_lines=self.court["cross_lines"], held_out_error_m={})
        out = Court(video="", clip_sha256="", frame_size=tuple(derived["frame_size"]),
                    fps=derived["fps"], image_to_court=np.array(derived["image_to_court"]),
                    court_to_image=np.array(derived["court_to_image"]),
                    horizon_y=derived["horizon_y"], corners_image=np.array(derived["corners_image"]),
                    cross_lines=derived["cross_lines"], held_out_error_m={})
        sx, sy = HALF.axis_scale((1920, 1080))
        for x, y in ((960, 540), (100, 1000), (1500, 300)):
            np.testing.assert_allclose(out.to_court(x * sx, y * sy), src.to_court(x, y), atol=1e-6)
            cx, cy = src.to_court(x, y)
            ox, oy = out.to_image(cx, cy)
            np.testing.assert_allclose((ox, oy), (x * sx, y * sy), atol=1e-6)
        self.assertEqual(derived["frame_size"], [854, 480])
        self.assertAlmostEqual(derived["cross_lines"][-1]["image_y"],
                               self.court["cross_lines"][-1]["image_y"] * sy, places=1)

    def test_an_unscaled_condition_leaves_the_geometry_untouched(self):
        derived = derive_court(self.court, DROP, DROP.stem_for(SOURCE_STEM), "x" * 64)
        np.testing.assert_allclose(derived["image_to_court"], self.court["image_to_court"])
        self.assertEqual(derived["fps"], 12.5)
        self.assertEqual(derived["frame_size"], [1920, 1080])

    def test_labels_keep_every_closed_event(self):
        derived = derive_labels(self.labels, DROP, DROP.stem_for(SOURCE_STEM))
        self.assertEqual(len(derived["events"]), len(self.labels["events"]))
        for a, b in zip(self.labels["events"], derived["events"]):
            self.assertEqual(b["release_frame"], a["release_frame"] // 2)
            self.assertEqual(b["thrower"]["box"], a["thrower"]["box"])
        self.assertEqual(derived["fps"], 12.5)
        self.assertEqual(derived["live_play"][0]["start_frame"],
                         self.labels["live_play"][0]["start_frame"] // 2)

    def test_labels_scale_boxes_under_downscale(self):
        derived = derive_labels(self.labels, HALF, HALF.stem_for(SOURCE_STEM))
        sx, sy = HALF.axis_scale((1920, 1080))
        a, b = self.labels["events"][0]["thrower"]["box"], derived["events"][0]["thrower"]["box"]
        self.assertAlmostEqual(b["x1"], a["x1"] * sx, places=1)
        self.assertAlmostEqual(b["y2"], a["y2"] * sy, places=1)
        self.assertEqual((derived["width"], derived["height"]), (854, 480))

    def test_sets_carry_starts_and_drop_ends(self):
        derived = derive_sets(self.sets, DROP, DROP.stem_for(SOURCE_STEM), "y" * 64,
                              "run", 2625)
        confirmed = [s for s in derived["sets"] if s["status"] == "confirmed"][0]
        source = [s for s in self.sets["sets"] if s["status"] == "confirmed"][0]
        self.assertEqual(confirmed["start_frame"], source["start_frame"] // 2)
        self.assertNotIn("end", confirmed)
        self.assertEqual(confirmed["armed"]["start_frame"], source["armed"]["start_frame"] // 2)
        self.assertAlmostEqual(confirmed["start_s"], source["start_s"], delta=0.05)
        self.assertEqual(derived["frame_count"], 2625)
        self.assertEqual(derived["clip_sha256"], "y" * 64)


if __name__ == "__main__":
    unittest.main()
