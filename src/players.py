"""One player from the several tracks that followed them.

A track is not a player. The tracker loses a player in the huddle between sets
and gives them a fresh id on the other side, so a player who is on court for a
whole set is two or three tracks - and attribution that named the thrower by
track would count one player as three. The number joins them: it is the only
identity that survives a lost track, and it never has to be read across the gap.
Each fragment is named on its own crops, and fragments that confirm to the same
number are one player.

The same number on the other side, though, is another player. Numbers are per
team, both teams are on court at once, and #2 and #13 on the evaluation clip are
USA - so the key a fragment is joined on is the team and the number together,
with the team taken from the half of the court the track played in, which the
roster decides. Time is the last check: two tracks with one key in the same
frames are two people the roster could not tell apart, or a misread, and either
way the number cannot say which later fragment is whose.
"""

from __future__ import annotations

from dataclasses import dataclass

# Two tracks of one player can overlap briefly: when a tracker swap is cut, the
# player's own starved track lingers a second on stray detections after the
# other track has taken his body (56 and 422 on the evaluation clip share 24
# frames). Two seconds covers that, and two *players* sharing a key overlap for
# as long as they are both in play, which is hundreds of frames.
JOIN_MAX_OVERLAP = 50


# Two players can wear one number at one moment: the teams are numbered
# separately, so a near 2 and a far 2 are both real and the join key carries the
# side for exactly that reason. Three cannot - there are two teams on court.
MAX_WEARERS = 2

# A track is only claiming a number if it read it often enough that the number
# could have named it. One or two readings is the reader guessing at a fold, and
# counting those as claims lets stray misreads condemn a real number.
CLAIM_MIN_READINGS = 3


def worn_at_once(spans: dict[int, tuple[int, int]],
                 counts: dict[int, dict[str, int]],
                 max_wearers: int = MAX_WEARERS,
                 min_readings: int = CLAIM_MIN_READINGS) -> set[str]:
    """The numbers claimed by more players than could be wearing them.

    `counts` maps each track to how many times it read each number. A number
    claimed by more tracks than there are teams, while all of those tracks are
    on court together, is not a number at all: it is something every player on a
    side wears, which is what the team's name across the chest is. On the
    evaluation clip the reader returns `54` for the `USA` print, and six far
    tracks claim it in the same frames.

    This is the same argument `clash` makes when it refuses to join, made one
    stage earlier and against the reading rather than the name - because a print
    read as a number does not just fail to join, it outvotes the real number on
    the crops it appears in.
    """
    claimants: dict[str, list[int]] = {}
    for tid, per_number in counts.items():
        if tid not in spans:
            continue
        for number, count in per_number.items():
            if count >= min_readings:
                claimants.setdefault(number, []).append(tid)
    impossible = set()
    for number, ids in claimants.items():
        if len(ids) <= max_wearers:
            continue
        # Most tracks on court at any one moment, by sweeping their ends.
        edges = sorted([(spans[i][0], 1) for i in ids] + [(spans[i][1] + 1, -1) for i in ids])
        live = most = 0
        for _, step in edges:
            live += step
            most = max(most, live)
        if most > max_wearers:
            impossible.add(number)
    return impossible


@dataclass(frozen=True)
class Player:
    """A team and number, and every track that wore it in the order worn."""

    team: str | None
    number: str
    track_ids: tuple[int, ...]
    start: int
    end: int


def clash(spans: dict[int, tuple[int, int]], ids: list[int],
          max_overlap: int = JOIN_MAX_OVERLAP) -> tuple[int, int] | None:
    """The first two of these tracks that are on court together, or None.

    Together means overlapping by more than `max_overlap` frames.
    """
    ordered = sorted(ids, key=lambda i: spans[i])
    for k, a in enumerate(ordered):
        for b in ordered[k + 1:]:
            overlap = min(spans[a][1], spans[b][1]) - max(spans[a][0], spans[b][0]) + 1
            if overlap > max_overlap:
                return a, b
    return None


def join(spans: dict[int, tuple[int, int]], numbers: dict[int, str],
         teams: dict[int, str | None] | None = None,
         max_overlap: int = JOIN_MAX_OVERLAP) -> list[Player]:
    """The players in a clip: one per team and number, or one per track where
    that key is worn by two people at once.

    `spans` is each track's first and last frame; `numbers` the confirmed
    number of each track that has one; `teams` the side each track played on,
    where known. Unnamed tracks are nobody's, and are not returned.
    """
    teams = teams or {}
    by_key: dict[tuple[str, str], list[int]] = {}
    for tid, number in numbers.items():
        by_key.setdefault((teams.get(tid) or "", number), []).append(tid)
    players: list[Player] = []
    for (team, number), ids in sorted(by_key.items()):
        ordered = sorted(ids, key=lambda i: spans[i])
        groups = [ordered] if clash(spans, ids, max_overlap) is None else [[i] for i in ordered]
        for group in groups:
            players.append(Player(
                team=team or None,
                number=number,
                track_ids=tuple(group),
                start=min(spans[i][0] for i in group),
                end=max(spans[i][1] for i in group),
            ))
    return players
