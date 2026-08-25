#!/usr/bin/env python3
"""Put jersey numbers on the players in a clip.

Two stages. ByteTrack follows every player on court for as long as it can, which
on the evaluation clip is most of a set. Then each track's largest crops - the
frames where that player was closest to the camera - are read for a number, and a
number several crops agree on is confirmed for the whole track.

That order is what makes it work. Reading is hard at the far baseline and easy at
the near one, and a track that spans a set contains both, so the number never has
to be read where it is hard.

Writes ``data/players/<stem>.json`` and, with --sheet, a contact sheet of the
crops behind each confirmed number so the result can be checked by eye.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.court import Court  # noqa: E402
from src.jersey import (CROPS_PER_TRACK, JerseyReader, Reading,  # noqa: E402
                        confirm, largest_crops, torso_crop)
from src.pose import PoseRun  # noqa: E402
from src.tracking import track as track_players  # noqa: E402

SCHEMA_VERSION = 1

# A track shorter than this is a detection artefact rather than a player, and
# naming one spends an identity on noise.
MIN_TRACK_FRAMES = 25

# Crops are collected every few frames. Consecutive frames show the same pose from
# the same distance, so they are near-duplicates as far as a reader is concerned,
# and keeping all of them just fills the shortlist with one moment.
SAMPLE_EVERY = 5


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("video", nargs="?", default="wdbf2014_final_h2_set2")
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=None)
    ap.add_argument("--sheet", type=Path, default=None)
    ap.add_argument("--cpu", action="store_true", help="run OCR on the CPU")
    args = ap.parse_args()

    stem = Path(args.video).stem
    court = Court.for_video(stem)
    run = PoseRun.for_video(stem)

    end = args.end if args.end is not None else run.frame_count
    frames = {f: run.frame(f) for f in range(args.start, end)}
    tracks = track_players(court, frames, run.fps)
    tracks = [t for t in tracks if len(t.frames) >= MIN_TRACK_FRAMES]
    span = end - args.start
    held = sum(len(t.frames) for t in tracks)
    lengths = sorted(len(t.frames) for t in tracks)
    print(f"{len(tracks)} tracks over {span} frames "
          f"({held / span:.1f} concurrent, median {lengths[len(lengths) // 2]} frames)")

    video = REPO_ROOT / "data" / "footage" / f"{stem}.mp4"
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        print(f"cannot open {video}", file=sys.stderr)
        return 1

    # One sequential pass to collect crops. Seeking per track would decode the
    # same frames many times over.
    wanted: dict[int, list] = defaultdict(list)
    for t in tracks:
        for i, f in enumerate(t.frames):
            if i % SAMPLE_EVERY == 0:
                wanted[f].append(t)

    crops: dict[int, list[np.ndarray]] = defaultdict(list)
    cap.set(cv2.CAP_PROP_POS_FRAMES, args.start)
    for f in range(args.start, end):
        ok, image = cap.read()
        if not ok:
            break
        for t in wanted.get(f, ()):
            det = t.at(f)
            if det is None:
                continue
            crop = torso_crop(image, det)
            if crop is not None:
                crops[t.id].append(crop)
    cap.release()

    with_crops = sum(1 for t in tracks if crops.get(t.id))
    print(f"{with_crops}/{len(tracks)} tracks have a crop tall enough to read")

    reader = JerseyReader(gpu=not args.cpu)
    numbers: dict[int, int] = {}
    evidence: dict[int, list[Reading]] = {}
    shortlists: dict[int, list[np.ndarray]] = {}
    for t in tracks:
        shortlist = largest_crops(crops.get(t.id, []), CROPS_PER_TRACK)
        if not shortlist:
            continue
        shortlists[t.id] = shortlist
        readings: list[Reading] = []
        for crop in shortlist:
            readings.extend(reader.read(crop))
        evidence[t.id] = readings
        got = confirm(readings)
        if got is not None:
            numbers[t.id] = got

    read_any = sum(1 for r in evidence.values() if r)
    print(f"{read_any} tracks returned a reading, {len(numbers)} confirmed")

    players: dict[int, list[int]] = defaultdict(list)
    for tid, number in numbers.items():
        players[number].append(tid)
    print(f"{len(players)} distinct numbers: "
          + ", ".join(str(n) for n in sorted(players)))
    by_id = {t.id: t for t in tracks}
    for number in sorted(players):
        frames_held = sum(len(by_id[tid].frames) for tid in players[number])
        print(f"  #{number:<3} {len(players[number]):2d} tracks, {frames_held:5d} frames")

    out = REPO_ROOT / "data" / "players" / f"{stem}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "schema_version": SCHEMA_VERSION,
        "video": f"{stem}.mp4",
        "pose_run": run.dir.name,
        "clip_sha256": run.manifest["clip_sha256"],
        "tracks": [{
            "id": t.id,
            "start_frame": t.start,
            "end_frame": t.end,
            "frames": len(t.frames),
            "number": numbers.get(t.id),
            "readings": [
                {"number": r.number, "confidence": r.confidence}
                for r in evidence.get(t.id, [])
            ],
        } for t in tracks],
    }, indent=1))
    print(f"\nwrote {out.relative_to(REPO_ROOT)}")

    if args.sheet:
        write_sheet(args.sheet, tracks, numbers, evidence, shortlists)
        print(f"wrote {args.sheet}")
    return 0


def write_sheet(path: Path, tracks, numbers, evidence, shortlists) -> None:
    """Each confirmed number beside the crops that confirmed it."""
    cell = 96
    rows = []
    for t in tracks:
        if t.id not in numbers:
            continue
        counts = Counter(r.number for r in evidence.get(t.id, []))
        rows.append((t, numbers[t.id], counts, shortlists.get(t.id, [])[:5]))
    rows.sort(key=lambda r: r[1])
    if not rows:
        return
    width = max(sum(int(c.shape[1] * cell / c.shape[0]) + 6 for c in r[3])
                for r in rows) + 210
    sheet = np.full(((cell + 14) * len(rows) + 10, max(width, 400), 3), 250, np.uint8)
    y = 6
    for t, number, counts, shortlist in rows:
        cv2.putText(sheet, f"#{number}", (8, y + 34), cv2.FONT_HERSHEY_SIMPLEX,
                    0.9, (20, 20, 20), 2)
        cv2.putText(sheet, f"track {t.id}", (8, y + 56), cv2.FONT_HERSHEY_SIMPLEX,
                    0.38, (90, 90, 90), 1)
        cv2.putText(sheet, dict(counts).__repr__()[:22], (8, y + 74),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.34, (90, 90, 90), 1)
        x = 120
        for crop in shortlist:
            up = cv2.resize(crop, (int(crop.shape[1] * cell / crop.shape[0]), cell),
                            interpolation=cv2.INTER_AREA)
            if x + up.shape[1] >= sheet.shape[1]:
                break
            sheet[y:y + cell, x:x + up.shape[1]] = up
            x += up.shape[1] + 6
        y += cell + 14
    cv2.imwrite(str(path), sheet)


if __name__ == "__main__":
    raise SystemExit(main())
