"""What the ball did at the player it reached, read by following it there and through.

The chain in [[release-gate]] links colour blobs on a velocity prediction
and dies twice over at the target: it loses a fast ball short of the box,
and where it does reach the box the ball is against the body for a frame or
three and comes out in a new direction, which the prediction does not allow.
What the eye sees in the next few frames is the outcome - a hit comes back
off the player the way it came, a miss carries on past, a block deflects
with nobody leaving - and the count witness in [[outcome]] cannot tell two
balls at one target apart, or see a block at all.

So from the chain's last clean blob the ball is followed by a video
segmenter (SAM2), which re-acquires after occlusion from appearance rather
than motion: forward until it enters a player's box - the contact, whether
or not the chain got there - and on through it. The turn between the ball's
direction into the contact and its direction out is the witness; speed is
not, a rebound can come off as fast as it went in.

Measured on the evaluation clip: hits turn 80-153 degrees, misses under 30,
and blocks deflect. The tracker leaves a fast ball before it arrives on a
few throws, which are reported as no answer rather than guessed. Six
visible hits is the sample; DEFLECT_MIN_TURN_DEG is set by eye between the
two groups.
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

# The seed is the chain's last point with a clean blob under it, looking
# back this many points from the end - the chain's last link is often the
# one that went wrong. Chains shorter than this are not followed.
SEED_LOOKBACK_LINKS = 3
# Follow the ball this long looking for a player, then this long past the
# contact, in segments: each segment is one tracker run on a tight crop
# round the ball, re-seeded from the last position, so a twenty-pixel ball
# is never handed to the segmenter small.
EXTEND_MAX_S = 0.48
FOLLOW_AFTER_S = 0.32
SEGMENT_S = 0.32
# The crop is square, sized by how far the ball moves in a segment and the
# court scale where it is, and resized to CROP_SIDE_PX.
CROP_SPEED_MARGIN = 1.5
CROP_SCALE_NORM = 0.5
CROP_MIN_PX, CROP_MAX_PX = 320, 640
CROP_SIDE_PX = 768
# Lengths in court scale units (src/court.py); the ball is about 0.025.
BLOB_NEAR_NORM = 0.10          # a blob this close to the chain point seeds the tracker
BLOB_SIZE_NORM = (0.015, 0.075)
SEED_BOX_FACTOR = 0.7          # half-extent of the prompt box as a fraction of the blob
ON_CHAIN_NORM = 0.075          # the tracker must sit this close to the chain where they overlap
JUMP_SPEED_FRAMES = 2.0        # a step longer than this many frames of the ball's speed...
JUMP_SLACK_NORM = 0.15         # ...plus this is a jump the ball could not make: another ball
# The ball's direction into a box is the median of its last steps.
VELOCITY_LINKS = 3
# The turn is measured over the ball's first player-widths out of the box,
# before a wall or the floor can turn it again.
TURN_SPAN_WIDTHS = 1.5
DEFLECT_MIN_TURN_DEG = 60.0
# A turn this close to the bottom of the box is the floor at the player's
# feet, not the player: the ball bounced beside them.
FLOOR_BAND = 0.15


@dataclass(frozen=True)
class Contact:
    frame: int
    team: str | None
    track_id: int
    participant_id: str


@dataclass(frozen=True)
class Rebound:
    """What the tracker saw of one throw's ball on its way to a player and after."""

    # Whether the tracker sat on the chain where the two overlap; a tracker
    # that had already left the ball has nothing to say about what it did next.
    seeded: bool
    # The player the ball turned at, or the last one it passed through.
    contact: Contact | None
    # Frames the ball was followed past the contact before the track ended.
    tracked: int
    turn_deg: float | None
    # True where the ball turned at the player, False where it carried on
    # through (or bounced at their feet), None for no answer.
    deflected: bool | None = None
    # How many players' boxes the ball went through without turning.
    passed: int = 0


Point = tuple[float, float]
Box = tuple[float, float, float, float]
# For a frame, every player as (team, track id, participant id, box).
PlayersAt = Callable[[int], list[tuple[str | None, int, str, Box]]]


def inside(point: Point, box: Box, margin: float) -> bool:
    x1, y1, x2, y2 = box
    mx, my = margin * (x2 - x1), margin * (y2 - y1)
    return x1 - mx <= point[0] <= x2 + mx and y1 - my <= point[1] <= y2 + my


def box_entries(points: list[tuple[int, Point]], players_at: PlayersAt, thrower: int,
                margin: float) -> list[tuple[int, Contact, Box]]:
    """Each player's box the ball enters, at the index it enters it, the thrower's own excluded."""
    entries: list[tuple[int, Contact, Box]] = []
    inside_now: set[int] = set()
    for i, (f, p) in enumerate(points):
        here: set[int] = set()
        for team, track_id, participant_id, box in players_at(f):
            if track_id == thrower or not inside(p, box, margin):
                continue
            here.add(track_id)
            if track_id not in inside_now:
                entries.append((i, Contact(f, team, track_id, participant_id), box))
        inside_now = here
    return entries


def at_the_feet(point: Point, box: Box) -> bool:
    return point[1] >= box[3] - FLOOR_BAND * (box[3] - box[1])


def velocity_into(points: list[Point], links: int = VELOCITY_LINKS) -> np.ndarray:
    steps = np.diff(np.asarray(points[-(links + 1):], float), axis=0)
    return np.median(steps, axis=0) if len(steps) > 1 else steps[0]


def on_chain(positions: dict[int, Point], chain: list[tuple[int, Point]], tolerance: float) -> bool:
    """Whether every tracked position on a chain frame is within tolerance of the chain."""
    pairs = [(positions[f], p) for f, p in chain if f in positions]
    return bool(pairs) and all(math.hypot(a[0] - b[0], a[1] - b[1]) <= tolerance for a, b in pairs)


def cut_at_jump(positions: dict[int, Point], start: Point, speed: float,
                slack: float) -> list[tuple[int, Point]]:
    """The tracked positions in order, ended at the first step the ball could not make."""
    out: list[tuple[int, Point]] = []
    prev = start
    for f in sorted(positions):
        p = positions[f]
        if math.hypot(p[0] - prev[0], p[1] - prev[1]) > JUMP_SPEED_FRAMES * speed + slack:
            break
        out.append((f, p))
        prev = p
    return out


def turn(velocity: np.ndarray, points: list[Point], span: float,
         box: Box | None = None, margin: float = 0.0) -> float | None:
    """Degrees between the incoming velocity and the ball's travel out of the entry point.

    Measured to where the ball leaves the box it entered at `points[0]` - a
    ball out the far side passed through, one back out the near side turned -
    or, where it never leaves, over its first `span` of travel.
    """
    if len(points) < 2:
        return None
    end = len(points) - 1
    for i in range(1, len(points)):
        if box is not None and not inside(points[i], box, margin):
            end = i
            break
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


def blob_under(frame: np.ndarray, point: Point, scale: float) -> tuple[float, float, int, int] | None:
    """The ball-sized colour blob nearest the point, if one is close enough."""
    strict, _ = ball_masks(frame)
    components, _ = blobs_in(strict)
    lo, hi = BLOB_SIZE_NORM[0] * scale, BLOB_SIZE_NORM[1] * scale
    near = [(x, y, w, h) for x, y, w, h, _ in components
            if math.hypot(x - point[0], y - point[1]) <= BLOB_NEAR_NORM * scale and lo <= max(w, h) <= hi]
    return min(near, key=lambda b: math.hypot(b[0] - point[0], b[1] - point[1])) if near else None


def seed_prompt(blob: tuple[float, float, int, int] | None, point: Point, origin: Point, up: float) -> dict:
    """A box on the blob in clip pixels; a point on the chain if there is none.

    The prompt has to be the ball and not the floor round it: a box twice the
    ball's size segments the patch, and the tracker follows the patch.
    """
    if blob is not None:
        x, y, w, h = blob
        cx, cy = (x - origin[0]) * up, (y - origin[1]) * up
        rw, rh = SEED_BOX_FACTOR * w * up, SEED_BOX_FACTOR * h * up
        return {"bboxes": [[cx - rw, cy - rh, cx + rw, cy + rh]]}
    return {"points": [[(point[0] - origin[0]) * up, (point[1] - origin[1]) * up]], "labels": [1]}


def window_for(chain: list[tuple[int, Point]], fps: float = REFERENCE_FPS) -> tuple[int, int]:
    """The frames the tracker may need for a chain: from its seed to the end of the follow."""
    seed = chain[max(0, len(chain) - SEED_LOOKBACK_LINKS)][0]
    return seed, seed + frames(EXTEND_MAX_S, fps) + frames(FOLLOW_AFTER_S, fps)


def _segment(frames_at: dict[int, np.ndarray], first: int, last: int, seed: Point, velocity: np.ndarray,
             blob, scale: float, tracker: Tracker) -> dict[int, Point]:
    """One tracker run on a crop round the ball, from `first` to `last`; positions in frame pixels."""
    h, w = frames_at[first].shape[:2]
    speed = float(np.hypot(*velocity))
    side = int(np.clip(CROP_SPEED_MARGIN * speed * (last - first) + CROP_SCALE_NORM * scale,
                       CROP_MIN_PX, min(CROP_MAX_PX, h, w)))
    centre = np.asarray(seed, float) + velocity * ((last - first) / 2.0)
    ox = int(np.clip(centre[0] - side / 2, 0, w - side))
    oy = int(np.clip(centre[1] - side / 2, 0, h - side))
    up = CROP_SIDE_PX / side
    clip = [cv2.resize(frames_at[f][oy:oy + side, ox:ox + side], (CROP_SIDE_PX, CROP_SIDE_PX),
                       interpolation=cv2.INTER_CUBIC if up > 1 else cv2.INTER_AREA)
            for f in range(first, last + 1)]
    found = tracker(clip, seed_prompt(blob, seed, (ox, oy), up))
    return {first + i: (p[0] / up + ox, p[1] / up + oy) for i, p in enumerate(found) if p is not None}


def follow(chain: list[tuple[int, Point]], thrower: int, players_at: PlayersAt, margin: float,
           scale_at: Callable[[float], float], frames_at: dict[int, np.ndarray], tracker: Tracker,
           fps: float = REFERENCE_FPS) -> Rebound:
    """Seed the tracker on the chain's last clean blob and follow the ball to a player and through.

    `chain` is the departure path as (frame, point); `players_at` every
    player's box on a frame; `scale_at` the court scale at an image row;
    `frames_at` the decoded frames over `window_for(chain)`. The contact is
    the first box the ball turns in; boxes it passes straight through are
    not contacts, and a turn at the bottom of a box is the floor.
    """
    none = Rebound(seeded=False, contact=None, tracked=0, turn_deg=None)
    first, last = window_for(chain, fps)
    if len(chain) < SEED_LOOKBACK_LINKS or any(f not in frames_at for f in range(first, last + 1)):
        return none
    # the seed: the last chain point with a blob under it, else the earliest looked at
    candidates = [(f, p) for f, p in chain if f >= first]
    scale = float(scale_at(candidates[-1][1][1]))
    seed, blob = candidates[0], None
    for f, p in reversed(candidates):
        blob = blob_under(frames_at[f], p, scale)
        if blob is not None:
            seed = (f, p)
            break
    path = [(f, p) for f, p in chain if f <= seed[0]]
    segment = frames(SEGMENT_S, fps)
    after = frames(FOLLOW_AFTER_S, fps)
    seeded: bool | None = None
    start, prompt_blob = seed, blob
    while True:
        end = min(start[0] + segment, last)
        velocity = velocity_into([p for _, p in path]) if len(path) >= 2 else velocity_into([p for _, p in chain[:2]])
        found = _segment(frames_at, start[0], end, start[1], velocity, prompt_blob, scale, tracker)
        found.pop(start[0], None)
        if seeded is None:
            seeded = on_chain(found, [(f, p) for f, p in chain if f > start[0]], ON_CHAIN_NORM * scale) \
                if any(f > start[0] for f, _ in chain) else bool(found)
        track = cut_at_jump(found, start[1], float(np.hypot(*velocity)), JUMP_SLACK_NORM * scale)
        path += track
        # stop when the ball is lost, the window is spent, or the follow past a turn is long enough
        if not track or track[-1][0] < end or end >= last:
            break
        entries = box_entries(path, players_at, thrower, margin)
        if entries and len(path) - entries[0][0] > after:
            break
        start = track[-1]
        scale = float(scale_at(start[1][1]))
        prompt_blob = blob_under(frames_at[start[0]], start[1], scale)
    # the contact: the first box the ball turns in; pass-throughs are counted and skipped
    passed = 0
    through: tuple[Contact, int, float | None] | None = None
    for i, contact, box in box_entries(path, players_at, thrower, margin):
        into = [p for _, p in path[:i + 1]]
        out = [p for _, p in path[i:]]
        width = max(box[2] - box[0], box[3] - box[1])
        t = turn(velocity_into(into), out, TURN_SPAN_WIDTHS * width, box, margin) if len(into) >= 2 else None
        if len(out) < 2:
            return Rebound(seeded=bool(seeded), contact=contact, tracked=0, turn_deg=None, passed=passed)
        if t is not None and t >= DEFLECT_MIN_TURN_DEG and not at_the_feet(path[i][1], box):
            return Rebound(seeded=bool(seeded), contact=contact, tracked=len(out) - 1, turn_deg=t,
                           deflected=True if seeded else None, passed=passed)
        passed += 1
        through = (contact, len(out) - 1, t)
    if through is not None:
        contact, n, t = through
        return Rebound(seeded=bool(seeded), contact=contact, tracked=n, turn_deg=t,
                       deflected=False if seeded else None, passed=passed - 1)
    return Rebound(seeded=bool(seeded), contact=None, tracked=0, turn_deg=None, passed=0)


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
        "seed_lookback_links": SEED_LOOKBACK_LINKS, "extend_max_s": EXTEND_MAX_S,
        "follow_after_s": FOLLOW_AFTER_S, "segment_s": SEGMENT_S, "crop_side_px": CROP_SIDE_PX,
        "floor_band": FLOOR_BAND,
        "on_chain_norm": ON_CHAIN_NORM, "jump_speed_frames": JUMP_SPEED_FRAMES,
        "jump_slack_norm": JUMP_SLACK_NORM, "turn_span_widths": TURN_SPAN_WIDTHS,
        "deflect_min_turn_deg": DEFLECT_MIN_TURN_DEG,
    }
