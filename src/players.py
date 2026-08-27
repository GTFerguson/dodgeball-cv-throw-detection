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

from collections.abc import Callable
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


# --------------------------------------------------------------------------
# Folding the pieces no number was read on
# --------------------------------------------------------------------------

# Players a side in a WDBF set. The rule of the game the fold rests on: nobody
# but those six is inside a side's court while the set is live.
SIDE_SIZE = 6


@dataclass(frozen=True)
class Fold:
    """What folding decided about the unnamed pieces.

    ``folded`` maps a piece to the player it turned out to be; ``excess`` holds
    the pieces that were in play when their side already had its six on the
    floor, which no player can be - a second track on one body, or a misrole;
    ``unsure`` is the rest: two players missing at once, a side with fewer than
    six players known, or no side at all.
    """

    players: list[Player]
    folded: dict[int, Player]
    excess: frozenset[int]
    unsure: frozenset[int]


def _present(player: Player, piece: int, spans: dict[int, tuple[int, int]],
             max_overlap: int, together: Callable[[int, int], bool] | None) -> bool:
    """Whether any of a player's tracks is on court with the piece.

    Two tracks on court together for longer than a hand-over are two people.
    A shorter overlap is a hand-over - the player's own track lingering while
    the piece takes their body - or two people after all, and only position
    can say which: `together` answers whether two tracks share one body over
    the frames they share. Without it a short overlap is taken as a hand-over.
    """
    a, b = spans[piece]
    for tid in player.track_ids:
        overlap = min(spans[tid][1], b) - max(spans[tid][0], a) + 1
        if overlap > max_overlap:
            return True
        if overlap > 0 and together is not None and not together(tid, piece):
            return True
    return False


def fold_by_occupancy(players: list[Player], pieces: list[int],
                      spans: dict[int, tuple[int, int]],
                      teams: dict[int, str | None],
                      core_frames: dict[int, dict[int, int]],
                      min_core_frames: int,
                      side_size: int = SIDE_SIZE,
                      max_overlap: int = JOIN_MAX_OVERLAP,
                      together: Callable[[int, int], bool] | None = None,
                      continues: Callable[[int, int], bool] | None = None,
                      claims: dict[int, set[str]] | None = None) -> Fold:
    """Name the pieces no number was read on, by who is missing from the six.

    A piece is an unnamed track that was in play inside a set's live core. Only
    a side's six players can be on its court then, so if exactly one of the six
    has no track on court during the piece, the piece is that player. The rule
    is exact rather than a guess, and it keeps silent whenever it is not: with
    fewer than six of a side's players numbered the sixth is an unknown who is
    always a candidate, and with two players missing at once the number cannot
    say which. It runs to a fixpoint, because naming one piece can be what
    makes the next one unambiguous.

    `core_frames` is each track's in-play frames inside each set's core, by set
    index; a piece is judged in the set it was mostly in play in, against the
    players who played that set. `together(a, b)` says whether two tracks were
    one body over the frames they share, which is what tells a hand-over from
    two players briefly on court at once (see :func:`_present`); `continues(a,
    b)` says whether track `b` picks up where `a` left off - a short gap with
    the box in the same place - which names the piece when two players are
    missing at once but only one of them was just lost there. `claims` holds
    the numbers each piece read often enough to claim, short of confirming:
    the count never overrules the reader, so a piece that read a number can
    only be that number, and one that read a number the count rules out is
    left unnamed and reported rather than folded. Two undecided pieces on court together whose
    only candidate is the same player are left undecided, rather than one being
    named by the order they were looked at.
    """
    players = list(players)
    folded: dict[int, Player] = {}
    undecided = [p for p in pieces if teams.get(p) and core_frames.get(p)]
    unsure = set(pieces) - set(undecided)

    def set_of(piece: int) -> int:
        frames = core_frames[piece]
        return max(frames, key=lambda s: (frames[s], -s))

    def played(player: Player, set_index: int) -> bool:
        return sum(core_frames.get(t, {}).get(set_index, 0) for t in player.track_ids) >= min_core_frames

    def candidates(piece: int) -> list[int] | None:
        """Indices into `players`, or None where the rule cannot speak."""
        side, set_index = teams[piece], set_of(piece)
        six = [i for i, p in enumerate(players) if p.team == side and played(p, set_index)]
        if len(six) < side_size:
            return None
        found = [i for i in six if not _present(players[i], piece, spans, max_overlap, together)]
        if not found:
            return found  # a seventh body, whatever it read
        claimed = (claims or {}).get(piece)
        if claimed:
            found = [i for i in found if players[i].number in claimed]
            if not found:
                return None
        if len(found) > 1 and continues is not None:
            seam = [i for i in found if any(continues(t, piece) for t in players[i].track_ids)]
            if len(seam) == 1:
                return seam
        return found

    while True:
        options = {p: candidates(p) for p in undecided}
        decided: dict[int, int] = {}
        for piece, found in options.items():
            if not found or len(found) != 1:
                continue
            only = found[0]
            rivals = [q for q in undecided if q != piece and options[q] == [only]
                      and min(spans[q][1], spans[piece][1]) - max(spans[q][0], spans[piece][0]) + 1 > max_overlap]
            if not rivals:
                decided[piece] = only
        if not decided:
            break
        for piece, i in decided.items():
            p = players[i]
            ids = tuple(sorted(p.track_ids + (piece,), key=lambda t: spans[t]))
            players[i] = Player(team=p.team, number=p.number, track_ids=ids,
                                start=min(p.start, spans[piece][0]), end=max(p.end, spans[piece][1]))
            folded[piece] = players[i]
            undecided.remove(piece)
        # Whatever was named this round now names the player it became, so
        # every earlier fold points at the player's final shape.
        for piece, p in folded.items():
            folded[piece] = next(q for q in players if q.team == p.team and q.number == p.number
                                 and piece in q.track_ids)

    excess = set()
    for piece in undecided:
        found = candidates(piece)
        if found is not None and not found:
            excess.add(piece)
        else:
            unsure.add(piece)
    return Fold(players=players, folded=folded, excess=frozenset(excess), unsure=frozenset(unsure))


# --------------------------------------------------------------------------
# A swap between two tracks
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Swap:
    """Two tracks that traded players: `a` wore `number` until `last_a`, and
    `b` wears it from `first_b`. The trade happened in between."""

    a: int
    b: int
    number: str
    last_a: int
    first_b: int


def swaps_between(spans: dict[int, tuple[int, int]],
                  windows: dict[int, dict[str, tuple[int, int]]],
                  max_overlap: int = JOIN_MAX_OVERLAP) -> list[Swap]:
    """Pairs of concurrent tracks that claim one number one after the other.

    A track that reads a number and then stops, while another track on court
    with it starts reading the same number, is the tracker having swapped the
    two players between them: the number moved from one id to the other, and
    the man it was on did not. `windows` maps each track to the first and
    last frame it read each number it claims. Both tracks must be on court
    together for longer than a hand-over - a number handed from one track to
    its successor is a join, not a swap - and the reading windows must not
    overlap, since a number two tracks read at once is two people or a misread.
    Where the trade happened is for the boxes to say (`tracking.swap_frame`).
    """
    found = []
    ids = sorted(windows, key=lambda i: spans[i])
    for k, a in enumerate(ids):
        for b in ids[k + 1:]:
            overlap = min(spans[a][1], spans[b][1]) - max(spans[a][0], spans[b][0]) + 1
            if overlap <= max_overlap:
                continue
            for number in windows[a].keys() & windows[b].keys():
                (fa, la), (fb, lb) = windows[a][number], windows[b][number]
                if la < fb:
                    found.append(Swap(a, b, number, la, fb))
                elif lb < fa:
                    found.append(Swap(b, a, number, lb, fa))
    return found
