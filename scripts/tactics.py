#!/usr/bin/env python3
"""Split team throw efficiency by set-up: solo v coordinated, and fakes before.

Reads the clip's timeline and set intervals, or with ``--truth`` the labels,
and prints one table per source. See ``src/tactics.py`` for the definitions.

Usage::

    .venv/bin/python scripts/tactics.py wdbf2014_final_h2_set2
    .venv/bin/python scripts/tactics.py wdbf2014_final_h2_set2 --truth
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from src.evaluate import ELIMINATING, TruthSet  # noqa: E402
from src.release import TIMELINE_ROOT  # noqa: E402
from src.tactics import Event, format_table, split  # noqa: E402
from setstart import SetTimeline  # noqa: E402


def from_timeline(stem: str) -> tuple[list[Event], list[tuple[int, int | None]], float, str]:
    data = json.loads((TIMELINE_ROOT / f"{stem}.json").read_text())
    events = [Event(frame=e["frame"], team=e["team"], kind=e["kind"],
                    won=e["kind"] == "throw" and e.get("outcome") in ELIMINATING)
              for e in data["events"] if e.get("team") in ("near", "far")]
    sets = [(iv.start_frame, iv.end_frame)
            for iv in SetTimeline.for_video(stem).live_play_intervals()]
    return events, sets, float(data["fps"]), f"predicted ({stem})"


def from_truth(stem: str) -> tuple[list[Event], list[tuple[int, int | None]], float, str]:
    truth = TruthSet.for_video(stem)
    events = [Event(frame=t.release_frame, team=t.team, kind=t.kind, won=t.wins_elimination)
              for t in truth.events if t.team in ("near", "far")]
    return events, truth.set_intervals(), truth.fps, f"truth ({stem})"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("video", help="clip stem or path under data/footage/")
    ap.add_argument("--truth", action="store_true", help="split the labels instead")
    ap.add_argument("--markdown", type=Path, help="write the table here as well")
    args = ap.parse_args()
    stem = Path(args.video).stem
    events, sets, fps, title = (from_truth if args.truth else from_timeline)(stem)
    table = format_table(split(events, sets, fps), title)
    print(table)
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(table + "\n")
        print(f"wrote {args.markdown}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
