"""Who is on the floor: every tracked person in a clip, with a role and a team.

A track is a span the tracker held on to; it says nothing about whether the
person was a player, a referee or someone on the bench, and nothing about which
side they play for. Every stage downstream asks exactly those questions - the
candidate detector must not propose a referee's arm, attribution must name a
side, occupancy per side is the elimination stream - and each one re-deriving
the answers from geometry is how the same test gets written twice and drifts.

This module is the one place the answers live. The identity pass
(``scripts/identify_players.py``) writes ``data/roster/<stem>.json`` in the
same run that reads the jersey numbers; :class:`Roster` reads it; nothing else
decides who is a player.

Two levels are recorded, because callers ask at two grains:

* a **track** is one tracker span, with a role, a team, the frames it holds and
  the frames the player was in play;
* a **participant** is a person - one or more tracks joined by the number they
  wore, or a single track where no number was read.

How role is decided
-------------------

The game's own rule does most of the work: nobody but a player is inside the
court while a set is live. So a track with in-play frames inside the live core
of a set - the stretch after the whistle where a set is certainly still being
played - is a player, whatever they are wearing. That matters because kit
colour alone cannot be trusted: on the evaluation footage USA #2 wears a large
black print across the chest and reads as black as a referee's shirt.

Only for tracks never seen in live play does kit decide. Officials wear black;
each team wears one kit; a track with too few clean crops to vote stays
``unknown`` rather than being guessed. Kit is read from the chest - the strip
between the shoulder and hip keypoints - because a box-based torso crop drags
in hair, sleeves and background until a white jersey with black sleeves and a
black shirt with white shoulder panels look alike.

Who played
----------

``player`` is a role, and it is wider than "played the set": a team kit on a
track never seen in play is a player waiting to rush, eliminated, or on the
bench. The question the cards, the occupancy stream and attribution all ask is
narrower - who was on the court while a set was live - and it is answered per
set at the participant grain: ``played_sets`` names every set whose live core
held the person's tracks in play for at least ``PLAYER_MIN_CORE_FRAMES``, the
same evidence that made their tracks players, and ``played`` is whether that
names any. A clip holds several sets and a player sits some out, so the list
is what a per-set filter needs; the total alone cannot say which. It is a
decision the roster writes down, not one readers derive.

The same rule of the game names the pieces no number was read on. A track
lost and picked up again is a fresh id with no number until the reader gets
one, and on a set's court there are only the six: a piece in play on a side
while exactly one of its six has no track is that player
(:func:`players.fold_by_occupancy`). A piece in play when all six are already
tracked is a seventh body - a second track on one player, or a misrole - and
is marked ``excess`` rather than counted as someone who played.

The live core has a start (the whistle, exact) and a length, because the end
of a set is still only bounded - officials lay balls out on the court between
sets and the interval runs into that. Sets on this footage run three minutes
and more, so the core stops well short of any of them ending.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from src.venue import VENUE

REPO_ROOT = Path(__file__).resolve().parent.parent
ROSTER_ROOT = REPO_ROOT / "data" / "roster"

SCHEMA_VERSION = 6
# Schema 5 lacks only the fold's provenance, which reads as "nothing folded".
READABLE_SCHEMAS = (5, SCHEMA_VERSION)

ROLES = ("player", "official", "unknown")
TEAMS = ("near", "far")

# The kits on the evaluation footage. Team kits map to a side once the roster
# has seen which half each colour plays in; the officials' kit maps to no side.
# The kit colours chests are classified into and which the officials wear are
# the venue's (config/venue.toml); "unknown" is the classifier's own answer.
KITS = (*VENUE["teams"]["kits"], "unknown")
OFFICIAL_KIT = VENUE["teams"]["official_kit"]

# COCO keypoint indices.
LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP = 5, 6, 11, 12
KEYPOINT_MIN_CONF = 0.30

# The chest strip: shoulder-to-hip, trimmed at the sides to stay off the arms
# and top and bottom to stay off the neckline and the waistband.
CHEST_SIDE_TRIM = 0.20
CHEST_TOP_TRIM = 0.10
CHEST_BOTTOM_TRIM = 0.10
CHEST_MIN_SIZE_PX = 12

# HSV limits for the three kit colours (OpenCV ranges: H 0-179, S and V 0-255).
BLACK_MAX_VALUE = 80
RED_HUE_BELOW, RED_HUE_ABOVE = 12, 168
RED_MIN_SAT = 90
WHITE_MAX_SAT = 60
WHITE_MIN_VALUE = 150

# A crop votes only when one colour clearly covers the chest, and a track is
# named only when enough crops agree. Referees measured 0.64-0.91 black and the
# team kits 0.40-0.87 of their colour on the evaluation clip; the print on a
# jersey is what pulls a crop below the floor, and it is right to abstain there.
KIT_MIN_SAMPLES = 5
KIT_MIN_COVERAGE = 0.30
KIT_MIN_MARGIN = 2.0
KIT_MIN_AGREEMENT = 0.60

# How long after the whistle a set is certainly still live. Sets on the
# evaluation footage run 3-3.5 minutes; a referee inside the court in the
# first 150 s of one would be a rule violation, not a false positive.
LIVE_CORE_S = 150.0
# In-play frames inside the live core needed to call a track a player - one
# second, so a single detection blown across the line does not do it.
PLAYER_MIN_CORE_FRAMES = 25


def live_cores(timeline, fps: float) -> dict[int, tuple[int, int]]:
    """The stretch of each set that is certainly still live, by set index."""
    cores = {}
    for interval in timeline.live_play_intervals():
        end = min(interval.end_frame, interval.start_frame + int(LIVE_CORE_S * fps))
        cores[interval.set_index] = (interval.start_frame, end)
    return cores


def core_of(frame: int, cores: dict[int, tuple[int, int]]) -> int | None:
    """The set whose live core holds a frame, or None."""
    for index, (a, b) in cores.items():
        if a <= frame <= b:
            return index
    return None


def in_core(frame: int, cores: dict[int, tuple[int, int]]) -> bool:
    return core_of(frame, cores) is not None


def participant_id(role: str, team: str | None, number: str | None, track_id: int) -> str:
    """`near-7` for a numbered player on a known side; `<role>-t<track>` otherwise.

    An id says what is known about the person and nothing more.
    """
    if role == "player" and number is not None and team is not None:
        return f"{team}-{number}"
    return f"{role}-t{track_id}"


# --------------------------------------------------------------------------
# Kit colour
# --------------------------------------------------------------------------

def chest_region(detection: dict) -> tuple[int, int, int, int] | None:
    """Pixel box of the chest strip, or None when the keypoints cannot place it."""
    kpts = detection.get("kpts") or []
    needed = (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP)
    if len(kpts) <= max(needed) or any(kpts[i][2] < KEYPOINT_MIN_CONF for i in needed):
        return None
    xs = [kpts[i][0] for i in needed]
    shoulder_y = (kpts[LEFT_SHOULDER][1] + kpts[RIGHT_SHOULDER][1]) / 2
    hip_y = (kpts[LEFT_HIP][1] + kpts[RIGHT_HIP][1]) / 2
    width, height = max(xs) - min(xs), hip_y - shoulder_y
    if width < CHEST_MIN_SIZE_PX or height < CHEST_MIN_SIZE_PX:
        return None
    x1 = int(min(xs) + CHEST_SIDE_TRIM * width)
    x2 = int(max(xs) - CHEST_SIDE_TRIM * width)
    y1 = int(shoulder_y + CHEST_TOP_TRIM * height)
    y2 = int(hip_y - CHEST_BOTTOM_TRIM * height)
    if x2 <= x1 or y2 <= y1:
        return None
    return max(0, x1), max(0, y1), x2, y2


def kit_fractions(chest_bgr: np.ndarray) -> tuple[float, float, float]:
    """Fraction of the chest that is black, red and white, in that order."""
    import cv2

    hsv = cv2.cvtColor(chest_bgr, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    n = float(h.size) or 1.0
    black = (v < BLACK_MAX_VALUE)
    red = ((h < RED_HUE_BELOW) | (h > RED_HUE_ABOVE)) & (s > RED_MIN_SAT) & ~black
    white = (s < WHITE_MAX_SAT) & (v > WHITE_MIN_VALUE)
    return float(black.sum() / n), float(red.sum() / n), float(white.sum() / n)


def crop_vote(fractions: tuple[float, float, float]) -> str | None:
    """The colour one crop votes for, or None when nothing clearly covers it."""
    black, red, white = fractions
    ranked = sorted((("black", black), ("red", red), ("white", white)),
                    key=lambda kv: kv[1], reverse=True)
    (top, share), (_, runner_up) = ranked[0], ranked[1]
    if share < KIT_MIN_COVERAGE or share < KIT_MIN_MARGIN * runner_up:
        return None
    return top


def vote_kit(samples: list[tuple[float, float, float]]) -> tuple[str, float]:
    """The kit a track wears and how much of the vote it took.

    ``unknown`` when there are too few crops, too few of them say anything, or
    they disagree - a guessed kit names a referee a player.
    """
    votes = [v for v in (crop_vote(s) for s in samples) if v is not None]
    if len(votes) < KIT_MIN_SAMPLES:
        return "unknown", 0.0
    top, count = Counter(votes).most_common(1)[0]
    share = count / len(votes)
    return (top if share >= KIT_MIN_AGREEMENT else "unknown"), share


# --------------------------------------------------------------------------
# Role and team
# --------------------------------------------------------------------------

def assign_role(kit: str, core_in_play_frames: int) -> str:
    """Player, official or unknown.

    Time on court while the set is certainly live decides first; kit only
    speaks for tracks never seen there.
    """
    if core_in_play_frames >= PLAYER_MIN_CORE_FRAMES:
        return "player"
    if kit == OFFICIAL_KIT:
        return "official"
    if kit in KITS and kit != "unknown":
        return "player"
    return "unknown"


def sides_from(observations: list[tuple[str, str]]) -> dict[str, str]:
    """Which side wears which kit, from (kit, half) pairs of players in play.

    A kit is mapped only when it is seen on one half far more than the other;
    a colour that shows up on both is not a team kit.
    """
    counts: dict[str, Counter] = {}
    for kit, half in observations:
        if kit in ("unknown", OFFICIAL_KIT):
            continue
        counts.setdefault(kit, Counter())[half] += 1
    sides = {}
    for kit, by_half in counts.items():
        (half, n), *rest = by_half.most_common()
        other = rest[0][1] if rest else 0
        if n >= 3 and n >= 3 * max(other, 1):
            sides[kit] = half
    return sides


def assign_team(half_counts: dict[str, int], kit: str,
                sides: dict[str, str]) -> tuple[str | None, str | None]:
    """The side a track belongs to and where that came from.

    The half a player stands in while in play is definitive - teams cannot cross
    the centre line - so it wins whenever there is one. Kit fills in for tracks
    never in play: the eliminated queue, the bench, and anyone waiting to rush.
    """
    in_play = {h: n for h, n in half_counts.items() if n > 0}
    if in_play:
        return max(in_play, key=in_play.get), "half"
    if kit in sides:
        return sides[kit], "kit"
    return None, None


# --------------------------------------------------------------------------
# The roster
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class TrackRecord:
    """One tracker span, with everything the roster decided about it."""

    id: int
    participant_id: str
    role: str
    team: str | None
    team_source: str | None
    kit: str
    kit_share: float
    number: str | None
    # How the track got its number: `read` off the jersey, or `occupancy` -
    # folded into the one player missing from the six while it was in play.
    number_source: str | None
    start_frame: int
    end_frame: int
    # (frame, index of the detection in the pose run's list for that frame).
    # The box and keypoints stay in the pose run; the roster only points at them.
    detections: tuple[tuple[int, int], ...]
    # Inclusive frame intervals where the player counted as in play.
    in_play: tuple[tuple[int, int], ...]
    # In-play frames inside each set's live core, by set index. Kept per set
    # so a person's `played_sets` can be seen track by track.
    core_in_play_by_set: dict[int, int]
    split_from: tuple[int, int] | None = None
    # Every jersey number the reader returned on this track, as
    # (frame, number, confidence) in time order - the evidence behind `number`,
    # kept so the sheet and a reviewer can see why a track was or was not named.
    readings: tuple[tuple[int, int, float], ...] = ()

    @property
    def frames(self) -> int:
        return len(self.detections)

    @property
    def in_play_frames(self) -> int:
        return sum(b - a + 1 for a, b in self.in_play)

    @property
    def core_in_play_frames(self) -> int:
        """In-play frames inside any live core - the evidence for `player`."""
        return sum(self.core_in_play_by_set.values())

    def is_in_play(self, frame: int) -> bool:
        return any(a <= frame <= b for a, b in self.in_play)


@dataclass(frozen=True)
class Participant:
    """A person: the tracks that were one player, referee or unknown."""

    id: str
    role: str
    team: str | None
    number: str | None
    track_ids: tuple[int, ...]
    start_frame: int
    end_frame: int
    # In-play frames inside each set's live core, summed over the tracks.
    core_in_play_by_set: dict[int, int]
    # In play when its side already had six on the floor: a second track on
    # one player, or a misrole. Kept as a player so the box is still not an
    # official's, but never counted as someone who played.
    excess: bool = False

    @property
    def core_in_play_frames(self) -> int:
        return sum(self.core_in_play_by_set.values())

    @property
    def played_sets(self) -> tuple[int, ...]:
        """The sets this person was on the court for while they were live.

        Judged set by set: a second inside one set's core, not a second spread
        over several. An official inside a core is a rule violation, never
        someone who played, and neither is a seventh body.
        """
        if self.role != "player" or self.excess:
            return ()
        return tuple(sorted(s for s, n in self.core_in_play_by_set.items()
                            if n >= PLAYER_MIN_CORE_FRAMES))

    @property
    def played(self) -> bool:
        """Whether this person was on the court while any set was live."""
        return bool(self.played_sets)


@dataclass(frozen=True)
class Presence:
    """One person on one frame."""

    track: TrackRecord
    participant: Participant
    detection_index: int
    in_play: bool


def intervals_of(frames: list[int], flags: list[bool]) -> list[tuple[int, int]]:
    """Run-length encode the frames where a flag holds, as inclusive intervals."""
    out: list[tuple[int, int]] = []
    for f, on in zip(frames, flags, strict=True):
        if not on:
            continue
        if out and out[-1][1] == f - 1:
            out[-1] = (out[-1][0], f)
        else:
            out.append((f, f))
    return out


@dataclass
class Roster:
    video: str
    clip_sha256: str
    pose_run: str
    fps: float
    frame_count: int
    sides: dict[str, str]
    # The frames the `player` rule was judged over, by set index.
    live_cores: dict[int, tuple[int, int]]
    tracks: dict[int, TrackRecord]
    participants: dict[str, Participant]
    _by_frame: dict[int, list[tuple[int, int]]] = field(default_factory=dict, repr=False)

    def __post_init__(self):
        for t in self.tracks.values():
            for frame, index in t.detections:
                self._by_frame.setdefault(frame, []).append((t.id, index))

    # -- reading -----------------------------------------------------------

    @classmethod
    def load(cls, path: str | Path) -> Roster:
        data = json.loads(Path(path).read_text())
        if data.get("schema_version") not in READABLE_SCHEMAS:
            raise ValueError(f"{path} is schema {data.get('schema_version')}, "
                             f"expected {SCHEMA_VERSION}")
        tracks = {
            t["id"]: TrackRecord(
                id=t["id"], participant_id=t["participant"], role=t["role"],
                team=t["team"], team_source=t["team_source"], kit=t["kit"],
                kit_share=t["kit_share"], number=t["number"],
                number_source=t.get("number_source", "read" if t["number"] is not None else None),
                start_frame=t["start_frame"], end_frame=t["end_frame"],
                detections=tuple((f, i) for f, i in t["detections"]),
                in_play=tuple((a, b) for a, b in t["in_play"]),
                core_in_play_by_set={int(s): n for s, n in t["core_in_play_by_set"]},
                split_from=tuple(t["split_from"]) if t.get("split_from") else None,
                readings=tuple((f, n, c) for f, n, c in t.get("readings", ())),
            ) for t in data["tracks"]
        }
        participants = {
            p["id"]: Participant(
                id=p["id"], role=p["role"], team=p["team"], number=p["number"],
                track_ids=tuple(p["track_ids"]),
                start_frame=p["start_frame"], end_frame=p["end_frame"],
                core_in_play_by_set={int(s): n for s, n in p["core_in_play_by_set"]},
                excess=p.get("excess", False),
            ) for p in data["participants"]
        }
        return cls(
            video=data["video"], clip_sha256=data["clip_sha256"],
            pose_run=data["pose_run"], fps=data["fps"], frame_count=data["frame_count"],
            sides=dict(data["sides"]),
            live_cores={s: (a, b) for s, a, b in data["live_cores"]},
            tracks=tracks, participants=participants,
        )

    @classmethod
    def for_video(cls, video: str | Path) -> Roster:
        return cls.load(ROSTER_ROOT / f"{Path(video).stem}.json")

    def check_clip(self, clip_sha256: str) -> None:
        """Refuse a roster built on a different cut of the footage."""
        if self.clip_sha256 != clip_sha256:
            raise ValueError(f"roster for {self.video} was built on a different clip")

    # -- writing -----------------------------------------------------------

    def to_json(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "video": self.video,
            "clip_sha256": self.clip_sha256,
            "pose_run": self.pose_run,
            "fps": self.fps,
            "frame_count": self.frame_count,
            "sides": dict(self.sides),
            "live_cores": [[s, a, b] for s, (a, b) in sorted(self.live_cores.items())],
            "thresholds": {
                "live_core_s": LIVE_CORE_S,
                "player_min_core_frames": PLAYER_MIN_CORE_FRAMES,
                "kit_min_samples": KIT_MIN_SAMPLES,
                "kit_min_coverage": KIT_MIN_COVERAGE,
                "kit_min_agreement": KIT_MIN_AGREEMENT,
            },
            "participants": [{
                "id": p.id, "role": p.role, "team": p.team, "number": p.number,
                "track_ids": list(p.track_ids),
                "start_frame": p.start_frame, "end_frame": p.end_frame,
                "core_in_play_by_set": [[s, n] for s, n in sorted(p.core_in_play_by_set.items())],
                "core_in_play_frames": p.core_in_play_frames,
                "played_sets": list(p.played_sets), "played": p.played,
                "excess": p.excess,
            } for p in sorted(self.participants.values(),
                              key=lambda p: (ROLES.index(p.role), p.team or "", p.number or "", p.id))],
            "tracks": [{
                "id": t.id, "participant": t.participant_id, "role": t.role,
                "team": t.team, "team_source": t.team_source,
                "kit": t.kit, "kit_share": round(t.kit_share, 3), "number": t.number,
                "number_source": t.number_source,
                "start_frame": t.start_frame, "end_frame": t.end_frame,
                "frames": t.frames, "in_play_frames": t.in_play_frames,
                "core_in_play_by_set": [[s, n] for s, n in sorted(t.core_in_play_by_set.items())],
                "core_in_play_frames": t.core_in_play_frames,
                "split_from": list(t.split_from) if t.split_from else None,
                "in_play": [list(iv) for iv in t.in_play],
                "readings": [list(r) for r in t.readings],
                "detections": [list(d) for d in t.detections],
            } for t in sorted(self.tracks.values(), key=lambda t: (t.start_frame, t.id))],
        }

    def write(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_json(), separators=(",", ":")))
        return path

    # -- queries -----------------------------------------------------------

    def track(self, track_id: int) -> TrackRecord:
        return self.tracks[track_id]

    def participant(self, participant_id: str) -> Participant:
        return self.participants[participant_id]

    def participant_of(self, track_id: int) -> Participant:
        return self.participants[self.tracks[track_id].participant_id]

    def players(self, team: str | None = None) -> list[Participant]:
        """Every player, or every player on one side."""
        return [p for p in self.participants.values()
                if p.role == "player" and (team is None or p.team == team)]

    def played(self, team: str | None = None, set_index: int | None = None) -> list[Participant]:
        """Who was on the court while a set was live: any set, or one set, on one side or both.

        Narrower than :meth:`players`, which also holds the bench, the queue and
        the pre-rush crowd in team kit.
        """
        return [p for p in self.participants.values()
                if p.played and (team is None or p.team == team)
                and (set_index is None or set_index in p.played_sets)]

    def excess(self) -> list[Participant]:
        """The seventh bodies: in play on a side that already had its six."""
        return [p for p in self.participants.values() if p.excess]

    def officials(self) -> list[Participant]:
        return [p for p in self.participants.values() if p.role == "official"]

    def unknown(self) -> list[Participant]:
        return [p for p in self.participants.values() if p.role == "unknown"]

    def player_tracks(self, team: str | None = None) -> list[TrackRecord]:
        return [t for t in self.tracks.values()
                if t.role == "player" and (team is None or t.team == team)]

    def at(self, frame: int, role: str | None = None) -> list[Presence]:
        """Everyone tracked on a frame, optionally only those with one role."""
        out = []
        for track_id, index in self._by_frame.get(frame, ()):
            t = self.tracks[track_id]
            if role is not None and t.role != role:
                continue
            out.append(Presence(track=t, participant=self.participants[t.participant_id],
                                detection_index=index, in_play=t.is_in_play(frame)))
        return out

    def in_play(self, track_id: int, frame: int) -> bool:
        return self.tracks[track_id].is_in_play(frame)

    def on_court(self, frame: int) -> dict[str, list[Presence]]:
        """Players in play on a frame, by side - the occupancy a set is scored on."""
        out: dict[str, list[Presence]] = {team: [] for team in TEAMS}
        for p in self.at(frame, role="player"):
            if p.in_play and p.track.team in out:
                out[p.track.team].append(p)
        return out
