#!/usr/bin/env python
"""Checks on the pose run reader.

The reader has to be honest about a run that is only partly computed: the
manifest is written when a run finishes, so a reader that trusted it would report
uncomputed frames as frames where nothing was detected. Those are opposite
statements and only one of them is a gap in the data.

Run with ``.venv/bin/python scripts/test_pose.py``.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from pose import MANIFEST_SCHEMA_VERSION, PoseRun  # noqa: E402

CHUNK = 1000
FRAMES = 4300


def a_run(root: Path, chunks_on_disk: int, chunks_in_manifest: int = 0) -> Path:
    run = root / "yolo11x-pose-1920-abc123"
    run.mkdir(parents=True)
    (run / "manifest.json").write_text(json.dumps({
        "schema_version": MANIFEST_SCHEMA_VERSION, "clip_sha256": "deadbeef",
        "fps": 25.0, "frame_count": FRAMES, "chunk_frames": CHUNK,
        "chunks": [{"file": f"frames_{i * CHUNK:05d}.json", "start_frame": i * CHUNK,
                    "end_frame": (i + 1) * CHUNK, "frames": CHUNK}
                   for i in range(chunks_in_manifest)],
    }))
    for i in range(chunks_on_disk):
        frame = i * CHUNK + 5
        (run / f"frames_{i * CHUNK:05d}.json").write_text(json.dumps(
            {str(frame): [{"box": [1, 2, 3, 4], "conf": 0.9, "kpts": []}]}))
    return run


class PartialRuns(unittest.TestCase):
    def test_counts_frames_from_disk_not_the_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = PoseRun(a_run(Path(tmp), chunks_on_disk=3, chunks_in_manifest=1))
            self.assertEqual(run.frames_done, 3 * CHUNK)

    def test_final_chunk_is_clipped_to_the_clip_length(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = PoseRun(a_run(Path(tmp), chunks_on_disk=5, chunks_in_manifest=5))
            self.assertEqual(run.frames_done, FRAMES)

    def test_an_unwritten_frame_reads_as_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = PoseRun(a_run(Path(tmp), chunks_on_disk=1))
            self.assertEqual(run.frame(5000), [])

    def test_reads_a_detection_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = PoseRun(a_run(Path(tmp), chunks_on_disk=2))
            self.assertEqual(len(run.frame(1005)), 1)
            self.assertEqual(run.frame(1006), [])


class Guards(unittest.TestCase):
    def test_rejects_a_run_from_a_different_clip(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = PoseRun(a_run(Path(tmp), chunks_on_disk=1))
            run.check_clip("deadbeef")
            with self.assertRaises(ValueError):
                run.check_clip("f00d")

    def test_rejects_a_future_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = a_run(Path(tmp), chunks_on_disk=1)
            manifest = json.loads((run / "manifest.json").read_text())
            manifest["schema_version"] = MANIFEST_SCHEMA_VERSION + 1
            (run / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaises(ValueError):
                PoseRun(run)


if __name__ == "__main__":
    unittest.main(verbosity=2)
