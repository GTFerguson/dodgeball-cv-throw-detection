---
title: Court Geometry
created: 2026-08-25
updated: 2026-08-25
tags: [architecture, geometry, homography, court]
---

# Court Geometry

Everything downstream needs to know where things are on the floor: which detections
are players, which team a thrower belongs to, whether a release was legal, how far
outside the line is still court-adjacent, and how to compare a 280 px near player
with a 150 px far one. This layer answers all of that from a single fit.

| File | Role |
|---|---|
| `scripts/fit_court.py` | Fits the calibration from the clip, writes `data/court/<stem>.json` |
| `src/court.py` | Reads it: transforms, zone tests, team half, scale normalisation, foot points |
| `scripts/render_court_overlay.py` | Draws the fit over a frame, through the same reader |
| `scripts/test_fit_court.py`, `scripts/test_court.py` | Checks over the writer and the reader; the whole suite is `scripts/test_*.py` |

## Challenges, and how the system gets around them

This is the honest core of the design. Each of these is a real property of the
footage, measured rather than assumed, and each is sidestepped rather than solved
head-on.

### Bystanders outnumber players three to one

The pose detector finds **38.0 people per frame** against 12 on court: sideline
queues, benches, referees, coaches, camera operators and a full crowd, all inside
the same frame and many wearing team kit. There are Canada supporters in red in
the stands, so an appearance filter cannot separate them.

*Circumvented by geometry.* Each detection is reduced to a foot point and tested
against the court polygon in court metres. That alone takes **38.0 → 9.7 per
frame, a 74% cut**, and the remainder sits just under the 12 a full set carries —
consistent with a set already carrying eliminations. Roster matching will later
provide a second, independent filter, so the two can disagree informatively rather
than one being trusted blindly.

### A threshold in pixels cannot be right at both ends

The camera is elevated and end-on, so one metre of floor spans roughly **190 px at
the near baseline and 45 px at the far one**. Any distance expressed in pixels —
"within N px of the line", "moved more than N px" — is necessarily wrong at one end
of the court whatever value it is given.

*Circumvented by working in metres.* The homography makes every position and
distance a court measurement. The out-of-play margin is 1.5 m everywhere, which is
a different pixel width at every row and correct at all of them.

### Far players are half the size of near ones

Median detection box height is **286 px in the near four metres and 150 px in the
far four**. A kinematic feature measured in pixels is not comparable between the
two ends, and the far team is exactly where the signal is already weakest.

*Circumvented by the horizon.* The court's cross-lines are image-horizontal, so
their vanishing point lies at infinity and the horizon is the horizontal line
through the sidelines' vanishing point, at **y = −331.4**. For a camera with a
known horizon, a vertical object of fixed height projects to a pixel height
proportional to `foot_y − horizon_y`. Dividing any pixel measurement by that makes
it scale-invariant, and the constant of proportionality — which would need the
camera height — cancels, so it is never needed. Checked against real detections:

| Court position | Detections | Median box height | Predicted |
|---|---|---|---|
| 0–4 m | 3375 | 286 px | 293 px |
| 4–8 m | 566 | 219 px | 227 px |
| 8–10 m | 626 | 152 px | 191 px |
| 10–14 m | 350 | 158 px | 163 px |
| 14–18 m | 4802 | 150 px | 141 px |

Within 2–6% everywhere except the 8–10 m band, which runs 20% short. That band is
the centre line, where players lunge and dive for balls, so the shortfall is a real
posture effect rather than a geometry error — which makes the residual a usable
signal rather than noise.

### The colour cue that finds the court dies at distance

The boundary is bright green tape on a grey floor, which separates trivially near
the camera. It does not survive perspective: green-channel dominance over the other
channels is **~50 at the near baseline and 4 at the far one**, fully desaturated by
lighting falloff and compression and indistinguishable from neutral white. A
colour-only detector finds three sides of the court and silently stops.

*Circumvented by using two cues for two jobs.* The sidelines run the full depth of
the frame and are fitted from colour, where it is strong. The cross-lines — including
both baselines — are found as narrow bright ridges in a brightness profile sampled
between the fitted sidelines, which works at both ends. The split is a consequence
of the measurement, not a preference.

### Players stand on the lines

Any single frame has twelve players on the court and more along its edges,
occluding exactly the markings the fit depends on.

*Circumvented by a median plate.* Players are transient and the floor is not, so a
per-pixel median over **121 frames spread across the clip** removes every person and
leaves the court fully exposed. Nothing downstream of the plate handles occlusion at
all. This is available only because the camera is fixed, and it is the single
property that makes the whole approach cheap.

### The floor carries three sports' markings

Volleyball attack lines, a badminton-height net rigged overhead, and two further
markings at 1.50 m and 16.43 m that match no volleyball feature. A generic
white-line detector has no way to know which rectangle is the court and would
happily fit the wrong one.

*Circumvented twice over.* Colour selects the taped court for the sidelines, and
the held-out check below rejects any fit whose interior structure is not a
regulation court. The two unidentified markings are recorded in the JSON **without
a semantic**, because guessing at one would be worse than admitting it.

### A wrong homography is perfectly self-consistent

This is the quiet failure. A fit with the wrong scale, or fitted to the wrong
rectangle, produces a homography that round-trips exactly, projects a beautiful
grid, and is wrong everywhere. Nothing internal to the fit can detect it.

*Circumvented by holding structure out.* Only the four corners enter the fit. The
interior markings must then land on their real-world positions:

| Marking | True | Fitted | Error |
|---|---|---|---|
| Volleyball attack line | 6 m | 6.061 m | +61 mm |
| Net / centre line | 9 m | 9.091 m | +91 mm |
| Volleyball attack line | 12 m | 12.090 m | +90 mm |

Sub-100 mm across an 18 m court, from evidence the fit never saw. This also
*identifies* the floor: three markings landing on 6/9/12 m is a regulation
volleyball court, **18 × 9 m**, which is where the court dimensions come from
rather than an assumption about what a dodgeball court measures. The fit aborts
if any held-out marking misses by more than 0.25 m, so a different venue fails
loudly instead of producing a plausible calibration that is wrong.

Corroborating this, the two unassigned markings sit at 1.50 m and 16.43 m —
symmetric about the centre to within 70 mm, which nothing in the fit arranged.

### A diving player's box does not touch the floor

Dodgeball players dive and lie prone constantly, and most of all at the centre
line where they lunge for balls. For a prone player the detection box bottom edge
is wherever the torso ends, which can place them metres from where they actually
are — and it lands them on the wrong side of the centre line, which would mean the
wrong team.

*Circumvented by using ankles.* `foot_point()` takes the visible ankle keypoints
and falls back to the box only when neither is confident. The source is returned
with the point, so the fallback rate is reported rather than hidden: on a full
12-player frame it is **zero**.

### Boundary flicker would read as an elimination

The observable that drives outcome resolution is a player crossing the boundary.
Detection noise on a player standing on the line would otherwise produce a stream
of departures and returns.

*Circumvented two ways.* The boundary test carries 0.10 m of slack, and crossings
are read as **transitions rather than membership** — standing still inside the
margin generates no event. This matters concretely: the far-end queue stands within
about 1.5 m of the sideline and therefore sits inside the margin band, so band
membership alone could never have been used as a "recently exited" proxy.

### Team attribution normally needs an appearance model

*Circumvented by the rules.* Teams may not cross the centre line, so the half a
player stands in gives their team directly. `Court.half()` is the whole
implementation. Jersey colour remains available as an independent cross-check
rather than as the mechanism.

### Camera drift would invalidate everything silently

A pan, zoom or knock partway through the clip leaves the calibration pointing at
the wrong floor from that frame on, with no error raised — just slowly wrong
occupancy, wrong crossings, wrong outcomes.

*Circumvented by construction, not yet implemented.* Refitting on segments of the
clip and comparing homographies detects drift **and supplies the correction**,
where a separate static-camera check could only raise a flag. This is why no such
check exists. The fixed camera has not required it so far.

## How the fit works

```mermaid
flowchart LR
    V[Clip] --> P[Median plate<br/>121 sampled frames]
    P --> G[Green mask<br/>sidelines]
    P --> R[Brightness ridges<br/>cross-lines]
    G --> S[Robust sideline fit<br/>0.6 px residual]
    S --> R
    S --> C[Corners]
    R --> C
    C --> H[Homography<br/>4 corners only]
    R --> X[Held-out markings<br/>6 / 9 / 12 m]
    H --> X
    X --> J[court JSON]
```

Each row of the green mask contributes its leftmost and rightmost run as one point
per sideline, fitted by least squares with three rounds of outlier rejection.
Measured residual: **0.6 px standard deviation over ~720 inlying rows** per
sideline. A row only evidences court if it lands on *both* fitted sidelines, so the
span of jointly-inlying rows brackets the court and excludes green in the crowd and
on signage — the baselines are then the outermost ridges within that span plus a
small pad, since a full-width line leaves no left/right runs to separate and so
falls just outside the span itself.

Court coordinates are metres, x across the court and y along it from the near
baseline, so a position is meaningful without knowing which part of the image it
came from.

## Reader

```python
from court import Court, foot_point

court = Court.for_video("wdbf2014_final_h2_set2.mp4")
cx, cy = court.to_court(*foot_point(detection)[:2])
if court.on_court(cx, cy):
    team = court.half(cy)                      # "near" | "far"
    height = court.normalise(box_height, foot_y)   # comparable across the court
```

Transforms accept scalars or arrays. `on_court`, `in_margin`, `half`, `scale_at`
and `normalise` all vectorise, so a whole frame's detections classify in one call.

## Inspection

```
.venv/bin/python scripts/render_court_overlay.py data/footage/<clip>.mp4 --frame 625 --open
.venv/bin/python scripts/render_court_overlay.py data/footage/<clip>.mp4 --plate
```

Renders through the same reader the pipeline uses, so a render that looked right
while the pipeline was wrong would mean the two had diverged. The title bar counts
are the check worth reading — a live set is twelve players, six a side, split on
the centre line, with the box-fallback count at zero.

## Rejected alternatives

**A hand-drawn polygon.** Five minutes and exact, but it yields only a polygon: no
metres, so the margin band would have to be a per-region pixel guess; no scale
model; no way to notice the camera moving; and a committed file of pixel
coordinates a reviewer cannot re-derive or check. The fit produces all four from
one pass.

**Running inference on rectified imagery.** Warping the floor to a rectangle
equalises player scale directly, but a floor-plane homography stretches upright
bodies into shapes no pose model has been trained on. Scale is handled by
normalising features with the horizon relation instead, leaving pixels untouched.

**A separate static-camera probe.** Template-matching background patches would flag
drift but not correct it, and segment refitting gives both.

## Boundaries

- One calibration per clip; segment-wise refitting is designed for but not built.
- Geometry places the floor, not people. Deciding *who* is a player — as against a
  referee standing inside the lines — is left to roster matching, which fails them
  by construction.
- The dodgeball out-of-bounds is asserted to be the 18 m court boundary rather than
  the 1.50 m inset marking, on the evidence that players routinely stand between
  the two. Worth reconfirming from the foot-position distribution over the full
  pose run.

## On-disk contract

`data/court/<video-stem>.json`, `schema_version` 1. Committed; the plate and frame
renders beside it are footage-derived and are not.

| Field | Meaning |
|---|---|
| `clip_sha256` | The clip this belongs to; a mismatch means it is stale |
| `image_to_court` / `court_to_image` | 3×3 homographies, court units metres |
| `court_metres` | Width and length, asserted by the held-out check |
| `centre_line_m` | The line teams may not cross |
| `margin_m` | Court-adjacent band width |
| `horizon_y` | Image row of the horizon, for the scale model |
| `corners_image` | Fitted corners, near-left first, clockwise |
| `cross_lines` | Every detected marking, in image rows and court metres |
| `held_out_error_m` | Validation residuals, so a consumer can judge the fit |
