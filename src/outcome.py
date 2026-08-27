"""What a throw did, read from the game rather than from the ball.

The chain cannot say. At 25 fps and twenty pixels across, the frame where
the ball meets a player is the frame the chain loses it: a dodge and a hit
both end the chain inside the box, and letting the chain through the box only
lets it grab whatever orange is next. The rebound after a hit is visible a
few frames later, slow and beside the struck player; reading it is a linking
problem not solved here.

The game can. In dodgeball the only thing that changes the state is a throw
resolving: a hit puts the player struck off the court, a catch puts the
thrower off and returns one of the catcher's team. So a persistent change in
how many of a side are in play *is* an outcome, and the throw responsible is
the last one thrown at that side before it. The whistle was measured as a
witness and is not one - the band it lives in is shoe squeak and crowd as
often as a referee - and the departure of an individual track is not one
either, since tracks fragment; the count of a side, held for a while, is.

The lag is the cost. An eliminated player takes one to seven seconds to
leave, so a step is attributed to the *latest* throw at that side before it,
within a window; two throws at one side inside that window are the case this
cannot separate, and the clip has one. Everything a step does not claim is a
miss: a block leaves no trace in the state, exactly as the plan said, and is
folded into miss here.

Folding the resolved outcomes forward is also the consistency check the plan
proposed, and it is what found the label that counted one player out twice.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from src.timing import REFERENCE_FPS, frames, window

# A change in a side's count must hold this long to be a step: a track that
# drops out and comes back within two seconds is the tracker, not a player.
HOLD_S = 2.0
# A step may be missed for this long inside the hold.
HOLD_SLACK_S = 0.16
# How long after a throw its elimination may show. The slowest departure on
# the evaluation clip is 5.6 s after the hit; a return after a catch came
# 8.8 s after the ball was caught.
ELIMINATION_WINDOW_S = 9.6
# A return on one side this close to a drop on the other makes the drop a
# catch. The return can precede the drop: the catcher's teammate walks on
# while the thrower is still walking off.
RETURN_WINDOW_S = (-4.8, 9.6)

TEAMS = ("near", "far")


def other(team: str) -> str:
    return "far" if team == "near" else "near"


@dataclass(frozen=True)
class Step:
    """A persistent change in how many of a side are in play."""

    frame: int
    team: str
    before: int
    after: int

    @property
    def delta(self) -> int:
        return self.after - self.before


def count_steps(counts: dict[str, list[int]], start_frame: int,
                fps: float = REFERENCE_FPS) -> list[Step]:
    """Every step in each side's count that holds for HOLD_S.

    `counts[team][i]` is the side's in-play count on frame `start_frame + i`.
    A value is a step when it differs from the current level and the next
    HOLD_S of frames sit at it with at most HOLD_SLACK_S of exceptions.
    """
    hold, slack = frames(HOLD_S, fps), frames(HOLD_SLACK_S, fps)
    steps: list[Step] = []
    for team, seq in counts.items():
        if not seq:
            continue
        level = seq[0]
        i = 0
        while i < len(seq):
            v = seq[i]
            if v != level:
                window = seq[i:i + hold]
                if len(window) >= hold and sum(1 for x in window if x == v) >= hold - slack:
                    steps.append(Step(start_frame + i, team, level, v))
                    level = v
                    i += hold
                    continue
            i += 1
    steps.sort(key=lambda s: s.frame)
    return steps


@dataclass(frozen=True)
class Thrown:
    """What the resolver needs to know about one throw."""

    id: int
    frame: int
    team: str


@dataclass(frozen=True)
class Resolution:
    throw_id: int
    outcome: str
    step_frame: int
    return_frame: int | None = None

    @property
    def lag(self) -> int:
        return self.step_frame


def resolve(throws: list[Thrown], steps: list[Step],
            fps: float = REFERENCE_FPS) -> tuple[dict[int, Resolution], list[Step]]:
    """Attribute every drop to a throw; return the outcomes and the drops no throw explains.

    Drops are taken in order. A drop on side X is a catch if an unused rise
    on the other side falls inside RETURN_WINDOW_S of it, and then belongs to
    the latest throw *by* X before the earlier of the two; otherwise it is a
    hit and belongs to the latest throw *at* X - by the other side - before
    it. Either way the throw must be within ELIMINATION_WINDOW_S, and a throw
    resolves once.
    """
    elimination_window = frames(ELIMINATION_WINDOW_S, fps)
    return_lo, return_hi = window(RETURN_WINDOW_S, fps)
    by_team = {t: sorted((x for x in throws if x.team == t), key=lambda x: x.frame)
               for t in TEAMS}
    rises = [s for s in steps if s.delta > 0]
    # A rise of +k is k players walking on, so it explains k catches.
    returns_used: Counter[int] = Counter()
    taken: set[int] = set()
    out: dict[int, Resolution] = {}
    orphans: list[Step] = []

    def latest(team: str, before: int) -> Thrown | None:
        for x in reversed(by_team.get(team, [])):
            if x.frame <= before and x.id not in taken and before - x.frame <= elimination_window:
                return x
        return None

    for drop in (s for s in steps if s.delta < 0):
        for _ in range(-drop.delta):
            rise = next((r for r in rises if r.team == other(drop.team)
                         and returns_used[r.frame] < r.delta
                         and return_lo <= r.frame - drop.frame <= return_hi), None)
            if rise is not None:
                thrown = latest(drop.team, min(drop.frame, rise.frame))
                if thrown is not None:
                    returns_used[rise.frame] += 1
                    taken.add(thrown.id)
                    out[thrown.id] = Resolution(thrown.id, "catch", drop.frame, rise.frame)
                    continue
            thrown = latest(other(drop.team), drop.frame)
            if thrown is None:
                orphans.append(drop)
                continue
            taken.add(thrown.id)
            out[thrown.id] = Resolution(thrown.id, "hit", drop.frame)
    return out, orphans


def fold(throws: list[Thrown], outcomes: dict[int, str], start: dict[str, int]) -> list[tuple[int, dict[str, int]]]:
    """The side counts implied by a set of outcomes, throw by throw.

    Run on the labels it audits them against the on-court count; run on the
    predictions it is the same check the plan asked for as a temporal prior.
    """
    state = dict(start)
    trail = []
    for x in sorted(throws, key=lambda x: x.frame):
        o = outcomes.get(x.id)
        if o == "hit":
            state[other(x.team)] -= 1
        elif o == "catch":
            state[x.team] -= 1
            state[other(x.team)] += 1
        trail.append((x.frame, dict(state)))
    return trail
