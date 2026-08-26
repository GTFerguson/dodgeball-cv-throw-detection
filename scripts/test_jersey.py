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

from jersey import (MIN_AGREEMENT_SPAN, MIN_CROP_HEIGHT, READ_BIN_FRAMES,  # noqa: E402
                    Crop, Reading, confirm, conflicts, in_time_order,
                    largest_crops, needs_review, shortlist, switch, torso_crop,
                    unobstructed)


def readings(*pairs: tuple[int, int], spread: int = MIN_AGREEMENT_SPAN) -> list[Reading]:
    """`(number, times)` pairs as a flat list of readings, spread out in time."""
    out = []
    for number, times in pairs:
        out.extend(Reading(number=number, confidence=0.8, frame=i * spread)
                   for i in range(times))
    return out


def crop(frame: int, height: int) -> Crop:
    return Crop(frame=frame, image=np.zeros((height, 20, 3), np.uint8))


class Confirmation(unittest.TestCase):
    def test_agreeing_readings_confirm(self):
        self.assertEqual(confirm(readings((6, 6))), 6)

    def test_a_single_reading_is_not_evidence(self):
        # One crop of a folded jersey can say anything; the claim needs further
        # independent views to be worth anything.
        self.assertIsNone(confirm(readings((23, 1))))

    def test_a_pair_agreeing_among_many_readings_is_chance(self):
        # USA 55 on white, read across its whole track: `5, 65, 35, 5, 65`. Two
        # 65s four seconds apart named it 65.
        self.assertIsNone(confirm(readings((65, 2), (35, 1), (5, 2))))

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
        self.assertEqual(confirm(readings((55, 3), (75, 1))), 55)

    def test_agreement_within_a_moment_is_one_view(self):
        # A referee's stripes read as `6` four times in twenty frames on the full
        # clip. Four crops of the same pose from the same distance are one view,
        # and the claim needs views that are independent, which means apart in
        # time.
        self.assertIsNone(confirm(readings((6, 4), spread=5)))
        self.assertEqual(confirm(readings((6, 4), spread=MIN_AGREEMENT_SPAN)), 6)

    def test_a_lost_digit_does_not_dissent(self):
        # Track 54's first half, read across its whole life: five 18s, four 1s,
        # and a 78, a 70, a 6 and a 3 from the far court. The 1s fit an 18 and
        # must not be counted as votes against it, or reading the far court
        # costs the name the near court gave.
        self.assertEqual(confirm(readings((18, 5), (1, 4), (78, 1), (70, 1), (6, 1), (3, 1))), 18)

    def test_a_fragment_of_a_longer_reading_is_ambiguous(self):
        # KUTNER 40 read as `4` five times and `40` once. The `4` is what the
        # reader returns when it loses the 0, so the evidence fits a 40 as well as
        # it fits a 4, and the track is left unnamed rather than named the fragment.
        self.assertIsNone(confirm(readings((4, 5), (40, 1))))

    def test_a_doubled_digit_does_not_make_the_digit_ambiguous(self):
        # `77` from a 7 is the reader repeating, not the reader dropping; a 7 that
        # is sometimes read as 77 is still a 7.
        self.assertEqual(confirm(readings((7, 5), (77, 1))), 7)

    def test_a_doubled_digit_does_not_dissent_either(self):
        # CHALMERS after the swap, track 285: eight 7s, three 77s and a 1. The
        # 77s counted as votes against left him unnamed for half a set.
        self.assertEqual(confirm(readings((7, 8), (77, 3), (1, 1))), 7)


class Switches(unittest.TestCase):
    # Two numbers each confirmed in disjoint stretches of one track is the
    # tracker having changed player mid-life. Interleaved numbers are the reader
    # being wrong about one player.

    def stretch(self, number, start, count, step=MIN_AGREEMENT_SPAN):
        return [Reading(number=number, confidence=0.8, frame=start + i * step)
                for i in range(count)]

    def test_a_clean_switch_is_found_between_the_stretches(self):
        rs = self.stretch(18, 0, 5) + self.stretch(7, 3000, 5)
        self.assertEqual(switch(rs), (18, 7, 400, 3000))

    def test_a_switch_needs_fewer_reads_than_a_name(self):
        # CHALMERS after frame 2881 on track 54 was read `7, 5, 7` - too few to
        # name, enough to say the 18 has stopped.
        rs = self.stretch(18, 0, 5) + [Reading(number=n, confidence=0.8, frame=f)
                                       for f, n in ((2891, 7), (3397, 5), (3517, 7))]
        self.assertEqual(switch(rs)[:2], (18, 7))

    def test_interleaved_numbers_are_not_a_switch(self):
        rs = self.stretch(6, 0, 4) + self.stretch(10, 50, 4)
        self.assertIsNone(switch(rs))

    def test_a_number_that_recurs_after_the_change_is_not_a_switch(self):
        # DICARLO 10 on the evaluation clip: `6, 6, 1, 10, 1, 6, 6, 1, 1, 10, 1`.
        # The prefix confirms 6 and the suffix confirms 10, and it is one man
        # whose 0 reads as a 6 - which the 6s after the first 10 give away.
        rs = [Reading(number=n, confidence=0.8, frame=f) for f, n in
              ((307, 6), (458, 6), (598, 1), (683, 10), (813, 1), (1573, 6),
               (1718, 6), (1753, 1), (2018, 1), (2743, 10), (3063, 1))]
        self.assertIsNone(switch(rs))

    def test_one_number_is_not_a_switch(self):
        self.assertIsNone(switch(self.stretch(18, 0, 8)))

    def test_a_stray_fragment_does_not_split_a_track(self):
        # A `1` read late on an 18 is the reader dropping a digit, not a new
        # player; the second stretch has to confirm on its own terms.
        rs = self.stretch(18, 0, 5) + [Reading(number=1, confidence=0.8, frame=3000)]
        self.assertIsNone(switch(rs))

    def test_a_second_stretch_too_brief_to_confirm_is_not_a_switch(self):
        rs = self.stretch(18, 0, 5) + self.stretch(7, 3000, 3, step=5)
        self.assertIsNone(switch(rs))

    def test_the_boundary_is_placed_between_the_last_and_first_agreeing_reads(self):
        # Noise between the stretches must not move the boundary.
        rs = (self.stretch(18, 0, 5)
              + [Reading(number=44, confidence=0.5, frame=1500)]
              + self.stretch(7, 3000, 5))
        a, b, last_a, first_b = switch(rs)
        self.assertEqual((a, b), (18, 7))
        self.assertLessEqual(last_a, 1500)
        self.assertGreaterEqual(first_b, 1500)


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
        crops = [crop(f, h) for f, h in ((0, 90), (5, 300), (10, 150), (15, 200))]
        picked = largest_crops(crops, limit=2)
        self.assertEqual([c.height for c in picked], [300, 200])

    def test_the_shortlist_covers_the_whole_track(self):
        # Track 54 on the evaluation clip was CERVUDO 18 until frame 2880 and
        # CHALMERS 7 after, and was named 18 on ten agreeing crops - all from the
        # first half, because the shortlist was the tallest ten and 18 stood
        # nearest the camera. Agreement among the tallest crops is not agreement
        # across the track's life; the shortlist has to sample every stretch.
        early = [crop(f, 300) for f in range(0, 1000, 50)]
        late = [crop(f, 100) for f in range(3000, 4000, 50)]
        picked = shortlist(early + late, limit=4)
        self.assertTrue(any(c.frame >= 3000 for c in picked))
        self.assertTrue(any(c.frame < 1000 for c in picked))

    def test_the_shortlist_still_reads_where_it_is_easy(self):
        # Spreading over time must not cost the tallest crops, which are the
        # ones that actually read.
        crops = [crop(f, 100) for f in range(0, 2000, 50)] + [crop(2010, 300)]
        picked = shortlist(crops, limit=2)
        self.assertIn(2010, [c.frame for c in picked])

    def test_one_crop_per_bin_and_no_duplicates(self):
        crops = [crop(f, 100 + f % 7) for f in range(0, 3 * READ_BIN_FRAMES, 10)]
        picked = shortlist(crops, limit=0)
        self.assertEqual(len(picked), 3)
        self.assertEqual(len({c.frame for c in picked}), 3)

    def test_a_crop_keeps_the_frame_it_came_from(self):
        # Without the frame, a track whose readings split cannot be told apart
        # from two players stitched together: noise interleaves, a merge switches.
        picked = largest_crops([crop(40, 100), crop(10, 200)], limit=2)
        self.assertEqual([c.frame for c in picked], [10, 40])
        self.assertEqual([c.frame for c in in_time_order(picked)], [10, 40])


class Obstruction(unittest.TestCase):
    def test_a_box_clear_of_others_is_read(self):
        me = {"box": [100, 100, 200, 400]}
        far = {"box": [400, 100, 500, 400]}
        self.assertTrue(unobstructed(me, [me, far]))

    def test_a_box_overlapping_a_neighbour_is_not(self):
        # KUTNER's crop at frame 2851 had CHALMERS' back in it and read 7.
        me = {"box": [1423, 674, 1545, 995]}
        neighbour = {"box": [1504, 618, 1586, 871]}
        self.assertFalse(unobstructed(me, [me, neighbour]))

    def test_a_grazing_touch_does_not_disqualify(self):
        me = {"box": [100, 100, 200, 400]}
        touch = {"box": [195, 100, 295, 400]}
        self.assertTrue(unobstructed(me, [me, touch]))


class Review(unittest.TestCase):
    # The contact sheet used to show only the confirmed tracks, which is the
    # inverse of what checking needs: those are the ones already trusted, and the
    # long tracks the vote declined to name are where the question lives.

    def test_a_long_unnamed_track_needs_a_look(self):
        self.assertTrue(needs_review(None, in_play_frames=1500, span=2000))

    def test_a_named_track_is_already_on_the_sheet(self):
        self.assertFalse(needs_review(18, in_play_frames=1500, span=2000))

    def test_a_short_unnamed_track_is_not_worth_the_space(self):
        # There are dozens of these and most are a player glimpsed for a second.
        self.assertFalse(needs_review(None, in_play_frames=100, span=2000))

    def test_an_official_is_not_a_question(self):
        # A referee is tracked for the whole set from the sideline. Long, unnamed,
        # and never in play - which is the answer, not a question.
        self.assertFalse(needs_review(None, in_play_frames=0, span=2000))


if __name__ == "__main__":
    unittest.main(verbosity=2)
