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
crops behind each confirmed number - and of every long track the vote declined to
name, in time order, so a reader that keeps dropping a digit can be told by eye
from a tracker that stitched two players together.
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
from src.jersey import (Crop, JerseyReader, Reading, confirm,  # noqa: E402
                        in_time_order, needs_review, shortlist, switch,
                        torso_crop, unobstructed)
from src.pose import PoseRun  # noqa: E402
from src.tracking import cut_frame, held_in_play, track as track_players  # noqa: E402

SCHEMA_VERSION = 3

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

    # Only frames where the player is in play are worth a crop. Tracking admits
    # the margin band, which is where the officials stand and the eliminated wait,
    # and a referee's stripes read as a digit as readily as a jersey does. Nothing
    # off court needs a name: attribution only ever asks about players in play.
    in_play: dict[int, int] = {}
    wanted: dict[int, list] = defaultdict(list)
    for t in tracks:
        playing = held_in_play(court, t)
        in_play[t.id] = sum(playing)
        for i, (f, on) in enumerate(zip(t.frames, playing)):
            if on and i % SAMPLE_EVERY == 0:
                wanted[f].append(t)

    crops: dict[int, list[Crop]] = defaultdict(list)
    cap.set(cv2.CAP_PROP_POS_FRAMES, args.start)
    for f in range(args.start, end):
        ok, image = cap.read()
        if not ok:
            break
        for t in wanted.get(f, ()):
            det = t.at(f)
            if det is None or not unobstructed(det, frames[f]):
                continue
            crop = torso_crop(image, det)
            if crop is not None:
                crops[t.id].append(Crop(frame=f, image=crop))
    cap.release()

    with_crops = sum(1 for t in tracks if crops.get(t.id))
    print(f"{with_crops}/{len(tracks)} tracks have a crop tall enough to read")

    reader = JerseyReader(gpu=not args.cpu)
    evidence: dict[int, list[Reading]] = {}
    shortlists: dict[int, list[Crop]] = {}
    for t in tracks:
        picked = shortlist(crops.get(t.id, []))
        if not picked:
            continue
        shortlists[t.id] = picked
        readings: list[Reading] = []
        for crop in picked:
            readings.extend(reader.read(crop))
        evidence[t.id] = readings

    # A track whose readings name one player and then another changed player
    # while the tracker was not looking. It is cut where the change is, and each
    # half is named on its own readings. A half can switch again, so cut until
    # nothing does.
    splits: dict[int, tuple[int, int]] = {}
    next_id = max(t.id for t in tracks) + 1
    queue = list(tracks)
    tracks = []
    while queue:
        t = queue.pop(0)
        found = switch(evidence.get(t.id, []))
        if found is None:
            tracks.append(t)
            continue
        a, b, last_a, first_b = found
        at = cut_frame(t, last_a, first_b)
        head, tail = t.split(at, next_id)
        print(f"track {t.id} reads #{a} then #{b}: cut at {at} -> {head.id}, {tail.id}")
        # The head keeps the id, so take both halves before either is stored.
        whole_readings, whole_crops = evidence[t.id], shortlists[t.id]
        evidence[head.id] = [r for r in whole_readings if r.frame < at]
        evidence[tail.id] = [r for r in whole_readings if r.frame >= at]
        shortlists[head.id] = [c for c in whole_crops if c.frame < at]
        shortlists[tail.id] = [c for c in whole_crops if c.frame >= at]
        in_play[head.id] = sum(held_in_play(court, head)) if head.frames else 0
        in_play[tail.id] = sum(held_in_play(court, tail)) if tail.frames else 0
        splits[tail.id] = (t.id, at)
        next_id += 1
        queue[:0] = [head, tail]
    tracks.sort(key=lambda t: (t.start, t.id))

    numbers: dict[int, int] = {}
    for t in tracks:
        got = confirm(evidence.get(t.id, []))
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
            "in_play_frames": in_play[t.id],
            "split_from": list(splits[t.id]) if t.id in splits else None,
            "number": numbers.get(t.id),
            "readings": [
                {"number": r.number, "confidence": r.confidence, "frame": r.frame}
                for r in sorted(evidence.get(t.id, []), key=lambda r: r.frame)
            ],
        } for t in tracks],
    }, indent=1))
    print(f"\nwrote {out.relative_to(REPO_ROOT)}")

    review = [t for t in tracks
              if needs_review(numbers.get(t.id), in_play[t.id], span)]
    print(f"{len(review)} long tracks left unnamed: "
          + ", ".join(str(t.id) for t in review))

    if args.sheet:
        write_sheet(args.sheet, tracks, numbers, evidence, shortlists, review)
        print(f"wrote {args.sheet}")
    return 0


def write_sheet(path: Path, tracks, numbers, evidence, shortlists, review) -> None:
    """Each named track beside the crops that named it, then the unnamed long ones.

    Crops run left to right in frame order and each carries what the reader made
    of it, so a track whose readings switch part-way - one player then another -
    looks different from one the reader misreads throughout.
    """
    cell = 96
    caption = 16
    rows = []
    for t in tracks:
        if t.id not in numbers and t not in review:
            continue
        by_frame: dict[int, list[int]] = defaultdict(list)
        for r in evidence.get(t.id, []):
            by_frame[r.frame].append(r.number)
        rows.append((t, numbers.get(t.id), by_frame,
                     in_time_order(shortlists.get(t.id, []))))
    # Named tracks first, by number; the questions after, longest first.
    rows.sort(key=lambda r: (r[1] is None, r[1] or 0, -len(r[0].frames)))
    if not rows:
        return
    width = max(sum(int(c.image.shape[1] * cell / c.height) + 6 for c in r[3])
                for r in rows) + 210
    row_h = cell + caption + 14
    sheet = np.full((row_h * len(rows) + 10, max(width, 400), 3), 250, np.uint8)
    y = 6
    for t, number, by_frame, shortlist in rows:
        label = f"#{number}" if number is not None else "?"
        cv2.putText(sheet, label, (8, y + 34), cv2.FONT_HERSHEY_SIMPLEX,
                    0.9, (20, 20, 20), 2)
        cv2.putText(sheet, f"track {t.id}  {t.start}-{t.end}", (8, y + 56),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, (90, 90, 90), 1)
        counts = Counter(n for ns in by_frame.values() for n in ns)
        cv2.putText(sheet, dict(counts).__repr__()[:22], (8, y + 74),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.34, (90, 90, 90), 1)
        x = 120
        for crop in shortlist:
            up = cv2.resize(crop.image, (int(crop.image.shape[1] * cell / crop.height), cell),
                            interpolation=cv2.INTER_AREA)
            if x + up.shape[1] >= sheet.shape[1]:
                break
            sheet[y:y + cell, x:x + up.shape[1]] = up
            seen = ",".join(str(n) for n in by_frame.get(crop.frame, [])) or "-"
            cv2.putText(sheet, f"f{crop.frame} {seen}", (x, y + cell + 12),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.32, (60, 60, 60), 1)
            x += up.shape[1] + 6
        y += row_h
    cv2.imwrite(str(path), sheet)


if __name__ == "__main__":
    raise SystemExit(main())
