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
| `release_frame` | `T` (or `F`) at the current frame; `T` with an event selected moves its release there | the anchor for the temporal tolerance |
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

Set starts are also detected ([[set-start]]) and drawn on the `MODEL` track, so the annotator
checks a frame the detector proposes rather than hunting for the rush. The tool reads them and
never writes them: a track the annotator had edited would not be a track worth comparing
against. It does take a verdict on each — `Shift+A` accepts one into the label file as a
live-play start, `Shift+R` records it as wrong — and a start the detector missed is still marked
by hand with `L`. Shipped; the design is in [[set-start#In the labelling tool]].

Proposed throws follow the same pattern ([[throw-candidates#In the labelling tool]]): rings on
the `MODEL` track, `⇧A` / `⇧R` on the nearest one, `>` / `<` to walk the unreviewed ones, and
an accepted proposal becomes an ordinary event that records where it came from.

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

Drawn on it: on-court skeletons, coloured by team and cased so the hue never has to fight the
jersey underneath it ([[design-system]] § Team is the one thing the frame is allowed to
colour), with their player keys — near team `1`–`6`, far team `Q`–`Y`, ordered left to right
per team on the current frame, so no identity or tracking is needed; thrower and target boxes
for the selected event; live-play bands on the timeline.

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

## Build order

1. ~~Pose precompute script and per-frame-range serving~~ — `scripts/precompute_pose.py`,
   `tools/labeler/server/api.ts`
2. ~~Canvas overlay with the shared transform, zoom, pan, magnifier; skeletons with player
   keys~~ — `src/lib/transform.ts`, `src/components/Stage.tsx`
3. ~~Event flow (`T`/`F` + player, outcome + target, `Tab` for open throws) on the v2
   schema~~ — `src/lib/events.ts`, `src/lib/keys.ts`, `src/types.ts`
4. ~~Box editing: snap, corner and body drag, draw, nudge~~ — `src/lib/boxes.ts`
5. ~~Observability fields, ref signal, team inference and override, live-play intervals~~
6. ~~Restyle to the design system ([[design-system]]) — tokens into `src/index.css` and
   `tailwind.config.js`, then the components; the full key map lands in the instrument bar.
   Overlay wires are coloured by team, `src/overlay.py` holds the pipeline's copy~~
7. Labelling guide (`docs/labeling-guide.md`) — the rule handed to a second annotator
8. Second-pass agreement report script
9. ~~Proposed throws on the `MODEL` track with accept / reject, `>` `<` to walk the unreviewed
   ones, `source` and `proposed_frame` on accepted events~~ — `src/lib/candidates.ts`;
   design in [[throw-candidates#In the labelling tool]]
10. ~~One event stream in place of three panels: `Labels` / `Model` source toggles, set starts
    and proposals as cards, playhead-following emphasis, cards naming who threw and who was
    hit from the roster, the selected card opening into the editor~~ — `src/lib/stream.ts`,
    `src/lib/roster.ts`, `src/components/Stream.tsx`, `src/components/EventEditor.tsx`;
    design in [[design-system#Event stream]]
11. ~~Players list as the panel's second tab: everyone who played a set from the roster,
    filtered by set and side, ranked by what the labels say they did, each row opening into
    their record and its name taking the stage to them~~ — `src/lib/tally.ts`,
    `src/components/Roster.tsx`; design in [[design-system#Players list]], the per-set
    `played_sets` it filters on in [[roster#Player against played]]

## Resolved

**Court geometry comes from a fitted calibration, not a hand-picked polygon.**
`data/court/<video-stem>.json` holds a homography between source pixels and the court's
own metres, fitted from the painted lines, with a held-out error of 6–9 cm. The tool reads
it and reasons in metres: "on court" is the paint plus the tolerance a player standing on the
line needs, which is a budget of ankle error in pixels converted at the point where it is
spent — see [[court-geometry#The slack is spent in pixels, not metres]]. Team is the point's court y against `centre_line_m` — no
centre-line-at-x interpolation, and correct however the line slants in the picture.

The calibration's `margin_m` band is *not* the in-play test, and reading it as one was a
real defect: it put 22.1 people per frame on the roster against the pipeline's 9.1, because
the band is precisely where the eliminated queue and the officials stand. See
[[court-geometry]] § The same test, written twice, drifted.

This replaces the hand-picked quad the plan originally called for, and it is strictly
better: the test is metric, so it means the same thing at both ends of a court where near
players are twice the height of far ones, and the same geometry serves the pipeline. In-tool
court authoring was removed with it — the court is produced by the calibration step.

A court file that is missing or of an older shape means "no court": no overlay, no player
keys, no team inference. It must not be able to take the page down, which it previously did.

It still cannot exclude officials who are genuinely inside the lines, but the count is now
measured rather than feared: about 0.1 per frame during live play, rising to several during
dead balls when they walk the court to lay the balls out. That points at a live-play gate
rather than a team classifier as the next filter.

**Player-key ordering.** Sorted by the foot point's x, then its y ascending, then the
detection's own index so the order is total. The foot point is the visible ankle keypoints,
falling back to the box's bottom centre — never the box centre, which drifts upward on a jump,
and not the box bottom alone, which for a player lying prone at the centre line is metres from
where they are and lands them in the wrong half. Keys are recomputed per frame and carry no identity, so two players
crossing swap keys; the label stores the box, not the key, so nothing downstream notices.

**Who gets a key is the roster's call.** Geometry decides only when there is no roster file.
With one, `playerSlots` takes an eligibility predicate — `RosterIndex.isPlayerInPlay(frame,
index)`: the detection's track is a `player` and the frame is inside one of its `in_play`
intervals — in place of the held-on-court test. The two tests spend the same boundary slack
and hold window, so this is not a widening; it removes the people the geometry cannot tell
from players. At 0:21 on the clip the geometry gave `Q` to a queued player a metre outside
the far touchline and `4` to an official on the near paint, so the two far players on the
right and Chalmers ran past the key rows. Team still comes from where the feet stand, because
the roster's side is a per-track majority and a key is placed on one frame. Keys remain a
placement aid and carry no identity — see [[roster#Queries]].

**Team is `near` / `far`.** The fixed end-on camera makes the court half directly observable
and it does not change within a half, so no jersey model or roster is needed to name a side.
Inferred from the thrower's feet against the centre line, with `team_source` recording an
override.

**A pass is a `kind`, and destination is what resolves it.** `fake: boolean` became
`kind: 'fake' | 'pass' | 'throw' | null`, so the three classes are mutually exclusive by
construction rather than by convention, and the born-closed rule generalises to both terminal
kinds. Null is not a fourth class: it is a release whose destination has not been decided —
one still in the air, or one closed after the ball was lost from view. That state is what stops
an unobserved release from being silently counted as a throw, which is the failure the
tri-state exists to prevent. See [[throw-attempt-detection]] § Event definition for the
destination-not-intent rule that decides pass from throw.

Destination is only observable *after* the release, so it is entered as a resolution rather
than chosen when the event opens. `T` opens a release that claims nothing; `H` `C` `B` `M`
say the ball reached the far side and settle `kind` to `throw`; `P` says it stayed on the
thrower's own side. `U` is the one outcome that settles nothing — it asserts that nothing was
observed, so it leaves an undecided event undecided and retracts a pass, which it contradicts.
A pass can be re-resolved as a throw and the reverse, because the ball is often seen to cross a
beat after the annotator has called it; only a fake is inert, having released no ball to send
anywhere. `P` cost the placement-target cycle its key, which moved to `G`.

`target` already meant "the player the ball reached" and is team-agnostic, so a pass's receiver
reuses it — optional, since the receiver is not part of the metric.

## Still open

- Whether `start_frame` is worth labelling for every throw or only a subset, given the candidate
  stage will be evaluated on it.
- Pose chunks are 1000 frames per the contract, which is ~15 MB of JSON at this footage's crowd
  density (roughly forty people in frame). It loads fine from localhost but is heavy to hold in
  memory; if that bites, the contract is the place to change it, not the reader.

## Deliberately not built

- `docs/labeling-guide.md` and the second-pass agreement report — build-order items 7 and 8.
- Non-throw negatives, eliminations and game state: all derived at evaluation time.
