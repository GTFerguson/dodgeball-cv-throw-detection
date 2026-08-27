"""What the ball did after it reached a player, read by following it through.

The chain in [[release-gate]] dies at the target's box: the ball is against
the body for a frame or three and the linker has no velocity to predict a
rebound with. What the eye sees in the next few frames is the outcome — a
hit comes back off the player the way it came, a miss carries on past — and
the count witness in [[outcome]] cannot tell two balls at one target apart.
So where the chain reached a player, the ball is followed through the
contact by a video segmenter (SAM2) seeded on the chain's last clean blob:
it re-acquires after occlusion from appearance rather than motion, which is
exactly what the chain lacks. The turn between the ball's direction into the
contact and its direction out of it is the witness; speed is not - a
rebound can come off as fast as it went in.

Measured on the evaluation clip: hits turn 80-153 degrees, misses under 30,
two of four blocks deflect, and the tracker leaves the ball before the
contact on four of twenty throws, which are reported as no answer rather
than guessed. Six visible hits is the sample; DEFLECT_MIN_TURN_DEG is set by
eye between the two groups.
"""

from __future__ import annotations

import math
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from src.ball import ball_masks, blobs_in
from src.timing import REFERENCE_FPS, frames

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WEIGHTS = REPO_ROOT / "weights" / "sam2_l.pt"

# Seed this long before the contact frame, and follow this long past it.
SEED_BEFORE_S = 0.12
FOLLOW_AFTER_S = 0.32
# The crop handed to the segmenter is square, sized by how far the ball
# moves per frame and how big the player is, then resized to CROP_SIDE_PX so
# a twenty-pixel ball is not lost in a 1024-pixel resize of the whole frame.
CROP_SPEED_FRAMES = 4.0
CROP_PLAYER_WIDTHS = 1.5
CROP_MIN_PX, CROP_MAX_PX = 320, 640
CROP_SIDE_PX = 768
# Lengths in court scale units (src/court.py); the ball is about 0.025.
BLOB_NEAR_NORM = 0.10          # a blob this close to the chain point seeds the tracker
BLOB_SIZE_NORM = (0.015, 0.075)
SEED_BOX_FACTOR = 0.7          # half-extent of the prompt box as a fraction of the blob
ON_CHAIN_NORM = 0.075          # the tracker must sit this close to the chain up to the contact
JUMP_SPEED_FRAMES = 2.0        # a step longer than this many frames of the incoming speed...
JUMP_SLACK_NORM = 0.15         # ...plus this is a jump the ball could not make: another ball
# The turn is measured over the ball's first player-widths out of the
# contact, before a wall or the floor can turn it again.
TURN_SPAN_WIDTHS = 1.5
DEFLECT_MIN_TURN_DEG = 60.0
# The chain's incoming velocity is the median step over its last links.
VELOCITY_LINKS = 3


@dataclass(frozen=True)
class Rebound:
    """What the tracker saw of one throw's ball after its contact."""

    contact_frame: int
    # Whether the tracker was on the chain from the seed to the contact; a
    # turn from a tracker that had already left the ball is not evidence.
    seeded: bool
    # Frames the ball was followed past the contact before the track ended.
    tracked: int
    turn_deg: float | None

    @property
    def deflected(self) -> bool | None:
        """True where the ball turned, False where it carried on, None for no answer."""
        if not self.seeded or self.turn_deg is None:
            return None
        return self.turn_deg >= DEFLECT_MIN_TURN_DEG


BoxOf = Callable[[int, int], tuple[float, float, float, float] | None]
Point = tuple[float, float]


def contact_frame(path: list[tuple[int, Point]], track_id: int, box_of: BoxOf,
                  margin: float) -> int | None:
    """The first chain frame whose point is inside the contact player's box."""
    for f, (x, y) in path:
        box = box_of(track_id, f)
        if box is None:
            continue
        x1, y1, x2, y2 = box
        mx, my = margin * (x2 - x1), margin * (y2 - y1)
        if x1 - mx <= x <= x2 + mx and y1 - my <= y <= y2 + my:
            return f
    return None


def incoming_velocity(points: list[Point], links: int = VELOCITY_LINKS) -> np.ndarray:
    steps = np.diff(np.asarray(points[-(links + 1):], float), axis=0)
    return np.median(steps, axis=0) if len(steps) > 1 else steps[0]


def on_chain(positions: dict[int, Point], chain: list[tuple[int, Point]], tolerance: float) -> bool:
    """Whether every tracked position on a chain frame is within tolerance of the chain."""
    pairs = [(positions[f], p) for f, p in chain if f in positions]
    return bool(pairs) and all(math.hypot(a[0] - b[0], a[1] - b[1]) <= tolerance for a, b in pairs)


def after_contact(positions: dict[int, Point], contact: int, start: Point,
                  max_step: float) -> list[Point]:
    """The tracked positions past the contact, ended at the first step the ball could not make."""
    out: list[Point] = []
    prev = positions.get(contact, start)
    for f in sorted(positions):
        if f <= contact:
            continue
        p = positions[f]
        if math.hypot(p[0] - prev[0], p[1] - prev[1]) > max_step:
            break
        out.append(p)
        prev = p
    return out


def turn(velocity: np.ndarray, points: list[Point], span: float) -> float | None:
    """Degrees between the incoming velocity and the ball's first `span` of travel out."""
    if len(points) < 2:
        return None
    end = len(points) - 1
    for i in range(1, len(points)):
        if math.hypot(points[i][0] - points[0][0], points[i][1] - points[0][1]) > span:
            end = i
            break
    disp = np.asarray(points[end], float) - np.asarray(points[0], float)
    norm = float(np.hypot(*disp) * np.hypot(*velocity))
    if norm == 0.0:
        return None
    return float(math.degrees(math.acos(float(np.clip(np.dot(disp, velocity) / norm, -1.0, 1.0)))))


# A tracker takes the clip's frames (BGR, all one size) and a prompt on the
# first - a box or a point in clip pixels - and returns the object's centre
# on every frame it found it.
Tracker = Callable[[list[np.ndarray], dict], list[Point | None]]


class Sam2Tracker:
    """SAM2 video propagation through ultralytics, one clip at a time."""

    def __init__(self, weights: str | Path = DEFAULT_WEIGHTS, imgsz: int = 1024):
        self.weights = str(weights)
        self.imgsz = imgsz
        self._tmp = tempfile.TemporaryDirectory(prefix="rebound-")

    def _predictor(self):
        import logging

        from ultralytics.models.sam import SAM2VideoPredictor
        from ultralytics.utils import LOGGER
        LOGGER.setLevel(logging.ERROR)
        # A fresh predictor per clip: the video predictor keeps a memory bank
        # for the source it was set up on, and a throw's clip is its own source.
        return SAM2VideoPredictor(overrides=dict(
            conf=0.25, task="segment", mode="predict", imgsz=self.imgsz, model=self.weights,
            verbose=False, save=False, project=self._tmp.name, name="runs", exist_ok=True))

    def __call__(self, clip: list[np.ndarray], prompt: dict) -> list[Point | None]:
        h, w = clip[0].shape[:2]
        path = Path(self._tmp.name) / "clip.mp4"
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 25, (w, h))
        for frame in clip:
            writer.write(frame)
        writer.release()
        out: list[Point | None] = []
        for r in self._predictor()(source=str(path), stream=True, **prompt):
            if r.masks is not None and len(r.masks.xy) and len(r.masks.xy[0]) > 2:
                xy = r.masks.xy[0]
                out.append((float(xy[:, 0].mean()), float(xy[:, 1].mean())))
            else:
                out.append(None)
        return out


def seed_prompt(frame: np.ndarray, point: Point, scale: float, origin: Point, up: float) -> dict:
    """A box on the colour blob under the chain point, in clip pixels; a point if there is none.

    The prompt has to be the ball and not the floor round it: a box twice the
    ball's size segments the patch, and the tracker follows the patch.
    """
    strict, _ = ball_masks(frame)
    components, _ = blobs_in(strict)
    lo, hi = BLOB_SIZE_NORM[0] * scale, BLOB_SIZE_NORM[1] * scale
    near = [(x, y, w, h) for x, y, w, h, _ in components
            if math.hypot(x - point[0], y - point[1]) <= BLOB_NEAR_NORM * scale and lo <= max(w, h) <= hi]
    if near:
        x, y, w, h = min(near, key=lambda b: math.hypot(b[0] - point[0], b[1] - point[1]))
        cx, cy = (x - origin[0]) * up, (y - origin[1]) * up
        rw, rh = SEED_BOX_FACTOR * w * up, SEED_BOX_FACTOR * h * up
        return {"bboxes": [[cx - rw, cy - rh, cx + rw, cy + rh]]}
    return {"points": [[(point[0] - origin[0]) * up, (point[1] - origin[1]) * up]], "labels": [1]}


def follow(chain: list[tuple[int, Point]], contact: int, player_box: tuple[float, float, float, float],
           scale: float, frames_at: dict[int, np.ndarray], tracker: Tracker,
           fps: float = REFERENCE_FPS) -> Rebound:
    """Seed the tracker on the chain before the contact and read the turn after it.

    `chain` is the departure path as (frame, point), `contact` the frame it
    first entered the player's box, `frames_at` the decoded frames from
    SEED_BEFORE_S before the seed to FOLLOW_AFTER_S past the contact.
    """
    before, after = frames(SEED_BEFORE_S, fps), frames(FOLLOW_AFTER_S, fps)
    pre = [(f, p) for f, p in chain if f <= contact]
    velocity = incoming_velocity([p for _, p in pre]) if len(pre) >= 2 else incoming_velocity([p for _, p in chain[:2]])
    speed = float(np.hypot(*velocity))
    seed = next(((f, p) for f, p in chain if contact - before <= f < contact), None) or pre[-1]
    first, last = seed[0], contact + after
    if any(f not in frames_at for f in range(first, last + 1)):
        return Rebound(contact_frame=contact, seeded=False, tracked=0, turn_deg=None)
    x1, y1, x2, y2 = player_box
    width = max(x2 - x1, y2 - y1)
    side = int(np.clip(CROP_SPEED_FRAMES * speed + CROP_PLAYER_WIDTHS * width, CROP_MIN_PX, CROP_MAX_PX))
    h, w = frames_at[first].shape[:2]
    cx, cy = pre[-1][1]
    ox = int(np.clip(cx - side / 2, 0, max(0, w - side)))
    oy = int(np.clip(cy - side / 2, 0, max(0, h - side)))
    up = CROP_SIDE_PX / side
    clip = [cv2.resize(frames_at[f][oy:oy + side, ox:ox + side], (CROP_SIDE_PX, CROP_SIDE_PX),
                       interpolation=cv2.INTER_CUBIC) for f in range(first, last + 1)]
    prompt = seed_prompt(frames_at[first], seed[1], scale, (ox, oy), up)
    found = tracker(clip, prompt)
    positions = {first + i: (p[0] / up + ox, p[1] / up + oy)
                 for i, p in enumerate(found) if p is not None}
    seeded = on_chain(positions, [(f, p) for f, p in chain if first <= f <= contact], ON_CHAIN_NORM * scale)
    out = after_contact(positions, contact, pre[-1][1],
                        JUMP_SPEED_FRAMES * speed + JUMP_SLACK_NORM * scale)
    return Rebound(contact_frame=contact, seeded=seeded, tracked=len(out),
                   turn_deg=turn(velocity, out, TURN_SPAN_WIDTHS * width))


def read_frames(video: str | Path, wanted: set[int]) -> dict[int, np.ndarray]:
    """Decode just the frames asked for, seeking to each run of them."""
    out: dict[int, np.ndarray] = {}
    if not wanted:
        return out
    cap = cv2.VideoCapture(str(video))
    try:
        index = None
        for f in sorted(wanted):
            if index is None or f != index + 1:
                cap.set(cv2.CAP_PROP_POS_FRAMES, f)
            ok, frame = cap.read()
            if not ok:
                break
            index = f
            out[f] = frame
    finally:
        cap.release()
    return out


def thresholds() -> dict:
    return {
        "seed_before_s": SEED_BEFORE_S, "follow_after_s": FOLLOW_AFTER_S,
        "crop_side_px": CROP_SIDE_PX, "on_chain_norm": ON_CHAIN_NORM,
        "jump_speed_frames": JUMP_SPEED_FRAMES, "jump_slack_norm": JUMP_SLACK_NORM,
        "turn_span_widths": TURN_SPAN_WIDTHS, "deflect_min_turn_deg": DEFLECT_MIN_TURN_DEG,
    }
