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
digits-only, magnified, with CRAFT's detection thresholds dropped well below their
defaults, because a jersey number is large bold print on moving cloth rather than
a line of text on a page.
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
# handful are all near the camera, and any one of them is enough.
CROPS_PER_TRACK = 10

# A single reading is not evidence. Two crops of one track agreeing, and a clear
# majority, is - that is the same claim from independent views.
MIN_CONFIRMATIONS = 2
MIN_MAJORITY = 0.60

# Below this the reader is guessing at cloth texture.
MIN_OCR_CONF = 0.3

# Jersey numbers run 1-99. A reading outside that is a misparse of print that is
# not a number.
MIN_NUMBER, MAX_NUMBER = 1, 99

# CRAFT is tuned for text on a page and finds almost nothing on a jersey at its
# defaults. Magnifying and dropping all three detection thresholds is what makes
# large bold digits on moving cloth detectable at all.
OCR_PARAMS = dict(
    allowlist="0123456789",
    paragraph=False,
    detail=1,
    mag_ratio=2.0,
    text_threshold=0.2,
    low_text=0.1,
    link_threshold=0.1,
)


@dataclass(frozen=True)
class Reading:
    """One number seen on one crop, before anything has agreed with it."""

    number: int
    confidence: float


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


def largest_crops(crops: list[np.ndarray], limit: int = CROPS_PER_TRACK) -> list[np.ndarray]:
    """The tallest crops of a track: the frames where the player was closest."""
    return sorted(crops, key=lambda c: c.shape[0], reverse=True)[:limit]


class JerseyReader:
    """EasyOCR, configured for jersey print rather than for documents."""

    def __init__(self, gpu: bool = True):
        import easyocr

        self.reader = easyocr.Reader(["en"], gpu=gpu, verbose=False)

    def read(self, crop: np.ndarray) -> list[Reading]:
        """Every number the reader finds on one crop."""
        out: list[Reading] = []
        for _, text, conf in self.reader.readtext(crop, **OCR_PARAMS):
            text = text.strip()
            if not text:
                continue
            try:
                number = int(text)
            except ValueError:
                continue
            if MIN_NUMBER <= number <= MAX_NUMBER and conf > MIN_OCR_CONF:
                out.append(Reading(number=number, confidence=round(float(conf), 3)))
        return out


def confirm(readings: list[Reading]) -> int | None:
    """The number a track carries, or None where its readings do not agree.

    Agreement, not confidence: the reader is confident about folds. None is the
    preferred way to be wrong, because an unnamed track costs one join by hand
    while a wrongly named one silently merges two players.

    Two-digit readings are weighted above one-digit ones, because the reader's
    commonest failure is losing a digit rather than inventing one. Both errors
    seen on the evaluation clip were of that shape - a jersey reading 18 returned
    `1` more often than `18`, and a 10 returned `6` - and an unweighted count
    hands the track to the fragment.
    """
    if not readings:
        return None
    counts = Counter(r.number for r in readings)
    weighted = Counter()
    for number, count in counts.items():
        weighted[number] = count * len(str(number))
    number, weight = weighted.most_common(1)[0]
    if counts[number] < MIN_CONFIRMATIONS:
        return None
    if weight / sum(weighted.values()) <= MIN_MAJORITY:
        return None
    return number


def conflicts(a: int | None, b: int | None) -> bool:
    """Whether two confirmed numbers rule out their tracks being one player.

    The number's job is to *forbid* joins rather than to propose them. Prior work
    on football footage found that is where the value is: coverage was 8% of
    fragments and it was still enough, because the wrongly merged groups were
    large, so almost any confirmed number inside one caught the mistake.
    """
    return a is not None and b is not None and a != b
