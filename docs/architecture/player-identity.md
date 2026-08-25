---
title: Player Identity
created: 2026-08-25
updated: 2026-08-25
tags: [architecture, tracking, reid, jersey-ocr]
---

# Player Identity

Attribution needs to say *which* player threw, not only which team. That is two
different problems wearing one name, and they are solved by different means.

| File | Role |
|---|---|
| `src/tracking.py` | Follows players between frames with ByteTrack, driven from the pose run |
| `src/jersey.py` | Reads and confirms the number on a track |
| `scripts/identify_players.py` | Runs both over a clip, writes `data/players/<stem>.json` |
| `scripts/test_jersey.py` | Checks on the confirmation rules |

## Two problems, not one

**Short horizon.** Following a player from frame to frame is easy: they move a
third of a metre at a sprint and the court coordinates say who is who.

**Long horizon.** Saying that the player at the far baseline now is the one who
was at the near baseline a minute ago is not, and no amount of motion association
answers it. Only the jersey number does.

The first version here conflated them, and solved the first badly: greedy
nearest-neighbour on the foot point, with no memory. A player occluded behind a
team-mate in a centre-line scrum came out the other side as a new track, so a
number read before the collision did not carry across it.

## Tracking is not a thing to hand-roll

ByteTrack does the two things greedy matching cannot. It predicts where a track
should be with a Kalman filter, so a gap is bridged by motion rather than by
proximity; and it runs a second association pass over the *low-confidence*
detections a partly-occluded player produces, which is the exact frame where the
naive matcher gave up.

It is driven from the precomputed pose run rather than from a live model, so
tracking costs no inference - the detections the labelling tool draws are the ones
tracked. Off-court detections are dropped *before* tracking: the pose run sees the
whole hall, and a bench that is never tracked costs nothing downstream, where a
bench that is tracked competes for association with the players in front of it.

The difference on the evaluation clip's first 2067 frames:

| | Greedy nearest-neighbour | ByteTrack |
|---|---|---|
| Median track length | 40 frames (1.6 s) | 223 frames (8.9 s) |
| Concurrent tracks | 34.8 | 19.7 |
| Tracks spanning >50% of the window | — | 12 |

Twelve tracks covering more than half the window, nine of them unbroken across all
2067 frames, is the twelve players - held without reading a single number.

> [!WARNING]
> That is evidence of one-track-per-player, not proof. There is no identity ground
> truth for this clip, and prior work on football footage found ByteTrack switches
> identity mid-track during melees. A track is not a pure atom.

## The number is read where it is easy

A digit is 34 px tall at the near baseline and 13 px at the far one, so reading is
easy at one end of the court and marginal at the other. The trick is not a better
reader: it is that a track spanning a set contains *both* ends. So the question is
never "what number is this player showing now" but "what is the largest view of
this player anywhere in their track".

Only a track's tallest crops are read - `CROPS_PER_TRACK` of them, above
`MIN_CROP_HEIGHT` - and the rest are not attempted. The legs are cropped away
first: they carry no print and they cost magnified pixels.

The crop comes from the detection box rather than the pose keypoints, because a
box is always present where a shoulder keypoint drops out exactly when a player
turns, which is also when the number comes into view.

### The reader is configured for cloth, not paper

EasyOCR's CRAFT detector finds almost nothing on a jersey at its defaults. The
configuration in `OCR_PARAMS` - digits-only allowlist, `mag_ratio` doubled, and
all three detection thresholds dropped well below default - is carried over from
prior work on football footage, where it was tuned for exactly this: large bold
print on moving cloth.

### Confirmation is agreement, not confidence

The reader is confident about folds. What it cannot do is return the same wrong
number from several independent crops of one track, so a number is confirmed by a
majority across a track's crops and by nothing else.

Two-digit readings are weighted above one-digit ones, because the reader's
commonest failure is losing a digit rather than inventing one. Both errors on the
evaluation clip were that shape: a jersey reading **18** returned `1` five times
and `18` three, and a **10** returned `6`. An unweighted majority handed both
tracks to the fragment. The weighting cannot simply prefer the longer reading
either - a **7** returns `77` sometimes - which is why it is a weight and not a
rule.

Where the weighted majority is not clear enough, the track keeps **no** number.
An unnamed track costs one join by hand; a wrongly named one silently merges two
players and poisons every event attributed to either.

## Numbers veto, they do not name

Coverage is low by design and low in fact: 5 confirmed numbers across 85 tracks on
the evaluation window, all five verified correct by eye. Prior football work saw
8% at fragment level and found it sufficient, because the value is in *forbidding*
joins rather than proposing them - the groups being merged wrongly are large, so
almost any confirmed number inside one catches the mistake. `conflicts()` is that
test.

An absent number vetoes nothing. Most tracks carry none, and if absence forbade a
join the veto would forbid every join rather than the wrong ones.

## What does not work here, and why it was not built

- **Faces.** Around 13 px tall at the far baseline. No identity at that size.
  Prior work reached the same conclusion independently on football footage.
- **Appearance embeddings.** Each team wears one kit. OSNet separated same-kit
  players by 0.088 in prior work, which is not a separation at all, and merging on
  it is what mixed identities there.
- **A hand-trained digit classifier.** Segment-then-classify was built here first
  and abandoned: threshold, connected components, line grouping and a per-digit
  CNN are four stages that each drop a digit independently, so two-digit numbers
  degraded to one. Reading the whole crop sidesteps all four.

## Holding a player in play

Tracks are what let the boundary test have a memory. `held_in_play` counts a
player as in play if their track was on court anywhere within
`IN_PLAY_HOLD_FRAMES` either side of the frame, which is what stops a baseline
player's constant crossings reading as a stream of exits and returns. The window
and the reasoning are in [[court-geometry#Stepping out for a moment is not leaving the game]];
this layer only supplies the identity it needs.

## Boundaries

Track identity is not evaluated - there is no labelled ground truth for who is
who in this clip, so the twelve-track result is a sanity check rather than a
score. Numbers are confirmed per track and are not yet carried across tracks: the
veto exists and nothing consumes it, because no stage merges tracks yet.
