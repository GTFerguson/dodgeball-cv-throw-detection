#!/usr/bin/env python3
"""Score the cascade with its later stages switched off.

Three prediction sets from one run of the pipeline, each scored by
``scripts/evaluate.py`` against the same truth:

* ``pose_only`` - every proposal the wind-up detector made, claimed as a
  throw. What a pose-only detector would report.
* ``release_gate`` - the proposals that pass the ball gates, claimed as a
  throw where the ball was seen leaving and a fake otherwise. No
  destination test, so a pass is a throw.
* ``full`` - the timeline as written: fake, pass or throw.

Each row is the same matching against the same events, so the difference
between rows is exactly what the stage removed. Writes the variant
timelines and reports to ``output/ablation/`` and a table to
``output/ablation/summary.md``.

Usage::

    .venv/bin/python scripts/ablate.py wdbf2014_final_h2_set2
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.candidates import CandidateSet  # noqa: E402
from src.release import TIMELINE_ROOT  # noqa: E402

PYTHON = REPO_ROOT / ".venv" / "bin" / "python"
OUTPUT = REPO_ROOT / "output" / "ablation"

ROWS = (
    ("pose_only", "wind-up from pose; every proposal a throw"),
    ("release_gate", "+ ball in hand, ball seen leaving; released = throw"),
    ("full", "+ destination: pass or throw"),
)


def variants(stem: str) -> dict[str, dict]:
    timeline = json.loads((TIMELINE_ROOT / f"{stem}.json").read_text())
    proposals = CandidateSet.for_video(stem)
    header = {k: timeline[k] for k in ("video", "clip_sha256", "pose_run", "fps")}

    pose_only = [{"frame": c.frame, "box": list(c.box), "team": c.team,
                  "released": True, "kind": "throw"} for c in proposals.candidates]
    release_gate = [{"frame": e["frame"], "box": e["box"], "team": e["team"],
                     "released": e["released"],
                     "kind": "throw" if e["released"] else "fake"}
                    for e in timeline["events"]]
    full = [{"frame": e["frame"], "box": e["box"], "team": e["team"],
             "released": e["released"], "kind": e["kind"], "outcome": e["outcome"]}
            for e in timeline["events"]]
    return {"pose_only": {**header, "ablation": "pose_only", "events": pose_only},
            "release_gate": {**header, "ablation": "release_gate", "events": release_gate},
            "full": {**header, "ablation": "full", "events": full}}


def pct(x: float) -> str:
    return f"{100 * x:.0f}%"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("video", help="clip stem or path under data/footage/")
    args = ap.parse_args()
    stem = Path(args.video).stem
    OUTPUT.mkdir(parents=True, exist_ok=True)

    reports = {}
    for name, data in variants(stem).items():
        path = OUTPUT / f"{stem}.{name}.json"
        path.write_text(json.dumps(data, indent=1))
        report = OUTPUT / f"{stem}.{name}.report.json"
        subprocess.run([str(PYTHON), str(REPO_ROOT / "scripts" / "evaluate.py"), stem,
                        "--predictions", str(path), "--json", str(report)],
                       check=True, cwd=REPO_ROOT, stdout=subprocess.DEVNULL)
        reports[name] = json.loads(report.read_text())

    lines = ["# Ablation", "",
             f"One pipeline run on `{stem}`, scored three times with later stages withheld. "
             "Candidate-level matching is identical across rows; what moves is what each "
             "stage claims about the matched motion.", "",
             "| Stage | Claims | Predictions | Throw P | Throw R | Throw F1 | "
             "Fake F1 | Pass F1 | Kind acc. |",
             "|---|---|---|---|---|---|---|---|---|"]
    for name, desc in ROWS:
        r = reports[name]
        d = r["detection"]
        n = r["candidate"]["tp"] + r["candidate"]["fp"]
        lines.append(
            f"| {name} | {desc} | {n} | {pct(d['throw']['precision'])} | "
            f"{pct(d['throw']['recall'])} | {pct(d['throw']['f1'])} | {pct(d['fake']['f1'])} | "
            f"{pct(d['pass']['f1'])} | {pct(r['kind']['accuracy'])} |")
    out = OUTPUT / "summary.md"
    out.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"wrote {out.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
