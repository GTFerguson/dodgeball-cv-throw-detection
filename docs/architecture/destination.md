---
title: Destination
created: 2026-08-26
updated: 2026-08-26
tags: [architecture, event-detection, ball, pass]
---

# Destination

Pass or throw: the third decision of the cascade, made on the ball's first
direction after it leaves the hand. Lives in `src/release.py` beside the
release gate, because it is one more reading of the same departure chain;
`scripts/detect_events.py` writes it as `kind` on the timeline.

Upstream: [[release-gate]] for the chain, [[roster]] for which side the
thrower is on. Downstream: [[evaluation]] scores `kind`.

## What the rules say

A pass is a throw that did not cross: "passing throws and plays are not
deemed invalid throws, if the ball does not cross into the opponent team's
fair territory" (WDBF 2024, 16.2 — [[wdbf-rules]]). Destination, not intent.
A pass leaves no trace in game state, so it has no cross-check: the metric's
denominator is throws only, and every pass read as a throw understates
efficiency.

## Why direction, and why in the image

Where the ball *ends* is the right evidence and is the outcome resolver's
to find. At release the only evidence is where it is going.

The floor homography cannot say where a ball in the air is: at shoulder
height it projects metres beyond the hand, and near-team throwers "stand"
at court y 11–15 m by their ball. Its *direction* in the image is sound,
though, because this camera looks along the court: the opponent is straight
up the frame for the near team and straight down for the far, and a pass to
a teammate goes across. The angle between the chain's first
`DIRECTION_LINKS` links and that axis is the feature — the first links,
because the chain's end is contaminated by whatever the ball bounced off.

On the clip's matched releases every labelled pass is at 81° or beyond
(sideways or back) and most throws under 70°. The band between is
perspective: depth is foreshortened, so a diagonal cross-court throw sits
in the high seventies. `PASS_MIN_ANGLE_DEG` is set where every pass clears
it, and a throw is the default — the choice that protects the denominator.
A pass is only claimed on a direction measured over the full
`DIRECTION_LINKS`; a two-link chain's heading is one hop's jitter and
misread two throws before the rule.

## What it scores

On the clip, kind on the 56 matched events: **82%** — fakes 22 of 23,
passes 4 of 6, throws 20 of 27. Six of the seven throw errors are the
release gate's misses carried down (a throw called a fake has no direction
to read); the one direction misread is a chain that seeded on a different
ball crossing the wrist, admitted by a first hop across a bridged frame.
The two pass errors: one pass with no chain at all (the annotator's
"literally hands it over"), and one at 76° — a pass diagonal enough to
look like a cross-court throw.

## Boundaries

- Six labelled passes, two of them doubtful by the annotator's own notes.
  The angle bar is where the data says, not where it is proven.
- Direction at release cannot see a pass that turns into a throw by
  crossing (a live ball counts wherever it was meant), nor a throw that
  falls short. Both are the outcome stage's, from where the ball ends.
- No team, no direction: a thrower the roster cannot side is a throw by
  default, and the timeline says so with a null angle.
