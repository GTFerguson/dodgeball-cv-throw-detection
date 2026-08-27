#!/usr/bin/env python3
"""Run the cascade on a degraded copy of the clip and score it.

One condition at a time: encode the degraded clip, run pose on it, derive
the inputs that carry over from the source (court, set starts, labels),
then run every pixel-reading stage afresh - identity, set end, candidates,
events - and score the result. ``--report`` tabulates every condition
scored so far against the source clip. See ``src/stress.py`` for what is
recomputed and what is carried, and why.

Usage::

    .venv/bin/python scripts/stress.py 480p crf40 drop2
    .venv/bin/python scripts/stress.py --report
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from src.evaluate import TOLERANCE_FRAMES  # noqa: E402
from src.hashing import clip_sha256  # noqa: E402
from src.stress import (CONDITIONS, FOOTAGE_ROOT, Condition, derive_court,  # noqa: E402
                        derive_labels, derive_sets, read_json, tolerance_for, write_json)
from run import PYTHON, SCRIPTS, run, run_stages  # noqa: E402

OUTPUT = REPO_ROOT / "output" / "stress"
SOURCE_STEM = "wdbf2014_final_h2_set2"


def probe(path: Path) -> tuple[float, tuple[int, int], int]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
         "-show_entries", "stream=width,height,r_frame_rate,nb_read_frames", "-of", "json",
         str(path)], check=True, capture_output=True, text=True).stdout
    s = json.loads(out)["streams"][0]
    num, den = s["r_frame_rate"].split("/")
    return float(num) / float(den), (int(s["width"]), int(s["height"])), int(s["nb_read_frames"])


def encode(cond: Condition, source: Path, target: Path, fps: float, size: tuple[int, int]) -> None:
    if target.exists():
        print(f"already encoded: {target.relative_to(REPO_ROOT)}")
        return
    filters = cond.ffmpeg_filters(fps, size)
    cmd = ["ffmpeg", "-v", "error", "-i", source]
    if filters:
        cmd += ["-vf", ",".join(filters)]
    if cond.keep_every > 1:
        cmd += ["-r", str(fps / cond.keep_every)]
    # Same encoder settings as scripts/make_clip.sh apart from the condition
    # itself, so nothing but the intended degradation separates the clips.
    cmd += ["-c:v", "libx264", "-preset", "slow", "-crf", str(cond.crf), "-pix_fmt", "yuv420p",
            "-c:a", "copy", "-movflags", "+faststart", target]
    run(cmd, f"encode {cond.name}")


def pose_run_for(stem: str) -> dict:
    root = REPO_ROOT / "data" / "pose" / stem
    runs = [p for p in root.iterdir() if (p / "manifest.json").exists()] if root.is_dir() else []
    if len(runs) != 1:
        raise SystemExit(f"expected one pose run under {root}, found {len(runs)}")
    return read_json(runs[0] / "manifest.json")


def stress(cond: Condition, skip_pose: bool) -> None:
    stem = cond.stem_for(SOURCE_STEM)
    source = FOOTAGE_ROOT / f"{SOURCE_STEM}.mp4"
    target = FOOTAGE_ROOT / f"{stem}.mp4"
    fps, size, _ = probe(source)
    encode(cond, source, target, fps, size)
    clip = clip_sha256(target)

    if not skip_pose:
        run_stages(target, start="pose", stop="pose")
    manifest = pose_run_for(stem)
    if manifest["clip_sha256"] != clip:
        raise SystemExit(f"pose run for {stem} is from a different encode; delete data/pose/{stem}")

    data = REPO_ROOT / "data"
    write_json(data / "court" / f"{stem}.json",
               derive_court(read_json(data / "court" / f"{SOURCE_STEM}.json"), cond, stem, clip),
               indent=2)
    write_json(data / "sets" / f"{stem}.json",
               derive_sets(read_json(data / "sets" / f"{SOURCE_STEM}.json"), cond, stem, clip,
                           manifest["run_id"], manifest["frame_count"]), indent=2)
    write_json(data / "labels" / f"{stem}.json",
               derive_labels(read_json(data / "labels" / f"{SOURCE_STEM}.json"), cond, stem))
    print(f"derived court, sets and labels for {stem}")

    # Identity onward is the pipeline proper; court and set starts were derived above.
    run_stages(target, start="identity")
    tol = tolerance_for(TOLERANCE_FRAMES, cond)
    run([PYTHON, SCRIPTS / "evaluate.py", stem, "--tolerance", tol,
         "--json", OUTPUT / f"{cond.name}.json"], f"evaluate {cond.name}")
    run([PYTHON, SCRIPTS / "evaluate.py", stem, "--tolerance", tol, "--candidates",
         "--json", OUTPUT / f"{cond.name}.candidates.json"], f"evaluate candidates {cond.name}")


def reference() -> None:
    run([PYTHON, SCRIPTS / "evaluate.py", SOURCE_STEM, "--json", OUTPUT / "source.json"],
        "evaluate source")
    run([PYTHON, SCRIPTS / "evaluate.py", SOURCE_STEM, "--candidates",
         "--json", OUTPUT / "source.candidates.json"], "evaluate source candidates")


def pct(x: float | None) -> str:
    return "—" if x is None else f"{100 * x:.0f}%"


def acc(level: dict | None) -> str:
    return "—" if not level else f"{pct(level['accuracy'])} ({level['n']})"


def report() -> Path:
    rows = [("source", "1080p, CRF 16, 25 fps", "source")]
    rows += [(c.name, c.description, c.name) for c in CONDITIONS.values()
             if (OUTPUT / f"{c.name}.json").exists()]
    lines = ["# Stress conditions", "",
             "Every pixel-reading stage rerun on the degraded clip; court fit, set starts "
             "and labels carried over from the source (see `src/stress.py`). Tolerance "
             "±0.25 s throughout.", "",
             "| Condition | Clip | Cand. P | Cand. R | Cand. F1 | Release MAE | Release | Kind | "
             "Outcome | Efficiency near | Efficiency far |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for name, desc, key in rows:
        r = read_json(OUTPUT / f"{key}.json")
        c, b = r["candidate"], r["boundary"]
        eff = r["efficiency"].get("predicted", {})
        truth = r["efficiency"]["truth"]

        def e(team):
            p = eff.get(team)
            return "—" if not p else (f"{p['eliminations']}/{p['throws']} "
                                      f"(truth {truth[team]['eliminations']}/{truth[team]['throws']})")
        lines.append(
            f"| {name} | {desc} | {pct(c['precision'])} | {pct(c['recall'])} | {pct(c['f1'])} | "
            f"{b['release_mae']:.1f} f | {acc(r['release'])} | {acc(r['kind'])} | "
            f"{acc(r['outcome'])} | {e('near')} | {e('far')} |")
    lines += ["", "Proposals alone (pose only, before the ball is consulted):", "",
              "| Condition | P | R | F1 | n proposals |", "|---|---|---|---|---|"]
    for name, _, key in rows:
        path = OUTPUT / f"{key}.candidates.json"
        if not path.exists():
            continue
        c = read_json(path)["candidate"]
        lines.append(f"| {name} | {pct(c['precision'])} | {pct(c['recall'])} | {pct(c['f1'])} | "
                     f"{c['tp'] + c['fp']} |")
    out = OUTPUT / "summary.md"
    out.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("conditions", nargs="*", choices=list(CONDITIONS),
                    help=f"one or more of {', '.join(CONDITIONS)}")
    ap.add_argument("--skip-pose", action="store_true",
                    help="reuse the pose run already on disk for the condition")
    ap.add_argument("--report", action="store_true", help="tabulate output/stress/*.json")
    args = ap.parse_args()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    if args.conditions and not (OUTPUT / "source.json").exists():
        reference()
    for name in args.conditions:
        stress(CONDITIONS[name], args.skip_pose)
    if args.report or args.conditions:
        if not (OUTPUT / "source.json").exists():
            reference()
        out = report()
        print(f"wrote {out.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
