"""Reading the jersey number off a tracked player.

The number is the only durable identity this footage carries. Faces are around
13 px tall at the far baseline, which is no identity at all, and each team wears
one kit, so an appearance embedding cannot separate team-mates either.

Two things make this tractable, and neither is a better reader.

The first is that a number does not have to be read often. A track spans most of
a set and a player crosses the whole court within it, so the question is not "what
number is this player showing now" but "what is the largest, most legible view of
this player anywhere in their track" - and at the near baseline a digit is 34 px
tall and unmistakable. Only the biggest crops are read; the rest are not worth the
attempt.

The second is that a number is confirmed by agreement rather than by confidence.
A single reading of a folded jersey can say anything; the same number returned by
several independent crops of one track cannot.

The OCR configuration is carried over from prior work on football footage:
magnified, with CRAFT's confidence thresholds dropped well below their defaults,
because a jersey number is large bold print on moving cloth rather than a line of
text on a page. Letters are read as well as digits, because both kits print text
above the number and a reader confined to digits has to return that text as
digits - which is how the team's name came to outvote the numbers under it.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

import numpy as np

# Crops shorter than this are not worth an OCR call. Below it the digits are into
# single-figure pixel heights and the reader returns noise that still has to be
# outvoted, so a cheap size test is worth more than a confidence threshold.
MIN_CROP_HEIGHT = 80

# The number sits on the upper back and chest, so the legs are cropped away before
# reading: they carry no print and they cost magnified pixels.
TORSO_FRACTION = 0.6

# How many of a track's largest crops to read. A track holds hundreds; the biggest
# handful are all near the camera, and any one of them is enough to name it.
CROPS_PER_TRACK = 10

# The tallest crops are not enough to *check* it. A track that changes player
# part-way is named after whichever player stood nearest the camera, and its
# tallest crops all agree with each other. So the tallest crop of every stretch
# of this many frames (ten seconds) is read as well, and a track's readings then
# cover its whole life rather than its best moment.
READ_BIN_FRAMES = 250

# A single reading is not evidence. Several crops of one track agreeing, and a
# clear majority, is - that is the same claim from independent views. Three
# rather than two because a track now offers twenty or thirty readings across
# its life rather than its best ten, and on that many a pair agreeing by chance
# (a white 55 read as `65` twice) is no longer rare.
MIN_CONFIRMATIONS = 3
MIN_MAJORITY = 0.60

# A crop whose box overlaps another player's this much holds two backs, and the
# reader will return whichever number is clearer - KUTNER's track was named 7
# on two crops that had CHALMERS in them. Such crops are not read.
MAX_CROP_OVERLAP = 0.10

# A change of player needs fewer agreeing readings than a name does, because the
# costs are not symmetric: cutting a track that did not change makes a fragment,
# which its number joins back; leaving one that did change keeps the wrong man
# under a name. The span and no-interleaving rules still apply to each half.
SWITCH_MIN_CONFIRMATIONS = 2

# Independent means apart in time. Crops taken within a second of each other
# show the same pose at the same distance, and a fold that reads as a `6` reads
# as a `6` in all of them, so agreement among them is one view counted several
# times. The readings that agree must span at least this many frames - four
# seconds at this footage's 25 fps, long enough for a player to have moved.
MIN_AGREEMENT_SPAN = 100

# Below this the reader is guessing at cloth texture.
MIN_OCR_CONF = 0.3

# What a jersey carries here is at most two characters, the first of them a
# digit. That admits `7`, `44`, DICARLO's `10`, the far side's `01` and KUTNER's
# `4C`, and turns away what the print throws off once letters are read: `USA`,
# `US4`, `S4IULT`, `IUT`. It is kept as written rather than as a count, because
# `01` is not 1 and `4C` is not a number at all - and a player whose shirt the
# reader can read but the roster cannot hold is a player it can only misname.
MAX_PRINT_LENGTH = 2

# A track this much of the clip long that the vote declined to name is either a
# player the reader keeps misreading or two players stitched together, and only
# looking at the crops in time order tells which. Shorter unnamed tracks are
# glimpses and there are dozens of them.
REVIEW_FRACTION = 0.5

# CRAFT is tuned for text on a page and finds almost nothing on a jersey at its
# defaults. Magnifying and dropping the confidence thresholds is what makes large
# bold digits on moving cloth detectable at all.
#
# `low_text` is the exception, and is left where CRAFT puts it. It is not a
# confidence bar but the floor on the region-score map that decides how far each
# character's blob grows before boxes are cut, and one text box is one connected
# component of that map - a step with no notion of lines. Lowered, the blobs of a
# two-line chest print grow together, and the reader is handed the team name and
# the number as one image: `USA` over `01` comes back as `73`, `70` or `6`. The
# recogniser is not the weak part. Given the number alone it reads it at full
# confidence, so the detector is left able to cut the number out.
#
# Letters are admitted so that the print can say what it is. Both kits put text
# above the number - the team's name on one side, the player's surname on the
# other - and a reader confined to digits has no way to return it except as
# digits: `USA` comes back as `54`, and `KUTNER 4C` as `40`. A token that is
# still not a number once it has been read is the print, and can be set aside
# instead of outvoting the number below it.
#
# The crop is enlarged before the call rather than by `mag_ratio`, which is left
# at 1. Measured across every player track on the evaluation clip, a cubic
# upscale names 24 tracks correctly against 21 for `mag_ratio` 2 and 18 for
# `mag_ratio` 3, and doing both is worse than doing either - it returns more
# tokens and fewer names. Below roughly a 100 px torso crop the detector
# otherwise finds no text box at all, which is how a legible `13` and `11` on
# the far side went unread rather than misread.
READ_UPSCALE = 2

OCR_PARAMS = dict(
    allowlist="0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ",
    paragraph=False,
    detail=1,
    mag_ratio=1.0,
    text_threshold=0.2,
    low_text=0.4,
    link_threshold=0.1,
)


@dataclass(frozen=True)
class Crop:
    """A player's upper body on one frame.

    The frame travels with the pixels because a reading without one cannot be
    placed in time, and time is what separates a reader dropping a digit from a
    tracker stitching two players together: the first interleaves, the second
    switches.
    """

    frame: int
    image: np.ndarray

    @property
    def height(self) -> int:
        return int(self.image.shape[0])


@dataclass(frozen=True)
class Reading:
    """One number seen on one crop, before anything has agreed with it."""

    number: str
    confidence: float
    frame: int


def torso_crop(image: np.ndarray, detection: dict) -> np.ndarray | None:
    """The upper body of a detection, or None when there is too little of it.

    Taken from the detection box rather than from the pose keypoints: a box is
    always present, where a shoulder keypoint drops out exactly when a player
    turns - which is also when their number comes into view.
    """
    x1, y1, x2, y2 = (int(v) for v in detection["box"])
    x1, y1 = max(0, x1), max(0, y1)
    crop = image[y1:y2, x1:x2]
    if crop.size == 0 or crop.shape[0] < MIN_CROP_HEIGHT:
        return None
    torso = crop[:int(crop.shape[0] * TORSO_FRACTION), :]
    return torso if torso.size else None


def unobstructed(detection: dict, others: list[dict],
                 max_overlap: float = MAX_CROP_OVERLAP) -> bool:
    """Whether a detection's box is clear enough of every other box to read."""
    x1, y1, x2, y2 = detection["box"]
    area = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    for o in others:
        if o is detection:
            continue
        ox1, oy1, ox2, oy2 = o["box"]
        w = min(x2, ox2) - max(x1, ox1)
        h = min(y2, oy2) - max(y1, oy1)
        if w <= 0 or h <= 0:
            continue
        inter = w * h
        union = area + max(0.0, ox2 - ox1) * max(0.0, oy2 - oy1) - inter
        if union > 0 and inter / union > max_overlap:
            return False
    return True


def largest_crops(crops: list[Crop], limit: int = CROPS_PER_TRACK) -> list[Crop]:
    """The tallest crops of a track: the frames where the player was closest."""
    return sorted(crops, key=lambda c: c.height, reverse=True)[:limit]


def shortlist(crops: list[Crop], limit: int = CROPS_PER_TRACK,
              bin_frames: int = READ_BIN_FRAMES) -> list[Crop]:
    """The crops worth reading: the tallest overall, and the tallest of every bin.

    The first name the track; the second are what let a change of player show
    up as a change of number, which the tallest crops alone never would.
    """
    best_in_bin: dict[int, Crop] = {}
    for c in crops:
        b = c.frame // bin_frames
        if b not in best_in_bin or c.height > best_in_bin[b].height:
            best_in_bin[b] = c
    picked = {c.frame: c for c in largest_crops(crops, limit)}
    for c in best_in_bin.values():
        picked.setdefault(c.frame, c)
    return sorted(picked.values(), key=lambda c: c.height, reverse=True)


def switch(readings: list[Reading]) -> tuple[str, str, int, int] | None:
    """Whether a track's readings name one player and then another.

    Returns `(first, second, last_frame_of_first, first_frame_of_second)` when
    the readings split into a prefix and a suffix that each confirm - by the
    same rules as a whole track - to different numbers. Interleaved numbers are
    the reader disagreeing with itself about one player and do not qualify; nor
    does a suffix too brief or too scattered to confirm on its own.
    """
    ordered = in_time_order_readings(readings)
    best = None
    for i in range(1, len(ordered)):
        before, after = ordered[:i], ordered[i:]
        a = confirm(before, SWITCH_MIN_CONFIRMATIONS)
        b = confirm(after, SWITCH_MIN_CONFIRMATIONS)
        if a is None or b is None or a == b:
            continue
        if _is_fragment_of(a, b) or _is_fragment_of(b, a):
            continue
        # DICARLO 10 reads as `6` whenever the 0 is on a fold, and those 6s go
        # on after the first clean `10`. Two players in sequence do not do that:
        # the old number stops when the new one starts.
        if any(r.number == b for r in before) or any(r.number == a for r in after):
            continue
        score = sum(r.number == a for r in before) + sum(r.number == b for r in after)
        if best is None or score > best[0]:
            best = (score, a, b, before, after)
    if best is None:
        return None
    _, a, b, before, after = best
    last_a = max(r.frame for r in before if r.number == a)
    first_b = min(r.frame for r in after if r.number == b)
    return a, b, last_a, first_b


def in_time_order_readings(readings: list[Reading]) -> list[Reading]:
    return sorted(readings, key=lambda r: r.frame)


def in_time_order(crops: list[Crop]) -> list[Crop]:
    """The same crops as the track saw them, for checking a split vote by eye."""
    return sorted(crops, key=lambda c: c.frame)


def needs_review(number: str | None, in_play_frames: int, span: int) -> bool:
    """Whether an unnamed track is long enough that its silence is a question.

    Measured in frames *in play*: an official is tracked from the sideline for
    the whole set and carries no number, and that is an answer.
    """
    return number is None and in_play_frames >= span * REVIEW_FRACTION


# At jersey size `1` and `I` are one shape, and so are `0` and `O`. Once letters
# are on the table the reader prefers the letter: DICARLO's `10` comes back as
# `I0` on five crops in six. They are read back before anything asks whether a
# token is a number, so that admitting letters cannot cost a digit.
CONFUSED_LETTERS = {"I": "1", "O": "0"}


def as_number(text: str) -> str | None:
    """What a reader's token says a player wears, or None where it is not that.

    A number here is what is printed on the shirt, which is usually digits and on
    this footage is sometimes not: KUTNER wears `4C`. What separates a shirt from
    the team's name above it is shape rather than spelling - a shirt is short and
    it leads with a digit, and `USA`, `US4` and `S4IULT` are neither.
    """
    token = "".join(CONFUSED_LETTERS.get(c, c) for c in text.strip().upper())
    if not token or len(token) > MAX_PRINT_LENGTH or not token[0].isdigit():
        return None
    if not token.isalnum():
        return None
    # Nobody is numbered nothing, and `0` is what the reader offers for a fold,
    # a shadow and half a digit alike.
    if token.isdigit() and int(token) == 0:
        return None
    return token


class JerseyReader:
    """EasyOCR, configured for jersey print rather than for documents."""

    def __init__(self, gpu: bool = True):
        import easyocr

        self.reader = easyocr.Reader(["en"], gpu=gpu, verbose=False)

    def read(self, crop: Crop) -> list[Reading]:
        """Every number the reader finds on one crop."""
        import cv2

        out: list[Reading] = []
        image = crop.image
        if READ_UPSCALE > 1:
            image = cv2.resize(image, (image.shape[1] * READ_UPSCALE,
                                       image.shape[0] * READ_UPSCALE),
                               interpolation=cv2.INTER_CUBIC)
        for _, text, conf in self.reader.readtext(image, **OCR_PARAMS):
            number = as_number(text)
            if number is not None and conf > MIN_OCR_CONF:
                out.append(Reading(number=number, confidence=round(float(conf), 3),
                                   frame=crop.frame))
        return out


def confirm(readings: list[Reading],
            min_confirmations: int = MIN_CONFIRMATIONS) -> str | None:
    """The number a track carries, or None where its readings do not agree.

    Agreement, not confidence: the reader is confident about folds. None is the
    preferred way to be wrong, because an unnamed track costs one join by hand
    while a wrongly named one silently merges two players.

    Two-digit readings are weighted above one-digit ones, because the reader's
    commonest failure is losing a digit rather than inventing one. Both errors
    seen on the evaluation clip were of that shape - a jersey reading 18 returned
    `1` more often than `18`, and a 10 returned `6` - and an unweighted count
    hands the track to the fragment. Crops read across the whole track, far
    court included, add more of the same, so a fragment of the leading number is
    left out of the vote rather than counted against it.
    """
    if not readings:
        return None
    counts = Counter(r.number for r in readings)
    weighted = Counter()
    for number, count in counts.items():
        weighted[number] = count * len(number)
    number, weight = weighted.most_common(1)[0]
    if counts[number] < min_confirmations:
        return None
    # A lost digit is not a dissenting vote. `1` read beside `18` is what the
    # reader returns when the 8 is on a fold, and it fits an 18 - so it neither
    # supports nor opposes, and the majority is taken over readings that do.
    # Nor is a doubled one: `77` beside `7` is the reader repeating, and CHALMERS
    # was left unnamed for half a set when three of them outweighed eight 7s.
    opposing = sum(w for n, w in weighted.items()
                   if n != number and not _is_fragment_of(n, number)
                   and not _is_doubling_of(n, number))
    if weight / (weight + opposing) <= MIN_MAJORITY:
        return None
    frames = [r.frame for r in readings if r.number == number]
    if max(frames) - min(frames) < MIN_AGREEMENT_SPAN:
        return None
    if any(_is_fragment_of(number, other) for other in counts):
        return None
    return number


def _is_fragment_of(number: str, other: str) -> bool:
    """Whether `number` is what the reader returns when it drops a digit of `other`.

    A `4` read five times beside a `40` read once fits a 40 whose 0 was lost as
    well as it fits a 4, so the track is left unnamed. A `7` beside a `77` is not
    that case: the doubled digit is the reader repeating, not dropping.
    """
    return len(number) == 1 and len(other) == 2 and number in other and other != number * 2


def _is_doubling_of(number: str, other: str) -> bool:
    """Whether `number` is `other` read twice - `77` from a 7."""
    return len(other) == 1 and number == other * 2


def conflicts(a: str | None, b: str | None) -> bool:
    """Whether two confirmed numbers rule out their tracks being one player.

    The number's job is to *forbid* joins rather than to propose them. Prior work
    on football footage found that is where the value is: coverage was 8% of
    fragments and it was still enough, because the wrongly merged groups were
    large, so almost any confirmed number inside one caught the mistake.
    """
    return a is not None and b is not None and a != b
