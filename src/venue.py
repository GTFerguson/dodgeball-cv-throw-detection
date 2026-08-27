"""The venue and footage assumptions, from ``config/venue.toml``.

The ball's colour and the court's dimensions are facts about one venue and
one match ball, not about dodgeball. They live in one file so that a second
venue is a config change rather than a hunt through the modules, and so the
write-up can point at exactly what would have to change. Everything that is
a tuning of the algorithms - chain slack, hold durations, score floors -
stays a named constant beside the code that owns it.

The file is optional: every key has the value the pipeline shipped with, so
a checkout without it behaves identically.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
VENUE_FILE = REPO_ROOT / "config" / "venue.toml"

DEFAULTS: dict[str, dict[str, Any]] = {
    "ball": {"hsv_lo": [9, 120, 90], "hsv_hi": [22, 255, 255]},
    "court": {"width_m": 9.0, "length_m": 18.0, "margin_m": 1.5},
    "teams": {"kits": ["red", "white", "black"], "official_kit": "black"},
}


def load(path: Path = VENUE_FILE) -> dict[str, dict[str, Any]]:
    """The config with every default filled in; unknown keys are refused so a
    typo cannot silently leave a default in place."""
    data = tomllib.loads(path.read_text()) if path.exists() else {}
    out: dict[str, dict[str, Any]] = {}
    for section, defaults in DEFAULTS.items():
        given = data.get(section, {})
        unknown = set(given) - set(defaults)
        if unknown:
            raise ValueError(f"{path}: unknown key(s) in [{section}]: {sorted(unknown)}")
        out[section] = {**defaults, **given}
    unknown = set(data) - set(DEFAULTS)
    if unknown:
        raise ValueError(f"{path}: unknown section(s): {sorted(unknown)}")
    return out


VENUE = load()
