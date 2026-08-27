#!/usr/bin/env python3
"""Propose throw candidates for a clip, for the labelling tool to show.

Reads the pose run, the court fit, the set timeline and the roster, and writes
``data/candidates/<stem>.json`` for ``src.candidates.CandidateSet``. See
``docs/architecture/throw-candidates.md``.

Usage::

    .venv/bin/python scripts/detect_candidates.py wdbf2014_final_h2_set2
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
# setstart imports its siblings bare, the rest of src by package; serve both.
sys.path.insert(0, str(REPO_ROOT / "src"))

from src.candidates import (MIN_SCORE, MIN_SEPARATION_S,  # noqa: E402
                            WINDUP_LOOKBACK_S, CandidateSet, detect)
from src.court import Court  # noqa: E402
from src.pose import PoseRun  # noqa: E402
from src.roster import Roster  # noqa: E402
from setstart import SetTimeline  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("video", help="clip stem or path under data/footage/")
    ap.add_argument("--min-score", type=float, default=MIN_SCORE)
    args = ap.parse_args()
    stem = Path(args.video).stem

    court = Court.for_video(stem)
    pose = PoseRun.for_video(stem)
    clip = pose.manifest["clip_sha256"]
    timeline = SetTimeline.for_video(stem)
    timeline.check_clip(clip)
    roster = Roster.for_video(stem)
    roster.check_clip(clip)

    found = detect(roster, pose, court, timeline, args.min_score)
    result = CandidateSet(
        video=f"{stem}.mp4", clip_sha256=clip, pose_run=pose.dir.name, fps=pose.fps,
        thresholds={
            "min_score": args.min_score,
            "min_separation_s": MIN_SEPARATION_S,
            "windup_lookback_s": WINDUP_LOOKBACK_S,
        },
        candidates=found)
    out = result.write(REPO_ROOT / "data" / "candidates" / f"{stem}.json")
    back = CandidateSet.load(out)

    live = sum(iv.end_frame - iv.start_frame + 1 for iv in timeline.live_play_intervals())
    minutes = live / pose.fps / 60
    by_team = Counter(c.team for c in back.candidates)
    print(f"{len(back.candidates)} candidates over {minutes:.2f} min of live play "
          f"= {len(back.candidates) / minutes:.1f}/min; "
          + ", ".join(f"{t}: {n}" for t, n in sorted(by_team.items(), key=str)))
    tracks = Counter(c.track_id for c in back.candidates)
    print(f"from {len(tracks)} tracks; busiest " + ", ".join(
        f"{roster.track(t).participant_id} x{n}" for t, n in tracks.most_common(5)))
    print(f"wrote {out.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
