#!/usr/bin/env python
"""Find where each set begins in a clip, and write the live-play interval starts.

A set start is the one moment in a match with an unmistakable signature: balls
laid out on the centre line, a whistle heard while they are, and both teams
breaking for them. Detecting it removes the only per-set label a human would
otherwise have to place by hand, and it anchors the interval the throw metric is
computed over.

Reads the court fit and the pose run for the clip; both are keyed to the clip
hash, so a re-encode is refused rather than silently mis-timed.

Usage::

    .venv/bin/python scripts/detect_set_start.py data/footage/clip.mp4
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from court import Court  # noqa: E402
from src.hashing import clip_sha256  # noqa: E402
from pose import PoseRun  # noqa: E402
from setstart import (  # noqa: E402
    ARMED_MIN_BALLS, ARMED_MIN_SPREAD_M, SCHEMA_VERSION, SETS_ROOT,
    SPRINT_MIN_PLAYERS, WHISTLE_MIN_PROMINENCE_DB, SetTimeline, detect_set_starts,
)


def timecode(seconds: float) -> str:
    return f"{int(seconds // 60)}:{seconds % 60:05.2f}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    parser.add_argument("--run-id", default=None,
                        help="pose run to use when the clip has more than one")
    parser.add_argument("--offset", type=float, default=0.0,
                        help="seconds from the start of the source match to the "
                             "start of this clip, for reporting match timecodes")
    args = parser.parse_args()

    if not args.video.exists():
        print(f"no such clip: {args.video}", file=sys.stderr)
        return 1

    court = Court.for_video(args.video)
    pose = PoseRun.for_video(args.video, args.run_id)
    digest = clip_sha256(args.video)
    if court.clip_sha256 != digest:
        print(f"court fit in data/court/ was made on a different cut of {args.video.name}",
              file=sys.stderr)
        return 1
    pose.check_clip(digest)

    results = detect_set_starts(args.video, court, pose)
    fps = court.fps

    payload = {
        "schema_version": SCHEMA_VERSION,
        "created": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "video": args.video.name,
        "clip_sha256": digest,
        "pose_run": pose.manifest["run_id"],
        "fps": fps,
        "frame_count": pose.frame_count,
        "clip_offset_s": args.offset,
        "thresholds": {
            "armed_min_balls": ARMED_MIN_BALLS,
            "armed_min_spread_m": ARMED_MIN_SPREAD_M,
            "whistle_min_prominence_db": WHISTLE_MIN_PROMINENCE_DB,
            "sprint_min_players": SPRINT_MIN_PLAYERS,
        },
        "sets": [
            {
                "status": r.status,
                "start_frame": r.start_frame,
                "start_s": None if r.start_frame is None else round(r.start_frame / fps, 2),
                "whistle_prominence_db": None if r.whistle_prominence_db is None
                else round(r.whistle_prominence_db, 1),
                "sprint_frame": r.sprint_frame,
                "first_ball_moves_frame": r.first_ball_moves_frame,
                "armed": {
                    "start_frame": r.armed.start_frame,
                    "end_frame": r.armed.end_frame,
                    "max_balls": r.armed.max_balls,
                    "max_spread_m": round(r.armed.max_spread_m, 2),
                },
                "notes": r.notes,
            }
            for r in results
        ],
    }
    SETS_ROOT.mkdir(parents=True, exist_ok=True)
    out = SETS_ROOT / f"{args.video.stem}.json"
    out.write_text(json.dumps(payload, indent=2) + "\n")
    # Read it straight back through the reader every stage downstream will use,
    # so a timeline that cannot be consumed fails here rather than three stages
    # later with the run already spent.
    timeline = SetTimeline.load(out)
    timeline.check_clip(digest)

    print(f"{len(results)} armed window(s) in {args.video.name}")
    for i, r in enumerate(results, 1):
        armed_from = r.armed.start_frame / fps
        armed_to = r.armed.end_frame / fps
        print(f"  set {i}: {r.status}")
        print(f"    balls laid out   {armed_from:7.2f}s -> {armed_to:7.2f}s  "
              f"({r.armed.max_balls} balls, {r.armed.max_spread_m:.1f} m spread)")
        if r.start_frame is not None:
            start_s = r.start_frame / fps
            print(f"    whistle          {start_s:7.2f}s  frame {r.start_frame}  "
                  f"({r.whistle_prominence_db:.0f} dB over crowd)")
            if args.offset:
                print(f"    match timecode   {timecode(args.offset + start_s)}")
        if r.sprint_frame is not None:
            lag = (r.sprint_frame - (r.start_frame or r.sprint_frame)) / fps
            print(f"    break for balls  {r.sprint_frame / fps:7.2f}s  (+{lag:.2f}s)")
        if r.first_ball_moves_frame is not None:
            print(f"    layout breaks    {r.first_ball_moves_frame / fps:7.2f}s")
        for note in r.notes:
            print(f"    note             {note}")
    print("  live play (set end is an upper bound until outcomes are resolved)")
    for i, interval in enumerate(timeline.live_play_intervals(), 1):
        print(f"    set {i}: frames {interval.start_frame}-{interval.end_frame}  "
              f"{interval.start_frame / fps:7.2f}s -> {interval.end_frame / fps:7.2f}s")
    print(f"  wrote              {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
