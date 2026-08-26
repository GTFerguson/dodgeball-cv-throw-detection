---
title: Player Identity
created: 2026-08-25
updated: 2026-08-26
tags: [architecture, tracking, reid, jersey-ocr]
---

# Player Identity

Attribution needs to say *which* player threw, not only which team. That is two
different problems wearing one name, and they are solved by different means.

| File | Role |
|---|---|
| `src/tracking.py` | Follows players between frames with ByteTrack, driven from the pose run |
| `src/jersey.py` | Reads and confirms the number on a track |
| `src/players.py` | Joins the tracks that wore one number on one side into a player |
| `src/roster.py` | Role and side per track, and the file all of this is written to - see [[roster]] |
| `scripts/identify_players.py` | Runs all of it over a clip, writes `data/roster/<stem>.json` and, with `--sheet`, the contact sheet |
| `scripts/test_jersey.py` | Checks on the confirmation and switch rules |
| `scripts/test_tracking.py` | Checks on the tracker gate and on cutting a track where it changed player |
| `scripts/test_players.py` | Checks on joining fragments by number and the same-time veto |

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

That gate is temporal, not frame-by-frame. A jump lifts the ankles, and at the far
end of an end-on view a few dozen pixels of lift is metres of court: number 55
throwing from the far baseline at frame 4001 rose seventy pixels, which projected
three metres past the baseline, outside the margin. Read one frame at a time,
every airborne frame was a person standing behind the court, dropped before the
tracker saw it - so the throw belonged to no track, and the labelling tool, which
takes who is in play from the roster, showed the thrower as a bystander for the
length of the jump. Widening the margin does not fix it: a jump's worth of margin
at the far end admits about one standing spectator per frame on the evaluation
clip, which is what the gate exists to keep out. Instead `admit` carries a chain:
a detection past the margin is admitted while it continues, by box overlap
(`CONTINUITY_MIN_IOU`), a detection that stood in play within
`AIRBORNE_HOLD_FRAMES`; it inherits the chain's age rather than resetting it, so a
spectator who once overlapped a player is carried for the hold and then let go,
and a chain survives a frame the detector missed. The crowd behind the baseline
never stood in play, so it never starts a chain.

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

A track's tallest crops are read - `CROPS_PER_TRACK` of them, above
`MIN_CROP_HEIGHT` - and so is the tallest crop of every `READ_BIN_FRAMES` stretch
of its life. The first name the track; the second are what let a change of
player show up as a change of number (below), which the tallest crops alone never
would, because they all come from wherever the player stood nearest the camera.
The legs are cropped away first: they carry no print and they cost magnified
pixels.

A crop whose box overlaps another player's by more than `MAX_CROP_OVERLAP` is
not read at all. It holds two backs, and the reader returns whichever number is
clearer: KUTNER's track was named 7 on two crops that had CHALMERS in them.

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
rule. And a lost digit is not a dissenting vote: `1` beside `18` fits an 18, so
it neither supports nor opposes, and the majority is taken over readings that
do. Reading the far court adds many such fragments, and counting them against
the whole cost CERVUDO's name the moment his far-court crops were read.

Agreement needs `MIN_CONFIRMATIONS` readings - three. It was two when a track
offered ten readings; across twenty or thirty a pair agreeing by chance stops
being rare, and a white **55** was named `65` on exactly such a pair.

Agreement has to come from independent views, and independent means apart in
time. Four crops within a second show the same pose at the same distance, and a
fold that reads as a `6` reads as a `6` in every one of them - that is one view
counted four times, and it is how a referee's stripes got named `6` on the full
clip. The readings that agree must span `MIN_AGREEMENT_SPAN` frames (four
seconds), long enough for the player to have moved. It costs names on tracks that
visit the near baseline only briefly, which is the right side to be wrong on.

A single digit is also declined when it is a fragment of a two-digit reading on
the same track: `4` five times beside `40` once fits a 40 that lost its 0 as well
as it fits a 4, so neither is claimed. A doubled digit (`77` from a 7) is the
reader repeating rather than dropping, and does not make the 7 ambiguous.

Where any of that is not satisfied, the track keeps **no** number. An unnamed
track costs one join by hand; a wrongly named one silently merges two players
and poisons every event attributed to either.

### Only players in play are read

Tracking admits the margin band around the court, because a player on the
baseline is often in it. But the band is also where the officials stand, the
eliminated wait and both teams crowd before the rush, and a referee's stripes
read as a digit as readily as a jersey does - three officials were named on the
full clip. Crops are taken only on frames where `held_in_play` says the player is
playing, and the roster records those frames as `in_play` intervals per track.
Nothing off court needs a name: attribution only ever asks about a player in
play.

This gate is what keeps officials out of the *reader*; it is not what decides
who is an official. That is the roster's rule - in play inside the live core of
a set is a player, whatever the kit, and kit decides only for tracks never seen
there ([[roster#How role is decided]]) - and the sheet lists only tracks the
roster calls players.

### A reading carries its frame

Every reading records the frame it was taken from, and the roster keeps them
on the track in time order. Without that, a track whose readings split cannot be told
apart from two players stitched together, because the two look the same as a
count and different only in time: a reader dropping a digit *interleaves*
(`6 6 1 10 1 6 6 1`), a tracker switching players *switches* (`44 44 19 19 19`).

The contact sheet is built for that comparison. It shows every named track beside
the crops that named it, and every unnamed track longer than `REVIEW_FRACTION` of
the clip beside its crops - the long silences are where the question lives, and
a sheet that showed only the confirmed tracks showed only the ones already
trusted. Crops run in frame order and each is captioned with what the reader made
of it.

### A track can change player, and the number is what shows it

Two numbers each confirmed in disjoint stretches of one track is the tracker
having changed player mid-life. `switch()` looks for a cut of the readings into
a prefix and a suffix that confirm, by the same rules as a whole track, to
different numbers - and refuses it if either number recurs on the other side,
because that is the reader disagreeing with itself about one man: DICARLO 10
reads `6` whenever the 0 is on a fold, and the 6s go on after the first clean
`10`. A change of player needs only `SWITCH_MIN_CONFIRMATIONS` agreeing readings
rather than three, because the costs are not symmetric: cutting a track that did
not change makes a fragment, which its number joins back; leaving one that did
change keeps the wrong man under a name.

The track is cut (`Track.split`) at the widest gap in its detections between the
last reading of the first number and the first reading of the second
(`cut_frame`), because the change happened while the player was hidden; a track
with no gap there is cut where the new player was first read. Each half is then
named on its own readings, and the roster records `split_from` on the tail.
Track 54 on the evaluation clip reads `18` to frame 2305 and `7` from 2891,
has a nineteen-frame gap at 2862-2881, and is cut at 2881 - the frame the swap
completed.

A half that does not confirm again at the full bar keeps the number the switch
found for it. The switch already established, on `SWITCH_MIN_CONFIRMATIONS`
agreeing readings four seconds apart with nothing interleaved, that the half is
one player wearing that number; asking the same readings to clear the higher
bar a second time left the tail of 54 - CHALMERS for 800 frames - unnamed, and
so unjoined to the rest of him.

### What the sheet showed on the full clip

The five-for-five result above was measured on the first 2067 frames of the set,
which is the clean part. Over the whole 5249-frame clip the same rule confirmed
29 tracks, and checking them by eye against the sheet found **17 right, 11 wrong
and 1 unclear**. Recorded here because it decides what to fix, not as a score.

| Failure | Tracks | Shape |
|---|---|---|
| Dropped digit named the fragment | 253 (18→1), 189 (23→3), 268 and 400 (40→4), 351 (19→1) | The full number never appeared often enough for the weighting to save it; on 253 the reader returned `1` and `8` as *separate* readings of one crop |
| A referee named | 212 (→2), 406 (→6), 379 (→5) | The stripe pattern reads as a digit, and refs are tracked as players all set long: tracks 8 and 122 are officials held for 4770 and 3348 frames |
| Two people stitched together | 418 (44 then 19), 382 (a blur then 44, named 6), 16, 379 (ref then 55) | All born in the dead-ball crowd at the centre line - frames 0–170 and 4700–5100 - none during live play |

Every long unnamed track was one player: 2 is #44, 82 is #10, 17 is USA #27 and
73 is USA #55. The tracker held them; the reader could not name them, and on the
white USA kit it barely read at all - 27 and 55 got one reading between them
across twenty clean crops.

So the two suspects were both guilty, in different places. Most merges are born
in the scrum between sets, and the vote was too cheap to satisfy on a short
track, where two noisy readings were enough to name it.

Not all of them, though. Track 54 is CERVUDO 18 from frame 121 and CHALMERS 7
from about 2880 to its end at 3671, and it was named 18 because every one of its
tallest crops came from the first half. The switch is an occlusion swap in live
play: the two stood a metre apart, 54 lost its detection for nineteen frames
(2862-2881) while CHALMERS crouched behind CERVUDO, and when the Kalman
prediction re-found a box it took the wrong man. CHALMERS' own track 56 starved
and died at 2905; CERVUDO got a new one. Nothing in the file could show this,
because the shortlist is chosen by height alone and never sampled the second
half - the readings agreed with each other and were still wrong about a third of
the track. A shortlist spread over the track's life would have read `7` after
2880, and two numbers each confirmed in disjoint stretches of one track is a
switch by definition. That is what the spread shortlist and `switch()` are.

With everything above in place the same clip names **12 tracks, all 12 right by
eye**, for seven distinct players (#2, #6, #7, #10, #13, #18, #44 - the
duplicates are one player's track breaking in the huddle), and cuts track 54 at
2881. Every scrum-born merge and every official is out of the named set because
none was ever in play long enough to agree with itself four seconds apart. The
three long tracks left unnamed - 17 (USA 27), 73 (USA 55), 82 (DICARLO 10) - are
each one player. The sheet in `output/jersey_sheet.png` is regenerated by
`--sheet` and is the check to rerun after any change.

## Fragments are joined by their number

A track is not a player. The tracker loses a player in the huddle between sets
and gives them a fresh id on the other side, so a player on court for a whole
set is two or three tracks, and attribution that named the thrower by track
would count one player as three. `src/players.py` joins them: tracks that
confirm to the same number on the same side are one player, and nothing has to
be read across the gap, because each fragment is named on its own crops.

The key is the side and the number together, not the number alone. Numbers are
per team, and the first pass at this joined by number only because every
readable number on the clip looked like one team's - until a chest-colour
measurement showed #13 and #2 are USA. The side comes from the roster, which
takes it from the half of the court the track played in while in play
([[roster#How team is decided]]); a named track is always in play, because
only in-play crops are read, so every named track has one.

Time is the last check. Two tracks with one key *in the same frames* are two
people the side could not tell apart, or a misread, which is the same thing to
a join. Prior football work reached the same shape from the other side: the
value of a number there was in forbidding merges rather than proposing them,
and 8% coverage was enough because the wrongly merged groups were large.

Two tracks of one player can overlap briefly. When a swap is cut, the player's
own starved track lingers on stray detections for a moment after the other
track has taken his body - 56 and 422 on the evaluation clip share 24 frames.
`JOIN_MAX_OVERLAP` allows two seconds of that; two players sharing a number
overlap for as long as they are both in play, which is hundreds of frames.

When a number does clash with itself, none of its tracks are joined, not just
the two that overlap: a third fragment that overlaps neither could belong to
either of them, and the number cannot say which. `clash()` finds the pair and
the script reports it.

On the evaluation clip this takes 14 named tracks to **7 players** - near 6,
7, 10, 18, 44 and far 2, 13. #44 is tracks 2, 227 and 270 with gaps of three
and six frames; #7 is 56, then 422 (the tail cut off 54), then 285; #6, #10
and #18 are two tracks each - and every join is correct by the sheet. The
roster's participants carry it (`near-7`: `track_ids` in the order worn, first
and last frame); unnamed tracks are a participant each, `player-t82`, and are
joined to nobody.

An absent number vetoes nothing and proposes nothing. Most tracks carry none,
and if absence forbade a join the veto would forbid every join rather than the
wrong ones; if it proposed one, the unnamed fragments between CERVUDO's two
tracks (2862-3634) would have to be joined by motion, which is not built.

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
- **Stopping the swap inside the tracker.** Track 54's swap was traced to its
  cause: the detector *lost CHALMERS* for seven frames (2877-2883) in a three-man
  pile-up at the near baseline, and in that window CERVUDO stepped into the spot
  he had just left, at IoU 0.51 with the track's last box. With no detection of
  its own body and a confident same-kit stranger in its predicted place, box
  overlap has nothing to choose with. Three things were tried and measured, each
  through the switch detector over the whole clip:

  | Change | Tracks | Full-set tracks | Names | Effect on the swap |
  |---|---|---|---|---|
  | stock ByteTrack | 223 | 11 | 11 | swaps; detected and cut |
  | `match_thresh` 0.7 / 0.6 / 0.5 | 249 / 281 / 335 | 10 / 8 / 3 | - | survives until 0.6, which fragments everything |
  | exclude boxes with no ankle inside them | 170 | 10 | 8 | still swaps, in a different order |
  | + refuse a match whose hips moved > 10% of box height in a frame | 175 | 10 | 7 | refused by 44 px against a 43 px budget; the pile-up then swapped by another route |

  Every setting that avoided this swap did so by fragmenting tracks everywhere
  else, and the two pose-aware gates cost names without removing it. So the
  tracker is left stock - fewest fragments - and the number does the long-horizon
  identity work: a fragment costs a join, a swap costs a poisoned track, and the
  number repairs both.

## Holding a player in play

Tracks are what let the boundary test have a memory. `held_in_play` counts a
player as in play if their track was on court anywhere within
`IN_PLAY_HOLD_FRAMES` either side of the frame, which is what stops a baseline
player's constant crossings reading as a stream of exits and returns. The window
and the reasoning are in [[court-geometry#Stepping out for a moment is not leaving the game]];
this layer only supplies the identity it needs.

## Boundaries

Track identity is not evaluated - there is no labelled ground truth for who is
who in this clip, so the seven-player result is a sanity check rather than a
score. Joining is by side and number only: a stretch where a player's track
broke and the fragment never confirmed - CERVUDO between 2862 and 3634, DICARLO
10 before 3296 (track 82, `10` twice against `6` and `1`) - stays outside the
player as its own unnamed participant.

The white USA kit is close to unreadable: #27 and #55 hold full-set tracks and
were read once or twice each across their whole lives. That is a reader problem
on dark-on-white print with `USA` above the number, and it is not addressed
here - those two players will be named by hand.

A switch is only visible where there are readings, so the detector's recall is
bounded by the reader's coverage. A change of player on the white USA kit, or in
a stretch a track spends entirely at the far baseline, or before live play -
track 2 is KUTNER for its first frames in the pre-set scrum and SARAULT 44
thereafter, with one crop to show it - goes unseen.
