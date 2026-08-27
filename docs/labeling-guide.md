---
title: Labelling Guide — Dodgeball Throw Attempts
created: 2026-08-27
updated: 2026-08-27
tags: [labelling, ground-truth, dodgeball]
---

# Labelling Guide — Dodgeball Throw Attempts

The rule for labelling throw attempts in fixed-camera dodgeball footage. It is written to
be handed to someone who has not seen the rest of this repository: everything needed to
label a clip consistently is here.

Read it once through before labelling anything. The decision procedure is short; the
ambiguous cases are the part that matters.

---

## 1. What you are labelling

A **throw attempt** is a player propelling a ball toward the opposing side with a throwing
motion.

Every throwing motion you label is a **candidate**, and every candidate resolves to exactly
one of three kinds:

```
candidate — a throwing motion by a player in play (ball in hand or not)
├── fake   — the ball never left the hand
├── pass   — the ball left the hand and stayed on the thrower's own side
└── throw  — the ball left the hand and crossed to the opposing side
    └── outcome: hit | catch | block | miss
```

The three kinds are mutually exclusive. A candidate is never two of them, and never none
of them unless you could not see enough to decide — in which case see §7.

> [!IMPORTANT]
> **The one rule that decides everything: destination, not intent.**
>
> You are never asked what the thrower meant. You are asked where the ball went. An errant
> pass that crosses the centre line and hits an opponent **is a throw with a hit**, because
> a live ball eliminates whoever it reaches regardless of intention. A hard throw that a
> teammate intercepts on the thrower's own side **is a pass**.
>
> This follows the ruleset: "passing throws and plays are not deemed invalid throws, if the
> ball does not cross into the opponent team's fair territory" (WDBF 2024, 16.2). It is also
> the only workable rule, because destination is visible and intent never is.

---

## 2. The decision procedure

Work through this in order for every throwing motion you see.

1. **Is it a throwing motion by a player in play?**
   If no — see §5, *What is not a candidate* — do not label it.
2. **Did the ball leave the hand?**
   No → `fake`. Stop; a fake has no outcome and no target.
   Yes → continue.
3. **Did the ball cross the centre line into the opponents' half?**
   No → `pass`. Stop; a pass has no outcome. Record the receiver as the target if a
   teammate caught it, but this is optional.
   Yes → `throw`. Continue.
4. **What settled the ball?** → the outcome, §4.

A candidate with **no ball in hand at all** is still a candidate: an empty-handed wind-up is
a move made to draw the opponent, and it is the same motion on screen. Label it `fake` and
note that there was no ball. These are rare and are reported separately, because a detector
that looks for the ball has nothing to find.

---

## 3. The three frames

Each event carries up to three frames. Only the **release frame** is required, and it is the
one everything is scored against — spend your time there.

| Frame | Definition | Notes |
|---|---|---|
| `start` | The first frame in which the throwing arm moves **behind the shoulder line** | The wind-up onset. Optional. Soft by nature; do not agonise |
| `release` | The **first frame in which the ball is no longer in contact with the hand** | Required. Step frame by frame; this is the anchor for the temporal tolerance |
| `end` | The first contact that **settles the ball** — an opponent, a catch, a block, the floor, or the far boundary | Optional. A pass ends the same way on its own side: the receiver's catch, or the floor if nobody catches it |

For a `fake`, place the release frame at the peak of the wind-up — the frame the motion turns
around. There is no `end`.

**Finding the release frame.** Play at speed to spot the motion, then step backwards frame by
frame from the ball clearly in flight until the ball is touching the hand. The release frame is
the *next* one forward. If the hand is occluded at that moment, see §7.

---

## 4. Outcomes

An outcome is required on every `throw` and is what closes the event.

| Outcome | Test |
|---|---|
| `hit` | The ball contacts an opposing player while live (before it touches the floor or a wall), and is not caught |
| `catch` | An opposing player takes the ball cleanly out of the air and retains it |
| `block` | An opposing player deflects the ball with a held ball. The ball stays live; nobody is eliminated |
| `miss` | The ball reaches nobody — dodged, or unobstructed to the floor, wall or out of the court |
| `unresolved` | You could not see what happened. Occluded, off-frame, or lost in traffic |

**`catch` versus `block`.** The difference is retention, not contact. If the defender ends up
holding the ball, it is a catch. If the ball carries on, it is a block. When you cannot tell,
the count is the tie-break: a catch eliminates the thrower and returns one of the catching
side's players to the court, so *the number of players on court changes*. A block changes
nothing. If nobody leaves and nobody returns, it was a block. (This test caught a real
mislabel on the evaluation clip.)

**`hit` on a player who is already out.** It happens — a live ball reaches somebody standing
in the out zone or walking off. Label the outcome `hit` and set `eliminated: false`. Only a
live player can be put out (WDBF 2024, 19.1), so it is a ball event and not an elimination,
and the metric must not count it.

**A hit is a hit whoever it eliminates.** If a throw deflects off one opponent onto another,
label the player the ball reached **first**.

---

## 5. What is not a candidate

Do not label these at all. They are not throwing motions.

- **Underarm rolls and lobs to retrieve or reposition a ball.** No throwing motion.
- **Hand-offs.** A ball passed to a teammate without a throwing motion — handed, tossed at
  arm's length, or dropped into their hands.
- **Anything after the play is dead.** Once the whistle has gone, nothing counts.
- **Pickups and dives.** A ball near a hand and an arm moving is not a wind-up.
- **Anybody who is not a player in play.** Officials, benched players, anyone in the out zone.

> [!NOTE]
> A hand-over that *does* have a throwing motion is a `pass`, not a hand-off. The boundary is
> genuinely blurry and one such case on the evaluation clip is flagged `uncertain` — which is
> the correct thing to do with it.

---

## 6. Who gets credit

| Field | Who | On which frame |
|---|---|---|
| `thrower` | The player who released the ball | The **release** frame |
| `target` | The player the ball reached | The **end** frame |

Thrower and target are marked on **different frames** — this is deliberate and the tool
supports it. Do not mark the target on the release frame.

**Required:** the thrower on every event, and the target on every `hit`, `catch` and `block`.
The target is required because a catch eliminates the *thrower* and returns a player to the
*catcher's* side, while a hit eliminates the *target* — the two move the game state in
opposite directions and cannot be told apart without knowing who.

**Team** is inferred from which half of the court the thrower's box lands in. The camera is
fixed and sides do not change within a half, so this is reliable; override it on the rare
occasion it is wrong (a player who has run past the centre line to retrieve a ball).

**A player is recorded as a box, never as a track ID or a name.** Pressing a player key
copies that skeleton's box into the label; from that moment it is a human-accepted box that
references nothing. If the snapped box is loose or straddles two players, adjust it or draw
your own — once you accept it, it is yours. This is what lets the truth set survive a change
of detector.

---

## 7. Ambiguous cases

These are the cases the truth set is genuinely uncertain about. Each has a required action
**and** a flag. Flagging is not an admission of failure — it is the data that separates label
uncertainty from model error later, and an unflagged guess is worse than a flagged one.

| Situation | What to do | What to flag |
|---|---|---|
| The release is hidden — a teammate crosses, or the thrower turns away | Label the **last visible frame with the ball in hand** as the release | `release_visible: false` |
| A graze: the ball deflects with no visible reaction from the player | Label `hit`, and use the referee's call if you can see or hear one | `uncertain`, plus `ref_signal` |
| You cannot tell a catch from a drop, or a block from a catch | Apply the count test in §4. If it still will not resolve, pick one | `uncertain` + a note saying which two |
| The ball is lost in traffic and you never see it settle | Outcome `unresolved` | `outcome_visible: false` |
| A release you saw, whose destination you never saw | Leave the **kind** unset. Do **not** guess pass or throw | `uncertain` + note |
| Two or more balls cross in flight and you lose which is which | Attribute each event **by its thrower**, never by following the ball | `uncertain` if you are unsure |
| Simultaneous releases (a coordinated attack) | One event per thrower. Use `Tab` to cycle the open throws when the outcomes arrive | — |

**A release whose destination was never observed carries no kind at all.** This is the single
most important instruction in this section. It is an absent claim, not a fourth category, and
it is reported separately. Defaulting it to `throw` inflates the metric's denominator;
defaulting it to `pass` deflates it. Leave it empty.

---

## 8. The flags, and what each is for

| Flag | Set it when | Why it exists |
|---|---|---|
| `release_visible` | **false** when the moment of release was occluded or off-frame | Separates "the model missed it" from "nobody could have seen it" |
| `outcome_visible` | **false** when you could not see what settled the ball | Same, for the outcome level |
| `ref_signal` | `seen` / `not seen` / `not visible` | The closest thing to external truth on a contested hit. A referee calling a player out is independent evidence |
| `uncertain` | Whenever you would not defend this label to a second annotator | Every `uncertain` event is re-decided the other way in the error budget, so this flag directly sets the label-uncertainty band |
| `note` | Freely, and often | Write what you actually saw and what you were torn between. Notes on the evaluation clip turned out to matter more than the flags |

> [!TIP]
> Write a note whenever you hesitate, even if you do not set `uncertain`. Two of the most
> consequential label problems on the evaluation clip were found in notes on events that were
> not flagged.

---

## 9. Set boundaries

Live play runs from the **opening rush** (both teams break from their baselines for the balls
on the centre line) to the **set end** (one side has been completely eliminated).

Throws outside live play do not count and the metric is computed per set, so the boundaries
must be right.

The tool shows detected set starts as proposals on the `MODEL` track. **Check the frame it
proposes rather than hunting for the rush**: `Shift+A` accepts one, `Shift+R` records it as
wrong. A start the detector missed is marked by hand with `L`.

---

## 10. Working from proposals

The clip arrives with proposed throwing motions drawn as rings on the `MODEL` track. Working
through them is far faster than scrubbing, and the proposer is deliberately loose — it offers
roughly 100 proposals for 60 real events, because a missed motion is unrecoverable and a
rejection costs one keypress.

- `>` and `<` walk to the next and previous **unreviewed** proposal.
- `Shift+A` accepts the nearest proposal, which becomes an ordinary event you then classify.
- `Shift+R` rejects it, with a reason.

**Reject generously.** Most rejections are sprints, dodges, pickups and pose glitches. A
rejection is data too — it records that a human looked and said no.

**Do not label only from proposals.** Scrub the clip independently at least once and mark
anything the proposer missed. If you only ever accept or reject, recall is guaranteed by
construction and the evaluation cannot measure it.

---

## 11. Keys

| Key | Effect |
|---|---|
| `T` | Open a throw at the current frame. With an event selected, move its release here |
| `F` | Mark a fake at the current frame — terminal, no outcome |
| `S` / `E` | Set the start and end frames of the selected event (optional) |
| `H` `C` `B` `M` `U` | Close the selected open throw: hit, catch, block, miss, unresolved |
| `1`–`6` | Snap a near-team player's box (ordered left to right on this frame) |
| `Q`–`Y` | Snap a far-team player's box (ordered left to right on this frame) |
| `Tab` | Cycle the open throws, for coordinated attacks with two or three balls in the air |
| `Shift+A` / `Shift+R` | Accept / reject the nearest proposal (throws and set starts) |
| `>` / `<` | Walk to the next / previous unreviewed proposal |
| `L` | Mark a live-play start by hand |
| Arrow keys | Nudge the selected box 1 px; hold shift for 10 px |
| Drag | Corner resizes, inside moves, empty space draws a new box |
| Hold shift | Magnifier — use it for far-court boxes, which cannot be judged honestly at 1× |

Player keys are recomputed every frame from left-to-right position and carry **no identity**.
Two players crossing will swap keys. This does not matter: the label stores the box, not the
key.

---

## 12. Before you call a clip done

Two checks, both cheap, both of which have caught real mistakes.

**Fold the game state forward.** Starting from six players a side, apply each event in order:
a hit removes one from the side struck; a catch removes the thrower and returns one to the
catcher's side; a miss and a block change nothing. Then check:

- No side ever goes below 0 or above 6.
- No player throws after they were eliminated.
- A catch never returns a player to a side that is already full.
- The count reaches zero on exactly one side, at the set end.

A violation locates a bad label without needing a second annotator.

**Compare against the floor.** Count the players actually standing on court at a few moments
through the set and check the fold agrees. Where it does not, one of the events between those
moments is wrong.

---

## 13. What is deliberately not labelled

- **Non-throw negatives** — hand-offs, pickups, retrieval rolls. Too expensive to label
  exhaustively. Every false positive is given a cause category during analysis instead.
- **Eliminations.** They follow from the outcome and the target; labelling them separately
  would create a second source of truth that could disagree with the first.

---

## 14. Reference

- **The ruleset:** World Dodgeball Federation, *Rules of Dodgeball* (2024). The rules that
  matter here are 15.2 (a throw must leave the hand), 16.2 (a pass is a throw that did not
  cross), 19.1 (only a live player can be put out) and 10.2.1 (a set is won by eliminating
  every opposing player).
- **Why the event is defined this way:** [design.tex](design.tex) §1, and
  [plans/throw-attempt-detection.md](plans/throw-attempt-detection.md).
- **The tool:** `tools/labeler/`.
