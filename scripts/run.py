#!/usr/bin/env python3
"""Footage in, timeline and metric out: every stage of the pipeline in order.

The stages are separate scripts so each can be rerun and inspected on its
own; this is the front door that runs them in the only order that works,
on one clip, and stops at the first failure. Every stage keys its output
on the clip's hash and refuses a mismatch, so rerunning is safe: the pose
run resumes, the rest recompute.

    fit_court -> precompute_pose -> detect_set_start -> identify_players
    -> detect_set_end -> detect_candidates -> detect_events
    -> tactics (and evaluate, where labels exist)

Usage::

    .venv/bin/python scripts/run.py data/footage/wdbf2014_final_h2.mp4
    .venv/bin/python scripts/run.py data/footage/clip.mp4 --from candidates
    .venv/bin/python scripts/run.py data/footage/clip.mp4 --offset 360   # match timecodes
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PYTHON = REPO_ROOT / ".venv" / "bin" / "python"
SCRIPTS = REPO_ROOT / "scripts"
OUTPUT = REPO_ROOT / "output"

# Name, script, whether it takes the clip path (else the stem), extra args.
STAGES = (
    ("court", "fit_court.py", True),
    ("pose", "precompute_pose.py", True),
    ("sets", "detect_set_start.py", True),
    ("identity", "identify_players.py", False),
    ("set_end", "detect_set_end.py", False),
    ("candidates", "detect_candidates.py", False),
    ("events", "detect_events.py", False),
)


def run(cmd: list[str | Path], label: str) -> None:
    t0 = time.time()
    print(f"\n== {label}", flush=True)
    subprocess.run([str(c) for c in cmd], check=True, cwd=REPO_ROOT)
    print(f"   {label}: {time.time() - t0:.0f} s", flush=True)


def run_stages(video: Path, start: str = "court", stop: str | None = None,
               offset: float = 0.0, skip_court: bool = False) -> None:
    """The stages from `start` to `stop` inclusive, in order, on one clip."""
    stem = video.stem
    names = [s[0] for s in STAGES]
    if start not in names or (stop is not None and stop not in names):
        raise ValueError(f"stages are {names}")
    active = False
    for name, script, takes_path in STAGES:
        active = active or name == start
        if not active:
            continue
        if name == "court" and skip_court and (REPO_ROOT / "data" / "court" / f"{stem}.json").exists():
            print("== court: kept the fit on disk")
        else:
            cmd = [PYTHON, SCRIPTS / script, video if takes_path else stem]
            if name == "sets" and offset:
                cmd += ["--offset", offset]
            run(cmd, name)
        if name == stop:
            break


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("video", type=Path, help="clip under data/footage/")
    ap.add_argument("--from", dest="start", choices=[s[0] for s in STAGES], default="court",
                    help="resume at this stage, reusing what is on disk before it")
    ap.add_argument("--offset", type=float, default=0.0,
                    help="seconds from the start of the match to this clip, for timecodes")
    ap.add_argument("--skip-court", action="store_true",
                    help="keep an existing court fit rather than refitting")
    args = ap.parse_args()

    video = args.video if args.video.is_absolute() else REPO_ROOT / args.video
    if not video.exists():
        print(f"no such clip: {video}", file=sys.stderr)
        return 1
    stem = video.stem
    started = time.time()
    run_stages(video, args.start, offset=args.offset, skip_court=args.skip_court)

    out = OUTPUT / stem
    run([PYTHON, SCRIPTS / "tactics.py", stem, "--markdown", out / "tactics.md"], "tactics")
    if (REPO_ROOT / "data" / "labels" / f"{stem}.json").exists():
        run([PYTHON, SCRIPTS / "evaluate.py", stem, "--json", out / "evaluation.json"], "evaluate")
    else:
        print("\n== evaluate: no labels for this clip; timeline and metric are unscored")
    print(f"\ndone in {(time.time() - started) / 60:.1f} min: data/timeline/{stem}.json, "
          f"output/{stem}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
