"""Score a predicted event timeline against the hand-labelled truth set.

The event is a cascade - candidate, release, destination, outcome - and each
level is a separate decision with its own failure mode, so this scores each
level on its own rather than blending them into one F1. A stage that only
claims "a throwing motion happened here" is scored on that claim alone; the
lower levels are reported only where the prediction makes a claim at them,
so a stage is never marked wrong for a question it did not answer.

Matching is by *where*, not by id: a prediction matches a truth event when its
frame is within ``TOLERANCE_FRAMES`` of the labelled release and its thrower
box overlaps the labelled thrower's box on that same frame by ``MIN_IOU`` -
the test the labelling tool uses to tie a proposal to a labelled thrower, so
"the tool agreed" and "the harness agreed" are one statement. The truth file
keys nothing on a track id, which a re-run of the identity pass renumbers;
the roster's tracks are used only to carry the labelled box to neighbouring
frames (``TruthSet.anchored``), never to name a match.

Fakes are events. A wind-up that released nothing is a candidate the model
should find and then classify as no release, so it counts at the candidate
level and is the negative class at the release level. A fake made with no
ball in the hand at all is still a throwing motion meant to draw the
opponent, so it is an event too; it is reported apart, because a stage that
looks for the ball cannot find one and that is a different failure from
missing a wind-up.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LABELS_ROOT = REPO_ROOT / "data" / "labels"

LABEL_SCHEMA_VERSION = 5

# The plan's tolerance on a release: ±0.25 s, six frames at 25 fps. The same
# number the labelling tool uses to match a proposal to a labelled thrower.
TOLERANCE_FRAMES = 6
MIN_IOU = 0.5

KINDS = ("fake", "pass", "throw")
OUTCOMES = ("hit", "catch", "block", "miss")
# A throw that eliminates someone. A catch eliminates the thrower; it is still
# an elimination the throw caused, but the metric counts what the throw won
# for its team, and a catch loses a player. A hit on a player already out
# (WDBF 19.1: only a live player can be put out) carries `eliminated: false`
# and wins nothing.
ELIMINATING = ("hit",)

Box = tuple[float, float, float, float]


def iou(a: Box, b: Box) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    if inter <= 0:
        return 0.0
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _box(d: dict) -> Box:
    return (float(d["x1"]), float(d["y1"]), float(d["x2"]), float(d["y2"]))


@dataclass(frozen=True)
class TruthEvent:
    id: str
    kind: str
    release_frame: int
    end_frame: int | None
    box: Box
    box_frame: int
    team: str | None
    outcome: str | None
    uncertain: bool
    source: str
    proposed_frame: int | None
    # On a fake: whether a ball was in the hand. None where the label does not say.
    ball_in_hand: bool | None = None
    # On a hit: False where the player struck was already out, so nobody was
    # eliminated. None where the label does not say, which counts as an out.
    eliminated: bool | None = None

    @property
    def wins_elimination(self) -> bool:
        return self.outcome in ELIMINATING and self.eliminated is not False
    # The thrower's box on each frame near the release, from the roster track
    # that holds the labelled box; empty until `TruthSet.anchored` fills it.
    track_boxes: dict[int, Box] = field(default_factory=dict, compare=False)

    @property
    def released(self) -> bool:
        return self.kind != "fake"

    def box_on(self, frame: int) -> Box:
        """The thrower's box on a frame, or the labelled box where the track is unknown."""
        return self.track_boxes.get(frame, self.box)


@dataclass(frozen=True)
class Prediction:
    """One event the pipeline claims. Every field past the first two is a claim
    the stage may or may not make; None is "not answered", never "no"."""

    frame: int
    box: Box
    team: str | None = None
    released: bool | None = None
    kind: str | None = None
    outcome: str | None = None

    @classmethod
    def from_candidate(cls, c) -> Prediction:
        return cls(frame=c.frame, box=tuple(c.box), team=c.team)

    @classmethod
    def load_timeline(cls, path: str | Path) -> list[Prediction]:
        """Every event a timeline file claims, as the harness scores it."""
        data = json.loads(Path(path).read_text())
        return [cls(frame=int(e["frame"]), box=tuple(e["box"]), team=e.get("team"),
                    released=e.get("released"), kind=e.get("kind"), outcome=e.get("outcome"))
                for e in data["events"]]


@dataclass
class TruthSet:
    video: str
    fps: float
    events: list[TruthEvent]
    live_play: list[tuple[int, int | None]]

    @classmethod
    def load(cls, path: str | Path) -> TruthSet:
        data = json.loads(Path(path).read_text())
        if data.get("schema_version") != LABEL_SCHEMA_VERSION:
            raise ValueError(f"{path} is label schema {data.get('schema_version')}, "
                             f"expected {LABEL_SCHEMA_VERSION}")
        events = []
        for e in data["events"]:
            if e.get("status") != "closed" or e.get("release_frame") is None:
                continue
            events.append(TruthEvent(
                id=e["id"], kind=e["kind"], release_frame=int(e["release_frame"]),
                end_frame=e.get("end_frame"), box=_box(e["thrower"]["box"]),
                box_frame=int(e["thrower"]["frame"]), team=e.get("team"),
                outcome=e.get("outcome"), uncertain=bool(e.get("uncertain")),
                source=e.get("source", "manual"), proposed_frame=e.get("proposed_frame"),
                ball_in_hand=e.get("ball_in_hand"), eliminated=e.get("eliminated")))
        events.sort(key=lambda t: t.release_frame)
        live = [(int(iv["start_frame"]), iv.get("end_frame")) for iv in data.get("live_play", [])]
        return cls(video=data["video"], fps=float(data["fps"]), events=events, live_play=live)

    @classmethod
    def for_video(cls, video: str | Path) -> TruthSet:
        return cls.load(LABELS_ROOT / f"{Path(video).stem}.json")

    def set_intervals(self) -> list[tuple[int, int | None]]:
        """Live play with an unlabelled end closed at the last hit's outcome.

        A set ends on its last elimination. Where the annotator did not write
        an end, the last hit inside the interval settles it; an interval with
        no hit at all stays open-ended.
        """
        out = []
        for start, end in self.live_play:
            if end is None:
                hits = [t.end_frame or t.release_frame for t in self.events
                        if t.wins_elimination and t.release_frame >= start]
                end = max(hits) if hits else None
            out.append((start, end))
        return out

    def in_play(self, frame: int) -> bool:
        return any(s <= frame and (e is None or frame <= e) for s, e in self.set_intervals())

    def anchored(self, roster, pose, window: int = TOLERANCE_FRAMES) -> TruthSet:
        """The same truth with each thrower's box known on every frame near the release.

        The annotator's box is snapped on one frame, and a throwing player's
        box changes shape fast - the same track scores IoU 0.31 with itself
        five frames apart on the evaluation clip, as the arm comes through.
        Matching a prediction on frame f against the labelled box on another
        frame is therefore not the tool's test. The roster's track is the
        bridge: the track holding the labelled box on its frame gives the
        same player's box on every frame within the tolerance, so a match is
        always same-frame, same-player. An event whose box is on no track
        keeps the one box it has.
        """
        on_frame: dict[int, list[tuple[int, int]]] = {}
        for track in roster.tracks.values():
            for f, i in track.detections:
                on_frame.setdefault(f, []).append((track.id, i))
        events = []
        for t in self.events:
            best = max(((iou(t.box, tuple(pose.frame(t.box_frame)[i]["box"])), tid)
                        for tid, i in on_frame.get(t.box_frame, [])), default=(0.0, None))
            boxes: dict[int, Box] = {}
            if best[0] >= MIN_IOU:
                lo, hi = t.release_frame - window, t.release_frame + window
                for f, i in roster.track(best[1]).detections:
                    if lo <= f <= hi:
                        boxes[f] = tuple(float(v) for v in pose.frame(f)[i]["box"])
            events.append(TruthEvent(
                id=t.id, kind=t.kind, release_frame=t.release_frame, end_frame=t.end_frame,
                box=t.box, box_frame=t.box_frame, team=t.team, outcome=t.outcome,
                uncertain=t.uncertain, source=t.source, proposed_frame=t.proposed_frame,
                ball_in_hand=t.ball_in_hand, eliminated=t.eliminated, track_boxes=boxes))
        return TruthSet(video=self.video, fps=self.fps, events=events, live_play=self.live_play)


@dataclass
class Match:
    truth: TruthEvent
    prediction: Prediction

    @property
    def delta(self) -> int:
        return self.prediction.frame - self.truth.release_frame


@dataclass
class Matching:
    matches: list[Match]
    missed: list[TruthEvent]
    spurious: list[Prediction]


def match(truth: list[TruthEvent], predictions: list[Prediction],
          tolerance: int = TOLERANCE_FRAMES, min_iou: float = MIN_IOU) -> Matching:
    """One-to-one, nearest frame first among pairs that overlap.

    Greedy on frame distance: the pair closest in time is taken first, so a
    proposal a frame off a release is not stolen by a second event on the
    same player a few frames later.
    """
    pairs = []
    for ti, t in enumerate(truth):
        for pi, p in enumerate(predictions):
            d = abs(p.frame - t.release_frame)
            if d <= tolerance and iou(p.box, t.box_on(p.frame)) >= min_iou:
                pairs.append((d, ti, pi))
    pairs.sort()
    used_t: set[int] = set()
    used_p: set[int] = set()
    matches = []
    for _, ti, pi in pairs:
        if ti in used_t or pi in used_p:
            continue
        used_t.add(ti)
        used_p.add(pi)
        matches.append(Match(truth[ti], predictions[pi]))
    matches.sort(key=lambda m: m.truth.release_frame)
    return Matching(
        matches=matches,
        missed=[t for i, t in enumerate(truth) if i not in used_t],
        spurious=[p for i, p in enumerate(predictions) if i not in used_p])


def prf(tp: int, fp: int, fn: int) -> dict:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": p, "recall": r, "f1": f}


def confusion(pairs: list[tuple[str, str]], labels: tuple[str, ...]) -> dict:
    """Rows are truth, columns predicted; accuracy over the pairs given."""
    counts = Counter(pairs)
    table = {t: {p: counts.get((t, p), 0) for p in labels} for t in labels}
    n = sum(counts.values())
    right = sum(counts.get((k, k), 0) for k in labels)
    return {"n": n, "accuracy": right / n if n else 0.0, "table": table}


def detection_by_kind(truth: list[TruthEvent], predictions: list[Prediction],
                      m: Matching) -> dict[str, dict]:
    """P/R/F1 of each kind as a detector of that kind.

    A prediction is a positive for its claimed kind; it is a true positive
    only where it matched a truth event of the same kind. A throw claimed on
    a fake is a false positive for throws and a false negative for fakes.
    """
    out = {}
    for kind in KINDS:
        tp = sum(1 for mm in m.matches if mm.truth.kind == kind and mm.prediction.kind == kind)
        claimed = sum(1 for p in predictions if p.kind == kind)
        actual = sum(1 for t in truth if t.kind == kind)
        out[kind] = prf(tp, claimed - tp, actual - tp)
    return out


def efficiency(events: list[TruthEvent | Prediction]) -> dict[str, dict]:
    """Team throw efficiency: eliminations over throws, per team.

    Passes and fakes are outside the denominator; an unresolved outcome is a
    throw with no elimination, which is the conservative reading.
    """
    out: dict[str, dict] = {}
    for e in events:
        if e.kind != "throw" or e.team is None:
            continue
        row = out.setdefault(e.team, {"throws": 0, "eliminations": 0})
        row["throws"] += 1
        won = e.wins_elimination if isinstance(e, TruthEvent) else e.outcome in ELIMINATING
        row["eliminations"] += int(won)
    for row in out.values():
        row["efficiency"] = row["eliminations"] / row["throws"] if row["throws"] else 0.0
    return out


@dataclass
class Report:
    candidate: dict
    boundary: dict
    team: dict | None
    release: dict | None
    kind: dict | None
    outcome: dict | None
    # Per kind, the prediction of that kind as the positive class: what the
    # cascade is for is finding throws, and kind accuracy on matched events
    # hides the throws claimed on a fake or a proposal that matched nothing.
    detection: dict | None
    efficiency: dict
    matching: Matching = field(repr=False)


def evaluate(truth: TruthSet, predictions: list[Prediction],
             tolerance: int = TOLERANCE_FRAMES, min_iou: float = MIN_IOU) -> Report:
    m = match(truth.events, predictions, tolerance, min_iou)

    # A spurious prediction after the set has ended is a different failure
    # from one during play: the first is set end's to fix, the second this
    # stage's. Both count against precision; they are reported apart.
    dead = [p for p in m.spurious if not truth.in_play(p.frame)]
    candidate = prf(len(m.matches), len(m.spurious), len(m.missed))
    candidate["fp_after_set_end"] = len(dead)
    candidate["fp_in_play"] = len(m.spurious) - len(dead)
    candidate["precision_in_play"] = (
        len(m.matches) / (len(m.matches) + candidate["fp_in_play"])
        if m.matches or candidate["fp_in_play"] else 0.0)
    no_ball = [t for t in truth.events if t.ball_in_hand is False]
    candidate["no_ball_fakes"] = len(no_ball)
    candidate["no_ball_fakes_found"] = sum(
        1 for mm in m.matches if mm.truth.ball_in_hand is False)

    deltas = [mm.delta for mm in m.matches]
    boundary = {
        "n": len(deltas),
        "release_mae": sum(abs(d) for d in deltas) / len(deltas) if deltas else 0.0,
        "release_bias": sum(deltas) / len(deltas) if deltas else 0.0,
        "within_2": sum(abs(d) <= 2 for d in deltas),
    }

    team_pairs = [(mm.truth.team, mm.prediction.team) for mm in m.matches
                  if mm.prediction.team is not None and mm.truth.team is not None]
    team = confusion(team_pairs, ("near", "far")) if team_pairs else None

    rel_pairs = [("released" if mm.truth.released else "fake",
                  "released" if mm.prediction.released else "fake")
                 for mm in m.matches if mm.prediction.released is not None]
    release = confusion(rel_pairs, ("fake", "released")) if rel_pairs else None

    kind_pairs = [(mm.truth.kind, mm.prediction.kind) for mm in m.matches
                  if mm.prediction.kind is not None]
    kind = confusion(kind_pairs, KINDS) if kind_pairs else None

    out_pairs = [(mm.truth.outcome, mm.prediction.outcome) for mm in m.matches
                 if mm.truth.kind == "throw" and mm.truth.outcome in OUTCOMES
                 and mm.prediction.outcome is not None]
    outcome = confusion(out_pairs, OUTCOMES) if out_pairs else None
    detection = detection_by_kind(truth.events, predictions, m) if kind_pairs else None

    eff = {"truth": efficiency(truth.events)}
    if any(p.outcome is not None for p in predictions):
        eff["predicted"] = efficiency([p for p in predictions if truth.in_play(p.frame)])

    return Report(candidate=candidate, boundary=boundary, team=team, release=release,
                  kind=kind, outcome=outcome, detection=detection, efficiency=eff, matching=m)


def _pct(x: float) -> str:
    return f"{100 * x:.0f}%"


def _confusion_lines(name: str, c: dict, labels: tuple[str, ...]) -> list[str]:
    lines = [f"{name}: {_pct(c['accuracy'])} on {c['n']} matched",
             "  truth \\ predicted  " + "  ".join(f"{lab:>8}" for lab in labels)]
    for t in labels:
        if not any(c["table"][t].values()):
            continue
        lines.append(f"  {t:<18} " + "  ".join(f"{c['table'][t][p]:>8}" for p in labels))
    return lines


def format_report(r: Report) -> str:
    c = r.candidate
    lines = [
        f"candidate: P {_pct(c['precision'])} R {_pct(c['recall'])} F1 {_pct(c['f1'])} "
        f"(tp {c['tp']}, fp {c['fp']} of which {c['fp_after_set_end']} after set end, "
        f"fn {c['fn']}); in play P {_pct(c['precision_in_play'])}"
        + (f"; fakes with no ball {c['no_ball_fakes_found']}/{c['no_ball_fakes']} found"
           if c["no_ball_fakes"] else ""),
        f"release frame: MAE {r.boundary['release_mae']:.1f}, bias "
        f"{r.boundary['release_bias']:+.1f}, {r.boundary['within_2']}/{r.boundary['n']} "
        f"within 2 frames",
    ]
    if r.team:
        lines.append(f"team: {_pct(r.team['accuracy'])} on {r.team['n']} matched")
    for name, conf, labels in (("release", r.release, ("fake", "released")),
                               ("kind", r.kind, KINDS), ("outcome", r.outcome, OUTCOMES)):
        if conf:
            lines.extend(_confusion_lines(name, conf, labels))
        else:
            lines.append(f"{name}: not claimed")
    if r.detection:
        lines.append("detection by kind: " + "; ".join(
            f"{k} P {_pct(d['precision'])} R {_pct(d['recall'])} F1 {_pct(d['f1'])}"
            for k, d in r.detection.items()))
    for who, rows in r.efficiency.items():
        lines.append(f"efficiency ({who}): " + ", ".join(
            f"{team} {row['eliminations']}/{row['throws']} = {_pct(row['efficiency'])}"
            for team, row in sorted(rows.items())))
    if r.matching.missed:
        lines.append("missed: " + ", ".join(
            f"{t.kind}@{t.release_frame}" for t in r.matching.missed))
    return "\n".join(lines)


def report_json(r: Report) -> dict:
    return {
        "candidate": r.candidate, "boundary": r.boundary, "team": r.team,
        "release": r.release, "kind": r.kind, "outcome": r.outcome,
        "detection": r.detection, "efficiency": r.efficiency,
        "missed": [{"kind": t.kind, "release_frame": t.release_frame,
                    "ball_in_hand": t.ball_in_hand} for t in r.matching.missed],
        "spurious": [{"frame": p.frame, "kind": p.kind} for p in r.matching.spurious],
    }
