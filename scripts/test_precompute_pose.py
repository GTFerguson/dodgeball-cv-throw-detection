#!/usr/bin/env python
"""Checks on the pose chunk partition.

Every frame must land in exactly one chunk and every chunk must be reachable
from a frame range that touches it — a frame that falls between chunks would
show as "no skeleton" in the tool and be indistinguishable from a genuine
detector miss.

Run with ``.venv/bin/python scripts/test_precompute_pose.py``.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from precompute_pose import (  # noqa: E402
    CHUNK_FRAMES,
    chunk_bounds,
    chunk_filename,
    chunk_index,
    chunk_indices,
)


class ChunkPartition(unittest.TestCase):
    def test_frame_lands_in_exactly_one_chunk(self):
        frame_count = CHUNK_FRAMES * 4 + 37
        for frame in range(frame_count):
            owners = [i for i in range(chunk_index(frame_count - 1) + 1)
                      if chunk_bounds(i)[0] <= frame < chunk_bounds(i)[1]]
            self.assertEqual(owners, [chunk_index(frame)], f"frame {frame}")

    def test_bounds_are_contiguous_and_half_open(self):
        for i in range(10):
            start, end = chunk_bounds(i)
            self.assertEqual(end - start, CHUNK_FRAMES)
            self.assertEqual(start, chunk_bounds(i - 1)[1] if i else 0)

    def test_boundary_frames(self):
        self.assertEqual(chunk_index(0), 0)
        self.assertEqual(chunk_index(CHUNK_FRAMES - 1), 0)
        self.assertEqual(chunk_index(CHUNK_FRAMES), 1)

    def test_range_covers_every_frame_it_names(self):
        for start, end in [(0, 1), (0, CHUNK_FRAMES), (0, CHUNK_FRAMES + 1),
                           (CHUNK_FRAMES - 1, CHUNK_FRAMES + 1), (700, 1300)]:
            touched = chunk_indices(start, end)
            for frame in range(start, end):
                self.assertIn(chunk_index(frame), touched, f"{start}-{end} f{frame}")

    def test_empty_range_touches_no_chunks(self):
        self.assertEqual(chunk_indices(10, 10), [])
        self.assertEqual(chunk_indices(10, 5), [])

    def test_filenames_are_unique_and_sort_by_frame(self):
        names = [chunk_filename(i) for i in range(50)]
        self.assertEqual(len(set(names)), len(names))
        self.assertEqual(names, sorted(names))


if __name__ == "__main__":
    unittest.main()
