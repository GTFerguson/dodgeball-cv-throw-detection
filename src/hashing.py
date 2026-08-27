"""The clip hash every derived file carries.

Frame indices are all that tie calibration, detections, labels and the
timeline together, and a re-encode shifts them without changing a filename;
so every stage records the SHA-256 of the clip it read and every reader
refuses a mismatch. One definition, so the hash a writer records and the
hash a reader checks can never drift apart.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


def clip_sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()
