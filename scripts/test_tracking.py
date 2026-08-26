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

from src.tracking import AIRBORNE_HOLD_FRAMES, Carried, Track, admit, cut_frame  # noqa: E402


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


def det(box, playing: bool) -> dict:
    return {"box": list(box), "playing": playing}


def is_playing(d: dict) -> bool:
    return d["playing"]


class AdmittingToTheTracker(unittest.TestCase):
    # Track 73 on the evaluation clip, number 55 at the far baseline, threw with a
    # jump at frame 4001: the ankles rose seventy pixels, which at that end of the
    # court projects three metres past the baseline. Every airborne frame was
    # dropped before the tracker saw it, so the throw belonged to no track.

    def test_a_detection_in_play_is_admitted_and_starts_a_chain(self):
        admitted, carried = admit([det((0, 0, 100, 200), True)], is_playing, [], frame=10)
        self.assertEqual(len(admitted), 1)
        self.assertEqual(carried, [Carried((0, 0, 100, 200), 10)])

    def test_a_detection_out_of_play_with_nothing_to_continue_is_dropped(self):
        admitted, carried = admit([det((0, 0, 100, 200), False)], is_playing, [], frame=10)
        self.assertEqual(admitted, [])
        self.assertEqual(carried, [])

    def test_a_jump_continues_the_box_it_took_off_from(self):
        _, carried = admit([det((0, 100, 100, 300), True)], is_playing, [], frame=10)
        airborne = det((2, 85, 102, 285), False)
        admitted, carried = admit([airborne], is_playing, carried, frame=11)
        self.assertEqual(admitted, [airborne])
        # The chain's age is inherited, not reset: still grounded at 10.
        self.assertEqual(carried, [Carried((2, 85, 102, 285), 10)])

    def test_a_chain_carries_through_every_airborne_frame(self):
        _, carried = admit([det((0, 100, 100, 300), True)], is_playing, [], frame=0)
        for f in range(1, 12):
            d = det((0, 100 - 6 * f, 100, 300 - 6 * f), False)
            admitted, carried = admit([d], is_playing, carried, frame=f)
            self.assertEqual(admitted, [d], f"airborne frame {f} dropped")

    def test_a_bystander_who_overlapped_a_player_is_let_go_after_the_hold(self):
        _, carried = admit([det((0, 100, 100, 300), True)], is_playing, [], frame=0)
        standing = det((5, 100, 105, 300), False)
        last = None
        for f in range(1, AIRBORNE_HOLD_FRAMES + 3):
            admitted, carried = admit([standing], is_playing, carried, frame=f)
            if not admitted:
                last = f
                break
        self.assertEqual(last, AIRBORNE_HOLD_FRAMES + 1)

    def test_someone_else_beside_the_chain_is_not_admitted(self):
        _, carried = admit([det((0, 100, 100, 300), True)], is_playing, [], frame=0)
        beside = det((80, 100, 180, 300), False)
        admitted, _ = admit([beside], is_playing, carried, frame=1)
        self.assertEqual(admitted, [])

    def test_a_frame_the_detector_missed_does_not_break_a_chain(self):
        _, carried = admit([det((0, 100, 100, 300), True)], is_playing, [], frame=0)
        _, carried = admit([], is_playing, carried, frame=1)
        airborne = det((0, 90, 100, 290), False)
        admitted, _ = admit([airborne], is_playing, carried, frame=2)
        self.assertEqual(admitted, [airborne])

    def test_a_carried_box_that_was_continued_is_replaced_not_kept(self):
        _, carried = admit([det((0, 100, 100, 300), True)], is_playing, [], frame=0)
        _, carried = admit([det((0, 95, 100, 295), False)], is_playing, carried, frame=1)
        self.assertEqual(len(carried), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
