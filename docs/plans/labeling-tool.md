---
title: Labelling Tool — Plan
created: 2026-08-25
updated: 2026-08-25
status: built — labelling guide and agreement report outstanding
tags: [plan, labelling, tooling]
---

# Labelling Tool — Plan

Parent: [[throw-attempt-detection]] § Labels. This doc is the design for `tools/labeler/`;
when the tool is complete its design rationale graduates to `docs/architecture/` and this file
is deleted.

## Context

The truth set is built here, not sourced. Labelling ~60 throws plus fakes at frame accuracy,
with two players per event, has to be fast enough to fit in about an hour and repeatable
enough to run a blind second pass. Off-the-shelf tools were rejected: image labellers work
per frame and lose the temporal context, and general video annotators are not keyboard-driven
enough for two-keypress events.

## What a label is

Each throw is two moments, each captured with one or two keypresses:

```
release frame:   T  →  thrower key         throw opened
resolution:      H / C / B / M / U  →  target key (H, C, B only)    throw closed
fake:            F  →  thrower key         terminal — no resolution
```

An outcome closes the **selected open throw**; the most recently opened throw is selected by
default, and `Tab` cycles open throws for coordinated attacks with two or three balls in the
air. Open throws are highlighted in the list so none is forgotten.

### Fields per event

| Field | Captured by | Notes |
|---|---|---|
| `release_frame` | `T` (or `F`) at the current frame | the anchor for the temporal tolerance |
| `start_frame`, `end_frame` | `S`, `E` — optional | wind-up onset, resolution |
| `thrower` | player key or drag | box + frame, see below |
| `team` | inferred from the court half of the thrower box; override key | fixed camera, sides do not change within a half |
| `outcome` | `H` hit, `C` catch, `B` block, `M` miss, `U` unresolved | the throw branch |
| `target` | player key or drag, for hit / catch / block | box + frame — required, because a catch eliminates the thrower and returns a player to the catcher's side, a hit eliminates the target |
| `fake` | `F` | terminal |
| `release_visible`, `outcome_visible` | toggles, default true | separates unobservable from mislabelled |
| `ref_signal` | seen / not seen / not visible | closest thing to external truth on ambiguous hits |
| `uncertain`, `note` | toggle, text | the annotator's honest "I'm guessing" |

### Player boxes: stored by value, never by reference

A player is recorded as a **box** in source pixels plus the frame it was placed on — thrower
at the release frame, target at the resolution frame. A point was rejected: it has no extent
and is ambiguous inside an overlap. Boxes evaluate against predictions by IoU, which handles
overlapping players sensibly.

Pose detections are a **convenience for placing boxes, never the record**. Pressing a player
key copies that skeleton's box coordinates into the label; from then on it is a human-accepted
box that references nothing. Re-running the detector with different weights cannot change what
a label means. Each box carries:

- `source`: `snapped` (accepted from a detection, possibly adjusted) or `drawn` (manual)
- `adjusted`: whether the annotator moved or resized it after snapping
- provenance of the pose run on screen when it was placed (model, weights hash, input size) —
  for tracing annotator bias later; nothing in evaluation reads it

Accepting a snapped box makes the annotator responsible for it: if it is loose or straddles two
players, adjust it or draw instead. Snap, glance, accept or nudge.

Drawn boxes are the fallback when the detector missed the player, and they are more than a
fallback: they record the size and position of what the detector could not see, so the
evaluation can say *which* players it loses rather than that it lost some.

### Derived at evaluation time, never stored

Detector miss rate on throwers ("does this run's detections contain the labelled box?"),
attribution ("which of this run's tracks was the thrower?"), eliminations and game state.
All recompute when the model changes; the labels never move.

### Live-play intervals

Marked once per set with two keys (set start at the opening rush, set end), shaded on the
timeline. Throws outside live play do not count and the metric is computed per set. The clip
begins with ~18 s of pre-set.

## Design

### Transport and frame truth

The browser video element does transport; `requestVideoFrameCallback` reports the media time
of the frame actually presented, so the frame index is truth rather than a request. The clip is
constant 25 fps with a keyframe every second, so `frame = floor(mediaTime × fps)` is exact and
seeks land where asked; seeks target frame midpoints so rounding cannot cross a boundary.

Per-frame image extraction was considered and rejected: it buys decoder-free inspection, which
matters for a 10 px ball and not for a 90–280 px player. Frame-exactness matters for the
*release frame*, and the frame callback already gives that.

### Overlay

A canvas layered over the video, redrawn inside the frame callback — the overlay is derived from
the video's own report of what it is showing, so it cannot be on a different frame. One
image↔screen transform is shared by drawing and hit-testing, and carries wheel zoom, pan and a
shift-held magnifier, because far-court boxes at ~90 px cannot be adjusted honestly at 1×.

Drawn on it: on-court skeletons (court polygon filter) with their player keys — near team
`1`–`6`, far team `Q`–`Y`, ordered left to right per team on the current frame, so no identity
or tracking is needed; thrower and target boxes for the selected event; live-play bands on
the timeline.

### Box editing

| Interaction | Effect |
|---|---|
| player key | snap that skeleton's box |
| drag a corner | resize, opposite corner anchored |
| drag inside a box | move |
| drag on empty space | draw a new box |
| arrow keys | nudge 1 px, shift for 10 px |
| hover | cursor shows what a click will grab |

### Pose precompute

Run once per clip with the same detector and settings the pipeline uses, so "no skeleton
here" in the tool and "missed" in the evaluation mean the same thing. Stored outside the repo
under `data/pose/<video>/<run-id>/` with the run's settings alongside, chunked by frame range
for lazy loading. Regenerable and disposable.

**Contract** — shared by the tool (reads) and the pipeline (writes). If the tool was built
against a different shape, reconcile here rather than in two places.

```
data/pose/<video-stem>/<run-id>/
  manifest.json      model, weights sha256, imgsz, conf, iou, fps, clip sha256, frame count, created
  frames_00000.json  frames 0–999
  frames_01000.json  frames 1000–1999   ...
```

Each chunk is `{ "<frame>": [detection, ...] }` with one detection as:

```json
{ "box": [x1, y1, x2, y2], "conf": 0.91,
  "kpts": [[x, y, c], ... 17 entries, COCO order] }
```

Coordinates in source pixels of the clip, all people (no court filtering — the tool and the
pipeline filter with the same court polygon, kept in `data/court/<video-stem>.json`).
`run-id` is `<model>-<imgsz>-<short weights hash>` so two runs with the same settings collide
on purpose.

### Persistence

Autosave to `data/labels/<video>[.<annotator>].json`; `?annotator=<name>` gives a blind second
pass its own file. Label files are committed, footage and pose runs are not.

## Schema change required: `kind`

A pass — a throw to your own team — is identical to a throw up to the moment of release, so the
tool must be able to record one. It currently cannot: `fake: boolean` plus an `Outcome` leaves
an annotator meeting a pass with nowhere to put it, and a silently skipped event is one that
can never be measured.

Replace `fake: boolean` with `kind: 'fake' | 'pass' | 'throw'`. Mutual exclusivity becomes
structural rather than a convention, and the born-closed rule generalises: `fake` and `pass` are
terminal and open closed, `throw` opens waiting for an outcome. `target` already means "the
player the ball reached" and is team-agnostic, so a pass's receiver reuses it — optional, since
the receiver is not needed for the metric.

See [[throw-attempt-detection]] § Event definition for the destination-not-intent rule that
decides pass from throw.

## Build order

1. ~~Pose precompute script and per-frame-range serving~~ — `scripts/precompute_pose.py`,
   `tools/labeler/server/api.ts`
2. ~~Canvas overlay with the shared transform, zoom, pan, magnifier; skeletons with player
   keys~~ — `src/lib/transform.ts`, `src/components/Stage.tsx`
3. ~~Event flow (`T`/`F` + player, outcome + target, `Tab` for open throws) on the v2
   schema~~ — `src/lib/events.ts`, `src/lib/keys.ts`, `src/types.ts`
4. ~~Box editing: snap, corner and body drag, draw, nudge~~ — `src/lib/boxes.ts`
5. ~~Observability fields, ref signal, team inference and override, live-play intervals~~
6. Restyle to the design system ([[design-system]]) — tokens into `src/index.css` and
   `tailwind.config.js`, then the components; the full key map lands in the instrument bar
7. Labelling guide (`docs/labeling-guide.md`) — the rule handed to a second annotator
8. Second-pass agreement report script

## Resolved

**Court geometry comes from a fitted calibration, not a hand-picked polygon.**
`data/court/<video-stem>.json` holds a homography between source pixels and the court's
own metres, fitted from the painted lines, with a held-out error of 6–9 cm. The tool reads
it and reasons in metres: "on court" is `0 - margin ≤ x ≤ width + margin` and the same in
length, with `margin_m` the tolerance for a player standing on the paint. Team is the
point's court y against `centre_line_m` — no centre-line-at-x interpolation, and correct
however the line slants in the picture.

This replaces the hand-picked quad the plan originally called for, and it is strictly
better: the test is metric, so it means the same thing at both ends of a court where near
players are twice the height of far ones, and the same geometry serves the pipeline. In-tool
court authoring was removed with it — the court is produced by the calibration step.

A court file that is missing or of an older shape means "no court": no overlay, no player
keys, no team inference. It must not be able to take the page down, which it previously did.

It still cannot exclude officials standing in play — referees and line judges inside the
margin consume player keys. That is the cost of having no team classifier, and it is now at
least measurable: every detection has a court position in metres, so how often it happens
can be counted rather than guessed.

**Player-key ordering.** Sorted by the anchor's x, then its y ascending, then the detection's
own index so the order is total. The anchor is the box's bottom centre — the feet — rather
than its centre, which drifts upward on a jump and would flip a jumping player to the wrong
half of the court. Keys are recomputed per frame and carry no identity, so two players
crossing swap keys; the label stores the box, not the key, so nothing downstream notices.

**Team is `near` / `far`.** The fixed end-on camera makes the court half directly observable
and it does not change within a half, so no jersey model or roster is needed to name a side.
Inferred from the thrower's feet against the centre line, with `team_source` recording an
override.

## Still open

- The full key map has no home. The help overlay was removed — a keyboard-driven tool whose
  keys are hidden behind a shortcut teaches nobody — but the instrument bar currently shows
  only the event keys. Transport, zoom and magnifier, box editing, the observability toggles
  (`D` `V` `O` `X` `A` `N`), live play (`L` `K`) and court (`G`) are documented nowhere in the
  interface. They need to land in the bar during the restyle.
- Whether `start_frame` is worth labelling for every throw or only a subset, given the candidate
  stage will be evaluated on it.
- Pose chunks are 1000 frames per the contract, which is ~15 MB of JSON at this footage's crowd
  density (roughly forty people in frame). It loads fine from localhost but is heavy to hold in
  memory; if that bites, the contract is the place to change it, not the reader.

## Deliberately not built

- `docs/labeling-guide.md` and the second-pass agreement report — build-order items 7 and 8.
- Non-throw negatives, eliminations and game state: all derived at evaluation time.
