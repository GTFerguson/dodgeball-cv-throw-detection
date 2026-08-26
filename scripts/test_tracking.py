#!/usr/bin/env python
"""Checks on following players between frames.

Run with ``.venv/bin/python scripts/test_tracking.py``.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.tracking import Track, cut_frame  # noqa: E402


def track_over(frames: list[int], id: int = 1) -> Track:
    return Track(id=id, frames=list(frames), points=[(0.0, 0.0)] * len(frames),
                 detections=[{"box": [0, 0, 1, 1]} for _ in frames])


class Splitting(unittest.TestCase):
    # Track 54 on the evaluation clip was one player for 2750 frames and another
    # for 800, and was read as the first. Once the readings say where the change
    # is, the track is cut there so each half carries its own identity.

    def test_a_track_is_cut_at_the_widest_gap_inside_the_window(self):
        t = track_over(list(range(0, 50)) + list(range(69, 120)))
        self.assertEqual(cut_frame(t, after=20, before=100), 69)

    def test_a_track_with_no_gap_is_cut_where_the_new_player_was_first_read(self):
        t = track_over(range(0, 120))
        self.assertEqual(cut_frame(t, after=20, before=100), 100)

    def test_a_gap_outside_the_window_does_not_count(self):
        t = track_over(list(range(0, 10)) + list(range(15, 120)))
        self.assertEqual(cut_frame(t, after=20, before=100), 100)

    def test_the_halves_share_nothing_and_cover_everything(self):
        t = track_over(range(100, 200), id=7)
        head, tail = t.split(150, new_id=99)
        self.assertEqual((head.id, tail.id), (7, 99))
        self.assertEqual(head.frames[-1], 149)
        self.assertEqual(tail.frames[0], 150)
        self.assertEqual(len(head.frames) + len(tail.frames), 100)
        self.assertEqual(len(tail.detections), len(tail.frames))


if __name__ == "__main__":
    unittest.main(verbosity=2)
