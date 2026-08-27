#!/usr/bin/env python
"""Checks that the durations read as the frame counts they were tuned as.

Run with ``.venv/bin/python scripts/test_timing.py``. Every window in the
pipeline was tuned on a 25 fps clip as a frame count; this pins that at the
reference rate nothing moved when they became seconds, and that at another
rate they scale.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.ball import TRACE_AFTER_S, TRACE_BEFORE_S  # noqa: E402
from src.candidates import MIN_SEPARATION_S, WINDUP_LOOKBACK_S  # noqa: E402
from src.outcome import ELIMINATION_WINDOW_S, HOLD_S, HOLD_SLACK_S, RETURN_WINDOW_S  # noqa: E402
from src.release import (BALL_BEFORE_WINDOW_S, CHAIN_MAX_S, FIRST_STEP_NORM_PER_S,  # noqa: E402
                         SEED_WINDOW_S, WINDUP_WINDOW_S)
from src.timing import REFERENCE_FPS, frames, window  # noqa: E402


class AtTheReferenceRate(unittest.TestCase):
    """The frame counts the pipeline shipped with, at 25 fps."""

    def test_candidate_windows(self):
        self.assertEqual(frames(MIN_SEPARATION_S), 12)
        self.assertEqual(frames(WINDUP_LOOKBACK_S), 8)

    def test_trace_windows(self):
        self.assertEqual((frames(TRACE_BEFORE_S), frames(TRACE_AFTER_S)), (12, 36))

    def test_release_windows(self):
        self.assertEqual(window(BALL_BEFORE_WINDOW_S), (-12, -3))
        self.assertEqual(window(WINDUP_WINDOW_S), (-10, 0))
        self.assertEqual(window(SEED_WINDOW_S), (-8, 3))
        self.assertEqual(frames(CHAIN_MAX_S), 30)
        lo, hi = (v / REFERENCE_FPS for v in FIRST_STEP_NORM_PER_S)
        self.assertAlmostEqual(lo, 0.02)
        self.assertAlmostEqual(hi, 0.20)

    def test_outcome_windows(self):
        self.assertEqual((frames(HOLD_S), frames(HOLD_SLACK_S)), (50, 4))
        self.assertEqual(frames(ELIMINATION_WINDOW_S), 240)
        self.assertEqual(window(RETURN_WINDOW_S), (-120, 240))


class AtAnotherRate(unittest.TestCase):

    def test_windows_halve_with_the_rate(self):
        self.assertEqual(frames(HOLD_S, 12.5), 25)
        self.assertEqual(window(SEED_WINDOW_S, 12.5), (-4, 2))

    def test_a_short_window_never_rounds_to_nothing(self):
        self.assertEqual(frames(0.01, 12.5), 1)
        self.assertEqual(frames(-0.01, 12.5), -1)
        self.assertEqual(frames(0.0, 12.5), 0)


if __name__ == "__main__":
    unittest.main()
