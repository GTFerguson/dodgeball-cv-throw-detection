---
title: Destination
created: 2026-08-26
updated: 2026-08-27
tags: [architecture, event-detection, ball, pass]
---

# Destination

Pass or throw: the third decision of the cascade, made on where the ball
went after it left the hand — the player it reached where it reached one,
its first direction otherwise. Lives in `src/release.py` beside the release
gate, because both are readings of the same departure chain;
`scripts/detect_events.py` writes it as `kind` on the timeline, with which
witness decided and whether the other agreed.

Upstream: [[release-gate]] for the chain, [[roster]] for which side the
thrower is on. Downstream: [[evaluation]] scores `kind`.

## What the rules say

A pass is a throw that did not cross: "passing throws and plays are not
deemed invalid throws, if the ball does not cross into the opponent team's
fair territory" (WDBF 2024, 16.2 — [[wdbf-rules]]). Destination, not intent.
A pass leaves no trace in game state, so it has no cross-check: the metric's
denominator is throws only, and every pass read as a throw understates
efficiency.

## Two witnesses

**Contact.** The chain is followed to where it stops — traces run to
`TRACE_AFTER` frames and chains to `CHAIN_MAX_LINKS` links, enough to reach
every labelled outcome on the clip, which all settle within 21 frames of
release. If its last point falls inside a player's box on that frame
(grown by `CONTACT_BOX_MARGIN`; the thrower's own box excluded), the ball
reached that player: a teammate is a pass, an opponent a throw. This is
the rule's own test — did the ball cross to the other side — asked of the
one thing in the image that needs no projection, a person's box. On the
clip fifteen of the twenty-six chained releases end in a box: three passes
in a teammate's, twelve throws in an opponent's, none the other way round.

**Direction.** Where the chain ends in nobody — the floor, out of frame,
or lost — the ball's first direction speaks instead. The floor homography cannot say where a ball in the air is: at shoulder
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
Either witness is trusted only over a chain of at least `DIRECTION_LINKS`;
a two-link chain's heading is one hop's jitter and misread two throws
before the rule.

**Contact decides where it exists, direction otherwise.** Where both
speak they agreed on every one of the fifteen contacts on the clip, which
is the confidence the plan asked for reported as data: the timeline
carries `destination_source` (`contact`, `direction` or `default`) and
`destination_agreed` on every release.

## What it scores

On the clip, kind on the 56 matched events: **86%** — fakes 21 of 23,
passes 5 of 6, throws 22 of 27. Four of the five throw errors are the
release gate's misses carried down (a throw called a fake has nowhere to
go); the one misread is a chain that seeded on a different ball crossing
the wrist and ended in a teammate's box. The fake read as a pass is the
release gate's faint tier stepping onto a ball flying past a held one
([[release-gate]]); its direction, away from the opponent, is what keeps
it from being a throw. The one pass error has no chain
at all — the annotator's "literally hands it over". Direction alone had
scored 82%: the contact witness recovered a two-ball lob whose direction
was diagonal but whose chain, followed further, ends in the teammate's
box.

## Boundaries

- Six labelled passes, two of them doubtful by the annotator's own notes.
  The angle bar is where the data says, not where it is proven.
- A contact is a box, not a touch: a ball passing through a player's box
  without touching them reads as reaching them. The chain's kink at a
  real contact is the finer test, and is the outcome stage's.
- A pass that crosses after a bounce, or a throw that falls short, is
  read by where the chain ends only if the chain gets there; a chain lost
  early falls to direction, which cannot see either.
- No team, no direction: a thrower the roster cannot side is a throw by
  default, and the timeline says so with a null angle.
