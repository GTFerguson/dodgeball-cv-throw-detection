#!/usr/bin/env python3
"""Turn the throw proposals into an event timeline: event or not, released or not.

Reads the footage once around every proposal for the ball at the wrists,
then applies the release gate. Writes ``data/timeline/<stem>.json``; score it
with ``scripts/evaluate.py``. See ``docs/architecture/release-gate.md``.

Usage::

    .venv/bin/python scripts/detect_events.py wdbf2014_final_h2_set2
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from setstart import SetTimeline  # noqa: E402
from src.ball import trace_candidates  # noqa: E402
from src.candidates import CandidateSet  # noqa: E402
from src.court import Court  # noqa: E402
from src.outcome import Resolution, Thrown, blocks, count_steps, resolve  # noqa: E402
from src.pose import PoseRun  # noqa: E402
from src.rebound import Sam2Tracker, follow, read_frames, window_for  # noqa: E402
from src.rebound import thresholds as rebound_thresholds  # noqa: E402
from src.release import (  # noqa: E402
    CONTACT_BOX_MARGIN,
    TIMELINE_ROOT,
    Timeline,
    decide,
    thresholds,
)
from src.roster import Roster  # noqa: E402
from src.setend import LastStand, SetEnd, trace_back  # noqa: E402


def set_end_of(sets: SetTimeline, interval) -> SetEnd | None:
    """The end scripts/detect_set_end.py wrote for a set, as the tracer wants it."""
    end = sets.detected_end(interval)
    if end is None:
        return None
    a, b = end["last_stand"]
    return SetEnd(frame=end["frame"], source=end["source"], flood_frame=end["flood_frame"],
                  stand=LastStand(side=end["side"], start_frame=a, end_frame=b, total=0))


def follow_rebounds(video: Path, decisions: list, players_at, court: Court, fps: float,
                    skip: bool) -> list:
    """Follow every throw's ball to the player it reached and through; see src/rebound.py."""
    if skip:
        return decisions
    jobs = []
    for i, d in enumerate(decisions):
        if d.kind != "throw" or d.departure.seed_offset is None or len(d.departure.path) < 2:
            continue
        chain = [(d.frame + d.departure.seed_offset + k, p) for k, p in enumerate(d.departure.path)]
        jobs.append((i, chain))
    if not jobs:
        return decisions
    wanted = set()
    for _, chain in jobs:
        first, last = window_for(chain, fps)
        wanted.update(range(first, last + 1))
    frames_at = read_frames(video, wanted)
    tracker = Sam2Tracker()
    for i, chain in jobs:
        d = decisions[i]
        decisions[i] = replace(d, rebound=follow(chain, d.track_id, players_at, CONTACT_BOX_MARGIN,
                                                 court.scale_at, frames_at, tracker, fps))
    return decisions


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("video", help="clip stem or path under data/footage/")
    ap.add_argument("--no-rebound", action="store_true",
                    help="skip following the ball through its contact (outcomes by recency alone)")
    args = ap.parse_args()
    stem = Path(args.video).stem
    video = REPO_ROOT / "data" / "footage" / f"{stem}.mp4"

    court = Court.for_video(stem)
    pose = PoseRun.for_video(stem)
    clip = pose.manifest["clip_sha256"]
    sets = SetTimeline.for_video(stem)
    sets.check_clip(clip)
    roster = Roster.for_video(stem)
    roster.check_clip(clip)
    candidates = CandidateSet.for_video(stem)
    candidates.check_clip(clip)

    traces = trace_candidates(video, candidates.candidates, roster, pose, court)

    def players_at(frame: int):
        return [(p.track.team, p.track.id, p.participant.id,
                 tuple(float(v) for v in pose.frame(frame)[p.detection_index]["box"]))
                for p in roster.at(frame, role="player")]

    decisions = []
    for trace in traces:
        interval = sets.interval_for(trace.candidate.frame)
        decisions.append(decide(trace, interval.start_frame if interval else None, pose.fps,
                                players_at))
    decisions = follow_rebounds(video, decisions, players_at, court, pose.fps, args.no_rebound)
    # Outcomes from the game state: a side's in-play count over live play,
    # its persistent steps, each attributed to the last throw at that side.
    unexplained = []
    for interval in sets.live_play_intervals():
        frames = range(interval.start_frame, interval.end_frame + 1)
        counts = {team: [] for team in ("near", "far")}
        for f in frames:
            on = roster.on_court(f)
            for team in counts:
                counts[team].append(len(on[team]))
        steps = count_steps(counts, interval.start_frame, pose.fps)
        throws = [Thrown(i, d.frame, d.team, d.rebound.deflected if d.rebound else None)
                  for i, d in enumerate(decisions)
                  if d.kind == "throw" and d.team in ("near", "far") and interval.contains(d.frame)]
        resolved, orphans = resolve(throws, steps, pose.fps)
        # The final elimination never steps the count - the last player is still
        # on the paint while the floor fills - so the set end names the throw.
        end = set_end_of(sets, interval)
        if end is not None:
            free = [(t.id, t.frame, t.team) for t in throws if t.id not in resolved]
            last = trace_back(free, end)
            if last is not None:
                resolved[last] = Resolution(last, "hit", end.frame)
        # A ball seen to turn that nothing claimed: blocked, the ball stayed live.
        resolved.update(blocks(throws, resolved))
        for i, d in enumerate(decisions):
            if d.kind == "throw" and interval.contains(d.frame):
                r = resolved.get(i)
                decisions[i] = replace(d, outcome=r.outcome if r else "miss",
                                       outcome_step_frame=r.step_frame if r else None,
                                       outcome_return_frame=r.return_frame if r else None)
        unexplained += [{"frame": s.frame, "team": s.team, "before": s.before, "after": s.after}
                        for s in orphans]
    timeline = Timeline(video=f"{stem}.mp4", clip_sha256=clip, pose_run=pose.dir.name,
                        fps=pose.fps, thresholds={**thresholds(), **rebound_thresholds()},
                        decisions=decisions,
                        unexplained_steps=unexplained)
    out = timeline.write(TIMELINE_ROOT / f"{stem}.json")

    dropped = Counter(d.dropped for d in decisions if not d.is_event)
    kinds = Counter(d.kind for d in timeline.events)
    outcomes = Counter(d.outcome for d in timeline.events if d.kind == "throw")
    print(f"{len(candidates.candidates)} proposals -> {len(timeline.events)} events "
          f"({', '.join(f'{k}: {n}' for k, n in sorted(kinds.items()))}); dropped "
          + ", ".join(f"{n} {why}" for why, n in dropped.most_common()))
    print("throw outcomes: " + ", ".join(f"{o}: {n}" for o, n in sorted(outcomes.items(), key=str))
          + f"; {len(unexplained)} count steps no throw explains")
    print(f"wrote {out.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
