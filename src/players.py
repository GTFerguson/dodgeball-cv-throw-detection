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


@dataclass(frozen=True)
class Player:
    """A team and number, and every track that wore it in the order worn."""

    team: str | None
    number: int
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


def join(spans: dict[int, tuple[int, int]], numbers: dict[int, int],
         teams: dict[int, str | None] | None = None,
         max_overlap: int = JOIN_MAX_OVERLAP) -> list[Player]:
    """The players in a clip: one per team and number, or one per track where
    that key is worn by two people at once.

    `spans` is each track's first and last frame; `numbers` the confirmed
    number of each track that has one; `teams` the side each track played on,
    where known. Unnamed tracks are nobody's, and are not returned.
    """
    teams = teams or {}
    by_key: dict[tuple[str, int], list[int]] = {}
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
