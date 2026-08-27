#!/usr/bin/env python
"""Fetches the model weights into weights/. Weights are never committed.

Source: the Ultralytics assets release - YOLO11x-pose for people and keypoints,
SAM 2 large for following the ball through its contact:
https://github.com/ultralytics/assets/releases/download/v8.3.0/

The release tag and the checksums are pinned: the tag so a clean clone gets the
same files the labels and the evaluation were produced against, the checksum so
a truncated or substituted download fails here rather than showing up later as
detections that quietly differ. The run id in every pose run is derived from the
pose file's hash, so a different file would be a different run by construction.

Usage::

    .venv/bin/python scripts/download_weights.py
"""

from __future__ import annotations

import shutil
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.hashing import clip_sha256  # noqa: E402

WEIGHTS_DIR = Path(__file__).resolve().parent.parent / "weights"

# Every model the pipeline loads, pinned by checksum so a run is reproducible:
# YOLO11x-pose for every person on every frame (docs/architecture/pose-precompute.md),
# SAM 2 large for following the ball through its contact (docs/architecture/rebound.md).
WEIGHTS = (
    ("yolo11x-pose.pt",
     "013c43543b0751b8918486ba96e01ee44a59040683a07f96cc22bcc2cb7785f8", 118481010),
    ("sam2_l.pt",
     "fd618bcfc7b84c8f2e0a6997548e197b907098196dd075387d01f64d9cf8a93b", 449203114),
)
RELEASE = "https://github.com/ultralytics/assets/releases/download/v8.3.0"


def fetch(name: str, sha256: str, size_bytes: int) -> int:
    target = WEIGHTS_DIR / name
    url = f"{RELEASE}/{name}"

    if target.exists():
        if clip_sha256(target) == sha256:
            print(f"already present: {target}")
            return 0
        if target.is_symlink():
            # A hand-placed checkpoint under the pinned name (Meta's own SAM 2
            # release loads under it); leave it and say so.
            print(f"{target} is a link to other weights; leaving it in place")
            return 0
        print(f"{target} does not match the pinned checksum; re-downloading",
              file=sys.stderr)

    # Download beside the target and rename, so an interrupted fetch cannot leave
    # a partial file that looks like the real thing to the next run.
    tmp = target.with_suffix(target.suffix + ".part")
    print(f"downloading {url}")
    with urllib.request.urlopen(url) as response, tmp.open("wb") as out:
        shutil.copyfileobj(response, out)

    size = tmp.stat().st_size
    digest = clip_sha256(tmp)
    if size != size_bytes or digest != sha256:
        tmp.unlink()
        print(f"download does not match the pinned weights "
              f"(got {size} bytes, sha256 {digest})", file=sys.stderr)
        return 1

    tmp.replace(target)
    print(f"saved: {target}")
    return 0


def main() -> int:
    WEIGHTS_DIR.mkdir(parents=True, exist_ok=True)
    return max(fetch(*w) for w in WEIGHTS)


if __name__ == "__main__":
    raise SystemExit(main())
