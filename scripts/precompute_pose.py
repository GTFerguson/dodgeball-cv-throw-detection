#!/usr/bin/env python
"""Pre-compute whole-body pose for a clip so the labelling tool can place boxes.

The tool shows skeletons only as a placement aid; the label stores box
coordinates by value. What matters is that this run uses the *same* detector and
settings the pipeline will use, so "no skeleton here" in the tool and "missed" in
the evaluation are the same statement about the same model.

The on-disk shape is a contract shared with the detection pipeline, specified in
``docs/plans/labeling-tool.md`` § Pose precompute::

    data/pose/<video-stem>/<run-id>/manifest.json
    data/pose/<video-stem>/<run-id>/frames_00000.json   frames 0-999
    data/pose/<video-stem>/<run-id>/frames_01000.json   frames 1000-1999
    ...

A chunk maps frame index to the detections on it; a frame present with an empty
list was processed and had nothing, a frame absent was never processed. Every
person is written — court filtering happens in the reader, against the same
polygon the pipeline uses, so filtering can change without re-running inference.

Chunks are aligned to absolute multiples of ``CHUNK_FRAMES``, so a chunk written
by a ``--start``/``--end`` run covers the same frame range as the equivalent chunk
from a full pass and the two are interchangeable.

The run id is derived from the model, its input size and the weights hash, so
re-running the same model resumes into the same directory and skips chunks already
on disk. The thresholds are not in the id — a run refuses to extend a directory
whose manifest records different ones, so a resumed run cannot mix them.

Usage::

    .venv/bin/python scripts/precompute_pose.py data/footage/clip.mp4
    .venv/bin/python scripts/precompute_pose.py data/footage/clip.mp4 --limit 100
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Bumped when the on-disk chunk or manifest shape changes, so a stale run is
# recognisable rather than silently misread.
SCRIPT_VERSION = 1

# Fixed by the contract, not a tuning knob: the pipeline reads these chunks too.
CHUNK_FRAMES = 1000

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.hashing import clip_sha256  # noqa: E402

DEFAULT_WEIGHTS = REPO_ROOT / "weights" / "yolo11x-pose.pt"
POSE_ROOT = REPO_ROOT / "data" / "pose"

# COCO-17 order, the layout every ultralytics pose model emits. Written into the
# manifest so a consumer never has to assume it.
KEYPOINT_NAMES = [
    "nose", "left_eye", "right_eye", "left_ear", "right_ear",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_hip", "right_hip",
    "left_knee", "right_knee", "left_ankle", "right_ankle",
]


# ── chunk arithmetic ────────────────────────────────────────────────────────
# Pure, so the partition can be tested without a video or a model.

def chunk_index(frame: int) -> int:
    """Index of the chunk that owns ``frame``."""
    return frame // CHUNK_FRAMES


def chunk_bounds(index: int) -> tuple[int, int]:
    """Half-open ``[start, end)`` frame range of chunk ``index``."""
    start = index * CHUNK_FRAMES
    return start, start + CHUNK_FRAMES


def chunk_filename(index: int) -> str:
    return f"frames_{index * CHUNK_FRAMES:05d}.json"


def chunk_indices(start_frame: int, end_frame: int) -> list[int]:
    """Chunks touched by the half-open frame range ``[start_frame, end_frame)``."""
    if end_frame <= start_frame:
        return []
    return list(range(chunk_index(start_frame), chunk_index(end_frame - 1) + 1))


# ── provenance ──────────────────────────────────────────────────────────────

def make_run_id(weights: Path, weights_hash: str, imgsz: int) -> str:
    """Identify a run by the model that produced it, not by when it ran.

    Two runs of the same weights at the same input size are the same run: rerunning
    resumes rather than duplicating. Thresholds stay out of the id and live in the
    manifest instead; ``run`` refuses to extend a directory whose manifest was
    written with different ones, so a resumed run can never mix them.
    """
    return f"{weights.stem}-{imgsz}-{weights_hash[:8]}"


# ── inference ───────────────────────────────────────────────────────────────

def detections_from_result(result) -> list[dict]:
    """Boxes plus keypoints for one frame, in source pixels.

    Coordinates are rounded to a tenth of a pixel: finer than any box a human can
    place or adjust, and it roughly halves the chunk payload.
    """
    out: list[dict] = []
    boxes = getattr(result, "boxes", None)
    if boxes is None or len(boxes) == 0:
        return out

    keypoints = getattr(result, "keypoints", None)
    kp_data = keypoints.data.tolist() if keypoints is not None else []

    for i in range(len(boxes)):
        x1, y1, x2, y2 = (float(v) for v in boxes.xyxy[i].tolist())
        kps = kp_data[i] if i < len(kp_data) else []
        out.append({
            "box": [round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)],
            "conf": round(float(boxes.conf[i].item()), 3),
            "kpts": [
                [round(float(k[0]), 1), round(float(k[1]), 1), round(float(k[2]), 3)]
                for k in kps
            ],
        })
    return out


def write_json(path: Path, payload: dict) -> None:
    """Write via a temp file in the same directory so a crash cannot leave a
    half-written chunk that a later run would treat as complete."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, separators=(",", ":")))
    tmp.replace(path)


def run(args: argparse.Namespace) -> int:
    import cv2
    from ultralytics import YOLO

    video = Path(args.video).resolve()
    if not video.exists():
        print(f"no such video: {video}", file=sys.stderr)
        return 1

    weights = Path(args.weights).resolve()
    if not weights.exists():
        print(f"no such weights: {weights}", file=sys.stderr)
        return 1

    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        print(f"cannot open video: {video}", file=sys.stderr)
        return 1
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = float(cap.get(cv2.CAP_PROP_FPS))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    start = max(0, args.start)
    end = frame_count if args.end is None else min(args.end, frame_count)
    if args.limit is not None:
        end = min(end, start + args.limit)
    if end <= start:
        print(f"empty frame range [{start}, {end})", file=sys.stderr)
        return 1

    weights_hash = clip_sha256(weights)
    run_id = args.run_id or make_run_id(weights, weights_hash, args.imgsz)
    out_dir = POSE_ROOT / video.stem / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = out_dir / "manifest.json"
    if manifest_path.exists() and not args.force:
        prior = json.loads(manifest_path.read_text())
        changed = {k: (prior.get(k), v) for k, v in
                   (("conf", args.conf), ("iou", args.iou)) if prior.get(k) != v}
        if changed:
            print(f"run {run_id} was written with {changed}; pass --force to "
                  f"recompute it, or use --run-id for a separate run",
                  file=sys.stderr)
            return 1

    wanted = chunk_indices(start, end)
    print(f"{video.name}: frames [{start}, {end}) → {len(wanted)} chunks → {out_dir}")

    model = YOLO(str(weights))

    for idx in wanted:
        c_start, c_end = chunk_bounds(idx)
        c_start = max(c_start, start)
        c_end = min(c_end, end)
        path = out_dir / chunk_filename(idx)

        # A chunk left partial by an earlier --limit or --end run is not done just
        # because the file exists: it is done when it holds every frame this run
        # wants from it. Missing frames are filled in and merged back.
        chunk: dict[str, list[dict]] = {}
        if path.exists() and not args.force:
            chunk = json.loads(path.read_text())
        missing = [f for f in range(c_start, c_end) if str(f) not in chunk]
        if not missing:
            continue

        cap.set(cv2.CAP_PROP_POS_FRAMES, missing[0])
        landed = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
        if landed != missing[0]:
            # Some containers refuse an exact seek; walking from the start is slow
            # but keeps frame indices honest, which every label depends on.
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            for _ in range(missing[0]):
                cap.read()

        want = set(missing)
        added = 0
        for frame_idx in range(missing[0], missing[-1] + 1):
            ok, image = cap.read()
            if not ok:
                break
            if frame_idx not in want:
                continue
            result = model.predict(
                image, imgsz=args.imgsz, conf=args.conf, iou=args.iou,
                device=args.device, verbose=False,
            )[0]
            chunk[str(frame_idx)] = detections_from_result(result)
            added += 1

        if not chunk:
            continue

        write_json(path, {k: chunk[k] for k in sorted(chunk, key=int)})
        people = sum(len(d) for d in chunk.values())
        print(f"  {path.name}  +{added} frames ({len(chunk)} total), "
              f"{people} detections")

    cap.release()

    chunks = []
    for idx in wanted:
        path = out_dir / chunk_filename(idx)
        if not path.exists():
            continue
        present = [int(f) for f in json.loads(path.read_text())]
        chunks.append({
            "file": path.name,
            "start_frame": min(present),
            "end_frame": max(present) + 1,
            # Frame count as well as the span, so a reader can tell a chunk with
            # a hole in it from a contiguous one without parsing the whole file.
            "frames": len(present),
        })

    write_json(manifest_path, {
        "schema_version": SCRIPT_VERSION,
        "run_id": run_id,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "video": video.name,
        "clip_sha256": clip_sha256(video),
        "fps": fps,
        "frame_count": frame_count,
        "frame_size": [width, height],
        "model": weights.name,
        "weights_sha256": weights_hash,
        "imgsz": args.imgsz,
        "conf": args.conf,
        "iou": args.iou,
        "device": args.device,
        "keypoint_names": KEYPOINT_NAMES,
        "chunk_frames": CHUNK_FRAMES,
        "chunks": chunks,
    })
    covered = sum(c["end_frame"] - c["start_frame"] for c in chunks)
    print(f"manifest written: {len(chunks)} chunks, {covered} frames")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("video", help="path to the clip")
    p.add_argument("--weights", default=str(DEFAULT_WEIGHTS))
    p.add_argument("--imgsz", type=int, default=1920,
                   help="inference size; far-court players are small, so the "
                        "default matches the source width rather than 640")
    p.add_argument("--conf", type=float, default=0.25)
    p.add_argument("--iou", type=float, default=0.7, help="NMS IoU threshold")
    p.add_argument("--device", default="cuda:0")
    p.add_argument("--start", type=int, default=0, help="first frame (inclusive)")
    p.add_argument("--end", type=int, default=None, help="last frame (exclusive)")
    p.add_argument("--limit", type=int, default=None,
                   help="stop after this many frames — for a smoke test")
    p.add_argument("--run-id", default=None,
                   help="override the settings-derived run id")
    p.add_argument("--force", action="store_true",
                   help="recompute chunks that already exist")
    return p.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
