"""The overlay palette, shared by the labelling tool and the diagnostic render.

Team is data, so the wire colour carries it. The casing drawn under a wire is
the wire's tonal opposite rather than the kit's, which is what lets the hue mean
"team" and only "team": a light wire on a dark casing stays legible over a dark
jersey, black shorts and pale floor alike, so the pairing survives the teams
swapping ends and a clip whose two kits are both dark.

The hues are 107 degrees apart, but hue is not what carries the distinction --
under deuteranopia both collapse towards blue. What separates them there is the
lightness gap, which is why the pair is a light teal against a dark violet
rather than two colours of equal weight.

The tool's copy of these values lives in ``tools/labeler/src/index.css``, where
Tailwind and the canvas both read them. ``scripts/test_overlay_contract.py``
holds the two in step.
"""

from __future__ import annotations

# Complement of the near team's red kit, lifted until it clears the far wire in
# lightness as well as hue.
WIRE_NEAR = "#3AD9C8"

# Not a complement of the far kit: at this distance it measures S 0.13, and the
# complement of an almost-grey is another almost-grey. This is chosen instead as
# the near wire's harmonic partner, darkened for the lightness gap.
WIRE_FAR = "#7A3CB8"

WIRE_CASING_DARK = "#1C1A1E"
WIRE_CASING_LIGHT = "#FAF9F6"

# Detections the court test puts out of play. Deliberately the only achromatic
# mark on a body: out of play is the absence of a team, not a third team.
WIRE_OFF = "#6D6C72"

# Relative luminance above which a wire takes the dark casing. Placed between
# the two wires rather than at mid-grey, so each takes the casing that actually
# opposes it.
CASING_PIVOT = 0.25


def rgb(colour: str) -> tuple[int, int, int]:
    h = colour.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def bgr(colour: str) -> tuple[int, int, int]:
    """OpenCV's channel order."""
    r, g, b = rgb(colour)
    return b, g, r


def luminance(colour: str) -> float:
    """Relative luminance, WCAG 2.x definition."""
    def channel(v: float) -> float:
        v /= 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(v) for v in rgb(colour))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def casing_for(wire: str) -> str:
    return WIRE_CASING_DARK if luminance(wire) > CASING_PIVOT else WIRE_CASING_LIGHT


def wire_for(half: str) -> str:
    """The wire colour for a court half, as ``Court.half`` reports it."""
    return WIRE_NEAR if half == "near" else WIRE_FAR
