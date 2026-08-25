"""Reader for the pose runs in ``data/pose/``.

Written by ``scripts/precompute_pose.py``. One inference pass per clip serves the
labelling tool and every pipeline stage, so "no skeleton here" while labelling and
"missed" during evaluation are the same statement about the same model rather
than two different detectors disagreeing.

Chunks are loaded on demand and cached, because a full clip's detections are far
larger than the working set of any single stage.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
POSE_ROOT = REPO_ROOT / "data" / "pose"

MANIFEST_SCHEMA_VERSION = 1


class PoseRun:
    """One detector run over one clip."""

    def __init__(self, run_dir: str | Path):
        self.dir = Path(run_dir)
        self.manifest = json.loads((self.dir / "manifest.json").read_text())
        if self.manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
            raise ValueError(f"{self.dir} is schema {self.manifest.get('schema_version')}, "
                             f"expected {MANIFEST_SCHEMA_VERSION}")
        self.chunk_frames = self.manifest["chunk_frames"]
        self.frame_count = self.manifest["frame_count"]
        self.fps = self.manifest["fps"]
        self._cache: dict[int, dict] = {}

    @classmethod
    def for_video(cls, video: str | Path, run_id: str | None = None) -> "PoseRun":
        root = POSE_ROOT / Path(video).stem
        if not root.is_dir():
            raise FileNotFoundError(f"no pose runs for {Path(video).stem}; "
                                    f"run scripts/precompute_pose.py")
        if run_id:
            return cls(root / run_id)
        runs = sorted(p for p in root.iterdir() if (p / "manifest.json").exists())
        if len(runs) != 1:
            raise ValueError(f"{len(runs)} runs under {root}; pass run_id to choose")
        return cls(runs[0])

    def check_clip(self, clip_sha256: str) -> None:
        """Refuse to mix a run with a different cut of the footage.

        Frame indices are the only thing tying labels, calibration and detections
        together. A re-encode shifts them silently, so the clip hash is compared
        rather than the filename.
        """
        if self.manifest["clip_sha256"] != clip_sha256:
            raise ValueError(f"pose run {self.dir.name} was computed on a different clip")

    @property
    def frames_done(self) -> int:
        """Frames actually written, counted from disk.

        The manifest is only rewritten when a run finishes, so trusting it would
        under-report a run still in progress - and a consumer would read the gap
        as the detector having found nothing rather than as frames not yet
        computed. A chunk file is written whole, so its presence is the truth.
        """
        total = 0
        for path in self.dir.glob("frames_*.json"):
            start = int(path.stem.split("_")[1])
            total += max(0, min(start + self.chunk_frames, self.frame_count) - start)
        return total

    def _chunk(self, index: int) -> dict:
        if index not in self._cache:
            path = self.dir / f"frames_{index * self.chunk_frames:05d}.json"
            self._cache[index] = json.loads(path.read_text()) if path.exists() else {}
        return self._cache[index]

    def frame(self, index: int) -> list[dict]:
        """Detections on one frame. Empty for a frame that was never processed."""
        return self._chunk(index // self.chunk_frames).get(str(index), [])

    def __iter__(self):
        for index in range(self.frame_count):
            yield index, self.frame(index)
