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

from src.candidates import LEFT_WRIST, RIGHT_WRIST, Candidate, _kp
from src.court import foot_point

# Hue floor above the set-start mask's 5: red jersey pixels lie at hue 4-10 and
# ball pixels at 6-14 on the evaluation clip. Saturation and value floors are
# the set-start mask's own.
BALL_HUE_MIN = 9
BALL_HSV_LO = (BALL_HUE_MIN, 120, 90)
BALL_HSV_HI = (22, 255, 255)

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

# Frames traced either side of the proposal.
TRACE_BEFORE = 12
TRACE_AFTER = 16

WRISTS = {"L": LEFT_WRIST, "R": RIGHT_WRIST}


@dataclass(frozen=True)
class Blob:
    """One orange connected component near a wrist, in image pixels."""

    x: float
    y: float
    diameter_norm: float
    area: int

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


@dataclass
class Trace:
    """The ball around one proposal's wrists, frame by frame."""

    candidate: Candidate
    scale: float
    frames: dict[int, dict[str, WristFrame]] = field(default_factory=dict)

    def at(self, offset: int, wrist: str) -> WristFrame | None:
        return self.frames.get(offset, {}).get(wrist)


def ball_mask(frame_bgr: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, BALL_HSV_LO, BALL_HSV_HI)
    return cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))


def blobs_in(mask: np.ndarray) -> list[tuple[float, float, int, int, int]]:
    """Every component as (cx, cy, width, height, area)."""
    count, _, stats, centroids = cv2.connectedComponentsWithStats(mask)
    return [(float(centroids[i][0]), float(centroids[i][1]),
             int(stats[i, cv2.CC_STAT_WIDTH]), int(stats[i, cv2.CC_STAT_HEIGHT]),
             int(stats[i, cv2.CC_STAT_AREA])) for i in range(1, count)]


def disc_count(mask: np.ndarray, x: float, y: float, radius: float) -> int:
    h, w = mask.shape
    x0, y0 = int(max(0, x - radius)), int(max(0, y - radius))
    x1, y1 = int(min(w, x + radius + 1)), int(min(h, y + radius + 1))
    if x1 <= x0 or y1 <= y0:
        return 0
    yy, xx = np.mgrid[y0:y1, x0:x1]
    inside = (xx - x) ** 2 + (yy - y) ** 2 <= radius * radius
    return int(np.count_nonzero(mask[y0:y1, x0:x1][inside]))


def wrist_frame(mask: np.ndarray, components, wrist: tuple[float, float] | None,
                seen: bool, scale: float) -> WristFrame:
    if wrist is None:
        return WristFrame(None, False, 0.0, ())
    x, y = wrist
    count = disc_count(mask, x, y, DISC_RADIUS_NORM * scale)
    near = []
    for cx, cy, w, h, area in components:
        diameter = max(w, h) / scale
        if not BLOB_DIAMETER_NORM[0] <= diameter <= BLOB_DIAMETER_NORM[1]:
            continue
        distance = float(np.hypot(cx - x, cy - y)) / scale
        if distance > BLOB_REACH_NORM:
            continue
        near.append((distance, Blob(cx, cy, round(diameter, 4), area)))
    near.sort(key=lambda d: d[0])
    return WristFrame((x, y), seen, count / (scale * scale),
                      tuple(b for _, b in near[:BLOBS_PER_WRIST]))


def trace_candidates(video: str | Path, candidates: list[Candidate], roster, pose, court,
                     before: int = TRACE_BEFORE, after: int = TRACE_AFTER,
                     progress=None) -> list[Trace]:
    """One sequential read of the clip, tracing every proposal's window.

    Sequential rather than seeking, because the windows cover half the clip
    between them and a decoder seek costs more than a decode.
    """
    traces: list[Trace] = []
    wanted: dict[int, list[tuple[int, int]]] = {}
    lookup: list[dict[int, int]] = []
    for ti, cand in enumerate(candidates):
        track = roster.track(cand.track_id)
        lookup.append(dict(track.detections))
        peak = pose.frame(cand.frame)[cand.detection_index]
        _, foot_y, _ = foot_point(peak)
        traces.append(Trace(cand, float(court.scale_at(foot_y))))
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
            mask = ball_mask(frame)
            components = blobs_in(mask)
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
                    row[name] = wrist_frame(mask, components, wrist, seen, trace.scale)
                trace.frames[offset] = row
            if progress and index % 500 == 0:
                progress(index)
    finally:
        cap.release()
    return traces
