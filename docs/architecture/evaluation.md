---
title: Evaluation
created: 2026-08-26
updated: 2026-08-26
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
| Efficiency | eliminations over throws per team, truth and predicted | all events in play |

Fakes are events. A wind-up that released nothing is a candidate the model
should find and then say *no release* about, so it counts at the candidate
level and is the negative class at the release level.

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
and not the candidate stage's — but they still count against precision,
since the pipeline does not know set end either.

## Boundaries

- One clip's labels, one annotator. The blind second pass the plan calls
  for has not been run, so candidate recall is measured against a truth set
  every event of which was seeded by the candidate stage. The plan's own
  words: recall would be 1.0 by construction. The candidate stage was built
  loose for exactly that reason and the number should be read as the
  precision of a stage tuned for recall, not as recall.
- Efficiency is computed for the prediction only once it claims outcomes.
- No stress or ablation runs yet; the plan's table stands.
