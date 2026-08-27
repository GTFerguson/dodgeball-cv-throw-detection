#!/usr/bin/env python
"""Calibrate the court from a clip: image <-> court-metre homography.

The camera is fixed for the whole clip, so calibration is a one-off fit rather
than per-frame tracking. Two properties of this footage make it a clean fit:

* Players are transient and the floor is not, so a per-pixel median over frames
  sampled across the clip yields a plate with the court fully exposed - no
  occlusion handling required anywhere downstream of it.
* The court boundary is bright green tape on a grey floor, which separates on
  colour alone near the camera.

The green cue does not survive distance: at the far baseline the tape is fully
desaturated by lighting falloff and compression, so the cross-lines are found as
brightness ridges instead, which works at both ends. The sidelines carry the
colour fit; the baselines come from the ridge profile.

What the fit yields beyond a polygon:

* Distances in metres, so the out-of-play margin is one number rather than a
  per-region pixel guess that perspective would invalidate.
* The horizon, which is the image of the floor plane's points at infinity. The
  cross-lines are image-horizontal, so their vanishing point is at infinity and
  the horizon is the horizontal line through the sidelines' vanishing point. A
  vertical object of fixed height then projects to a pixel height proportional
  to (foot_y - horizon_y), giving a scale model for free.

The fit is checked against structure it was not fitted to. Only the four corners
enter the homography; the interior markings must then land on their real-world
positions, which is a check no amount of self-consistency could pass by accident.

Usage::

    .venv/bin/python scripts/fit_court.py data/footage/clip.mp4
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from src.hashing import clip_sha256  # noqa: E402
from court import (  # noqa: E402
    CENTRE_LINE_M, COURT_LENGTH_M, COURT_ROOT, COURT_WIDTH_M, HELD_OUT_MARKINGS_M,
    MARGIN_M, MARKING_TOLERANCE_M, SCHEMA_VERSION,
)

# Odd, so the median is an actual sample rather than an average of two. Enough
# samples that a player standing still for several seconds cannot survive it.
PLATE_SAMPLES = 121

# Green tape against a grey floor. Both bounds are needed: the difference alone
# also fires on dark green seating in the crowd.
GREEN_DOMINANCE = 10
GREEN_MIN = 120

# Rows are scanned for the leftmost and rightmost green run. Restricting x keeps
# crowd and signage out of the fit; restricting y stays clear of the baselines,
# where a full-width line leaves no left/right runs to separate.
SIDELINE_X_RANGE = (40, 1810)
SIDELINE_Y_MARGIN = 6

# A cross-line is a narrow bright ridge against the local floor brightness. The
# baseline window must be wide relative to a line's width or it absorbs the line.
RIDGE_BASELINE_WINDOW = 81
RIDGE_MIN_HEIGHT = 8.0
RIDGE_SEPARATION = 10

# The baselines sit fractionally outside the rows that carry two separable green
# runs, because a full-width line leaves only one. Enough slack to reach them,
# not enough to reach floor markings beyond the court.
COURT_Y_PAD = 30

# Sampled well inside the sidelines so the ridge profile never picks them up.
PROFILE_INSET = 0.20


def build_plate(video: Path, samples: int) -> tuple[np.ndarray, dict]:
    """Per-pixel median over frames spread across the clip."""
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise SystemExit(f"cannot open {video}")
    meta = {
        "fps": cap.get(cv2.CAP_PROP_FPS),
        "frame_count": int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
    }
    wanted = set(np.linspace(0, meta["frame_count"] - 1, samples).astype(int).tolist())
    frames, index = [], 0
    while cap.grab():
        if index in wanted:
            ok, frame = cap.retrieve()
            if ok:
                frames.append(frame)
        index += 1
    cap.release()
    if len(frames) < samples // 2:
        raise SystemExit(f"only decoded {len(frames)} of {samples} sample frames")
    stack = np.stack(frames)
    # partition keeps the array in uint8, where median would upcast the whole
    # stack to float64. An odd sample count makes the k-th element the median.
    return np.partition(stack, len(stack) // 2, axis=0)[len(stack) // 2], meta


def green_mask(plate: np.ndarray) -> np.ndarray:
    b, g, r = (plate[..., i].astype(int) for i in range(3))
    return ((g - np.maximum(r, b)) > GREEN_DOMINANCE) & (g > GREEN_MIN)


def _runs(xs: np.ndarray, gap: int = 3) -> list[tuple[int, int]]:
    """Contiguous runs in a sorted index array, as (first, last) pairs."""
    if not len(xs):
        return []
    breaks = np.nonzero(np.diff(xs) > gap)[0]
    out, start = [], 0
    for end in list(breaks) + [len(xs) - 1]:
        out.append((xs[start], xs[end]))
        start = end + 1
    return out


def _fit_robust(points: np.ndarray, rounds: int = 3) -> tuple[float, float, np.ndarray]:
    """Least squares x = a*y + b, refitted after discarding outliers."""
    keep = np.ones(len(points), bool)
    a = b = 0.0
    for _ in range(rounds):
        a, b = np.polyfit(points[keep, 1], points[keep, 0], 1)
        residual = np.abs(points[:, 0] - (a * points[:, 1] + b))
        keep = residual < max(2.5, 3 * np.median(residual))
    return float(a), float(b), keep


def fit_sidelines(mask: np.ndarray) -> dict:
    x0, x1 = SIDELINE_X_RANGE
    left, right = [], []
    for y in range(SIDELINE_Y_MARGIN, mask.shape[0] - SIDELINE_Y_MARGIN):
        runs = _runs(np.nonzero(mask[y, x0:x1])[0] + x0)
        if len(runs) < 2:
            continue
        left.append((0.5 * (runs[0][0] + runs[0][1]), y))
        right.append((0.5 * (runs[-1][0] + runs[-1][1]), y))
    if len(left) < 100:
        raise SystemExit(f"only {len(left)} rows carried two green runs; no sidelines")
    left, right = np.array(left, float), np.array(right, float)
    la, lb, l_keep = _fit_robust(left)
    ra, rb, r_keep = _fit_robust(right)
    # Green also appears in the crowd and on signage. A row only evidences court
    # if it lands on both fitted sidelines, so the span of jointly-inlying rows
    # is what brackets the court - not the raw extent of the green.
    both = l_keep & r_keep
    rows = left[both, 1]
    return {"left": (la, lb), "right": (ra, rb),
            "inliers": (int(l_keep.sum()), int(r_keep.sum())),
            "y_span": (float(rows.min()), float(rows.max()))}


def cross_line_ridges(plate: np.ndarray, sidelines: dict) -> list[float]:
    """Sub-pixel image rows of every horizontal court marking."""
    la, lb = sidelines["left"]
    ra, rb = sidelines["right"]
    grey = cv2.cvtColor(plate, cv2.COLOR_BGR2GRAY).astype(float)
    height = plate.shape[0]
    top = max(0, int(sidelines["y_span"][0]) - COURT_Y_PAD)
    bottom = min(height, int(sidelines["y_span"][1]) + COURT_Y_PAD)
    profile = np.full(height, np.nan)
    for y in range(top, bottom):
        span = (ra * y + rb) - (la * y + lb)
        a = int(la * y + lb + PROFILE_INSET * span)
        b = int(ra * y + rb - PROFILE_INSET * span)
        if 0 <= a < b <= plate.shape[1] and b - a > 20:
            profile[y] = grey[y, a:b].mean()
    valid = ~np.isnan(profile)
    # A NaN anywhere inside the smoothing kernel poisons the whole neighbourhood,
    # which would blind the detector to the very first and last lines.
    filled = np.interp(np.arange(height), np.nonzero(valid)[0], profile[valid])
    smooth = cv2.GaussianBlur(filled.reshape(-1, 1), (1, RIDGE_BASELINE_WINDOW), 0).ravel()
    ridge = filled - smooth
    ridge[~valid] = -np.inf

    centres = []
    for y in range(RIDGE_SEPARATION, height - RIDGE_SEPARATION):
        window = ridge[y - RIDGE_SEPARATION: y + RIDGE_SEPARATION + 1]
        if ridge[y] >= RIDGE_MIN_HEIGHT and ridge[y] == window.max():
            rows = np.arange(y - 6, y + 7)
            weights = np.clip(ridge[y - 6: y + 7], 0, None)
            centres.append(float((weights * rows).sum() / weights.sum()))
    return sorted(centres)


def fit_plate(plate: np.ndarray) -> dict:
    """Calibrate from an already-built plate, so the fit is testable without footage."""
    sidelines = fit_sidelines(green_mask(plate))
    la, lb = sidelines["left"]
    ra, rb = sidelines["right"]
    ridges = cross_line_ridges(plate, sidelines)
    if len(ridges) < 2:
        raise SystemExit(f"found {len(ridges)} cross-lines; need at least the two baselines")

    near, far = max(ridges), min(ridges)
    corners_image = np.array(
        [[la * near + lb, near], [ra * near + rb, near],
         [ra * far + rb, far], [la * far + lb, far]], np.float32)
    corners_court = np.array(
        [[0, 0], [COURT_WIDTH_M, 0],
         [COURT_WIDTH_M, COURT_LENGTH_M], [0, COURT_LENGTH_M]], np.float32)
    homography, _ = cv2.findHomography(corners_image, corners_court)

    def to_court(x: float, y: float) -> tuple[float, float]:
        v = homography @ np.array([x, y, 1.0])
        return float(v[0] / v[2]), float(v[1] / v[2])

    detected = []
    for row in ridges:
        centre_x = 0.5 * ((la * row + lb) + (ra * row + rb))
        detected.append({"image_y": round(row, 2), "court_y": round(to_court(centre_x, row)[1], 3)})

    # The interior markings never touched the homography. Their real-world
    # positions are therefore an independent verdict on it and on the assumption
    # that this floor is a regulation court at all.
    errors = {}
    for expected in HELD_OUT_MARKINGS_M:
        nearest = min(detected, key=lambda d: abs(d["court_y"] - expected))
        errors[expected] = round(nearest["court_y"] - expected, 3)
        if abs(errors[expected]) > MARKING_TOLERANCE_M:
            raise SystemExit(
                f"marking at {expected} m landed at {nearest['court_y']} m "
                f"(tolerance {MARKING_TOLERANCE_M} m) - the fit or the court is wrong")

    # Cross-lines are image-horizontal, so their vanishing point lies at infinity
    # and the horizon is the horizontal line through the sidelines' intersection.
    horizon_y = (rb - lb) / (la - ra)

    return {
        "plate": plate,
        "sidelines": sidelines,
        "corners_image": corners_image,
        "homography": homography,
        "horizon_y": float(horizon_y),
        "cross_lines": detected,
        "held_out_error_m": errors,
    }


def fit(video: Path, samples: int) -> dict:
    plate, meta = build_plate(video, samples)
    result = fit_plate(plate)
    result["meta"] = meta
    return result


def render_overlay(result: dict, path: Path) -> None:
    inverse = np.linalg.inv(result["homography"])

    def to_image(cx: float, cy: float) -> tuple[int, int]:
        v = inverse @ np.array([cx, cy, 1.0])
        return int(round(v[0] / v[2])), int(round(v[1] / v[2]))

    img = result["plate"].copy()
    for cy in np.arange(0, COURT_LENGTH_M + 0.01, 1.0):
        cv2.line(img, to_image(0, cy), to_image(COURT_WIDTH_M, cy), (0, 255, 255), 1)
    for cx in np.arange(0, COURT_WIDTH_M + 0.01, 1.0):
        cv2.line(img, to_image(cx, 0), to_image(cx, COURT_LENGTH_M), (0, 255, 255), 1)
    band = [to_image(x, y) for x, y in [
        (-MARGIN_M, -MARGIN_M), (COURT_WIDTH_M + MARGIN_M, -MARGIN_M),
        (COURT_WIDTH_M + MARGIN_M, COURT_LENGTH_M + MARGIN_M), (-MARGIN_M, COURT_LENGTH_M + MARGIN_M)]]
    cv2.polylines(img, [np.array(band, np.int32)], True, (255, 0, 255), 3)
    cv2.polylines(img, [result["corners_image"].astype(np.int32)], True, (0, 0, 255), 3)
    cv2.line(img, to_image(0, CENTRE_LINE_M), to_image(COURT_WIDTH_M, CENTRE_LINE_M), (255, 0, 0), 3)
    cv2.imwrite(str(path), img, [cv2.IMWRITE_JPEG_QUALITY, 92])


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("video", help="path to the clip")
    p.add_argument("--samples", type=int, default=PLATE_SAMPLES,
                   help="frames sampled across the clip for the median plate")
    args = p.parse_args(argv)

    video = Path(args.video).resolve()
    if not video.exists():
        raise SystemExit(f"no such clip: {video}")

    result = fit(video, args.samples)
    COURT_ROOT.mkdir(parents=True, exist_ok=True)
    stem = video.stem

    inverse = np.linalg.inv(result["homography"])
    payload = {
        "schema_version": SCHEMA_VERSION,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "video": video.name,
        "clip_sha256": clip_sha256(video),
        "frame_size": [int(result["plate"].shape[1]), int(result["plate"].shape[0])],
        "fps": result["meta"]["fps"],
        "plate_samples": args.samples,
        "court_metres": {"width": COURT_WIDTH_M, "length": COURT_LENGTH_M},
        "centre_line_m": CENTRE_LINE_M,
        "margin_m": MARGIN_M,
        "image_to_court": result["homography"].tolist(),
        "court_to_image": inverse.tolist(),
        "horizon_y": round(result["horizon_y"], 2),
        "corners_image": np.round(result["corners_image"], 2).tolist(),
        "cross_lines": result["cross_lines"],
        "held_out_error_m": {str(k): v for k, v in result["held_out_error_m"].items()},
        "sideline_inliers": list(result["sidelines"]["inliers"]),
    }
    (COURT_ROOT / f"{stem}.json").write_text(json.dumps(payload, indent=2) + "\n")
    cv2.imwrite(str(COURT_ROOT / f"{stem}_plate.png"), result["plate"])
    render_overlay(result, COURT_ROOT / f"{stem}_overlay.jpg")

    print(f"court fitted from {args.samples} sampled frames")
    print(f"  sideline inliers   {result['sidelines']['inliers']}")
    print("  cross-lines        " + "  ".join(
        f"{c['court_y']:.2f}m" for c in result["cross_lines"]))
    print(f"  horizon y          {result['horizon_y']:.1f}")
    print("  held-out markings  " + "  ".join(
        f"{k:g} m off by {v:+.3f}" for k, v in result["held_out_error_m"].items()))
    print(f"  wrote              {COURT_ROOT / f'{stem}.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
