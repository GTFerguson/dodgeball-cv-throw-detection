"""Throw efficiency split by how the throw was set up.

Team throw efficiency is eliminations over throws. This splits the throws by
the context the timeline already carries, so the same fold that gives the
headline number asks whether the set-up mattered:

* **coordinated** - an *attack* of two or more same-team throws released
  within ``COORDINATION_S`` of each other. The tactic against a lone dodger
  is two balls at once, since one player dodges one ball; the plan proposed
  this split. It is scored per attack, not per throw: two balls for one out
  is the tactic working, and per throw it would read as 1 for 2.
* **fake-led** - a throw with a same-team fake inside the trailing
  ``FAKE_WINDOW_S``. Fakes are first-class events in the timeline, so the
  question "does faking first convert more often" costs nothing to ask.

Nothing here is a result on one set - twenty-nine throws split three ways
are bins of four - it is the question the pipeline exists to ask over a
match. Both windows are durations so a timeline at another frame rate
splits the same way.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

# WDBF play has no rule here; 300 ms is the plan's figure for "released
# together" - the second ball is in the air before the first has arrived.
COORDINATION_S = 0.3
# Long enough to hold a whole hold-and-fake exchange, short enough that the
# fake is still what the defence is reacting to.
FAKE_WINDOW_S = 6.0
FAKE_BINS = ("0", "1", "2+")


@dataclass(frozen=True)
class Event:
    frame: int
    team: str
    kind: str  # fake | pass | throw
    won: bool  # a throw that put a live player out


def attacks(events: list[Event], fps: float) -> list[list[Event]]:
    """Same-team throws grouped into attacks: consecutive releases within
    COORDINATION_S of each other are one attack, however many balls."""
    window = round(COORDINATION_S * fps)
    out: list[list[Event]] = []
    for team in sorted({e.team for e in events}):
        throws = sorted((e for e in events if e.team == team and e.kind == "throw"),
                        key=lambda e: e.frame)
        group: list[Event] = []
        for t in throws:
            if group and t.frame - group[-1].frame > window:
                out.append(group)
                group = []
            group.append(t)
        if group:
            out.append(group)
    return sorted(out, key=lambda g: g[0].frame)


def coordinated(events: list[Event], throw: Event, fps: float) -> bool:
    return any(len(g) > 1 and throw in g for g in attacks(events, fps))


def fakes_before(events: list[Event], throw: Event, fps: float) -> int:
    lo = throw.frame - FAKE_WINDOW_S * fps
    return sum(1 for e in events if e.team == throw.team and e.kind == "fake"
               and lo <= e.frame < throw.frame)


def fake_bin(n: int) -> str:
    return FAKE_BINS[min(n, 2)]


def split(events: list[Event], sets: list[tuple[int, int | None]], fps: float) -> dict:
    """Per set and team: eliminations over throws overall and by fake bin, and
    over *attacks* solo and coordinated.

    Returns ``{set_index: {team: {"all": (hits, throws), "solo": (outs, attacks),
    "coordinated": (outs, attacks), "fakes": {"0": ..., "1": ..., "2+": ...}}}}``;
    a final key ``"total"`` sums the sets.
    """
    out: dict = {}
    for i, (start, end) in enumerate(sets):
        inside = [e for e in events if start <= e.frame and (end is None or e.frame <= end)]
        rows = defaultdict(lambda: {"all": [0, 0], "solo": [0, 0], "coordinated": [0, 0],
                                    "fakes": {b: [0, 0] for b in FAKE_BINS}})
        for t in inside:
            if t.kind != "throw":
                continue
            row = rows[t.team]
            for cell in (row["all"], row["fakes"][fake_bin(fakes_before(inside, t, fps))]):
                cell[0] += int(t.won)
                cell[1] += 1
        for group in attacks(inside, fps):
            cell = rows[group[0].team]["coordinated" if len(group) > 1 else "solo"]
            cell[0] += int(any(t.won for t in group))
            cell[1] += 1
        out[i] = {team: row for team, row in sorted(rows.items())}
    total = defaultdict(lambda: {"all": [0, 0], "solo": [0, 0], "coordinated": [0, 0],
                                 "fakes": {b: [0, 0] for b in FAKE_BINS}})
    for rows in out.values():
        for team, row in rows.items():
            for k in ("all", "solo", "coordinated"):
                total[team][k][0] += row[k][0]
                total[team][k][1] += row[k][1]
            for b in FAKE_BINS:
                total[team]["fakes"][b][0] += row["fakes"][b][0]
                total[team]["fakes"][b][1] += row["fakes"][b][1]
    out["total"] = dict(sorted(total.items()))
    return out


def cell(hits_throws: list[int]) -> str:
    h, n = hits_throws
    return "—" if n == 0 else f"{h}/{n} = {100 * h / n:.0f}%"


def format_table(result: dict, title: str) -> str:
    lines = [f"| {title} | Team | All throws | Solo attacks | Coordinated attacks | "
             f"Fakes before: 0 | 1 | 2+ |",
             "|---|---|---|---|---|---|---|---|"]
    for key, rows in result.items():
        name = "total" if key == "total" else f"set {key + 1}"
        for team, row in rows.items():
            f = row["fakes"]
            lines.append(f"| {name} | {team} | {cell(row['all'])} | {cell(row['solo'])} | "
                         f"{cell(row['coordinated'])} | {cell(f['0'])} | {cell(f['1'])} | "
                         f"{cell(f['2+'])} |")
    return "\n".join(lines)
