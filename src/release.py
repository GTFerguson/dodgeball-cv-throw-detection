"""From proposed throwing motions to events, and from events to releases.

Two decisions, each on the ball rather than the body, because the body has
already been asked everything it can answer by ``src/candidates``:

**Is this an event at all?** A throw or a fake is wound up with a ball in the
hand. The proposals the annotator rejected are bodies doing other things at
speed - the opening sprint, standing up, dodging, a pose glitch - and most of
them have no ball at the wrist in the frames before the peak. Two structural
cuts come first: nothing inside the opening rush, when the balls are still
on the centre line; and nothing after the set has ended, which this layer
cannot know and leaves to the timeline's bound.

**Was the ball released?** A fake keeps the ball; a throw's ball leaves. But
"the disc on the wrist went dark" is also what a ball tucked behind the body
looks like, and a second ball held in the other hand keeps the disc lit
through a genuine release. So the claim is made on seeing the ball *leave*:
a blob at the hand, then a chain of blobs stepping away from it frame by
frame, each step continuing the last one's direction, reaching a distance no
hand could carry it in the time. The chain may bridge one frame in which the
ball is not seen - at the whip it is a desaturated streak the mask can
drop - and no link may land on a blob that was already there the frame
before, because a ball in flight is never where it was: that one test is
what stops a chain hopping between socks, a ball on the floor and the
other hand's ball.

**Where did it go?** A pass is a throw that stays on the thrower's side
(WDBF 16.2), and the only evidence at release is the ball's direction. The
floor homography cannot place a ball in the air - at shoulder height it
projects metres beyond the hand - so the direction is taken in the image,
where this camera looks along the court and the opponent is straight up or
down the frame: the angle between the chain's first few links and that
axis. Every labelled pass on the clip goes sideways or back; a throw goes
along the court, though perspective flattens a cross-court throw towards
the lateral, so the bar for calling a pass is set high and a throw is the
default. Where the ball ends up will settle it better, and that is the
outcome stage's.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

from src.ball import Trace, WristFrame

REPO_ROOT = Path(__file__).resolve().parent.parent
TIMELINE_ROOT = REPO_ROOT / "data" / "timeline"

SCHEMA_VERSION = 1

# No throw can happen until a player has sprinted to the centre line, picked
# a ball up and wound up. Four proposals on the evaluation clip fall in the
# first 1.5 s after the whistle, all sprinters; the first event is at 2.5 s.
RUSH_S = 2.0

# The frames before the peak in which a thrower must already hold the ball.
# The window stops short of the peak: at the whip the ball is a streak that
# the disc may or may not catch, and a release before the peak has already
# emptied the hand.
BALL_BEFORE_WINDOW = (-12, -3)
# Mean ball-sized orange inside the wrist disc over that window, in units of
# the squared perspective scale. Set low on purpose: on the evaluation clip's
# 105 reviewed proposals it keeps every event with a ball that the tolerance
# can match and drops half the rejections; raising it to 0.00003 loses five
# events for no precision.
BALL_BEFORE_MIN = 0.00002

# The frames before the peak in which the hand holding the ball must have
# reached the shoulder line - the wind-up. Zero is the line itself, in torso
# lengths along the body; a block or a raised catch peaks just below it, a
# throw goes past it. Raising the bar past zero starts losing sidearm
# throws, which reach the line only at the whip.
WINDUP_WINDOW = (-10, 0)
WINDUP_MIN_HEIGHT = 0.0
# A blob within this of the wrist keypoint is in the hand.
HAND_NORM = 0.08
# Offsets around the peak at which a chain may begin: a release comes as
# early as eight frames before the wrist-speed peak (the peak is the whip or
# the follow-through, not the release) and rarely more than three after.
SEED_WINDOW = (-8, 3)
# The first step of a chain has no velocity to predict from. A hard throw
# moves the ball a fifth of the perspective scale in a frame at most on the
# clip; a ball that has not moved a fiftieth of it is still in the hand.
# A looser cap (0.45) let chains hop to other balls: two thirds of fakes
# then had a chain leaving the hand.
FIRST_STEP_NORM = (0.02, 0.20)
# A step may skip this many frames when no blob continues the chain: at the
# whip the ball is a streak the mask drops for a frame. Over a skipped frame
# the predicted position and the tolerances scale with the frames covered.
LINK_GAP_FRAMES = 1
# A blob within this many of its own diameters of a blob on the previous
# frame is standing still and is not the ball leaving. Costs the slowest
# far-court balls, which move under a diameter a frame; buys every fake
# whose chain ran through stationary orange.
STATIC_TOLERANCE_DIAMETERS = 1.0
# Later steps land within a fixed slack plus a fraction of the last step's
# length of where the last velocity predicts, turning no more than MAX_TURN.
LINK_SLACK_NORM = 0.06
LINK_VELOCITY_FRACTION = 0.6
MAX_TURN_DEG = 50.0
CHAIN_MAX_LINKS = 8
# Each link tries at most this many blobs, nearest first.
BRANCH = 6

# A chain is a release when it carries the ball this far from the hand with
# at least this many links. A hand cannot move a ball a quarter of the scale
# in two frames; a ball in flight does it in one. Accuracy on the evaluation
# clip is flat from 0.20 to 0.25 and falls either side.
DEPART_MIN_NORM = 0.25
CHAIN_MIN_LINKS = 2

# The links whose direction says where the ball went: enough to average the
# jitter of the first hop, few enough to precede any bounce. From the axis
# towards the opponent, 0 is straight at them, 90 sideways, 180 backwards.
# Every labelled pass on the clip is at 81 or more and most throws under 70;
# perspective flattens a cross-court throw to the high seventies, so the
# bar is set where every pass clears it and a throw is the default.
DIRECTION_LINKS = 3
PASS_MIN_ANGLE_DEG = 80.0


@dataclass(frozen=True)
class Departure:
    """The best chain of ball blobs leaving a wrist."""

    wrist: str | None
    distance: float
    links: int
    seed_offset: int | None
    # The chain's points in image pixels, the blob at the hand first.
    path: tuple[tuple[float, float], ...] = ()

    @property
    def released(self) -> bool:
        return self.distance >= DEPART_MIN_NORM and self.links >= CHAIN_MIN_LINKS

    def angle_from(self, team: str | None) -> float | None:
        """Degrees between the ball's first direction and the way to the opponent.

        The near team throws up the image, the far team down. None without a
        team to say which, or without a chain.
        """
        if team not in ("near", "far") or self.links < 1:
            return None
        k = min(DIRECTION_LINKS, self.links)
        (x0, y0), (x1, y1) = self.path[0], self.path[k]
        towards = -1.0 if team == "near" else 1.0
        return math.degrees(math.atan2(abs(x1 - x0), towards * (y1 - y0)))


NO_DEPARTURE = Departure(None, 0.0, 0, None)


def ball_before(trace: Trace, window: tuple[int, int] = BALL_BEFORE_WINDOW) -> float:
    """The most ball either wrist held before the peak."""
    best = 0.0
    for wrist in ("L", "R"):
        counts = [wf.disc for o in range(window[0], window[1] + 1)
                  if (wf := trace.at(o, wrist)) is not None]
        if counts:
            best = max(best, sum(counts) / len(counts))
    return best


def ball_heights(trace: Trace, window: tuple[int, int]) -> list[float]:
    """The height of every hand seen holding the ball inside the window."""
    out = []
    for offset in range(window[0], window[1] + 1):
        for wrist in ("L", "R"):
            wf = trace.at(offset, wrist)
            if wf is not None and wf.disc > 0 and wf.height is not None:
                out.append(wf.height)
    return out


def wound_up_with_ball(trace: Trace) -> bool:
    heights = ball_heights(trace, WINDUP_WINDOW)
    return bool(heights) and max(heights) >= WINDUP_MIN_HEIGHT


def _chains(trace: Trace, wrist: str, seed_offset: int, origin: tuple[float, float]):
    """Every consistent chain from a blob at the hand, depth-first."""
    scale = trace.scale
    out: list[list[tuple[float, float]]] = []

    def options(pos, vel, offset, covered):
        """Blobs on `offset` that continue the chain over `covered` frames."""
        wf: WristFrame | None = trace.at(offset, wrist)
        previous: WristFrame | None = trace.at(offset - 1, wrist)
        found = []
        if wf is None:
            return found
        for blob in wf.blobs:
            if previous is not None and any(
                    math.hypot(q.x - blob.x, q.y - blob.y) / scale
                    <= STATIC_TOLERANCE_DIAMETERS * blob.diameter_norm for q in previous.blobs):
                continue
            mv = (blob.x - pos[0], blob.y - pos[1])
            length = math.hypot(*mv)
            if vel is None:
                if not FIRST_STEP_NORM[0] * covered <= length / scale <= FIRST_STEP_NORM[1] * covered:
                    continue
            else:
                px, py = pos[0] + vel[0] * covered, pos[1] + vel[1] * covered
                radius = covered * (LINK_SLACK_NORM * scale + LINK_VELOCITY_FRACTION * math.hypot(*vel))
                if math.hypot(blob.x - px, blob.y - py) > radius:
                    continue
                cos = (mv[0] * vel[0] + mv[1] * vel[1]) / (length * math.hypot(*vel) + 1e-9)
                if math.degrees(math.acos(max(-1.0, min(1.0, cos)))) > MAX_TURN_DEG:
                    continue
            found.append(((blob.x, blob.y), (mv[0] / covered, mv[1] / covered), offset))
        return found

    def step(path, pos, vel, offset, gaps):
        found = options(pos, vel, offset, 1)
        if not found and gaps < LINK_GAP_FRAMES:
            found = options(pos, vel, offset + 1, 2)
            gaps += 1
        if not found or len(path) > CHAIN_MAX_LINKS:
            out.append(path)
            return
        for p, v, at in found[:BRANCH]:
            step(path + [p], p, v, at + 1, gaps)

    step([origin], origin, None, seed_offset + 1, 0)
    return out


def departure(trace: Trace) -> Departure:
    """The farthest monotone chain of at least CHAIN_MIN_LINKS leaving either wrist.

    Farthest, not longest: a chain that follows the ball still in the hand
    can run the whole window without going anywhere, and it must not beat
    a three-link chain that leaves. Both wrists are tried: a player holding
    two balls throws with one hand while the disc on the other stays lit,
    and the pose's faster wrist at the peak is not reliably the throwing one.
    """
    best = NO_DEPARTURE
    for wrist in ("L", "R"):
        for seed_offset in range(SEED_WINDOW[0], SEED_WINDOW[1] + 1):
            wf = trace.at(seed_offset, wrist)
            if wf is None or wf.wrist is None:
                continue
            at_hand = [b for b in wf.blobs
                       if b.distance_norm(wf.wrist[0], wf.wrist[1], trace.scale) <= HAND_NORM]
            if not at_hand:
                continue
            origin = (at_hand[0].x, at_hand[0].y)
            for chain in _chains(trace, wrist, seed_offset, origin):
                links = len(chain) - 1
                if links < CHAIN_MIN_LINKS:
                    continue
                dists = [math.hypot(p[0] - origin[0], p[1] - origin[1]) for p in chain]
                if any(b <= a for a, b in zip(dists, dists[1:])):
                    continue
                far = dists[-1] / trace.scale
                if (far, links) > (best.distance, best.links):
                    best = Departure(wrist, round(far, 4), links, seed_offset,
                                     tuple((round(x, 1), round(y, 1)) for x, y in chain))
    return best


@dataclass(frozen=True)
class Decision:
    """What the release gate says about one proposal."""

    frame: int
    track_id: int
    participant_id: str
    team: str | None
    box: tuple[float, float, float, float]
    is_event: bool
    dropped: str | None
    ball_before: float
    departure: Departure

    @property
    def released(self) -> bool | None:
        return self.departure.released if self.is_event else None

    @property
    def angle(self) -> float | None:
        return self.departure.angle_from(self.team) if self.released else None

    @property
    def kind(self) -> str | None:
        if not self.is_event:
            return None
        if not self.released:
            return "fake"
        # A pass is claimed only on a direction measured over the full
        # DIRECTION_LINKS: a two-link chain's heading is one hop's jitter.
        angle = self.angle
        if angle is None or self.departure.links < DIRECTION_LINKS:
            return "throw"
        return "pass" if angle >= PASS_MIN_ANGLE_DEG else "throw"


def decide(trace: Trace, set_start_frame: int | None, fps: float) -> Decision:
    cand = trace.candidate
    dropped = None
    if set_start_frame is not None and cand.frame < set_start_frame + RUSH_S * fps:
        dropped = "rush"
    held = ball_before(trace)
    if dropped is None and held < BALL_BEFORE_MIN:
        dropped = "no ball in hand"
    if dropped is None and not wound_up_with_ball(trace):
        dropped = "no wind-up with the ball"
    # Computed for dropped proposals too, so the file carries the evidence a
    # threshold sweep needs without another read of the footage.
    dep = departure(trace)
    return Decision(
        frame=cand.frame, track_id=cand.track_id, participant_id=cand.participant_id,
        team=cand.team, box=cand.box, is_event=dropped is None, dropped=dropped,
        ball_before=held, departure=dep)


@dataclass
class Timeline:
    """The events the pipeline claims for one clip, as written to ``data/timeline/``."""

    video: str
    clip_sha256: str
    pose_run: str
    fps: float
    thresholds: dict
    decisions: list[Decision]

    @property
    def events(self) -> list[Decision]:
        return [d for d in self.decisions if d.is_event]

    def to_json(self) -> dict:
        def one(d: Decision) -> dict:
            return {
                "frame": d.frame, "track_id": d.track_id, "participant": d.participant_id,
                "team": d.team, "box": [round(v, 1) for v in d.box],
                "released": d.released, "kind": d.kind, "dropped": d.dropped,
                "evidence": {
                    "ball_before": round(d.ball_before * 1e3, 4),
                    "depart": d.departure.distance, "links": d.departure.links,
                    "seed_offset": d.departure.seed_offset, "wrist": d.departure.wrist,
                    "angle": round(d.angle, 1) if d.angle is not None else None,
                    "path": [list(p) for p in d.departure.path],
                },
            }
        return {
            "schema_version": SCHEMA_VERSION, "video": self.video,
            "clip_sha256": self.clip_sha256, "pose_run": self.pose_run, "fps": self.fps,
            "thresholds": dict(self.thresholds),
            "events": [one(d) for d in self.decisions if d.is_event],
            "dropped": [one(d) for d in self.decisions if not d.is_event],
        }

    def write(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_json(), indent=1))
        return path


def thresholds() -> dict:
    return {
        "rush_s": RUSH_S, "ball_before_window": list(BALL_BEFORE_WINDOW),
        "ball_before_min": BALL_BEFORE_MIN,
        "windup_window": list(WINDUP_WINDOW), "windup_min_height": WINDUP_MIN_HEIGHT,
        "hand_norm": HAND_NORM,
        "seed_window": list(SEED_WINDOW), "first_step_norm": list(FIRST_STEP_NORM),
        "link_gap_frames": LINK_GAP_FRAMES,
        "static_tolerance_diameters": STATIC_TOLERANCE_DIAMETERS,
        "link_slack_norm": LINK_SLACK_NORM, "link_velocity_fraction": LINK_VELOCITY_FRACTION,
        "max_turn_deg": MAX_TURN_DEG, "depart_min_norm": DEPART_MIN_NORM,
        "chain_min_links": CHAIN_MIN_LINKS,
    }
