---
title: Evaluation
created: 2026-08-26
updated: 2026-08-27
tags: [architecture, evaluation, labelling]
---

# Evaluation

Scoring a predicted timeline against the truth set, one level of the cascade
at a time. Every experiment on the pipeline runs through this and nothing
else, so two numbers from two sessions are the same measurement.

| File | Role |
|---|---|
| `src/evaluate.py` | The truth reader, the matcher, the per-level report |
| `scripts/evaluate.py` | Scores `data/timeline/<stem>.json`, or the proposals as a baseline |
| `scripts/test_evaluate.py` | Checks on matching and on what each level counts |
| `scripts/ablate.py` | The timeline scored with its later stages withheld — `output/ablation/` |
| `scripts/error_budget.py` | Efficiency error by source, model against labels — `output/error_budget.json` |
| `src/stress.py`, `scripts/stress.py`, `scripts/test_stress.py` | Degraded clips and their derived inputs — `output/stress/` |

Upstream: the labels in `data/labels/` (schema 5, written by `tools/labeler`),
[[roster]] and [[pose-precompute]] to carry a labelled box between frames.

## One level at a time

The plan defined the event as a cascade — candidate, release, destination,
outcome — because each is a separate decision with its own failure mode.
The report keeps them apart rather than blending them into one F1, and
scores a level only where the prediction makes a claim at it: a stage that
says "a throwing motion here" is scored on that and nothing below, so it is
never marked wrong for a question it did not answer.

| Level | What is scored | On |
|---|---|---|
| Candidate | precision, recall, F1; spurious predictions split into during play and after set end | every truth event, fakes included |
| Release frame | mean absolute error and bias against the labelled release | matched events |
| Team | accuracy | matched events where both name a team |
| Release | fake against released, as a confusion | matched events where the prediction claims `released` |
| Kind | fake, pass, throw | matched events where the prediction claims `kind` |
| Outcome | hit, catch, block, miss | matched throws where the prediction claims `outcome` |
| Detection by kind | precision, recall, F1 with a claimed kind as the positive class | every truth event of that kind, every prediction claiming it |
| Efficiency | eliminations over throws per team, truth and predicted | all events in play |

Fakes are events. A wind-up that released nothing is a candidate the model
should find and then say *no release* about, so it counts at the candidate
level and is the negative class at the release level.

Kind accuracy is on matched events only, and so it hides a throw claimed on
a proposal that matched nothing. Detection by kind treats each claimed kind
as a detector of that kind: a throw claimed on a fake is a false throw and a
missed fake, a throw claimed on nothing is a false throw. Throw F1 is the
number the metric's denominator rests on.

## Matching is same-frame, same-player

A prediction matches a truth event when its frame is within
`TOLERANCE_FRAMES` of the labelled release — the plan's ±0.25 s — and its
thrower box overlaps the labelled thrower's box **on that same frame** by
`MIN_IOU`. That is the test the labelling tool uses to tie a proposal to a
labelled thrower, so "the tool agreed" and "the harness agreed" are one
statement. Pairs are taken nearest in time first, one to one, so a proposal
a frame off a release is not stolen by a second event on the same player a
few frames later.

**Why the box has to be carried to the prediction's frame.** The annotator's
box is snapped on the frame they placed it, and for a corrected release that
is up to thirty frames from the release. A throwing player's box changes
shape fast: the same track scores IoU 0.31 with itself five frames apart as
the arm comes through. Matching against the labelled box on a different
frame is therefore not the tool's test, and it cost three of sixty events
that were right by eye. `TruthSet.anchored` uses the roster's track as the
bridge — the track holding the labelled box on its frame gives the same
player's box on every frame within the tolerance. The truth file itself
keys nothing on a track id, which a re-run of the identity pass renumbers;
the track is used only to move a box, never to name a match. Distinct
players never overlap above IoU 0.1 within twelve frames on the clip, so
the floor stays at the tool's 0.5.

## Set end falls out of the last hit

The label's live-play interval has no end written: the tool records the
start from the accepted set-start review and leaves the end to the last
elimination. `TruthSet.set_intervals` closes it at the outcome frame of the
last throw labelled `hit`. Spurious predictions after that frame are
reported apart from those during play, because they are set end's problem
and not the candidate stage's — but they still count against precision.
The pipeline now reads its own end from the floor ([[set-end]]); the count
of predictions after set end is what that closes, once the proposals are
regenerated under the tightened interval.

## Ablation

`scripts/ablate.py` scores one pipeline run three times: every proposal
claimed as a throw (what a pose-only detector would say), the release gate's
events with released = throw and nothing else (no pass test), and the full
timeline. The candidate matching is identical in every row — the rows differ
only in what is claimed about the same motion — so the gap between rows is
exactly the stage withheld. On the clip, throw F1 runs 43% → 69% → 75%: the
release gate buys 33 points of throw precision for 18 of recall (the five
releases it calls fake), the destination test 12 more for 3, and is the only
row that finds a pass.

## Stress conditions

`scripts/stress.py` reruns the cascade on a degraded copy of the clip —
480 rows, x264 CRF 40, every second frame dropped — and scores it at the
same ±0.25 s. The pipeline keys every input on the clip hash, so a degraded
clip is a new stem (`<stem>--<condition>`, gitignored on the marker) with its
own inputs. Which inputs are recomputed and which are carried over is the
design decision, and `src/stress.py` records it: everything that reads
pixels is rerun — pose, tracking and identity, set end, candidates,
releases, outcomes — because the degradation acts on pixels; the court fit
(a downscale is a known affine map, so refitting would test only the
fitter), the set starts (a whistle in the audio, which no condition touches)
and the labels (truth does not change with the encode) are transformed
instead: boxes scaled, frames remapped to the kept ones, the tolerance
scaled with the frame rate so it stays a duration. Results are in
`output/stress/summary.md` and the README.

The frame-drop condition produced the one finding that changed the code:
the candidate loss looked like frame-count windows doubling in length, the
windows became durations ([[pipeline#Time is in seconds]]), and the loss
did not move — the wind-up detector's peak is under-sampled at half rate,
which no unit change repairs. Both rows are kept in the table.

## Error budget

`scripts/error_budget.py` reads the same matching per team and names where
the efficiency's error comes from: the denominator (throws claimed that were
fakes, passes, nothing, or the other team's; true throws called fake or
pass or never proposed) and the numerator (hits right, missed, invented).
Three uncertainties are stated apart. The model's, as a paired bootstrap
over the matching's units — each matched pair, spurious prediction and
missed event resampled together, so every draw has a truth and a predicted
efficiency from the same events. The labels', as the range the truth spans
if every `uncertain` event went the other way. And the clip's own sampling
interval on the truth, which on fifteen throws a side is wider than either:
the metric is a match-level quantity read off one set.

## Boundaries

- One clip's labels, one annotator. The blind second pass the plan calls
  for has not been run, so candidate recall is measured against a truth set
  every event of which was seeded by the candidate stage. The plan's own
  words: recall would be 1.0 by construction. The candidate stage was built
  loose for exactly that reason and the number should be read as the
  precision of a stage tuned for recall, not as recall.
- Efficiency is computed for the prediction only once it claims outcomes.
- The stress test does not stress the court fitter, the set-start detector
  or the annotator; a condition that moved the camera would need all three
  rerun, and the carry-over would be wrong.
- The bootstrap resamples this clip's events; it says nothing about a second
  venue, camera or kit.
- Nearest-first pairing can cross two throws a frame apart by two players
  whose boxes overlap: the set-ending double on the clip is scored as two
  outcome errors where the pipeline put the hit on the right ball. A pairing
  that maximises total agreement rather than taking the nearest first would
  fix it; it is one event on this clip and is reported rather than fixed.
