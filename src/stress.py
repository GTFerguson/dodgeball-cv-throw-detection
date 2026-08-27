"""Stress conditions: a degraded copy of the clip, with its inputs derived.

A stress test asks how the throw cascade holds up when the footage is
worse - fewer pixels, heavier compression, half the frames. The pipeline
keys every input on the clip hash, so a degraded clip is a new clip with
its own pose run, roster, set timeline, court fit and labels.

What is recomputed and what is carried over is the design decision here.
Everything that reads pixels is rerun on the degraded clip - pose, tracking
and identity, set end, candidates, releases, outcomes - because that is what
the degradation acts on. Three inputs are deterministic transforms of the
source and are carried across instead of recomputed: the court fit (a
downscale is a known affine map of the image, so refitting would only test
the court fitter), the set starts (a whistle in the audio track, which no
condition touches), and the labels (truth does not change with the encode).
Frame indices are remapped where frames were dropped, and boxes scaled where
the picture was.

The truth is the same truth: a label at source frame ``f`` sits at
``frame_map(f)`` in the degraded clip, so the evaluation tolerance in
seconds is preserved by scaling it with the frame rate (``tolerance_for``).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
FOOTAGE_ROOT = REPO_ROOT / "data" / "footage"

# The derived stem is the source stem plus the condition, joined by a marker
# no source clip uses; .gitignore drops every derived artefact on the marker.
STEM_MARKER = "--"


@dataclass(frozen=True)
class Condition:
    """One way of degrading the clip.

    ``scale`` is the picture's size factor; ``keep_every`` the frame stride
    (2 keeps even frames, halving the rate); ``crf`` the x264 quality, where
    the source clip was cut at 16.
    """
    name: str
    scale: float = 1.0
    keep_every: int = 1
    crf: int = 16
    description: str = ""

    @property
    def fps_factor(self) -> float:
        return 1.0 / self.keep_every

    def frame_map(self) -> Callable[[int], int]:
        """Source frame index -> index in the degraded clip.

        Kept frames are those at multiples of the stride; a dropped frame maps
        to the kept frame before it, so a label never moves later in time
        than the picture it described.
        """
        k = self.keep_every
        return lambda f: f // k

    def frame_size(self, source: tuple[int, int]) -> tuple[int, int]:
        """The encoder's output size: height scaled and rounded, width kept
        even for the chroma subsampling, so the two axes scale by slightly
        different factors and must be treated separately."""
        w, h = source
        nh = int(round(h * self.scale))
        nw = int(round(w * self.scale / 2)) * 2
        return nw, nh

    def axis_scale(self, source: tuple[int, int]) -> tuple[float, float]:
        nw, nh = self.frame_size(source)
        return nw / source[0], nh / source[1]

    def ffmpeg_filters(self, source_fps: float, source_size: tuple[int, int]) -> list[str]:
        filters = []
        if self.keep_every > 1:
            # Rebase timestamps so the kept frames play at the reduced rate
            # rather than leaving gaps the muxer would fill by duplication.
            filters.append(f"select='not(mod(n\\,{self.keep_every}))'")
            filters.append(f"setpts=N/({source_fps / self.keep_every}*TB)")
        if self.scale != 1.0:
            nw, nh = self.frame_size(source_size)
            filters.append(f"scale={nw}:{nh}:flags=lanczos")
        return filters

    def stem_for(self, source_stem: str) -> str:
        return f"{source_stem}{STEM_MARKER}{self.name}"


# Heavy compression at 40 is well past where broadcast encoders sit; the
# ball's edges and hue are what it takes first, which is where the release
# gate looks.
CONDITIONS = {
    "480p": Condition("480p", scale=480 / 1080,
                      description="downscaled to 480 rows, same encode quality"),
    "crf40": Condition("crf40", crf=40,
                       description="re-encoded at x264 CRF 40 (source was 16)"),
    "drop2": Condition("drop2", keep_every=2,
                       description="every second frame dropped, 12.5 fps"),
}


def tolerance_for(tolerance_frames: int, condition: Condition) -> int:
    """The evaluation tolerance in the degraded clip's frames.

    The plan states the tolerance as a duration (±0.25 s); keeping the frame
    count fixed on a half-rate clip would double it in seconds.
    """
    return max(1, int(round(tolerance_frames * condition.fps_factor)))


# -- generic remapping ---------------------------------------------------------
# Label, set and review files nest frames and boxes several levels deep under
# a handful of consistent key names; one walk covers them all rather than a
# hand-written list per schema that would drift as the schemas do.

def _is_box(value: Any) -> bool:
    return isinstance(value, dict) and set(value) >= {"x1", "y1", "x2", "y2"}


def remap(data: Any, frame_map: Callable[[int], int], scale: tuple[float, float]) -> Any:
    sx, sy = scale

    def walk(node: Any, key: str | None) -> Any:
        if isinstance(node, dict):
            if _is_box(node):
                return {**node, "x1": round(node["x1"] * sx, 1), "x2": round(node["x2"] * sx, 1),
                        "y1": round(node["y1"] * sy, 1), "y2": round(node["y2"] * sy, 1)}
            return {k: walk(v, k) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v, key) for v in node]
        if key is not None and (key == "frame" or key.endswith("_frame")) \
                and isinstance(node, int) and not isinstance(node, bool):
            return frame_map(node)
        return node

    return walk(data, None)


# -- per-file derivations ------------------------------------------------------

def derive_labels(source: dict, condition: Condition, stem: str) -> dict:
    scale = condition.axis_scale((source["width"], source["height"]))
    out = remap(source, condition.frame_map(), scale)
    nw, nh = condition.frame_size((source["width"], source["height"]))
    out.update(video=f"{stem}.mp4", width=nw, height=nh,
               fps=source["fps"] * condition.fps_factor,
               derived={"from": source["video"], "condition": condition.name})
    return out


def derive_sets(source: dict, condition: Condition, stem: str, clip_sha256: str,
                pose_run: str, frame_count: int) -> dict:
    """The set starts, carried over; any end is dropped so the set-end stage
    recomputes it from the degraded clip's own roster."""
    out = remap(source, condition.frame_map(), (1.0, 1.0))
    fps = source["fps"] * condition.fps_factor
    for s in out["sets"]:
        s.pop("end", None)
        if s.get("start_frame") is not None:
            s["start_s"] = round(s["start_frame"] / fps, 2)
    out.update(video=f"{stem}.mp4", clip_sha256=clip_sha256, pose_run=pose_run, fps=fps,
               frame_count=frame_count,
               derived={"from": source["video"], "condition": condition.name})
    return out


def derive_court(source: dict, condition: Condition, stem: str, clip_sha256: str) -> dict:
    """The homography under a change of image size.

    Scaling the picture by S = diag(sx, sy, 1) composes with the fit:
    image' -> court is H · S⁻¹, court -> image' is S · H⁻¹. Every stored
    pixel quantity (corners, cross-line rows, horizon) scales the same way.
    """
    sx, sy = condition.axis_scale(tuple(source["frame_size"]))
    S = np.diag([sx, sy, 1.0])
    S_inv = np.diag([1 / sx, 1 / sy, 1.0])
    i2c = np.array(source["image_to_court"], float) @ S_inv
    c2i = S @ np.array(source["court_to_image"], float)
    out = dict(source)
    out.update(
        video=f"{stem}.mp4", clip_sha256=clip_sha256,
        frame_size=list(condition.frame_size(tuple(source["frame_size"]))),
        fps=source["fps"] * condition.fps_factor,
        image_to_court=i2c.tolist(), court_to_image=c2i.tolist(),
        horizon_y=round(source["horizon_y"] * sy, 2),
        corners_image=[[x * sx, y * sy] for x, y in source["corners_image"]],
        cross_lines=[{**c, "image_y": round(c["image_y"] * sy, 2)} for c in source["cross_lines"]],
        derived={"from": source["video"], "condition": condition.name, "scale": [sx, sy]},
    )
    return out


def read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def write_json(path: Path, data: dict, indent: int | None = 1) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=indent) + ("\n" if indent else ""))
    return path
