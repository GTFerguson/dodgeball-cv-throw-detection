#!/usr/bin/env python
"""Checks on scoring a timeline against the truth set.

Run with ``.venv/bin/python scripts/test_evaluate.py``. The clip-level checks
run only when the labels, roster and candidates exist for the evaluation clip.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from src.evaluate import (  # noqa: E402
    LABELS_ROOT,
    MIN_IOU,
    TOLERANCE_FRAMES,
    Prediction,
    TruthEvent,
    TruthSet,
    efficiency,
    evaluate,
    iou,
    match,
)

CLIP = "wdbf2014_final_h2_set2"


def truth(frame: int, kind: str = "throw", box=(100.0, 100.0, 200.0, 300.0), team="near",
          outcome=None, end=None, boxes=None, ball_in_hand=None, eliminated=None) -> TruthEvent:
    return TruthEvent(id=f"t{frame}", kind=kind, release_frame=frame, end_frame=end, box=box,
                      box_frame=frame, team=team, outcome=outcome, uncertain=False,
                      source="manual", proposed_frame=None, ball_in_hand=ball_in_hand,
                      eliminated=eliminated, track_boxes=boxes or {})


def pred(frame: int, box=(100.0, 100.0, 200.0, 300.0), **claims) -> Prediction:
    return Prediction(frame=frame, box=box, **claims)


class Matching(unittest.TestCase):

    def test_a_prediction_within_tolerance_on_the_same_player_matches(self):
        m = match([truth(100)], [pred(100 + TOLERANCE_FRAMES)])
        self.assertEqual(len(m.matches), 1)
        self.assertEqual(m.matches[0].delta, TOLERANCE_FRAMES)

    def test_one_frame_past_tolerance_is_a_miss_and_a_false_positive(self):
        m = match([truth(100)], [pred(100 + TOLERANCE_FRAMES + 1)])
        self.assertEqual((len(m.matches), len(m.missed), len(m.spurious)), (0, 1, 1))

    def test_the_same_frame_on_another_player_does_not_match(self):
        m = match([truth(100)], [pred(100, box=(400.0, 100.0, 500.0, 300.0))])
        self.assertEqual(len(m.missed), 1)

    def test_a_fake_is_an_event_at_the_candidate_level(self):
        m = match([truth(100, kind="fake")], [pred(100)])
        self.assertEqual(len(m.matches), 1)

    def test_the_closer_prediction_takes_the_event_and_the_other_is_spurious(self):
        m = match([truth(100)], [pred(104), pred(101)])
        self.assertEqual(m.matches[0].prediction.frame, 101)
        self.assertEqual([p.frame for p in m.spurious], [104])

    def test_two_events_on_one_player_are_matched_nearest_first(self):
        # Fake at 100, throw at 108: the proposal at 107 belongs to the throw,
        # not stolen by the fake it is also within tolerance of.
        m = match([truth(100, kind="fake"), truth(108)], [pred(101), pred(107)])
        self.assertEqual({(x.truth.release_frame, x.prediction.frame) for x in m.matches},
                         {(100, 101), (108, 107)})

    def test_matching_uses_the_players_box_on_the_predictions_frame(self):
        # The labelled box is on the release frame; on the frame the prediction
        # sits, the same player's box has grown past the overlap floor.
        grown = (80.0, 60.0, 240.0, 320.0)
        self.assertLess(iou(grown, (100.0, 100.0, 200.0, 300.0)), MIN_IOU)
        t = truth(100, boxes={103: grown})
        self.assertEqual(len(match([t], [pred(103, box=grown)]).matches), 1)
        self.assertEqual(len(match([truth(100)], [pred(103, box=grown)]).matches), 0)


class Levels(unittest.TestCase):

    def setUp(self):
        self.truth = TruthSet(video="x", fps=25.0, live_play=[(0, None)], events=[
            truth(100, kind="fake"),
            truth(200, kind="throw", outcome="hit", end=210),
            truth(300, kind="pass"),
            truth(400, kind="throw", outcome="miss", end=415, team="far"),
        ])

    def test_a_stage_that_claims_only_a_motion_is_not_scored_below_it(self):
        r = evaluate(self.truth, [pred(100), pred(200), pred(300), pred(400)])
        self.assertEqual(r.candidate["recall"], 1.0)
        self.assertIsNone(r.release)
        self.assertIsNone(r.kind)
        self.assertIsNone(r.outcome)

    def test_release_is_scored_only_where_claimed(self):
        r = evaluate(self.truth, [pred(100, released=False), pred(200, released=True),
                                  pred(300), pred(400, released=False)])
        self.assertEqual(r.release["n"], 3)
        self.assertEqual(r.release["table"]["fake"]["fake"], 1)
        self.assertEqual(r.release["table"]["released"]["released"], 1)
        self.assertEqual(r.release["table"]["released"]["fake"], 1)

    def test_outcome_is_scored_on_throws_only(self):
        r = evaluate(self.truth, [pred(200, outcome="hit"), pred(300, outcome="miss")])
        self.assertEqual(r.outcome["n"], 1)
        self.assertEqual(r.outcome["accuracy"], 1.0)

    def test_a_throw_claimed_on_a_fake_is_a_false_throw_and_a_missed_fake(self):
        r = evaluate(self.truth, [pred(100, kind="throw"), pred(200, kind="throw"),
                                  pred(300, kind="pass"), pred(500, kind="throw")])
        throw = r.detection["throw"]
        self.assertEqual((throw["tp"], throw["fp"], throw["fn"]), (1, 2, 1))
        self.assertEqual(r.detection["fake"], {"tp": 0, "fp": 0, "fn": 1, "precision": 0.0,
                                               "recall": 0.0, "f1": 0.0})
        self.assertEqual(r.detection["pass"]["f1"], 1.0)

    def test_spurious_predictions_after_the_last_hit_are_reported_apart(self):
        # No labelled end: the set ends at the last hit's outcome, 210.
        self.assertEqual(self.truth.set_intervals(), [(0, 210)])
        r = evaluate(self.truth, [pred(150), pred(500)])
        self.assertEqual((r.candidate["fp_in_play"], r.candidate["fp_after_set_end"]), (1, 1))

    def test_a_fake_with_no_ball_counts_and_is_reported_apart(self):
        t = TruthSet(video="x", fps=25.0, live_play=[(0, None)], events=[
            truth(100, kind="fake", ball_in_hand=False), truth(200, kind="fake", ball_in_hand=True)])
        r = evaluate(t, [pred(200)])
        self.assertEqual(r.candidate["fn"], 1)
        self.assertEqual((r.candidate["no_ball_fakes"], r.candidate["no_ball_fakes_found"]), (1, 0))
        r = evaluate(t, [pred(100), pred(200)])
        self.assertEqual(r.candidate["no_ball_fakes_found"], 1)

    def test_a_hit_on_a_player_already_out_wins_nothing(self):
        events = [truth(200, outcome="hit", end=210), truth(300, outcome="hit", end=310, eliminated=False)]
        self.assertEqual(efficiency(events)["near"], {"throws": 2, "eliminations": 1, "efficiency": 0.5})
        t = TruthSet(video="x", fps=25.0, live_play=[(0, None)], events=events)
        self.assertEqual(t.set_intervals(), [(0, 210)])

    def test_efficiency_counts_hits_over_throws_per_team(self):
        eff = efficiency(self.truth.events)
        self.assertEqual(eff["near"], {"throws": 1, "eliminations": 1, "efficiency": 1.0})
        self.assertEqual(eff["far"]["efficiency"], 0.0)


@unittest.skipUnless((LABELS_ROOT / f"{CLIP}.json").exists(), "no labels for the clip")
class OnTheClip(unittest.TestCase):

    def test_the_set_ends_at_the_last_hit(self):
        t = TruthSet.for_video(CLIP)
        (start, end), = t.set_intervals()
        self.assertEqual(start, 433)
        self.assertEqual(end, 4660)

    def test_every_event_has_a_box_on_its_release_frame_once_anchored(self):
        from src.pose import PoseRun
        from src.roster import Roster
        t = TruthSet.for_video(CLIP).anchored(Roster.for_video(CLIP), PoseRun.for_video(CLIP))
        unanchored = [e.release_frame for e in t.events if e.release_frame not in e.track_boxes]
        self.assertEqual(unanchored, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
