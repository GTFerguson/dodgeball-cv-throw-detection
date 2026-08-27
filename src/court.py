"""Court geometry: the reader side of the calibration in ``data/court/``.

Written by ``scripts/fit_court.py``, read by everything that needs to know where
something is on the floor. Positions are in metres, x across the court and y
along it from the near baseline, so a value is meaningful without knowing which
part of the image it came from.

Distances in this footage cannot be reasoned about in pixels. The camera is
elevated and end-on, so one metre of floor spans roughly 190 px at the near
baseline and 45 px at the far one. Any threshold expressed in pixels is therefore
wrong at one end of the court whatever value it takes; the same threshold in
metres is right at both.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

# setstart and the court scripts import this module bare off src/; the rest
# of the pipeline imports it as a package. The config must load either way.
try:
    from src.venue import VENUE
except ImportError:  # pragma: no cover - the bare-path import
    from venue import VENUE

REPO_ROOT = Path(__file__).resolve().parent.parent
COURT_ROOT = REPO_ROOT / "data" / "court"

SCHEMA_VERSION = 1

# A regulation volleyball court, which is what this venue's floor is. Asserted by
# the fit rather than assumed: see docs/architecture/court-geometry.md. The
# dimensions are the venue's (config/venue.toml), not the pipeline's.
COURT_WIDTH_M = float(VENUE["court"]["width_m"])
COURT_LENGTH_M = float(VENUE["court"]["length_m"])

# The line teams may not cross, which is the net line on this floor.
CENTRE_LINE_M = COURT_LENGTH_M / 2

# Volleyball markings measured along the court from the near baseline. Held out
# of the homography fit and used only to validate it.
HELD_OUT_MARKINGS_M = (6.0, 9.0, 12.0)
MARKING_TOLERANCE_M = 0.25

# How far outside the boundary still counts as court-adjacent: wide enough that a
# player leaving is seen crossing it over several frames rather than appearing to
# teleport out, narrow enough to leave the benches and crowd outside.
MARGIN_M = float(VENUE["court"]["margin_m"])

# Slack on the boundary test, as a budget of ankle-keypoint error in *pixels*.
#
# A foot point is quantised by detection noise and the lines have real width, so
# an exact test would flicker for a player standing on the line - and flicker
# reads downstream as a player leaving and returning. The slack was a flat 0.10 m,
# which failed because a metre is not worth the same everywhere: the camera is
# end-on, so on this footage's fit a metre along the court is five times fewer
# pixels at the far baseline than at the near one. A tenth of a metre bought ten
# pixels of tolerance near the camera and under two at the far baseline, which is
# less than the keypoint's own wobble, and the far-side waiting line strobed in
# and out of play.
#
# Spending the budget in pixels puts it where the pixels are scarce. Set from the
# 90th percentile of the ankle overshoot measured on the flickering tracks of the
# evaluation clip; docs/architecture/court-geometry.md carries the derivation.
ANKLE_SLACK_PX = 8.0

# A ceiling on what that budget can buy. A point projecting near the horizon has
# an unbounded metres-per-pixel, and the in-play test has to stay clear of the
# court-adjacent ring regardless: if the two overlap they stop being disjoint and
# the eliminated queue joins the roster. Kept well inside MARGIN_M, and above what
# the budget is worth at the far baseline, so it binds only on degenerate geometry.
MAX_BOUNDARY_SLACK_M = 0.75

# How far either side of a frame a player is still counted as in play, having
# been seen on court there. Set from the excursions measured on the evaluation
# clip: with the boundary slack already spent in pixels, a one-second hold absorbs
# 93 of the 113 excursions that returned, and two seconds buys only four more.
#
# The window is deliberately *symmetric* rather than a timeout. A causal "still
# counts for a second after they were last seen" rule makes in-play depend on the
# direction the clip was played, so the same frame shows a different roster
# depending on whether the annotator scrubbed forwards or backwards onto it. In
# play has to be a function of the frame and nothing else.
IN_PLAY_HOLD_FRAMES = 25

# COCO-17 indices. Ultralytics pose models emit this layout; the manifest records
# it so a consumer never has to assume.
LEFT_ANKLE, RIGHT_ANKLE = 15, 16

# Below this an ankle keypoint is a guess, and a guessed ankle places a player
# somewhere they are not. The box is a worse estimator but a more honest one.
ANKLE_MIN_CONF = 0.30


@dataclass(frozen=True)
class Court:
    """A fitted court, loaded from ``data/court/<video-stem>.json``."""

    video: str
    clip_sha256: str
    frame_size: tuple[int, int]
    fps: float
    image_to_court: np.ndarray
    court_to_image: np.ndarray
    horizon_y: float
    corners_image: np.ndarray
    cross_lines: list[dict]
    held_out_error_m: dict[str, float]

    @classmethod
    def load(cls, path: str | Path) -> "Court":
        data = json.loads(Path(path).read_text())
        if data.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(
                f"{path} is schema {data.get('schema_version')}, expected {SCHEMA_VERSION}")
        return cls(
            video=data["video"],
            clip_sha256=data["clip_sha256"],
            frame_size=tuple(data["frame_size"]),
            fps=data["fps"],
            image_to_court=np.array(data["image_to_court"], float),
            court_to_image=np.array(data["court_to_image"], float),
            horizon_y=float(data["horizon_y"]),
            corners_image=np.array(data["corners_image"], float),
            cross_lines=data["cross_lines"],
            held_out_error_m={k: float(v) for k, v in data["held_out_error_m"].items()},
        )

    @classmethod
    def for_video(cls, video: str | Path) -> "Court":
        return cls.load(COURT_ROOT / f"{Path(video).stem}.json")

    def _apply(self, h: np.ndarray, a, b):
        a, b = np.asarray(a, float), np.asarray(b, float)
        pts = np.stack(np.broadcast_arrays(a, b, np.ones_like(a)), axis=-1)
        v = pts @ h.T
        out = v[..., :2] / v[..., 2:3]
        if out.ndim == 1:
            return float(out[0]), float(out[1])
        return out[..., 0], out[..., 1]

    def to_court(self, x, y):
        """Image pixels -> court metres. Scalars or arrays."""
        return self._apply(self.image_to_court, x, y)

    def to_image(self, cx, cy):
        """Court metres -> image pixels. Scalars or arrays."""
        return self._apply(self.court_to_image, cx, cy)

    def slack_at(self, cx, cy):
        """The boundary slack in metres at a court position.

        One pixel of image is worth more court at the far end than the near, so
        the budget is converted where it is spent: measured against the court,
        one image row up from the point itself.
        """
        ix, iy = self.to_image(cx, cy)
        _, up = self.to_court(ix, np.asarray(iy, float) - 1.0)
        metres_per_pixel = np.abs(np.asarray(up, float) - np.asarray(cy, float))
        return np.minimum(ANKLE_SLACK_PX * metres_per_pixel, MAX_BOUNDARY_SLACK_M)

    def on_court(self, cx, cy):
        cx, cy = np.asarray(cx), np.asarray(cy)
        # NaN slack - a point projecting through the horizon - fails every
        # comparison, which puts it off court rather than everywhere at once.
        s = self.slack_at(cx, cy)
        return ((cx >= -s) & (cx <= COURT_WIDTH_M + s)
                & (cy >= -s) & (cy <= COURT_LENGTH_M + s))

    def in_margin(self, cx, cy):
        """Court-adjacent but out of play - where a crossing is observed."""
        cx, cy = np.asarray(cx), np.asarray(cy)
        near = ((cx >= -MARGIN_M) & (cx <= COURT_WIDTH_M + MARGIN_M)
                & (cy >= -MARGIN_M) & (cy <= COURT_LENGTH_M + MARGIN_M))
        return near & ~self.on_court(cx, cy)

    def half(self, cy):
        """Which team's half a court position falls in.

        Teams cannot cross the centre line, so the half a thrower stands in gives
        their team directly - no appearance model, and nothing to re-derive when
        kit or lighting changes.
        """
        return np.where(np.asarray(cy) < CENTRE_LINE_M, "near", "far")

    def scale_at(self, foot_y):
        """Perspective scale factor at an image row, in arbitrary consistent units.

        The court's cross-lines are image-horizontal, so the horizon is a known
        row, and a vertical object of fixed height projects to a pixel height
        proportional to its foot point's distance below it. Dividing a pixel
        measurement by this makes it comparable between a near player at 280 px
        tall and a far one at 150 px, which is what lets one threshold serve both
        ends of the court. The constant of proportionality depends on camera
        height and cancels, so it is never needed.
        """
        return np.asarray(foot_y, float) - self.horizon_y

    def normalise(self, pixels, foot_y):
        """A pixel measurement rendered scale-invariant for its court position."""
        return np.asarray(pixels, float) / self.scale_at(foot_y)


def foot_point(detection: dict) -> tuple[float, float, str]:
    """Where a detected person meets the floor, and how confidently.

    The box bottom edge is only the feet for someone standing. Dodgeball players
    dive and lie prone constantly - most of all at the centre line, where they
    lunge for balls - and for those the box bottom is wherever the body happens to
    end, which places them metres from where they are. Ankle keypoints survive
    that; the box is the fallback when they are not visible at all.

    Returns the point plus its source, so callers can report how often the
    fallback fired instead of presenting both as equally trustworthy.
    """
    kpts = detection.get("kpts") or []
    ankles = [kpts[i] for i in (LEFT_ANKLE, RIGHT_ANKLE)
              if len(kpts) > i and kpts[i][2] >= ANKLE_MIN_CONF]
    if ankles:
        x = sum(a[0] for a in ankles) / len(ankles)
        y = sum(a[1] for a in ankles) / len(ankles)
        return x, y, "ankles" if len(ankles) == 2 else "ankle"
    x1, y1, x2, y2 = detection["box"]
    return 0.5 * (x1 + x2), y2, "box"
