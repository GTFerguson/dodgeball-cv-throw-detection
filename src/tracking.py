"""Following players between frames.

Association is not the interesting problem here and should not be solved by hand.
The first version in this repo was greedy nearest-neighbour on the foot point,
which has no memory: a player occluded behind a team-mate at the centre line - a
scrum that lasts most of a second - came out the other side as a new track, and a
number read before the collision did not carry across it.

ByteTrack does the two things that fixes. It predicts where a track should be with
a Kalman filter, so a gap is bridged by motion rather than by proximity, and it
runs a *second* association pass over the low-confidence detections that a
partially-occluded player produces, which is exactly the frame where the naive
matcher gave up.

It is driven from the precomputed pose run rather than from a live model, so
tracking costs no inference: the same detections the labelling tool draws are the
ones tracked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Callable

import numpy as np

from .court import IN_PLAY_HOLD_FRAMES, Court, foot_point

# ByteTrack's own defaults, with the two that this footage argues about.
#
# `track_buffer` is how many frames a lost track is kept alive to be re-found. A
# dodgeball set has players stationary at the baseline behind a moving screen of
# team-mates, so it is set to about two seconds rather than the default one.
#
# `new_track_thresh` is raised because a spurious track here is worse than a late
# one: every track is a candidate identity, and an identity that does not exist
# takes a jersey number with it.
TRACKER_ARGS = SimpleNamespace(
    track_high_thresh=0.30,
    track_low_thresh=0.10,
    new_track_thresh=0.40,
    track_buffer=50,
    match_thresh=0.80,
    fuse_score=True,
)


# A jump lifts the ankles, and at the far end of an end-on view a few dozen
# pixels of lift is metres of court: a far-baseline thrower leaves the margin in
# the air and lands back in it. Read frame by frame, the airborne frames are a
# person standing well behind the baseline, and dropping them before tracking
# leaves the throw itself untracked. So the gate holds: a detection past the
# margin is still admitted while it continues one that stood in play within the
# hold, and the crowd behind the baseline, which never stood in play, is not.
# A jump is airborne for well under a second; the hold is one, at the clip's
# 25 fps, the same window as the in-play hold.
AIRBORNE_HOLD_FRAMES = IN_PLAY_HOLD_FRAMES

# How much a detection must overlap the box it continues, frame to frame. A
# box moves a small fraction of itself per frame, in the air or on the ground;
# the tracker itself accepts far less, so this admits nothing it would not.
CONTINUITY_MIN_IOU = 0.5


@dataclass
class Carried:
    """An admitted box, and the frame its chain of detections last stood in play."""

    box: tuple[float, float, float, float]
    last_playing: int


def box_iou(a, b) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    inter = w * h
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def admit(
    detections: list[dict], playing: Callable[[dict], bool],
    carried: list[Carried], frame: int, hold: int = AIRBORNE_HOLD_FRAMES,
) -> tuple[list[dict], list[Carried]]:
    """The detections on a frame that the tracker should see, and what to carry.

    A detection in play is admitted outright and starts a fresh chain. One out
    of play is admitted if it continues a carried box whose chain stood in play
    within the hold, and inherits that chain's age rather than resetting it, so
    a bystander who once overlapped a player is carried for the hold and then
    let go. Carried boxes nothing continued survive to the next frame, so a
    frame the detector missed does not break a chain, and expire with the hold.
    """
    live = [c for c in carried if frame - c.last_playing <= hold]
    admitted: list[dict] = []
    fresh: list[Carried] = []
    for d in detections:
        box = tuple(d["box"])
        if playing(d):
            admitted.append(d)
            fresh.append(Carried(box, frame))
            continue
        best = max(live, key=lambda c: box_iou(c.box, box), default=None)
        if best is not None and box_iou(best.box, box) >= CONTINUITY_MIN_IOU:
            admitted.append(d)
            fresh.append(Carried(box, best.last_playing))
    kept = [c for c in live
            if all(box_iou(c.box, f.box) < CONTINUITY_MIN_IOU for f in fresh)]
    return admitted, fresh + kept


@dataclass
class Track:
    """One player, followed for as long as the tracker could hold on to them."""

    id: int
    frames: list[int] = field(default_factory=list)
    points: list[tuple[float, float]] = field(default_factory=list)
    detections: list[dict] = field(default_factory=list)
    reads: list = field(default_factory=list)

    @property
    def start(self) -> int:
        return self.frames[0]

    @property
    def end(self) -> int:
        return self.frames[-1]

    def at(self, frame: int) -> dict | None:
        try:
            return self.detections[self.frames.index(frame)]
        except ValueError:
            return None

    def split(self, frame: int, new_id: int) -> tuple["Track", "Track"]:
        """This track up to `frame` (exclusive), and from it on under a new id."""
        i = next((k for k, f in enumerate(self.frames) if f >= frame), len(self.frames))
        head = Track(id=self.id, frames=self.frames[:i], points=self.points[:i],
                     detections=self.detections[:i])
        tail = Track(id=new_id, frames=self.frames[i:], points=self.points[i:],
                     detections=self.detections[i:])
        return head, tail


def cut_frame(track: Track, after: int, before: int) -> int:
    """Where to split a track known to change player somewhere in (after, before].

    The change happened while the player was hidden, so the widest gap in the
    track's detections inside the window is the best estimate of when; a track
    with no gap there is cut at the first frame the new player was read.
    """
    best_gap, best_frame = 1, before
    for a, b in zip(track.frames, track.frames[1:]):
        if a >= after and b <= before and b - a > best_gap:
            best_gap, best_frame = b - a, b
    return best_frame


class _Detections:
    """The results-shaped view ByteTrack expects, over plain pose-run boxes."""

    def __init__(self, boxes: np.ndarray, conf: np.ndarray):
        self.xyxy = boxes
        self.conf = conf
        self.cls = np.zeros(len(conf), dtype=np.float32)
        if len(boxes):
            wh = boxes[:, 2:4] - boxes[:, 0:2]
            self.xywh = np.concatenate([boxes[:, 0:2] + wh / 2, wh], axis=1)
        else:
            self.xywh = np.zeros((0, 4), dtype=np.float32)

    def __len__(self) -> int:
        return len(self.conf)

    def __getitem__(self, mask) -> "_Detections":
        # ByteTrack splits its input into high- and low-confidence subsets by
        # boolean mask, so the view has to slice like the results object it
        # stands in for.
        return _Detections(self.xyxy[mask], self.conf[mask])


def track(
    court: Court, frames: dict[int, list[dict]], fps: float,
    on_court_only: bool = True,
) -> list[Track]:
    """Follow every player through the frames given, in frame order.

    Detections off the court are dropped before tracking rather than after. The
    pose run sees the whole hall, and a bench that is never tracked costs nothing
    downstream - where a bench that is tracked competes for association with the
    players in front of it. A player in the air is not off the court, whatever
    the foot point says for those frames; `admit` carries them through.
    """
    from ultralytics.trackers.byte_tracker import BYTETracker

    tracker = BYTETracker(TRACKER_ARGS)
    tracker.frame_rate = fps
    out: dict[int, Track] = {}
    carried: list[Carried] = []

    for frame in sorted(frames):
        detections = frames[frame]
        if on_court_only:
            detections, carried = admit(
                detections, lambda d: _is_playing(court, d), carried, frame)
        boxes = np.array([d["box"] for d in detections], dtype=np.float32).reshape(-1, 4)
        conf = np.array([d.get("conf", 1.0) for d in detections], dtype=np.float32)

        result = tracker.update(_Detections(boxes, conf))
        for row in result:
            # ByteTrack returns the index of the detection it matched, which is
            # what ties a track back to its keypoints - the box alone would have
            # to be matched back by value.
            index = int(row[-1])
            if not 0 <= index < len(detections):
                continue
            detection = detections[index]
            track_id = int(row[4])
            px, py, _ = foot_point(detection)
            cx, cy = court.to_court(px, py)
            entry = out.setdefault(track_id, Track(id=track_id))
            entry.frames.append(frame)
            entry.points.append((float(cx), float(cy)))
            entry.detections.append(detection)

    return [t for t in out.values() if t.frames]


def held_in_play(
    court: Court, track: Track, hold: int = IN_PLAY_HOLD_FRAMES,
) -> list[bool]:
    """Whether the player counts as in play at each frame of a track.

    A player standing on the baseline crosses it constantly - reaching for a ball,
    turning, or simply being detected a few centimetres further back than they
    were - and each crossing is a departure and a return to anything reading the
    boundary as membership. Stepping out for a moment is not leaving the game, so
    a frame counts as in play if the player was on court anywhere nearby.

    Returns one verdict per frame of the track, in the track's frame order.
    """
    raw = [bool(court.on_court(cx, cy)) for cx, cy in track.points]
    frames = track.frames
    out: list[bool] = []
    lo = hi = 0
    for i, frame in enumerate(frames):
        while lo < len(frames) and frames[lo] < frame - hold:
            lo += 1
        while hi < len(frames) and frames[hi] <= frame + hold:
            hi += 1
        out.append(any(raw[lo:hi]) if lo < hi else raw[i])
    return out


def _is_playing(court: Court, detection: dict) -> bool:
    px, py, _ = foot_point(detection)
    cx, cy = court.to_court(px, py)
    return bool(court.on_court(cx, cy)) or bool(court.in_margin(cx, cy))
