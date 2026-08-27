"""Throw candidates proposed from the pose run, for the annotator to judge.

Labelling from nothing means scrubbing three minutes of footage for every
throwing motion. Most of that time is finding the moment, not describing it.
This module finds the moments: for every player in play it looks for the
fastest thing a wrist does relative to the body, after that wrist has been
raised past the shoulder, and proposes the frame and the thrower. Nothing more
is claimed - not release, not whether the ball went anywhere, not the outcome.
Those are the annotator's, and the proposals are deliberately loose: a rejected
proposal costs one keypress, a throw never proposed costs the scrub the tool
exists to remove, and a missed candidate is the one error that corrupts recall.

Two things separate a throw from everything else a wrist does at speed:

* **The body is subtracted.** A sprinting arm and a diving body move the wrist
  as fast as a throw does. Measured against the shoulders, they do not.
* **The wrist has been up.** A throw is wound up first, with the wrist past the
  shoulder. Up is along the torso - hips to shoulders - not up the image, or a
  player lying on the floor has every wrist "above" the shoulder.

Speed is scale-normalised through the court fit, so one threshold serves a
near player at 280 px and a far one at 150 px.

``scripts/detect_candidates.py`` writes ``data/candidates/<stem>.json``;
:class:`CandidateSet` reads it; the labelling tool draws it and takes a verdict.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
CANDIDATES_ROOT = REPO_ROOT / "data" / "candidates"

from src.timing import REFERENCE_FPS, frames  # noqa: E402

SCHEMA_VERSION = 1

# COCO keypoint indices.
LEFT_SHOULDER, RIGHT_SHOULDER = 5, 6
LEFT_WRIST, RIGHT_WRIST = 9, 10
LEFT_HIP, RIGHT_HIP = 11, 12
KEYPOINT_MIN_CONF = 0.30

# Wrist speed relative to the shoulders, in perspective scales per second,
# is a small number; it is reported x40 so that a frame's displacement on
# the 25 fps clip the scores were tuned on reads x1000. Per second rather
# than per frame: on a half-rate clip the wrist moves twice as far a frame
# and every flick cleared MIN_SCORE.
SPEED_SCALE_PER_S = 40.0
# On the evaluation clip this admits about one proposal per expected event,
# roughly half of them throws, and lost no throw among fast non-wound-up peaks.
MIN_SCORE = 30.0
# Two peaks closer than this on one track are one motion.
MIN_SEPARATION_S = 0.48
# How far back the wrist must have been past the shoulder for a peak to count.
# The peak frame itself counts: a sidearm throw reaches the shoulder line only
# at the whip, and losing it costs recall where a spurious flick costs a keypress.
WINDUP_LOOKBACK_S = 0.32


@dataclass(frozen=True)
class Candidate:
    """One proposed throwing motion."""

    frame: int
    track_id: int
    participant_id: str
    team: str | None
    score: float
    detection_index: int
    box: tuple[float, float, float, float]


def _kp(detection: dict, index: int) -> np.ndarray | None:
    kpts = detection.get("kpts") or []
    if len(kpts) <= index or kpts[index][2] < KEYPOINT_MIN_CONF:
        return None
    return np.asarray(kpts[index][:2], float)


def shoulders(detection: dict) -> np.ndarray | None:
    """The mid-shoulder point, or one shoulder when only one is seen."""
    seen = [p for p in (_kp(detection, LEFT_SHOULDER), _kp(detection, RIGHT_SHOULDER))
            if p is not None]
    return sum(seen) / len(seen) if seen else None


def torso_up(detection: dict) -> np.ndarray | None:
    """Unit vector from the hips to the shoulders - the body's own up."""
    s = shoulders(detection)
    hips = [p for p in (_kp(detection, LEFT_HIP), _kp(detection, RIGHT_HIP)) if p is not None]
    if s is None or not hips:
        return None
    v = s - sum(hips) / len(hips)
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else None


def wound_up(detection: dict) -> bool:
    """Whether either wrist is past the shoulder line along the body's up."""
    s, up = shoulders(detection), torso_up(detection)
    if s is None or up is None:
        return False
    for w in (LEFT_WRIST, RIGHT_WRIST):
        p = _kp(detection, w)
        if p is not None and float(np.dot(p - s, up)) > 0:
            return True
    return False


def relative_wrist_speed(before: dict, after: dict, scale: float,
                         fps: float = REFERENCE_FPS) -> float:
    """How fast the faster wrist moved between two consecutive frames, with
    the shoulders' own motion taken out and the perspective scale divided off,
    as a speed per second at the clip's rate.
    """
    s0, s1 = shoulders(before), shoulders(after)
    if s0 is None or s1 is None or scale <= 0:
        return 0.0
    body = s1 - s0
    best = 0.0
    for w in (LEFT_WRIST, RIGHT_WRIST):
        p0, p1 = _kp(before, w), _kp(after, w)
        if p0 is None or p1 is None:
            continue
        best = max(best, float(np.linalg.norm((p1 - p0) - body)) / scale * fps * SPEED_SCALE_PER_S)
    return best


def peaks(scores: list[float], min_score: float = MIN_SCORE,
          min_separation: int = frames(MIN_SEPARATION_S)) -> list[int]:
    """Indices of local maxima at least `min_score` high and `min_separation`
    apart, strongest first."""
    order = sorted(range(len(scores)), key=lambda i: -scores[i])
    taken: list[int] = []
    for i in order:
        if scores[i] < min_score:
            break
        if all(abs(i - t) >= min_separation for t in taken):
            taken.append(i)
    return taken


def detect(roster, pose, court, timeline, min_score: float = MIN_SCORE) -> list[Candidate]:
    """Every proposed throw in a clip, in frame order.

    Only player tracks, only frames where the player was in play and a set was
    live: a referee's arm is not a candidate, and nothing before the whistle is.
    """
    from src.court import foot_point

    intervals = timeline.live_play_intervals()
    lookback = frames(WINDUP_LOOKBACK_S, pose.fps)

    def live(frame: int) -> bool:
        return any(iv.contains(frame) for iv in intervals)

    out: list[Candidate] = []
    for track in roster.player_tracks():
        seq = [(f, i) for f, i in track.detections if live(f) and track.is_in_play(f)]
        if len(seq) < 2:
            continue
        dets = [pose.frame(f)[i] for f, i in seq]
        scores = [0.0]
        for k in range(1, len(seq)):
            if seq[k][0] != seq[k - 1][0] + 1:
                scores.append(0.0)
                continue
            _, foot_y, _ = foot_point(dets[k])
            scores.append(relative_wrist_speed(dets[k - 1], dets[k], float(court.scale_at(foot_y)),
                                               pose.fps))
        for k in peaks(scores, min_score, frames(MIN_SEPARATION_S, pose.fps)):
            if not any(wound_up(d) for d in dets[max(0, k - lookback):k + 1]):
                continue
            frame, index = seq[k]
            out.append(Candidate(
                frame=frame, track_id=track.id, participant_id=track.participant_id,
                team=track.team, score=round(scores[k], 1), detection_index=index,
                box=tuple(float(v) for v in dets[k]["box"])))
    out.sort(key=lambda c: (c.frame, c.track_id))
    return out


@dataclass
class CandidateSet:
    video: str
    clip_sha256: str
    pose_run: str
    fps: float
    thresholds: dict
    candidates: list[Candidate]

    @classmethod
    def load(cls, path: str | Path) -> "CandidateSet":
        data = json.loads(Path(path).read_text())
        if data.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"{path} is schema {data.get('schema_version')}, "
                             f"expected {SCHEMA_VERSION}")
        return cls(
            video=data["video"], clip_sha256=data["clip_sha256"], pose_run=data["pose_run"],
            fps=data["fps"], thresholds=dict(data["thresholds"]),
            candidates=[Candidate(
                frame=c["frame"], track_id=c["track_id"], participant_id=c["participant"],
                team=c["team"], score=c["score"], detection_index=c["detection_index"],
                box=tuple(c["box"])) for c in data["candidates"]],
        )

    @classmethod
    def for_video(cls, video: str | Path) -> "CandidateSet":
        return cls.load(CANDIDATES_ROOT / f"{Path(video).stem}.json")

    def check_clip(self, clip_sha256: str) -> None:
        if self.clip_sha256 != clip_sha256:
            raise ValueError(f"candidates for {self.video} were detected on a different clip")

    def to_json(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "video": self.video,
            "clip_sha256": self.clip_sha256,
            "pose_run": self.pose_run,
            "fps": self.fps,
            "thresholds": dict(self.thresholds),
            "candidates": [{
                "frame": c.frame, "track_id": c.track_id, "participant": c.participant_id,
                "team": c.team, "score": c.score, "detection_index": c.detection_index,
                "box": [round(v, 1) for v in c.box],
            } for c in self.candidates],
        }

    def write(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_json(), indent=1))
        return path

    def near(self, frame: int, tolerance: int) -> list[Candidate]:
        """Proposals within `tolerance` frames of a frame."""
        return [c for c in self.candidates if abs(c.frame - frame) <= tolerance]
