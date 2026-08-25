#!/usr/bin/env python
"""Checks on jersey-number confirmation.

The reader is not the fragile part - the vote is. Every wrong number on the
evaluation clip came from a track whose readings disagreed and whose majority was
taken anyway, so these pin the rules that decide when a track is left unnamed.

Run with ``.venv/bin/python scripts/test_jersey.py``.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from jersey import (MIN_CROP_HEIGHT, Reading, confirm,  # noqa: E402
                    conflicts, largest_crops, torso_crop)


def readings(*pairs: tuple[int, int]) -> list[Reading]:
    """`(number, times)` pairs as a flat list of readings."""
    out = []
    for number, times in pairs:
        out.extend(Reading(number=number, confidence=0.8) for _ in range(times))
    return out


class Confirmation(unittest.TestCase):
    def test_agreeing_readings_confirm(self):
        self.assertEqual(confirm(readings((6, 6))), 6)

    def test_a_single_reading_is_not_evidence(self):
        # One crop of a folded jersey can say anything; the claim needs a second
        # independent view to be worth anything.
        self.assertIsNone(confirm(readings((23, 1))))

    def test_nothing_read_confirms_nothing(self):
        self.assertIsNone(confirm([]))

    def test_a_lost_digit_does_not_outvote_the_whole_number(self):
        # CERVUDO 18 on the evaluation clip: read as `1` five times and `18`
        # three. An unweighted majority named the track 1.
        self.assertNotEqual(confirm(readings((1, 5), (18, 3), (6, 1))), 1)

    def test_a_repeated_digit_is_not_invented(self):
        # The mirror case, and the reason the weighting cannot simply prefer the
        # longer reading: CHALMERS 7 reads as `77` twice and `7` seven times.
        self.assertEqual(confirm(readings((7, 7), (77, 2))), 7)

    def test_a_split_vote_is_left_unnamed(self):
        # DICARLO 10, read as 6, 1 and 10. No reading has the clear majority the
        # threshold asks for, so the track keeps no number rather than a wrong one.
        self.assertIsNone(confirm(readings((6, 4), (1, 2), (10, 1))))

    def test_two_digit_numbers_survive_a_stray_misread(self):
        self.assertEqual(confirm(readings((55, 2), (75, 1))), 55)


class Vetoes(unittest.TestCase):
    def test_different_numbers_cannot_be_one_player(self):
        self.assertTrue(conflicts(7, 23))

    def test_the_same_number_does_not_conflict(self):
        self.assertFalse(conflicts(7, 7))

    def test_an_unread_track_vetoes_nothing(self):
        # Most tracks carry no number at all. If absence vetoed, the veto would
        # forbid every join rather than the wrong ones.
        self.assertFalse(conflicts(None, 7))
        self.assertFalse(conflicts(7, None))
        self.assertFalse(conflicts(None, None))


class Crops(unittest.TestCase):
    def test_a_short_detection_yields_no_crop(self):
        # Reading a player who is 30 px tall returns noise that then has to be
        # outvoted, so the size test comes before the reader rather than after.
        image = np.zeros((400, 400, 3), np.uint8)
        short = {"box": [10, 10, 40, 10 + MIN_CROP_HEIGHT - 1]}
        self.assertIsNone(torso_crop(image, short))

    def test_a_tall_detection_yields_its_upper_body(self):
        image = np.zeros((400, 400, 3), np.uint8)
        tall = {"box": [10, 10, 60, 210]}
        crop = torso_crop(image, tall)
        self.assertIsNotNone(crop)
        self.assertLess(crop.shape[0], 200)

    def test_a_detection_off_the_frame_edge_is_clamped(self):
        image = np.zeros((400, 400, 3), np.uint8)
        crop = torso_crop(image, {"box": [-20, -30, 60, 210]})
        self.assertIsNotNone(crop)

    def test_the_largest_crops_are_the_ones_read(self):
        # The whole approach rests on reading a player where they are closest to
        # the camera, so the shortlist has to be by height and nothing else.
        crops = [np.zeros((h, 20, 3), np.uint8) for h in (90, 300, 150, 200)]
        picked = largest_crops(crops, limit=2)
        self.assertEqual([c.shape[0] for c in picked], [300, 200])


if __name__ == "__main__":
    unittest.main(verbosity=2)
