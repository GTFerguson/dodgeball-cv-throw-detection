"""The ball, seen as colour, around a player's wrists.

Pose cannot tell a fake from a throw: a fake is the same motion with the ball
kept, and every pose feature tried sat at chance. The ball can. It is the one
orange thing in the hall, so a colour mask finds it at 20 px where a stock
detector drops out on exactly the blurred frames that matter.

This module reads the footage once and records, for every proposed throw and
every frame around it, what the mask sees at each wrist: how much orange is
inside a small disc on the wrist, and every ball-sized blob within reach of it.
Nothing is decided here; ``src/release.py`` reads the traces and makes the
claims. Keeping the read separate means one pass over the video serves every
rule tried against it.

The colour range is the set-start mask's with the hue floor raised. The near
team's jerseys are red, and the set-start range admits red: with it, a red
sleeve at the wrist read as a ball held for the whole of a fake. Ball pixels
sit at hue 6-14 and the jersey at 4-10; the floor at ``BALL_HUE_MIN`` keeps
three quarters of the ball and a fifth of a percent of the jersey.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from src.candidates import (LEFT_HIP, LEFT_WRIST, RIGHT_HIP, RIGHT_WRIST, Candidate, _kp,
                            shoulders, torso_up)
from src.court import foot_point
from src.timing import REFERENCE_FPS, frames
from src.venue import VENUE

# Hue floor above the set-start mask's 5: red jersey pixels lie at hue 4-10 and
# ball pixels at 6-14 on the evaluation clip. Saturation and value floors are
# the set-start mask's own.
# The window is the venue's (config/venue.toml): this match ball, this kit.
BALL_HSV_LO = tuple(int(v) for v in VENUE["ball"]["hsv_lo"])
BALL_HSV_HI = tuple(int(v) for v in VENUE["ball"]["hsv_hi"])
BALL_HUE_MIN = BALL_HSV_LO[0]
# A ball in flight at the whip is a motion-blurred streak, and blur mixes
# the orange with the floor until its saturation falls under the floor above:
# on the evaluation clip's final throw the streak read a median saturation of
# 70-75 on the two frames after release (0 of 309 pixels above 120) against
# 118-157 for the same ball at rest. A second mask with this floor sees the
# streak; the floor and the shirts it lets in are held off by shape and by
# the chain, since a faint blob may continue a chain and never start one.
BALL_FAINT_SAT_MIN = 60
BALL_HSV_FAINT_LO = (BALL_HUE_MIN, BALL_FAINT_SAT_MIN, BALL_HSV_LO[2])

# A ball on the floor spans 0.020-0.036 of the perspective scale (set-start's
# measurement). In flight it blurs into a streak several times longer, so the
# blob filter here is loose at the top; the bottom keeps out specks.
BLOB_DIAMETER_NORM = (0.010, 0.144)
# How far from the wrist a blob is still recorded. A hard throw covers 0.06 of
# the scale per frame and the trace runs a dozen frames past the peak.
BLOB_REACH_NORM = 0.9
BLOBS_PER_WRIST = 12

# The disc on the wrist that "ball in hand" is measured in. The ball's radius
# is under 0.02; the disc is wider because the wrist keypoint sits at the
# joint and the ball in the palm is a hand's length beyond it.
DISC_RADIUS_NORM = 0.05

# Traced either side of the proposal. Every labelled outcome on the clip
# settles within 0.85 s of the release, and a release can precede the peak
# by a third of a second.
TRACE_BEFORE_S = 0.48
TRACE_AFTER_S = 1.44

WRISTS = {"L": LEFT_WRIST, "R": RIGHT_WRIST}


@dataclass(frozen=True)
class Blob:
    """One orange connected component near a wrist, in image pixels."""

    x: float
    y: float
    diameter_norm: float
    area: int
    # Seen only by the faint mask: a blurred ball, or something dull enough
    # to fail the strict one. Continues a chain, never seeds one.
    faint: bool = False

    def distance_norm(self, x: float, y: float, scale: float) -> float:
        return float(np.hypot(self.x - x, self.y - y)) / scale


@dataclass(frozen=True)
class WristFrame:
    """What the mask saw at one wrist on one frame."""

    wrist: tuple[float, float] | None
    # Whether the wrist keypoint was seen on this frame, or carried from the
    # last frame it was.
    seen: bool
    # Orange pixels inside the disc, divided by the squared scale so a near
    # and a far ball count the same.
    disc: float
    blobs: tuple[Blob, ...]
    # The wrist's height along the body, from the shoulders in torso lengths:
    # positive is past the shoulder line towards the head, whichever way the
    # body is lying. None where the shoulders or hips were not seen.
    height: float | None = None
    # Ball-sized blobs the faint mask sees that the strict one does not.
    faint: tuple[Blob, ...] = ()


@dataclass
class Trace:
    """The ball around one proposal's wrists, frame by frame."""

    candidate: Candidate
    scale: float
    frames: dict[int, dict[str, WristFrame]] = field(default_factory=dict)
    # The clip's rate, so every window read off the trace is a duration.
    fps: float = REFERENCE_FPS

    def at(self, offset: int, wrist: str) -> WristFrame | None:
        return self.frames.get(offset, {}).get(wrist)


def _mask(hsv: np.ndarray, lo) -> np.ndarray:
    mask = cv2.inRange(hsv, lo, BALL_HSV_HI)
    return cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))


def ball_mask(frame_bgr: np.ndarray) -> np.ndarray:
    return _mask(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV), BALL_HSV_LO)


def ball_masks(frame_bgr: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The strict mask and the faint one, from one colour conversion."""
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    return _mask(hsv, BALL_HSV_LO), _mask(hsv, BALL_HSV_FAINT_LO)


def blobs_in(mask: np.ndarray) -> tuple[list[tuple[float, float, int, int, int]], np.ndarray]:
    """Every component as (cx, cy, width, height, area), and the label image."""
    count, labels, stats, centroids = cv2.connectedComponentsWithStats(mask)
    return [(float(centroids[i][0]), float(centroids[i][1]),
             int(stats[i, cv2.CC_STAT_WIDTH]), int(stats[i, cv2.CC_STAT_HEIGHT]),
             int(stats[i, cv2.CC_STAT_AREA])) for i in range(1, count)], labels


def ball_sized(components, labels: np.ndarray, scale: float) -> np.ndarray:
    """The mask with only ball-sized components left in it.

    Colour alone leaves skin, socks and the odd edge of a sleeve in the mask;
    none of those is the size of a ball. Counting the disc on this rather than
    on the raw mask makes "ball in hand" a claim about shape as well as hue.
    """
    keep = np.zeros(len(components) + 1, bool)
    for i, (_, _, w, h, _) in enumerate(components, start=1):
        keep[i] = BLOB_DIAMETER_NORM[0] <= max(w, h) / scale <= BLOB_DIAMETER_NORM[1]
    return keep[labels].astype(np.uint8) * 255


def disc_count(mask: np.ndarray, x: float, y: float, radius: float) -> int:
    h, w = mask.shape
    x0, y0 = int(max(0, x - radius)), int(max(0, y - radius))
    x1, y1 = int(min(w, x + radius + 1)), int(min(h, y + radius + 1))
    if x1 <= x0 or y1 <= y0:
        return 0
    yy, xx = np.mgrid[y0:y1, x0:x1]
    inside = (xx - x) ** 2 + (yy - y) ** 2 <= radius * radius
    return int(np.count_nonzero(mask[y0:y1, x0:x1][inside]))


def wrist_height(detection: dict | None, wrist: tuple[float, float] | None) -> float | None:
    """How far past the shoulder line the wrist is, along the torso, in torso lengths."""
    if detection is None or wrist is None:
        return None
    s, up = shoulders(detection), torso_up(detection)
    hips = [p for p in (_kp(detection, LEFT_HIP), _kp(detection, RIGHT_HIP)) if p is not None]
    if s is None or up is None or not hips:
        return None
    torso = float(np.linalg.norm(s - sum(hips) / len(hips)))
    if torso <= 0:
        return None
    return float(np.dot(np.asarray(wrist) - s, up)) / torso


def _near(components, x: float, y: float, scale: float, faint: bool) -> list[Blob]:
    """Ball-sized components within reach of a wrist, nearest first."""
    near = []
    for cx, cy, w, h, area in components:
        diameter = max(w, h) / scale
        if not BLOB_DIAMETER_NORM[0] <= diameter <= BLOB_DIAMETER_NORM[1]:
            continue
        distance = float(np.hypot(cx - x, cy - y)) / scale
        if distance > BLOB_REACH_NORM:
            continue
        near.append((distance, Blob(cx, cy, round(diameter, 4), area, faint)))
    near.sort(key=lambda d: d[0])
    return [b for _, b in near[:BLOBS_PER_WRIST]]


def wrist_frame(mask: np.ndarray, components, labels: np.ndarray,
                wrist: tuple[float, float] | None, seen: bool, scale: float,
                height: float | None = None, faint_components=()) -> WristFrame:
    if wrist is None:
        return WristFrame(None, False, 0.0, ())
    x, y = wrist
    count = disc_count(ball_sized(components, labels, scale), x, y, DISC_RADIUS_NORM * scale)
    blobs = _near(components, x, y, scale, faint=False)
    # A strict blob grows under the faint mask and keeps its centre; only what
    # the strict mask had no blob for is new.
    faint = [f for f in _near(faint_components, x, y, scale, faint=True)
             if not any(np.hypot(f.x - b.x, f.y - b.y) <= f.diameter_norm * scale for b in blobs)]
    return WristFrame((x, y), seen, count / (scale * scale), tuple(blobs), height, tuple(faint))


def trace_candidates(video: str | Path, candidates: list[Candidate], roster, pose, court,
                     before_s: float = TRACE_BEFORE_S, after_s: float = TRACE_AFTER_S,
                     progress=None) -> list[Trace]:
    """One sequential read of the clip, tracing every proposal's window.

    Sequential rather than seeking, because the windows cover half the clip
    between them and a decoder seek costs more than a decode.
    """
    before, after = frames(before_s, pose.fps), frames(after_s, pose.fps)
    traces: list[Trace] = []
    wanted: dict[int, list[tuple[int, int]]] = {}
    lookup: list[dict[int, int]] = []
    for ti, cand in enumerate(candidates):
        track = roster.track(cand.track_id)
        lookup.append(dict(track.detections))
        peak = pose.frame(cand.frame)[cand.detection_index]
        _, foot_y, _ = foot_point(peak)
        traces.append(Trace(cand, float(court.scale_at(foot_y)), fps=pose.fps))
        for offset in range(-before, after + 1):
            wanted.setdefault(cand.frame + offset, []).append((ti, offset))
    last_wrist: dict[tuple[int, str], tuple[float, float]] = {}

    cap = cv2.VideoCapture(str(video))
    index = -1
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            index += 1
            if index not in wanted:
                continue
            mask, faint = ball_masks(frame)
            components, labels = blobs_in(mask)
            faint_components, _ = blobs_in(faint)
            for ti, offset in wanted[index]:
                trace = traces[ti]
                det_index = lookup[ti].get(index)
                det = pose.frame(index)[det_index] if det_index is not None else None
                row: dict[str, WristFrame] = {}
                for name, kp in WRISTS.items():
                    p = _kp(det, kp) if det is not None else None
                    seen = p is not None
                    if seen:
                        last_wrist[(ti, name)] = (float(p[0]), float(p[1]))
                    wrist = last_wrist.get((ti, name))
                    row[name] = wrist_frame(mask, components, labels, wrist, seen, trace.scale,
                                            wrist_height(det, wrist) if seen else None,
                                            faint_components)
                trace.frames[offset] = row
            if progress and index % 500 == 0:
                progress(index)
    finally:
        cap.release()
    return traces
