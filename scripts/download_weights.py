#!/usr/bin/env python
"""Fetches the pose weights into weights/. Weights are never committed.

Source: Ultralytics YOLO11x-pose, released at
https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11x-pose.pt

The release tag and the checksum are both pinned: the tag so a clean clone gets
the same file the labels and the evaluation were produced against, the checksum
so a truncated or substituted download fails here rather than showing up later as
detections that quietly differ. The run id in every pose run is derived from this
file's hash, so a different file would be a different run by construction.

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

NAME = "yolo11x-pose.pt"
URL = f"https://github.com/ultralytics/assets/releases/download/v8.3.0/{NAME}"
SHA256 = "013c43543b0751b8918486ba96e01ee44a59040683a07f96cc22bcc2cb7785f8"
SIZE_BYTES = 118481010


def main() -> int:
    WEIGHTS_DIR.mkdir(parents=True, exist_ok=True)
    target = WEIGHTS_DIR / NAME

    if target.exists():
        if clip_sha256(target) == SHA256:
            print(f"already present: {target}")
            return 0
        print(f"{target} does not match the pinned checksum; re-downloading",
              file=sys.stderr)

    # Download beside the target and rename, so an interrupted fetch cannot leave
    # a partial file that looks like the real thing to the next run.
    tmp = target.with_suffix(target.suffix + ".part")
    print(f"downloading {URL}")
    with urllib.request.urlopen(URL) as response, tmp.open("wb") as out:
        shutil.copyfileobj(response, out)

    size = tmp.stat().st_size
    digest = clip_sha256(tmp)
    if size != SIZE_BYTES or digest != SHA256:
        tmp.unlink()
        print(f"download does not match the pinned weights "
              f"(got {size} bytes, sha256 {digest})", file=sys.stderr)
        return 1

    tmp.replace(target)
    print(f"saved: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
