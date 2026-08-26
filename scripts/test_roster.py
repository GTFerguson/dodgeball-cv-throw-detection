#!/usr/bin/env python
"""Checks on the roster: who is a player, who is an official, and which side.

Run with ``.venv/bin/python scripts/test_roster.py``. The clip-level checks run
only when the evaluation clip's roster has been built, because the thresholds
are only meaningful against real footage.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.roster import (KIT_MIN_SAMPLES, PLAYER_MIN_CORE_FRAMES, ROSTER_ROOT,  # noqa: E402
                        Participant, Roster, TrackRecord, assign_role, assign_team,
                        chest_region, crop_vote, in_core, intervals_of, kit_fractions,
                        participant_id, sides_from, vote_kit)

CLIP = "wdbf2014_final_h2_set2"


def patch(bgr: tuple[int, int, int], noise_bgr: tuple[int, int, int] | None = None,
          share: float = 1.0) -> np.ndarray:
    """A chest of one colour, with an optional second colour over part of it."""
    img = np.zeros((40, 30, 3), np.uint8)
    img[:] = bgr
    if noise_bgr is not None:
        img[: int(40 * (1 - share))] = noise_bgr
    return img


def detection(shoulders=((100, 100), (140, 100)), hips=((105, 160), (135, 160)),
              conf=0.9) -> dict:
    kpts = [[0, 0, 0.0]] * 17
    kpts[5], kpts[6] = [*shoulders[0], conf], [*shoulders[1], conf]
    kpts[11], kpts[12] = [*hips[0], conf], [*hips[1], conf]
    return {"box": [90, 60, 150, 220], "conf": 0.9, "kpts": kpts}


class KitColour(unittest.TestCase):
    # A referee's shirt is black, a team kit is one colour, and the print on a
    # jersey is neither - it must abstain, not vote.

    def test_a_black_chest_is_black(self):
        black, red, white = kit_fractions(patch((20, 20, 20)))
        self.assertGreater(black, 0.95)
        self.assertEqual(crop_vote((black, red, white)), "black")

    def test_a_red_chest_is_red_and_a_white_chest_is_white(self):
        self.assertEqual(crop_vote(kit_fractions(patch((30, 30, 200)))), "red")
        self.assertEqual(crop_vote(kit_fractions(patch((230, 230, 230)))), "white")

    def test_a_chest_split_between_two_colours_abstains(self):
        # Half black print on white cloth - what USA #2's jersey looks like.
        self.assertIsNone(crop_vote(kit_fractions(patch((230, 230, 230), (20, 20, 20), 0.5))))

    def test_a_track_needs_enough_agreeing_crops(self):
        red = kit_fractions(patch((30, 30, 200)))
        self.assertEqual(vote_kit([red] * (KIT_MIN_SAMPLES - 1)), ("unknown", 0.0))
        self.assertEqual(vote_kit([red] * KIT_MIN_SAMPLES), ("red", 1.0))

    def test_crops_that_disagree_leave_the_kit_unknown(self):
        red = kit_fractions(patch((30, 30, 200)))
        black = kit_fractions(patch((20, 20, 20)))
        kit, share = vote_kit([red] * 5 + [black] * 5)
        self.assertEqual(kit, "unknown")
        self.assertEqual(share, 0.5)

    def test_the_chest_sits_between_the_shoulders_and_the_hips(self):
        x1, y1, x2, y2 = chest_region(detection())
        self.assertTrue(100 < x1 < x2 < 140)
        self.assertTrue(100 < y1 < y2 < 160)

    def test_a_missing_keypoint_gives_no_chest(self):
        self.assertIsNone(chest_region(detection(conf=0.1)))
        self.assertIsNone(chest_region({"box": [0, 0, 10, 10], "kpts": []}))

    def test_a_chest_too_small_to_read_is_skipped(self):
        self.assertIsNone(chest_region(detection(shoulders=((100, 100), (104, 100)),
                                                 hips=((101, 106), (103, 106)))))


class Role(unittest.TestCase):
    # Time inside the court while the set is certainly live makes a player; kit
    # only speaks for those never seen there.

    def test_in_play_during_the_live_core_is_a_player_whatever_the_kit(self):
        self.assertEqual(assign_role("black", PLAYER_MIN_CORE_FRAMES), "player")
        self.assertEqual(assign_role("unknown", PLAYER_MIN_CORE_FRAMES), "player")

    def test_a_flicker_inside_the_court_does_not_make_a_player(self):
        self.assertEqual(assign_role("black", PLAYER_MIN_CORE_FRAMES - 1), "official")

    def test_black_kit_never_in_live_play_is_an_official(self):
        self.assertEqual(assign_role("black", 0), "official")

    def test_a_team_kit_never_in_live_play_is_still_a_player(self):
        self.assertEqual(assign_role("red", 0), "player")
        self.assertEqual(assign_role("white", 0), "player")

    def test_no_kit_and_no_live_play_is_unknown_not_guessed(self):
        self.assertEqual(assign_role("unknown", 0), "unknown")


class Team(unittest.TestCase):

    def test_the_half_a_player_stands_in_wins_over_their_kit(self):
        self.assertEqual(assign_team({"near": 5, "far": 300}, "red", {"red": "near"}),
                         ("far", "half"))

    def test_kit_names_the_side_when_the_player_was_never_in_play(self):
        self.assertEqual(assign_team({}, "white", {"white": "far"}), ("far", "kit"))

    def test_no_evidence_gives_no_team(self):
        self.assertEqual(assign_team({}, "unknown", {"red": "near"}), (None, None))
        self.assertEqual(assign_team({"near": 0}, "black", {"red": "near"}), (None, None))

    def test_sides_come_from_players_seen_in_play(self):
        seen = [("red", "near")] * 6 + [("white", "far")] * 4 + [("red", "far")]
        self.assertEqual(sides_from(seen), {"red": "near", "white": "far"})

    def test_a_kit_seen_on_both_halves_maps_to_neither(self):
        seen = [("red", "near")] * 4 + [("red", "far")] * 3
        self.assertEqual(sides_from(seen), {})

    def test_the_officials_kit_never_maps_to_a_side(self):
        self.assertEqual(sides_from([("black", "near")] * 10), {})


class Intervals(unittest.TestCase):

    def test_runs_of_in_play_frames_become_inclusive_intervals(self):
        frames = [10, 11, 12, 13, 15, 16, 20]
        flags = [True, True, False, True, True, True, True]
        self.assertEqual(intervals_of(frames, flags), [(10, 11), (13, 13), (15, 16), (20, 20)])


def small_roster() -> Roster:
    tracks = {
        1: TrackRecord(id=1, participant_id="near-7", role="player", team="near",
                       team_source="half", kit="red", kit_share=1.0, number=7,
                       start_frame=0, end_frame=4, detections=((0, 0), (1, 0), (2, 1), (3, 0), (4, 0)),
                       in_play=((0, 2),), core_in_play_frames=3),
        2: TrackRecord(id=2, participant_id="near-7", role="player", team="near",
                       team_source="half", kit="red", kit_share=1.0, number=7,
                       start_frame=6, end_frame=8, detections=((6, 0), (7, 0), (8, 0)),
                       in_play=((6, 8),), core_in_play_frames=3,
                       readings=((6, 7, 0.9), (8, 7, 0.8))),
        3: TrackRecord(id=3, participant_id="official-t3", role="official", team=None,
                       team_source=None, kit="black", kit_share=0.9, number=None,
                       start_frame=0, end_frame=8, detections=tuple((f, 2) for f in range(9)),
                       in_play=((4, 4),), core_in_play_frames=0),
        4: TrackRecord(id=4, participant_id="player-t4", role="player", team="far",
                       team_source="kit", kit="white", kit_share=0.8, number=None,
                       start_frame=2, end_frame=3, detections=((2, 3), (3, 3)),
                       in_play=(), core_in_play_frames=0),
    }
    participants = {
        "near-7": Participant(id="near-7", role="player", team="near", number=7,
                              track_ids=(1, 2), start_frame=0, end_frame=8),
        "official-t3": Participant(id="official-t3", role="official", team=None, number=None,
                                   track_ids=(3,), start_frame=0, end_frame=8),
        "player-t4": Participant(id="player-t4", role="player", team="far", number=None,
                                 track_ids=(4,), start_frame=2, end_frame=3),
    }
    return Roster(video="clip.mp4", clip_sha256="abc", pose_run="run", fps=25.0, frame_count=10,
                  sides={"red": "near", "white": "far"}, live_core=(0, 5),
                  tracks=tracks, participants=participants)


class Ids(unittest.TestCase):

    def test_a_numbered_player_on_a_side_is_named_by_both(self):
        self.assertEqual(participant_id("player", "near", 7, 56), "near-7")

    def test_anyone_else_is_named_by_role_and_track(self):
        self.assertEqual(participant_id("player", "near", None, 82), "player-t82")
        self.assertEqual(participant_id("player", None, 7, 56), "player-t56")
        self.assertEqual(participant_id("official", None, None, 8), "official-t8")

    def test_the_core_is_inclusive(self):
        self.assertTrue(in_core(433, [(433, 4183)]))
        self.assertFalse(in_core(4184, [(433, 4183)]))


class Queries(unittest.TestCase):

    def test_everyone_on_a_frame_with_their_detection_and_in_play_state(self):
        r = small_roster()
        present = {p.track.id: (p.detection_index, p.in_play) for p in r.at(2)}
        self.assertEqual(present, {1: (1, True), 3: (2, False), 4: (3, False)})

    def test_a_frame_nobody_was_tracked_on_is_empty(self):
        self.assertEqual(small_roster().at(9), [])

    def test_occupancy_counts_only_players_in_play(self):
        r = small_roster()
        # Frame 4: the official is inside the court, the player is not in play.
        self.assertEqual({k: len(v) for k, v in r.on_court(4).items()}, {"near": 0, "far": 0})
        self.assertEqual({k: len(v) for k, v in r.on_court(1).items()}, {"near": 1, "far": 0})

    def test_players_by_side_and_officials(self):
        r = small_roster()
        self.assertEqual([p.id for p in r.players("near")], ["near-7"])
        self.assertEqual([p.id for p in r.players("far")], ["player-t4"])
        self.assertEqual([p.id for p in r.officials()], ["official-t3"])
        self.assertEqual(r.participant_of(2).id, "near-7")

    def test_a_participant_spans_its_tracks(self):
        self.assertEqual(small_roster().participant("near-7").track_ids, (1, 2))

    def test_the_file_round_trips(self):
        r = small_roster()
        with tempfile.TemporaryDirectory() as d:
            path = r.write(Path(d) / "roster.json")
            back = Roster.load(path)
        self.assertEqual(back.tracks, r.tracks)
        self.assertEqual(back.track(2).readings, ((6, 7, 0.9), (8, 7, 0.8)))
        self.assertEqual(back.participants, r.participants)
        self.assertEqual(back.sides, r.sides)
        self.assertEqual(back.live_core, (0, 5))
        self.assertEqual({p.track.id for p in back.at(2)}, {1, 3, 4})

    def test_a_roster_from_another_clip_is_refused(self):
        with self.assertRaises(ValueError):
            small_roster().check_clip("not-abc")

    def test_an_old_schema_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "roster.json"
            path.write_text(json.dumps({"schema_version": 0}))
            with self.assertRaises(ValueError):
                Roster.load(path)


@unittest.skipUnless((ROSTER_ROOT / f"{CLIP}.json").exists(), "roster not built for the clip")
class OnTheClip(unittest.TestCase):
    # The four referees the identity doc names, and the one jersey that reads
    # as black as their shirts.

    @classmethod
    def setUpClass(cls):
        cls.roster = Roster.for_video(CLIP)

    def test_the_referees_are_officials(self):
        for tid in (8, 122, 13, 174):
            self.assertEqual(self.roster.track(tid).role, "official", tid)

    def test_usa_2_in_a_black_print_jersey_is_a_player_on_the_far_side(self):
        for tid in (19, 137):
            t = self.roster.track(tid)
            self.assertEqual((t.role, t.team), ("player", "far"), tid)

    def test_no_official_is_in_play_during_the_live_core(self):
        start, end = self.roster.live_core
        for t in self.roster.tracks.values():
            if t.role == "official":
                inside = [f for a, b in t.in_play for f in (a, b) if start <= f <= end]
                self.assertEqual(inside, [], t.id)

    def test_each_kit_maps_to_one_side(self):
        self.assertEqual(self.roster.sides, {"red": "near", "white": "far"})

    def test_a_number_is_joined_within_its_side(self):
        # #13 and #2 are USA; the near side's 44 is three fragments of one man,
        # and CHALMERS 7 runs through the swap that cut track 54.
        self.assertEqual(self.roster.participant("far-13").track_ids, (75,))
        self.assertEqual(self.roster.participant("far-2").track_ids, (165,))
        self.assertEqual(self.roster.participant("near-44").track_ids, (2, 227, 270))
        self.assertEqual(self.roster.participant("near-7").track_ids, (56, 422, 285))

    def test_the_readings_behind_a_name_are_on_the_track(self):
        t = self.roster.track(56)
        self.assertEqual(t.number, 7)
        self.assertGreaterEqual(sum(n == 7 for _, n, _ in t.readings), 3)

    def test_both_sides_are_full_at_the_rush(self):
        start = self.roster.live_core[0]
        counts = {k: len(v) for k, v in self.roster.on_court(start + 150).items()}
        self.assertEqual(counts, {"near": 6, "far": 6})

    def test_every_player_track_has_a_side(self):
        for t in self.roster.player_tracks():
            self.assertIn(t.team, ("near", "far"), t.id)


if __name__ == "__main__":
    unittest.main(verbosity=2)
