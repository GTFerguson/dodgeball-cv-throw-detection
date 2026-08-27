#!/usr/bin/env python
"""Find where each set ends, and write it into the set timeline.

A set ends on the hit that puts out the last player of a side. The floor
shows it without the hit: one side down to a single player for a stretch,
then the court filling with more bodies than a set allows. Where the event
timeline has a resolved hit on that side inside the stand, the end is the
hit; otherwise it is the last frame of the stand, and the hit window is
written so the outcome stage can trace the missing hit back.

Reads ``data/sets/<stem>.json`` (the starts), ``data/roster/<stem>.json``
(who is in play) and, if present, ``data/timeline/<stem>.json`` (the hits).
Writes the end back into the sets file.

Usage::

    .venv/bin/python scripts/detect_set_end.py wdbf2014_final_h2_set2
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from setstart import SETS_ROOT, SetTimeline  # noqa: E402
from src.roster import Roster  # noqa: E402
from src.setend import (  # noqa: E402
    FLOOD_MIN_RISE,
    FLOOD_MIN_S,
    FLOOD_WINDOW_S,
    LAST_STAND_MIN_S,
    Hit,
    SetEnd,
    detect_set_end,
)

TIMELINE_ROOT = REPO_ROOT / "data" / "timeline"


def hits_from_timeline(stem: str, clip_sha256: str) -> list[Hit]:
    """Resolved hits, as eliminations of the side thrown at, ending where the ball did."""
    path = TIMELINE_ROOT / f"{stem}.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    if data.get("clip_sha256") != clip_sha256:
        raise ValueError(f"{path} was computed on a different clip")
    hits = []
    for e in data["events"]:
        if e.get("kind") == "throw" and e.get("outcome") == "hit" and e.get("team") in ("near", "far"):
            side = "far" if e["team"] == "near" else "near"
            hits.append(Hit(frame=e["frame"] + (e["evidence"].get("end_offset") or 0), side=side))
    return hits


def as_json(end: SetEnd, fps: float) -> dict:
    return {
        "frame": end.frame,
        "end_s": round(end.frame / fps, 2),
        "source": end.source,
        "side": end.stand.side,
        "last_stand": [end.stand.start_frame, end.stand.end_frame],
        "flood_frame": end.flood_frame,
        "hit_frame": end.hit.frame if end.hit else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("video", help="clip stem or path under data/footage/")
    args = ap.parse_args()
    stem = Path(args.video).stem

    path = SETS_ROOT / f"{stem}.json"
    timeline = SetTimeline.load(path)
    roster = Roster.for_video(stem)
    roster.check_clip(timeline.clip_sha256)
    hits = hits_from_timeline(stem, timeline.clip_sha256)

    data = json.loads(path.read_text())
    # Search each set up to its layout bound, not up to any end already written.
    for s in data["sets"]:
        s.pop("end", None)
    fresh = SetTimeline(**{**timeline.__dict__, "sets": data["sets"]})
    found = 0
    for i, interval in enumerate(fresh.live_play_intervals(), 1):
        end = detect_set_end(roster, interval.start_frame, interval.end_frame, timeline.fps, hits)
        if end is None:
            print(f"  set {i}: no end found before frame {interval.end_frame} ({interval.end_source})")
            continue
        found += 1
        for s in data["sets"]:
            if s["status"] == "confirmed" and s["start_frame"] == interval.start_frame:
                s["end"] = as_json(end, timeline.fps)
        a, b = end.hit_window
        print(f"  set {i}: ends at frame {end.frame} ({end.frame / timeline.fps:.2f}s) by {end.source} - "
              f"{end.stand.side} down to one from {end.stand.start_frame}, floor fills at "
              f"{end.flood_frame}; a missed hit lies in {a}-{b}")
    data["thresholds"].update({
        "last_stand_min_s": LAST_STAND_MIN_S, "flood_min_rise": FLOOD_MIN_RISE,
        "flood_min_s": FLOOD_MIN_S, "flood_window_s": FLOOD_WINDOW_S,
    })
    path.write_text(json.dumps(data, indent=2) + "\n")
    SetTimeline.load(path).check_clip(timeline.clip_sha256)
    print(f"{found} set end(s); wrote {path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
