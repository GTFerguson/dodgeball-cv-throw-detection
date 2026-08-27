#!/usr/bin/env python
"""Draw the fitted court, and optionally the detections, over a frame of the clip.

Calibration is geometry claimed about pixels, and the only honest way to check a
claim about pixels is to look at them. This renders from the committed JSON via
the same reader the pipeline uses, so what is drawn is what the pipeline believes
- a render that looked right while the pipeline was wrong would mean the two had
diverged.

The counts in the title bar are the check worth reading: a live set is twelve
players, six a side, and the near/far split should fall on the centre line.

Usage::

    .venv/bin/python scripts/render_court_overlay.py data/footage/clip.mp4 --frame 625
    .venv/bin/python scripts/render_court_overlay.py data/footage/clip.mp4 --plate
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from court import (  # noqa: E402
    CENTRE_LINE_M,
    COURT_LENGTH_M,
    COURT_WIDTH_M,
    MARGIN_M,
    Court,
    foot_point,
)
from overlay import WIRE_OFF, bgr, casing_for, wire_for  # noqa: E402
from pose import PoseRun  # noqa: E402

OUT_ROOT = REPO_ROOT / "data" / "court"

BOUNDARY_BGR = (0, 0, 255)
CENTRE_BGR = (255, 60, 0)
GRID_BGR = (0, 220, 220)

# The margin band is court furniture, so it is kept clear of the wire hues: a
# magenta band beside a violet far-team wire reads as the same statement twice.
MARGIN_BGR = (150, 130, 110)

# Out of play is drawn as the absence of a team rather than as a third team, and
# the margin is separated from the rejected only by weight.
OFF_BGR = bgr(WIRE_OFF)
REJECTED_BGR = (90, 90, 92)

# The grid is context, not the subject; drawn full strength it competes with the
# boxes that are actually being judged.
GRID_OPACITY = 0.35


def draw_court(img: np.ndarray, court: Court) -> np.ndarray:
    def px(cx, cy):
        x, y = court.to_image(cx, cy)
        return int(round(x)), int(round(y))

    grid = img.copy()
    for cy in np.arange(0, COURT_LENGTH_M + 0.01, 1.0):
        cv2.line(grid, px(0, cy), px(COURT_WIDTH_M, cy), GRID_BGR, 1)
    for cx in np.arange(0, COURT_WIDTH_M + 0.01, 1.0):
        cv2.line(grid, px(cx, 0), px(cx, COURT_LENGTH_M), GRID_BGR, 1)
    img = cv2.addWeighted(grid, GRID_OPACITY, img, 1 - GRID_OPACITY, 0)

    band = [px(x, y) for x, y in [
        (-MARGIN_M, -MARGIN_M), (COURT_WIDTH_M + MARGIN_M, -MARGIN_M),
        (COURT_WIDTH_M + MARGIN_M, COURT_LENGTH_M + MARGIN_M), (-MARGIN_M, COURT_LENGTH_M + MARGIN_M)]]
    cv2.polylines(img, [np.array(band, np.int32)], True, MARGIN_BGR, 2)
    cv2.polylines(img, [court.corners_image.astype(np.int32)], True, BOUNDARY_BGR, 3)
    cv2.line(img, px(0, CENTRE_LINE_M), px(COURT_WIDTH_M, CENTRE_LINE_M), CENTRE_BGR, 3)
    return img


def draw_detections(img: np.ndarray, court: Court, detections: list[dict]) -> dict:
    """Box every detection, coloured by the team whose half its feet are in.

    Which half a foot point lands in is the whole of the team claim, so drawing
    the box in that team's wire colour makes the claim checkable against the
    kit underneath it: a red player in a violet box is the fit or the foot point
    being wrong, and it is visible at a glance across the frame.
    """
    tally = {"court": 0, "margin": 0, "rejected": 0, "near": 0, "far": 0, "box_fallback": 0}
    for det in detections:
        fx, fy, source = foot_point(det)
        cx, cy = court.to_court(fx, fy)
        on, band = bool(court.on_court(cx, cy)), bool(court.in_margin(cx, cy))
        half = str(court.half(cy))
        colour = bgr(wire_for(half)) if on else (OFF_BGR if band else REJECTED_BGR)
        tally["court" if on else ("margin" if band else "rejected")] += 1
        if on:
            tally[half] += 1
            if source == "box":
                tally["box_fallback"] += 1
        x1, y1, x2, y2 = (int(v) for v in det["box"])
        cv2.rectangle(img, (x1, y1), (x2, y2), colour, 2 if on else 1)
        cv2.circle(img, (int(fx), int(fy)), 4, colour, -1)
        if on:
            # Same casing rule as the tool's wires: the label is legible on the
            # kit under it without the hue having to fight for it.
            for weight, ink in ((3, bgr(casing_for(wire_for(half)))), (1, colour)):
                cv2.putText(img, f"{cx:.1f},{cy:.1f}", (x1, y1 - 5),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, ink, weight, cv2.LINE_AA)
    return tally


def caption(img: np.ndarray, text: str) -> None:
    cv2.rectangle(img, (0, 0), (img.shape[1], 34), (0, 0, 0), -1)
    cv2.putText(img, text, (12, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)


def read_frame(video: Path, index: int) -> np.ndarray:
    cap = cv2.VideoCapture(str(video))
    cap.set(cv2.CAP_PROP_POS_FRAMES, index)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise SystemExit(f"cannot read frame {index} of {video}")
    return frame


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("video", help="path to the clip")
    p.add_argument("--frame", type=int, default=0, help="frame index to render")
    p.add_argument("--plate", action="store_true",
                   help="render on the median plate instead of a frame, for the bare fit")
    p.add_argument("--no-detections", action="store_true")
    p.add_argument("--run-id", default=None, help="pose run, when a clip has more than one")
    p.add_argument("--out", default=None)
    p.add_argument("--open", action="store_true", help="open the result in the image viewer")
    args = p.parse_args(argv)

    video = Path(args.video).resolve()
    court = Court.for_video(video)

    if args.plate:
        plate = OUT_ROOT / f"{video.stem}_plate.png"
        if not plate.exists():
            raise SystemExit(f"no plate at {plate}; run scripts/fit_court.py")
        img, label = cv2.imread(str(plate)), "median plate"
    else:
        img, label = read_frame(video, args.frame), f"frame {args.frame}  t={args.frame / court.fps:.2f}s"

    img = draw_court(img, court)
    bar = label
    if not args.plate and not args.no_detections:
        run = PoseRun.for_video(video, args.run_id)
        run.check_clip(court.clip_sha256)
        if args.frame >= run.frames_done:
            print(f"warning: frame {args.frame} is beyond the {run.frames_done} frames "
                  f"computed so far; detections will be empty", file=sys.stderr)
        t = draw_detections(img, court, run.frame(args.frame))
        bar += (f"   on court {t['court']} (near {t['near']} / far {t['far']})"
                f"   margin {t['margin']}   rejected {t['rejected']}"
                f"   box-fallback {t['box_fallback']}")
    caption(img, bar)

    out = Path(args.out) if args.out else OUT_ROOT / (
        f"{video.stem}_plate_overlay.jpg" if args.plate else f"{video.stem}_f{args.frame:05d}.jpg")
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), img, [cv2.IMWRITE_JPEG_QUALITY, 94])
    print(f"{bar}\nwrote {out}")
    if args.open:
        import subprocess
        subprocess.Popen(["xdg-open", str(out)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return 0


if __name__ == "__main__":
    sys.exit(main())
