---
title: Pose Precompute
created: 2026-08-25
updated: 2026-08-25
tags: [architecture, pose, detection, contract]
---

# Pose Precompute

`scripts/precompute_pose.py` runs whole-body detection and pose over a clip once
and writes it to `data/pose/<video-stem>/<run-id>/`. `src/pose.py` reads it.
Everything that needs people — the labelling tool, the court filter, the wind-up
detector, the evaluation — reads that one run.

## Why one shared run

The labelling tool draws skeletons as a placement aid, and the pipeline detects
players. If those were separate inference passes, "no skeleton here" while
labelling and "missed" during evaluation would be statements about two different
models, and the recall ceiling measured at evaluation would not be the ceiling the
annotator was actually working under. Sharing the run makes them the same
statement about the same model, which is what lets detector misses be separated
from model error in the error budget.

The run id is `<model>-<imgsz>-<short weights hash>`, so two runs with identical
settings collide on purpose and resume into the same directory, while two runs
that would place different boxes land in different ones. Labels record which run
was on screen when a box was placed.

## Contract

```
data/pose/<video-stem>/<run-id>/
  manifest.json      model, weights sha256, imgsz, conf, iou, fps, clip sha256, frame count
  frames_00000.json  frames 0-999
  frames_01000.json  frames 1000-1999   ...
```

A chunk is `{"<frame>": [detection, ...]}`, one detection being:

```json
{ "box": [x1, y1, x2, y2], "conf": 0.91,
  "kpts": [[x, y, c], "... 17 entries, COCO order"] }
```

Coordinates are source pixels of the clip. A frame present with an empty list was
processed and had nothing; a frame absent was never processed — the distinction
matters, because the second is a gap in the run and the first is a statement about
the footage.

**Every person is written, with no court filtering.** Filtering happens in the
reader against the calibration in `data/court/`, so the court polygon can change
without re-running inference — which it did, when the polygon became a fitted
homography. Chunks are aligned to absolute multiples of the chunk size, so a chunk
written by a partial `--start`/`--end` run covers the same frames as the equivalent
chunk from a full pass and the two are interchangeable.

Pose runs are regenerable and disposable, and are not committed. Labels are.

## Reader

```python
from pose import PoseRun

run = PoseRun.for_video("wdbf2014_final_h2_set2.mp4")
run.check_clip(court.clip_sha256)      # refuse a run computed on a different cut
for detection in run.frame(625):
    ...
```

Chunks load on demand and stay cached, because a whole clip's detections are far
larger than any one stage's working set. `check_clip` compares hashes rather than
filenames: frame indices are the only thing tying labels, calibration and
detections together, and a re-encode shifts them silently.

`frames_done` reports how many frames have actually been written, so a consumer
can tell a partial run from a clip where nothing was detected.

## Settings

YOLO11x-pose at `imgsz` 1920, `conf` 0.25, on CUDA. Full resolution is needed
because far-court players are ~150 px tall and their arm keypoints are the signal
the wind-up detector depends on; the near/far asymmetry this creates is handled
geometrically in [[court-geometry]].

## Boundaries

- Detection and pose only. No tracking: identities are associated downstream from
  the stored boxes, which keeps inference to a single pass and makes the linker a
  swappable, testable component rather than a detector setting.
- No court filtering, by design — see the contract above.
