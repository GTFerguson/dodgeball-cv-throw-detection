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
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from src.ball import trace_candidates  # noqa: E402
from src.candidates import CandidateSet  # noqa: E402
from src.court import Court  # noqa: E402
from src.pose import PoseRun  # noqa: E402
from src.release import TIMELINE_ROOT, Timeline, decide, thresholds  # noqa: E402
from src.roster import Roster  # noqa: E402
from setstart import SetTimeline  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("video", help="clip stem or path under data/footage/")
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
    decisions = []
    for trace in traces:
        interval = sets.interval_for(trace.candidate.frame)
        decisions.append(decide(trace, interval.start_frame if interval else None, pose.fps))
    timeline = Timeline(video=f"{stem}.mp4", clip_sha256=clip, pose_run=pose.dir.name,
                        fps=pose.fps, thresholds=thresholds(), decisions=decisions)
    out = timeline.write(TIMELINE_ROOT / f"{stem}.json")

    dropped = Counter(d.dropped for d in decisions if not d.is_event)
    kinds = Counter(d.kind for d in timeline.events)
    print(f"{len(candidates.candidates)} proposals -> {len(timeline.events)} events "
          f"({', '.join(f'{k}: {n}' for k, n in sorted(kinds.items()))}); dropped "
          + ", ".join(f"{n} {why}" for why, n in dropped.most_common()))
    print(f"wrote {out.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
