#!/usr/bin/env python
"""Checks on the venue config.

Run with ``.venv/bin/python scripts/test_venue.py``.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.ball import BALL_HSV_HI, BALL_HSV_LO  # noqa: E402
from src.court import CENTRE_LINE_M, COURT_LENGTH_M, COURT_WIDTH_M, MARGIN_M  # noqa: E402
from src.venue import DEFAULTS, VENUE, load  # noqa: E402


class Loading(unittest.TestCase):

    def test_a_missing_file_is_the_defaults(self):
        self.assertEqual(load(Path("/nonexistent/venue.toml")), DEFAULTS)

    def test_a_partial_file_fills_the_rest_in(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "venue.toml"
            p.write_text('[court]\nlength_m = 20.0\n')
            v = load(p)
        self.assertEqual(v["court"]["length_m"], 20.0)
        self.assertEqual(v["court"]["width_m"], 9.0)
        self.assertEqual(v["ball"], DEFAULTS["ball"])

    def test_an_unknown_key_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "venue.toml"
            p.write_text('[ball]\nhue_lo = 9\n')
            with self.assertRaises(ValueError):
                load(p)
            p.write_text('[balls]\nhsv_lo = [1, 2, 3]\n')
            with self.assertRaises(ValueError):
                load(p)


class Wiring(unittest.TestCase):
    """The modules read the config, and the checked-in file matches the defaults."""

    def test_the_checked_in_file_is_the_shipped_values(self):
        self.assertEqual(VENUE, DEFAULTS)

    def test_ball_and_court_take_their_values_from_it(self):
        self.assertEqual(BALL_HSV_LO, tuple(VENUE["ball"]["hsv_lo"]))
        self.assertEqual(BALL_HSV_HI, tuple(VENUE["ball"]["hsv_hi"]))
        self.assertEqual((COURT_WIDTH_M, COURT_LENGTH_M, MARGIN_M),
                         (VENUE["court"]["width_m"], VENUE["court"]["length_m"],
                          VENUE["court"]["margin_m"]))
        self.assertEqual(CENTRE_LINE_M, COURT_LENGTH_M / 2)


if __name__ == "__main__":
    unittest.main()
