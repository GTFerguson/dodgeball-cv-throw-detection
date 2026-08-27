---
title: Pipeline
created: 2026-08-27
updated: 2026-08-27
tags: [architecture, pipeline, configuration]
---

# Pipeline

Footage in, timeline and metric out: the order the stages run in, the
contract that lets them be run separately, and the two things every stage
shares — the clip's frame rate and the venue's assumptions.

| File | Role |
|---|---|
| `scripts/run.py` | The front door: every stage in order on one clip, scored where labels exist |
| `src/timing.py` | Durations to frames at the clip's rate |
| `src/venue.py`, `config/venue.toml` | What is assumed about the venue and the footage |

## The stages

```
fit_court          data/court/<stem>.json       image <-> court metres        [[court-geometry]]
precompute_pose    data/pose/<stem>/<run>/      every person, every frame     [[pose-precompute]]
detect_set_start   data/sets/<stem>.json        where each set begins         [[set-start]]
identify_players   data/roster/<stem>.json      who is a player, which side   [[roster]], [[player-identity]]
detect_set_end     data/sets/<stem>.json        where each set ends           [[set-end]]
detect_candidates  data/candidates/<stem>.json  throwing motions              [[throw-candidates]]
detect_events      data/timeline/<stem>.json    fake | pass | throw, outcome  [[release-gate]], [[destination]], [[rebound]], [[outcome]]
tactics            output/<stem>/tactics.md     efficiency by set-up
evaluate           output/<stem>/evaluation.json  every level, where labels exist   [[evaluation]]
```

Each stage is its own script and reads the outputs before it by the clip's
**stem**. Nothing is passed between stages except through the files, so any
stage can be rerun and inspected alone, and two sessions working on different
stages see the same inputs. `scripts/run.py` runs them in the only order that
works and stops at the first failure; `--from <stage>` resumes partway.

## The hash contract

Every derived file records the SHA-256 of the clip it was computed from, and
every reader refuses a mismatch (`check_clip`). Frame indices are the only
thing tying calibration, detections, labels and timeline together, and a
re-encode shifts them without changing a filename. The consequence for the
stress test ([[evaluation#Stress conditions]]) is that a degraded copy of the
clip is simply a new stem with its own inputs — nothing special-cased.

The pose run is the one stage that resumes rather than recomputes: chunks
already on disk for the same model and clip are kept. Everything downstream
is seconds and recomputes.

## Time is in seconds

Every window in the pipeline is a duration — how long a thrower holds the
ball before the whip, how long a side's count must hold to be a step — and
was tuned on a 25 fps clip. They are written as seconds (`*_S`) and converted
once, by `src/timing.py`, at the rate the pose run reports; the wrist-speed
score is likewise per second. At 25 fps every value is the frame count it
shipped as (`scripts/test_timing.py` pins this). Two windows stay in frames on
purpose: `LINK_GAP_FRAMES`, the number of consecutive frames a chain may miss
a detection on, which is a property of the detector not of time; and
`IN_PLAY_HOLD_FRAMES` in the tracking layer.

What this does *not* buy is rate invariance of the wind-up detector. On the
half-rate stress clip the per-second rewrite changed nothing for the better
(candidate recall 78% → 55%): a throw's whip lasts under 100 ms, so at
12.5 fps the wrist-speed peak is under-sampled and no rescaling of a
per-frame score reproduces the 25 fps threshold. `MIN_SCORE` is a property
of the rate it was tuned at.

## The venue is a file

`config/venue.toml` holds what is assumed about this venue and this footage
and nothing about dodgeball: the ball's HSV window (a hue floor one step above
the red kit), the court's dimensions and margin, the kit colours and which the
officials wear. `src/venue.py` reads it once with every
default filled in and refuses an unknown key, so a typo cannot leave a default
silently in place; a checkout without the file behaves identically.

`src/ball.py` reads the window, `src/court.py` the dimensions, `src/roster.py`
the kit vocabulary. The rules that classify a chest into one of those colours
are the roster's own.

What stays out of the file: every tuning of the algorithms — chain slack,
hold durations, score floors. Those are named constants beside the code that
owns them, with the reason for their value in the comment, and the timeline
file records the set it was written with.

## Boundaries

- One clip at a time. A match is a sequence of clips or one long clip. The
  whole second half (23 min, 35,146 frames) runs end to end in 12 min after
  pose: eight set starts found, seven set ends from the floor, 240 throws;
  the labelled set scored from that run matches the clip-level run.
- Memory is bounded by tracks, not frames: the identity pass keeps only the
  crops its shortlist can use (`CropKeeper`), after the half's 35k frames
  took the unbounded version to 27 GB.
- Batch. Pose is the cost (YOLO11x-pose at 1920 px, ~9 fps on a laptop RTX
  4080); everything after it is seconds.
- The front door does not retune. A second venue needs the config changed
  and the score floors revisited; the court fit and the hash checks will
  refuse before anything downstream guesses.
