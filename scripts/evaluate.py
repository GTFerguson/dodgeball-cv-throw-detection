#!/usr/bin/env python3
"""Score a predicted timeline against the truth set, level by level.

With no predictions file the clip's timeline in ``data/timeline/`` is scored;
``--candidates`` scores the proposals instead, as a timeline that claims only
"a throwing motion here" - the baseline row for every stage that follows. See ``src/evaluate.py`` for what is scored and how it matches.

Usage::

    .venv/bin/python scripts/evaluate.py wdbf2014_final_h2_set2
    .venv/bin/python scripts/evaluate.py wdbf2014_final_h2_set2 --predictions data/timeline/x.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.candidates import CandidateSet  # noqa: E402
from src.evaluate import (MIN_IOU, TOLERANCE_FRAMES, Prediction, TruthSet,  # noqa: E402
                          evaluate, format_report, report_json)
from src.pose import PoseRun  # noqa: E402
from src.release import TIMELINE_ROOT  # noqa: E402
from src.roster import Roster  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("video", help="clip stem")
    ap.add_argument("--predictions", type=Path, help="timeline JSON; default: data/timeline/<stem>.json")
    ap.add_argument("--candidates", action="store_true", help="score the proposals instead")
    ap.add_argument("--tolerance", type=int, default=TOLERANCE_FRAMES)
    ap.add_argument("--min-iou", type=float, default=MIN_IOU)
    ap.add_argument("--json", type=Path, help="write the report here as well")
    ap.add_argument("--raw-boxes", action="store_true",
                    help="match on the annotator's box as placed, not moved to the release frame")
    args = ap.parse_args()
    stem = Path(args.video).stem

    truth = TruthSet.for_video(stem)
    if not args.raw_boxes:
        truth = truth.anchored(Roster.for_video(stem), PoseRun.for_video(stem))
    if args.candidates:
        predictions = [Prediction.from_candidate(c)
                       for c in CandidateSet.for_video(stem).candidates]
        source = "candidates"
    else:
        path = args.predictions or TIMELINE_ROOT / f"{stem}.json"
        predictions = Prediction.load_timeline(path)
        source = str(path.relative_to(REPO_ROOT) if path.is_absolute() and path.is_relative_to(REPO_ROOT) else path)
    report = evaluate(truth, predictions, args.tolerance, args.min_iou)
    print(f"{stem}: {len(predictions)} predictions ({source}) against "
          f"{len(truth.events)} events, tolerance ±{args.tolerance} frames, IoU ≥ {args.min_iou}")
    print(format_report(report))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report_json(report), indent=1))
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
