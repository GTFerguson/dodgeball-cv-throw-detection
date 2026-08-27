"""Where a set ends: the last elimination, or the floor showing that it happened.

A set is won when a team has eliminated every player on the other side (WDBF
10.2.1), so a set ends on one hit - the one on the last player left - and the
frame the ball goes dead after it is the end. Naming that hit needs the
outcome stage. What the floor shows on its own is nearly as exact and needs
nothing but the roster: one side is down to a single player for a stretch -
the **last stand** - and then the court fills with more bodies than any set
allows. The last frame of the stand is the floor's end, and the hit, when it
is known, must lie between the stand beginning and the flood.

Why not the whistle
-------------------

Every elimination on the evaluation clip has a whistle the set-start detector
can hear, and the one that ends the set does not: the last whistle above the
gate is at frame 4608, an elimination call, and nothing follows the final hit
at 4651. It is match point of a final and the crowd lifts the noise floor the
whistle is measured against. The end whistle is corroboration where it is
audible and cannot be the anchor.

Why the flood and not any one rule
----------------------------------

Play has rules the floor breaks the moment a set is over - a side above six,
an official inside the lines - but none of them is a single-frame fact on
tracked footage. A side reads seven for up to 45 frames mid-set when a
tracker fragment doubles a player, and an official's track reads in play for
2.8 s during the last stand on the clip. What no set can do is put two or
more extra bodies on the floor at once: a catch returns one player, and
nothing else returns any. So the flood is the total in play rising by
``FLOOD_MIN_RISE`` over the stand's total and staying there, and it is what
confirms a stand was the last one rather than a side that a catch brought
back from the brink.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

TEAMS = ("near", "far")

# One player on a side has to hold for this long to be a last stand. Mid-set
# occupancy never reads one on the evaluation clip except in the stand itself
# (610 frames); the floor is 2 s so a tracker dropping a player for a moment
# does not make one.
LAST_STAND_MIN_S = 2.0
# The flood: at least this many more players in play than the stand had, held
# for FLOOD_MIN_S, beginning within FLOOD_WINDOW_S of the stand ending. On the
# clip the total goes 7 -> 8 -> 11 in 4.5 s.
FLOOD_MIN_RISE = 2
FLOOD_MIN_S = 0.4
FLOOD_WINDOW_S = 10.0


@dataclass(frozen=True)
class LastStand:
    """A stretch where one side had exactly one player in play."""

    side: str
    start_frame: int
    end_frame: int
    # Players in play on both sides over the stand, for the flood to rise from.
    total: int


@dataclass(frozen=True)
class Hit:
    """An elimination the outcome stage (or the truth set) knows about."""

    # When the ball went dead after the contact - the end of the event.
    frame: int
    # The side of the player put out.
    side: str


@dataclass(frozen=True)
class SetEnd:
    frame: int
    # "hit": the elimination of the last player, exact. "floor": the last frame
    # of the last stand, a bound the true end lies at or before.
    source: str
    stand: LastStand
    flood_frame: int
    hit: Hit | None = None

    @property
    def hit_window(self) -> tuple[int, int]:
        """Where a hit the outcome stage missed has to be."""
        return self.stand.start_frame, self.flood_frame


def last_stands(counts: list[tuple[int, int, int]], fps: float) -> list[LastStand]:
    """Every stretch of one-on-a-side that held for LAST_STAND_MIN_S, in order.

    ``counts`` is (frame, near, far) per frame, ascending. A side at one is a
    stand for that side; at one against one both sides stand and the flood
    decides nothing between them - it is the hit that names the loser.
    """
    minimum = int(round(LAST_STAND_MIN_S * fps))
    stands: list[LastStand] = []
    for column, side in ((1, "near"), (2, "far")):
        run: list[tuple[int, int, int]] = []
        for row in counts + [(-1, -1, -1)]:
            if row[column] == 1 and (not run or row[0] == run[-1][0] + 1):
                run.append(row)
                continue
            if len(run) >= minimum:
                stands.append(LastStand(side=side, start_frame=run[0][0], end_frame=run[-1][0],
                                        total=max(r[1] + r[2] for r in run)))
            run = [row] if row[column] == 1 else []
    return sorted(stands, key=lambda s: s.start_frame)


def flood_after(counts: list[tuple[int, int, int]], stand: LastStand, fps: float) -> int | None:
    """The frame the floor fills after a stand, or None if it never does in time."""
    needed = int(round(FLOOD_MIN_S * fps))
    deadline = stand.end_frame + int(round(FLOOD_WINDOW_S * fps))
    run_start: int | None = None
    run_len = 0
    for frame, near, far in counts:
        if frame <= stand.end_frame:
            continue
        if frame > deadline and run_start is None:
            return None
        if near + far >= stand.total + FLOOD_MIN_RISE:
            if run_start is None:
                run_start, run_len = frame, 0
            run_len += 1
            if run_len >= needed:
                return run_start
        else:
            run_start = None
    return None


def end_from_counts(counts: list[tuple[int, int, int]], fps: float,
                    hits: Iterable[Hit] = ()) -> SetEnd | None:
    """The set end the counts show, made exact by a hit where one is known.

    The last stand that a flood follows is the one that ended the set: an
    earlier stand a catch reversed has play, not a flood, after it.
    """
    for stand in reversed(last_stands(counts, fps)):
        flood = flood_after(counts, stand, fps)
        if flood is None:
            continue
        inside = [h for h in hits if h.side == stand.side and stand.start_frame <= h.frame <= flood]
        if inside:
            hit = max(inside, key=lambda h: h.frame)
            return SetEnd(frame=hit.frame, source="hit", stand=stand, flood_frame=flood, hit=hit)
        return SetEnd(frame=stand.end_frame, source="floor", stand=stand, flood_frame=flood)
    return None


def occupancy(roster, frames: Iterable[int]) -> list[tuple[int, int, int]]:
    """(frame, near, far) in play per frame, as the roster counts them."""
    out = []
    for f in frames:
        on = roster.on_court(f)
        out.append((f, len(on["near"]), len(on["far"])))
    return out


def detect_set_end(roster, start_frame: int, bound_frame: int, fps: float,
                   hits: Iterable[Hit] = ()) -> SetEnd | None:
    """The end of the set that starts at ``start_frame``, searched up to the bound."""
    return end_from_counts(occupancy(roster, range(start_frame, bound_frame + 1)), fps, hits)


def trace_back(throws: list[tuple[int, int, str]], end: SetEnd) -> int | None:
    """The throw that ended the set, when no step could name it.

    The count never drops for the final elimination - the last player is
    still on the paint while the floor fills - so the outcome stage cannot
    see it. The end says where it was: the latest throw by the other side at
    the stand's side inside the hit window. ``throws`` are (id, frame, team).
    """
    lo, hi = end.hit_window
    other = "far" if end.stand.side == "near" else "near"
    inside = [t for t in throws if t[2] == other and lo <= t[1] <= hi]
    return max(inside, key=lambda t: t[1])[0] if inside else None
