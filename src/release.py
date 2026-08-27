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
(WDBF 16.2). Two witnesses, read from the same chain. The ball's *contact*:
the chain is followed to where it stops, and if that is inside a player's
box, the ball reached that player - a teammate is a pass, an opponent a
throw, with no projection needed. Its *direction*: the floor homography
cannot place a ball in the air - at shoulder height it projects metres
beyond the hand - but the direction is sound in the image, where this
camera looks along the court and the opponent is straight up or down the
frame; the angle between the chain's first few links and that axis calls a
pass only when the ball clearly goes across or back. Contact decides where
it exists, direction otherwise, and the timeline records which spoke and
whether they agree. A throw is the default.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable

from src.ball import Trace, WristFrame
from src.rebound import Rebound
from src.timing import frames, window

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
BALL_BEFORE_WINDOW_S = (-0.48, -0.12)
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
WINDUP_WINDOW_S = (-0.40, 0.0)
WINDUP_MIN_HEIGHT = 0.0
# A blob within this of the wrist keypoint is in the hand.
HAND_NORM = 0.08
# Offsets around the peak at which a chain may begin: a release comes as
# early as a third of a second before the wrist-speed peak (the peak is the
# whip or the follow-through, not the release) and rarely more than an
# eighth after.
SEED_WINDOW_S = (-0.32, 0.12)
# The first step of a chain has no velocity to predict from. A hard throw
# moves the ball five perspective scales a second at most on the clip; a
# ball that has not moved half a scale a second is still in the hand. A
# looser cap (0.45 per frame at 25 fps) let chains hop to other balls: two
# thirds of fakes then had a chain leaving the hand.
FIRST_STEP_NORM_PER_S = (0.5, 5.0)
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
# Long enough to reach the contact: every labelled outcome settles within
# 0.85 s of release. The release claim itself is made in the first few links.
CHAIN_MAX_S = 1.2
# Each link tries at most this many blobs, nearest first, and one proposal's
# search stops after this many nodes: a hall of orange must not make the
# depth-first walk exponential.
BRANCH = 6
CHAIN_MAX_NODES = 4000

# A chain that ends inside a player's box, grown by this fraction of its
# size each way, reached that player. Boxes are the pose run's.
CONTACT_BOX_MARGIN = 0.10

# The faint mask may carry a chain across the whip, where the ball is a
# blurred streak the strict mask loses for a frame or two - but never for
# longer: a run of faint links beyond this is dull floor, not a ball.
FAINT_MAX_RUN = 2

# A chain is a release when it carries the ball this far from the hand with
# at least this many links - strict sightings, since the claim of a release
# rests on the ball seen properly on both sides of the blur; faint blobs
# bridge and do not count. A hand cannot move a ball a quarter of the scale
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
    # The offset of the chain's last point.
    end_offset: int | None = None

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


def ball_before(trace: Trace, window_s: tuple[float, float] = BALL_BEFORE_WINDOW_S) -> float:
    """The most ball either wrist held before the peak."""
    best = 0.0
    lo, hi = window(window_s, trace.fps)
    for wrist in ("L", "R"):
        counts = [wf.disc for o in range(lo, hi + 1)
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
    heights = ball_heights(trace, window(WINDUP_WINDOW_S, trace.fps))
    return bool(heights) and max(heights) >= WINDUP_MIN_HEIGHT


def _chains(trace: Trace, wrist: str, seed_offset: int, origin: tuple[float, float]):
    """Every consistent chain from a blob at the hand, depth-first."""
    scale = trace.scale
    max_links = frames(CHAIN_MAX_S, trace.fps)
    out: list[list[tuple[float, float]]] = []

    def options(pos, vel, offset, covered):
        """Blobs on `offset` that continue the chain over `covered` frames."""
        wf: WristFrame | None = trace.at(offset, wrist)
        previous: WristFrame | None = trace.at(offset - 1, wrist)
        found = []
        if wf is None:
            return found
        # A faint blob continues a chain: at the whip the ball is a blurred
        # streak the strict mask loses for a frame or two. It never seeds one.
        for blob in wf.blobs + wf.faint:
            # Standing still is judged against the previous frame's blobs of
            # the same kind: dull floor is faint on every frame, and a strict
            # ball is not still because a faint patch lay under its path.
            resting = () if previous is None else (previous.faint if blob.faint else previous.blobs)
            if any(
                    math.hypot(q.x - blob.x, q.y - blob.y) / scale
                    <= STATIC_TOLERANCE_DIAMETERS * blob.diameter_norm for q in resting):
                continue
            mv = (blob.x - pos[0], blob.y - pos[1])
            length = math.hypot(*mv)
            if vel is None:
                lo, hi = (v * covered / trace.fps for v in FIRST_STEP_NORM_PER_S)
                if not lo <= length / scale <= hi:
                    continue
            else:
                px, py = pos[0] + vel[0] * covered, pos[1] + vel[1] * covered
                radius = covered * (LINK_SLACK_NORM * scale + LINK_VELOCITY_FRACTION * math.hypot(*vel))
                if math.hypot(blob.x - px, blob.y - py) > radius:
                    continue
                cos = (mv[0] * vel[0] + mv[1] * vel[1]) / (length * math.hypot(*vel) + 1e-9)
                if math.degrees(math.acos(max(-1.0, min(1.0, cos)))) > MAX_TURN_DEG:
                    continue
            found.append(((blob.x, blob.y), (mv[0] / covered, mv[1] / covered), offset, blob.faint))
        return found

    nodes = 0

    def step(path, pos, vel, offset, gaps, faint_run):
        nonlocal nodes
        nodes += 1
        allowed = lambda opts: [o for o in opts if not o[3] or faint_run < FAINT_MAX_RUN]
        found = [(o, gaps) for o in allowed(options(pos, vel, offset, 1))]
        # The bridge over a dropped frame is tried whenever nothing strict
        # continues the chain: a faint blob on the next frame is a guess at the
        # ball, not a reason to stop looking for it properly a frame later.
        if all(o[3] for o, _ in found) and gaps < LINK_GAP_FRAMES:
            found += [(o, gaps + 1) for o in allowed(options(pos, vel, offset + 1, 2))]
        if not found or len(path) > max_links or nodes > CHAIN_MAX_NODES:
            out.append(path)
            return
        for (p, v, at, faint), g in found[:BRANCH]:
            step(path + [(p, at, faint)], p, v, at + 1, g, faint_run + 1 if faint else 0)

    step([(origin, seed_offset, False)], origin, None, seed_offset + 1, 0, 0)
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
    seed_lo, seed_hi = window(SEED_WINDOW_S, trace.fps)
    for wrist in ("L", "R"):
        for seed_offset in range(seed_lo, seed_hi + 1):
            wf = trace.at(seed_offset, wrist)
            if wf is None or wf.wrist is None:
                continue
            at_hand = [b for b in wf.blobs
                       if b.distance_norm(wf.wrist[0], wf.wrist[1], trace.scale) <= HAND_NORM]
            if not at_hand:
                continue
            origin = (at_hand[0].x, at_hand[0].y)
            for chain in _chains(trace, wrist, seed_offset, origin):
                # The chain is cut back to its last strict sighting: what the
                # faint mask saw beyond it is a bridge to nowhere.
                while len(chain) > 1 and chain[-1][2]:
                    chain = chain[:-1]
                links = sum(1 for _, _, faint in chain[1:] if not faint)
                if links < CHAIN_MIN_LINKS:
                    continue
                dists = [math.hypot(p[0] - origin[0], p[1] - origin[1]) for p, _, _ in chain]
                if any(b <= a for a, b in zip(dists, dists[1:])):
                    continue
                far = dists[-1] / trace.scale
                if (far, links) > (best.distance, best.links):
                    best = Departure(wrist, round(far, 4), links, seed_offset,
                                     tuple((round(x, 1), round(y, 1)) for (x, y), _, _ in chain),
                                     chain[-1][1])
    return best


@dataclass(frozen=True)
class Contact:
    """The player a chain ended in, if any."""

    team: str | None
    track_id: int
    participant_id: str


# What a stage needs to know about who is where: for a frame, every player
# other than the thrower as (team, track id, participant id, box).
PlayersAt = Callable[[int], list[tuple[str | None, int, str, tuple[float, float, float, float]]]]


def contact(dep: Departure, frame: int, thrower_track: int,
            players_at: PlayersAt | None) -> Contact | None:
    """The player whose box the chain's last point falls in on its frame."""
    if players_at is None or dep.end_offset is None or not dep.path:
        return None
    x, y = dep.path[-1]
    for team, track_id, participant_id, (x1, y1, x2, y2) in players_at(frame + dep.end_offset):
        if track_id == thrower_track:
            continue
        mx, my = CONTACT_BOX_MARGIN * (x2 - x1), CONTACT_BOX_MARGIN * (y2 - y1)
        if x1 - mx <= x <= x2 + mx and y1 - my <= y <= y2 + my:
            return Contact(team, track_id, participant_id)
    return None


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
    contact: Contact | None = None
    # What the ball did at the player it reached (src/rebound.py); None where
    # the chain reached nobody or the stage did not run.
    rebound: Rebound | None = None
    # What the throw did, from the game state (src/outcome.py); None until resolved
    # or for anything that is not a throw.
    outcome: str | None = None
    outcome_step_frame: int | None = None
    outcome_return_frame: int | None = None

    @property
    def released(self) -> bool | None:
        return self.departure.released if self.is_event else None

    @property
    def angle(self) -> float | None:
        return self.departure.angle_from(self.team) if self.released else None

    def _by_direction(self) -> str | None:
        """Pass or throw from the first direction; None where it cannot say.

        A direction is only trusted over the full DIRECTION_LINKS: a two-link
        chain's heading is one hop's jitter.
        """
        angle = self.angle
        if angle is None or self.departure.links < DIRECTION_LINKS:
            return None
        return "pass" if angle >= PASS_MIN_ANGLE_DEG else "throw"

    def _by_contact(self) -> str | None:
        """Pass or throw from the player the ball reached; None where it reached nobody."""
        if self.contact is None or self.contact.team is None or self.team is None:
            return None
        if self.departure.links < DIRECTION_LINKS:
            return None
        return "pass" if self.contact.team == self.team else "throw"

    @property
    def destination_source(self) -> str | None:
        """Which witness decided pass against throw: contact, direction, or the default."""
        if not self.released:
            return None
        if self._by_contact() is not None:
            return "contact"
        if self._by_direction() is not None:
            return "direction"
        return "default"

    @property
    def destination_agreed(self) -> bool | None:
        """Whether contact and direction agree, where both spoke."""
        c, d = self._by_contact(), self._by_direction()
        return (c == d) if c is not None and d is not None else None

    @property
    def kind(self) -> str | None:
        if not self.is_event:
            return None
        if not self.released:
            return "fake"
        return self._by_contact() or self._by_direction() or "throw"


def decide(trace: Trace, set_start_frame: int | None, fps: float,
           players_at: PlayersAt | None = None) -> Decision:
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
    hit = contact(dep, cand.frame, cand.track_id, players_at) if dropped is None else None
    return Decision(
        frame=cand.frame, track_id=cand.track_id, participant_id=cand.participant_id,
        team=cand.team, box=cand.box, is_event=dropped is None, dropped=dropped,
        ball_before=held, departure=dep, contact=hit)


@dataclass
class Timeline:
    """The events the pipeline claims for one clip, as written to ``data/timeline/``."""

    video: str
    clip_sha256: str
    pose_run: str
    fps: float
    thresholds: dict
    decisions: list[Decision]
    # Persistent drops in a side's count that no throw explains.
    unexplained_steps: list[dict] = field(default_factory=list)

    @property
    def events(self) -> list[Decision]:
        return [d for d in self.decisions if d.is_event]

    def to_json(self) -> dict:
        def one(d: Decision) -> dict:
            return {
                "frame": d.frame, "track_id": d.track_id, "participant": d.participant_id,
                "team": d.team, "box": [round(v, 1) for v in d.box],
                "released": d.released, "kind": d.kind, "dropped": d.dropped,
                "outcome": d.outcome,
                "evidence": {
                    "outcome_step_frame": d.outcome_step_frame,
                    "outcome_return_frame": d.outcome_return_frame,
                    "ball_before": round(d.ball_before * 1e3, 4),
                    "depart": d.departure.distance, "links": d.departure.links,
                    "seed_offset": d.departure.seed_offset, "wrist": d.departure.wrist,
                    "angle": round(d.angle, 1) if d.angle is not None else None,
                    "end_offset": d.departure.end_offset,
                    "contact": ({"team": d.contact.team, "track_id": d.contact.track_id,
                                 "participant": d.contact.participant_id}
                                if d.contact else None),
                    "destination_source": d.destination_source,
                    "destination_agreed": d.destination_agreed,
                    "rebound": ({"seeded": d.rebound.seeded,
                                 "contact": ({"frame": d.rebound.contact.frame,
                                              "team": d.rebound.contact.team,
                                              "track_id": d.rebound.contact.track_id,
                                              "participant": d.rebound.contact.participant_id}
                                             if d.rebound.contact else None),
                                 "tracked": d.rebound.tracked, "passed": d.rebound.passed,
                                 "turn_deg": (round(d.rebound.turn_deg, 1)
                                              if d.rebound.turn_deg is not None else None),
                                 "deflected": d.rebound.deflected}
                                if d.rebound else None),
                    "path": [list(p) for p in d.departure.path],
                },
            }
        return {
            "schema_version": SCHEMA_VERSION, "video": self.video,
            "clip_sha256": self.clip_sha256, "pose_run": self.pose_run, "fps": self.fps,
            "thresholds": dict(self.thresholds),
            "events": [one(d) for d in self.decisions if d.is_event],
            "dropped": [one(d) for d in self.decisions if not d.is_event],
            "unexplained_steps": list(self.unexplained_steps),
        }

    def write(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_json(), indent=1))
        return path


def thresholds() -> dict:
    return {
        "rush_s": RUSH_S, "ball_before_window_s": list(BALL_BEFORE_WINDOW_S),
        "ball_before_min": BALL_BEFORE_MIN,
        "windup_window_s": list(WINDUP_WINDOW_S), "windup_min_height": WINDUP_MIN_HEIGHT,
        "hand_norm": HAND_NORM,
        "seed_window_s": list(SEED_WINDOW_S), "first_step_norm_per_s": list(FIRST_STEP_NORM_PER_S),
        "chain_max_s": CHAIN_MAX_S,
        "link_gap_frames": LINK_GAP_FRAMES,
        "static_tolerance_diameters": STATIC_TOLERANCE_DIAMETERS,
        "link_slack_norm": LINK_SLACK_NORM, "link_velocity_fraction": LINK_VELOCITY_FRACTION,
        "max_turn_deg": MAX_TURN_DEG, "depart_min_norm": DEPART_MIN_NORM,
        "chain_min_links": CHAIN_MIN_LINKS,
    }
