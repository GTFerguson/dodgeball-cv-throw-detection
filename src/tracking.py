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
    players in front of it.
    """
    from ultralytics.trackers.byte_tracker import BYTETracker

    tracker = BYTETracker(TRACKER_ARGS)
    tracker.frame_rate = fps
    out: dict[int, Track] = {}

    for frame in sorted(frames):
        detections = frames[frame]
        if on_court_only:
            detections = [d for d in detections if _is_playing(court, d)]
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
