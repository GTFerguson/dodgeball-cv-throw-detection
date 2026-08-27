"""Durations to frames at the clip's own rate.

Every window in the pipeline is a duration - how long a thrower holds the
ball before the whip, how long a count must hold to be a step - and was
tuned on a 25 fps clip. Written as frame counts they silently doubled in
length on a half-rate clip (the stress test's frame-drop condition lost 20
points of candidate recall to exactly that). They are kept in seconds and
converted here, once, at the rate the pose run reports.
"""

from __future__ import annotations

# The rate the constants were tuned at; the default wherever a caller has no
# clip to ask, so a unit test at 25 fps reads the same numbers it always did.
REFERENCE_FPS = 25.0


def frames(seconds: float, fps: float = REFERENCE_FPS) -> int:
    """A duration as a whole number of frames, never fewer than one where
    the duration is positive - a window cannot round away to nothing."""
    n = int(round(seconds * fps))
    if seconds > 0 and n == 0:
        return 1
    if seconds < 0 and n == 0:
        return -1
    return n


def window(seconds: tuple[float, float], fps: float = REFERENCE_FPS) -> tuple[int, int]:
    """A (from, to) pair of offsets in seconds as frame offsets."""
    a, b = seconds
    return (int(round(a * fps)), int(round(b * fps)))
