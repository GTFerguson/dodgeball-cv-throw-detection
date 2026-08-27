#!/usr/bin/env python3
"""An error budget for team throw efficiency: what the real answer could be.

Efficiency is eliminations over throws, per team. The pipeline's number can
be wrong in the denominator (a throw missed, a fake or pass claimed as a
throw, a throw put on the wrong team) and in the numerator (a hit missed
or invented by the game-state fold). Both are read off the same matching
the evaluation uses, per team, so each error has a named source.

Two uncertainties are stated apart:

* **Model** - a paired bootstrap over the matching's units (a matched
  pair, a spurious prediction, a missed truth event), resampled with
  replacement. Each draw yields a truth efficiency and a predicted one from
  the same units, so the spread of their difference is the pipeline's
  error under resampling of this clip's events.
* **Labels** - the range the truth efficiency spans if every event the
  annotator marked ``uncertain`` went the other way, plus the sampling
  interval of the truth itself: with fifteen throws a team, the clip's
  own efficiency is a coarse estimate of the team's.

Usage::

    .venv/bin/python scripts/error_budget.py wdbf2014_final_h2_set2
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.evaluate import (  # noqa: E402
    ELIMINATING,
    MIN_IOU,
    TOLERANCE_FRAMES,
    Prediction,
    TruthEvent,
    TruthSet,
    match,
)
from src.pose import PoseRun  # noqa: E402
from src.release import TIMELINE_ROOT  # noqa: E402
from src.roster import Roster  # noqa: E402

TEAMS = ("near", "far")
DRAWS = 4000
SEED = 20260827


def truth_wins(t: TruthEvent | None) -> bool:
    return t is not None and t.kind == "throw" and t.wins_elimination


def pred_wins(p: Prediction | None) -> bool:
    return p is not None and p.kind == "throw" and p.outcome in ELIMINATING


def ratio(num: int, den: int) -> float | None:
    return num / den if den else None


def efficiency_of(units: list[tuple[TruthEvent | None, Prediction | None]], team: str
                  ) -> tuple[float | None, float | None]:
    t_throws = sum(1 for t, _ in units if t and t.kind == "throw" and t.team == team)
    t_hits = sum(1 for t, _ in units if t and t.team == team and truth_wins(t))
    p_throws = sum(1 for _, p in units if p and p.kind == "throw" and p.team == team)
    p_hits = sum(1 for _, p in units if p and p.team == team and pred_wins(p))
    return ratio(t_hits, t_throws), ratio(p_hits, p_throws)


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return (max(0.0, c - h), min(1.0, c + h))


def pct(x: float | None) -> str:
    return "—" if x is None else f"{100 * x:.0f}%"


def budget(truth: TruthSet, predictions: list[Prediction], in_play) -> tuple[list[str], dict]:
    live = [p for p in predictions if in_play(p.frame)]
    m = match(truth.events, live, TOLERANCE_FRAMES, MIN_IOU)
    units = [(mm.truth, mm.prediction) for mm in m.matches]
    units += [(None, p) for p in m.spurious]
    units += [(t, None) for t in m.missed]

    lines = []
    out = {}
    for team in TEAMS:
        t_throws = [t for t in truth.events if t.kind == "throw" and t.team == team]
        p_throws = [p for p in live if p.kind == "throw" and p.team == team]
        pairs = [(t, p) for t, p in units if (t and t.team == team) or (p and p.team == team)]

        # Denominator: where the predicted throws came from.
        tp = sum(1 for t, p in pairs if t and p and t.kind == "throw" and p.kind == "throw"
                 and t.team == p.team == team)
        from_fake = sum(1 for t, p in pairs if t and p and p.kind == "throw" and p.team == team
                        and t.kind == "fake")
        from_pass = sum(1 for t, p in pairs if t and p and p.kind == "throw" and p.team == team
                        and t.kind == "pass")
        from_nothing = sum(1 for t, p in pairs if t is None and p.kind == "throw" and p.team == team)
        wrong_team = sum(1 for t, p in pairs if t and p and p.kind == "throw" and p.team == team
                         and t.team != team)
        missed = sum(1 for t, p in pairs if t and t.kind == "throw" and t.team == team
                     and (p is None or p.kind != "throw" or p.team != team))
        missed_as = {}
        for t, p in pairs:
            if t and t.kind == "throw" and t.team == team and not (
                    p and p.kind == "throw" and p.team == team):
                key = "no proposal" if p is None else f"called {p.kind}"
                missed_as[key] = missed_as.get(key, 0) + 1

        # Numerator: hits, on the throws both sides agree are throws.
        hit_tp = sum(1 for t, p in pairs if t and p and truth_wins(t) and pred_wins(p)
                     and t.team == p.team == team)
        hit_missed = sum(1 for t, p in pairs if t and t.team == team and truth_wins(t)
                         and not (p and pred_wins(p) and p.team == team))
        hit_invented = sum(1 for t, p in pairs if p and p.team == team and pred_wins(p)
                           and not (t and truth_wins(t) and t.team == team))

        t_hits = sum(1 for t in t_throws if t.wins_elimination)
        p_hits = sum(1 for p in p_throws if pred_wins(p))
        t_eff, p_eff = ratio(t_hits, len(t_throws)), ratio(p_hits, len(p_throws))

        # Labels: the truth if every uncertain event went the other way.
        unc_throw_hits = sum(1 for t in t_throws if t.uncertain and t.wins_elimination)
        unc_throw_misses = sum(1 for t in t_throws if t.uncertain and not t.wins_elimination)
        unc_not_throw = sum(1 for t in truth.events if t.uncertain and t.team == team
                            and t.kind != "throw")
        lo = ratio(t_hits - unc_throw_hits, len(t_throws) + unc_not_throw)
        hi = ratio(t_hits + unc_throw_misses, len(t_throws))
        w = wilson(t_hits, len(t_throws))

        out[team] = dict(
            truth=dict(throws=len(t_throws), hits=t_hits, efficiency=t_eff),
            predicted=dict(throws=len(p_throws), hits=p_hits, efficiency=p_eff),
            denominator=dict(true_throws=tp, from_fake=from_fake, from_pass=from_pass,
                             from_nothing=from_nothing, wrong_team=wrong_team,
                             missed=missed, missed_as=missed_as),
            numerator=dict(true_hits=hit_tp, missed=hit_missed, invented=hit_invented),
            labels=dict(uncertain_throws=unc_throw_hits + unc_throw_misses,
                        uncertain_other=unc_not_throw, range=[lo, hi], wilson95=list(w)),
        )
        lines += [
            f"{team}: truth {t_hits}/{len(t_throws)} = {pct(t_eff)}, predicted "
            f"{p_hits}/{len(p_throws)} = {pct(p_eff)}",
            f"  throws claimed: {tp} true, {from_fake} were fakes, {from_pass} were passes, "
            f"{from_nothing} matched no event, {wrong_team} on the other team; "
            f"{missed} true throws not claimed"
            + (f" ({', '.join(f'{n} {k}' for k, n in sorted(missed_as.items()))})" if missed_as else ""),
            f"  hits: {hit_tp} right, {hit_missed} missed, {hit_invented} invented",
            f"  labels: {unc_throw_hits + unc_throw_misses} uncertain throws, {unc_not_throw} "
            f"uncertain non-throws -> truth could be {pct(lo)}..{pct(hi)}; "
            f"sampling 95% {pct(w[0])}..{pct(w[1])} on {len(t_throws)} throws",
        ]

    # Model: paired bootstrap over the matching's units.
    rng = random.Random(SEED)
    diffs = {team: [] for team in TEAMS}
    preds = {team: [] for team in TEAMS}
    for _ in range(DRAWS):
        sample = [units[rng.randrange(len(units))] for _ in units]
        for team in TEAMS:
            t_eff, p_eff = efficiency_of(sample, team)
            if t_eff is not None and p_eff is not None:
                diffs[team].append(p_eff - t_eff)
                preds[team].append(p_eff)
    for team in TEAMS:
        d = sorted(diffs[team])
        p = sorted(preds[team])
        lo, hi = d[int(0.025 * len(d))], d[int(0.975 * len(d))]
        plo, phi = p[int(0.025 * len(p))], p[int(0.975 * len(p))]
        out[team]["model"] = dict(draws=len(d), error95=[lo, hi], predicted95=[plo, phi])
        lines.append(f"{team}: model error (predicted − truth) 95% {100 * lo:+.0f}..{100 * hi:+.0f} "
                     f"points; predicted efficiency 95% {pct(plo)}..{pct(phi)} "
                     f"({len(d)} paired draws)")
    return lines, out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("video", help="clip stem or path under data/footage/")
    ap.add_argument("--predictions", type=Path)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()
    stem = Path(args.video).stem
    truth = TruthSet.for_video(stem).anchored(Roster.for_video(stem), PoseRun.for_video(stem))
    predictions = Prediction.load_timeline(args.predictions or TIMELINE_ROOT / f"{stem}.json")
    lines, out = budget(truth, predictions, truth.in_play)
    print("\n".join(lines))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(out, indent=1))
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
