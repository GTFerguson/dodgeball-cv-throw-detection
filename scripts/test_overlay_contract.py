#!/usr/bin/env python
"""Hold the tool's copy of the overlay contract level with the pipeline's.

The labelling tool is TypeScript reading CSS custom properties and the pipeline
is Python, so the values they share cannot live in one place at runtime. They
are therefore declared twice and pinned here.

This is not a style check. The bug this exists to prevent has already happened
once: the tool tested "on court" against the calibration's 1.5 m margin band
while the pipeline tested against a 0.10 m boundary slack, so the tool put
roughly twenty-two people per frame on the roster where the pipeline put nine —
the whole eliminated queue, the officials and the front row of the crowd. Both
were self-consistent and neither was obviously wrong on its own. Only a
comparison catches that, so the comparison is a test.

Run with ``.venv/bin/python scripts/test_overlay_contract.py``.
"""

from __future__ import annotations

import itertools
import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

import overlay  # noqa: E402
from court import (ANKLE_MIN_CONF, ANKLE_SLACK_PX,  # noqa: E402
                   IN_PLAY_HOLD_FRAMES, MAX_BOUNDARY_SLACK_M)

LABELER = REPO_ROOT / "tools" / "labeler" / "src"
CSS = LABELER / "index.css"
COURT_TS = LABELER / "lib" / "court.ts"
BOXES_TS = LABELER / "lib" / "boxes.ts"
WIRE_TS = LABELER / "lib" / "wire.ts"


def css_token(name: str) -> str:
    """The value of a CSS custom property declared on :root."""
    m = re.search(rf"^\s*{re.escape(name)}:\s*(#[0-9A-Fa-f]{{6}})\s*;", CSS.read_text(), re.M)
    if not m:
        raise AssertionError(f"{name} is not declared in {CSS.relative_to(REPO_ROOT)}")
    return m.group(1).upper()


def ts_number(path: Path, name: str) -> float:
    """The value of an exported numeric constant."""
    m = re.search(rf"export const {re.escape(name)}\s*=\s*([0-9.]+)", path.read_text())
    if not m:
        raise AssertionError(f"{name} is not exported from {path.relative_to(REPO_ROOT)}")
    return float(m.group(1))


class TestCourtThresholds(unittest.TestCase):
    """The numbers that decide who is in play."""

    def test_boundary_slack_matches(self):
        self.assertAlmostEqual(ts_number(COURT_TS, "ANKLE_SLACK_PX"), ANKLE_SLACK_PX)
        self.assertAlmostEqual(ts_number(COURT_TS, "MAX_BOUNDARY_SLACK_M"),
                               MAX_BOUNDARY_SLACK_M)

    def test_the_in_play_hold_matches(self):
        """Both sides hold a player in play for the same window.

        The tool approximates identity by proximity where the pipeline has
        ByteTrack, so the two cannot share an implementation - which makes it all
        the more important that they share the window. A tool that forgave a
        two-second excursion the pipeline counted as an exit would be showing the
        annotator a different match from the one being measured.
        """
        self.assertAlmostEqual(ts_number(COURT_TS, "IN_PLAY_HOLD_FRAMES"),
                               IN_PLAY_HOLD_FRAMES)

    def test_ankle_confidence_floor_matches(self):
        self.assertAlmostEqual(ts_number(BOXES_TS, "ANKLE_MIN_CONF"), ANKLE_MIN_CONF)

    def test_the_tool_does_not_test_on_court_against_the_margin(self):
        """The specific regression: `margin_m` must not reach the in-play test.

        `inMargin` is allowed it — that is what the band is for — so this pins
        the boundary test itself rather than the file as a whole.
        """
        body = re.search(r"export function isOnCourt\b.*?\n}", COURT_TS.read_text(), re.S)
        self.assertIsNotNone(body, "isOnCourt is no longer a standalone function")
        self.assertNotIn("margin_m", body.group(0))


class TestWirePalette(unittest.TestCase):
    """The colours, and the property that makes the pair legible."""

    def test_wire_colours_match(self):
        for token, value in (("--wire-near", overlay.WIRE_NEAR),
                             ("--wire-far", overlay.WIRE_FAR),
                             ("--wire-casing-dark", overlay.WIRE_CASING_DARK),
                             ("--wire-casing-light", overlay.WIRE_CASING_LIGHT),
                             ("--wire-off", overlay.WIRE_OFF)):
            with self.subTest(token=token):
                self.assertEqual(css_token(token), value.upper())

    def test_casing_pivot_matches(self):
        self.assertAlmostEqual(ts_number(WIRE_TS, "CASING_PIVOT"), overlay.CASING_PIVOT)

    def test_each_wire_takes_the_casing_that_opposes_it(self):
        self.assertEqual(overlay.casing_for(overlay.WIRE_NEAR), overlay.WIRE_CASING_DARK)
        self.assertEqual(overlay.casing_for(overlay.WIRE_FAR), overlay.WIRE_CASING_LIGHT)

    def test_the_two_wires_are_told_apart_by_lightness_not_only_hue(self):
        """Hue alone does not survive deuteranopia — both wires collapse to blue.

        A contrast ratio this far above 1 means the pair is still separable in
        greyscale, which is the property that holds under every deficiency at
        once. 3:1 is the floor for non-text marks in WCAG 2.1.
        """
        a, b = overlay.luminance(overlay.WIRE_NEAR), overlay.luminance(overlay.WIRE_FAR)
        ratio = (max(a, b) + 0.05) / (min(a, b) + 0.05)
        self.assertGreater(ratio, 3.0)

    def test_no_wire_crowds_an_outcome_colour(self):
        """A wire says which team; a --sig- token says what happened.

        Both are drawn on the frame, so a wire that reads as an outcome costs
        more than the coding buys. The bar is derived rather than chosen: the
        signal palette already ships six colours an annotator distinguishes in
        practice, so a wire no closer to any of them than the closest two are to
        each other is no harder to tell apart than what already works. Picking a
        round number instead put the bar above what the colour space can supply
        — no pair with a usable lightness gap clears dE 60 from all six.
        """
        sigs = {name: css_token(name) for name in
                ("--sig-hit", "--sig-catch", "--sig-block",
                 "--sig-miss", "--sig-open", "--sig-model")}
        floor = min(distance(a, b) for a, b in itertools.combinations(sigs.values(), 2))
        for wire in (overlay.WIRE_NEAR, overlay.WIRE_FAR):
            for name, sig in sigs.items():
                with self.subTest(wire=wire, sig=name):
                    self.assertGreater(distance(wire, sig), floor)


def distance(a: str, b: str) -> float:
    """CIE76 dE between two hex colours. Crude, but it ranks 'too close' fine."""
    def lab(colour):
        def channel(v):
            v /= 255
            return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
        r, g, bl = (channel(v) for v in overlay.rgb(colour))
        x = (0.4124 * r + 0.3576 * g + 0.1805 * bl) / 0.95047
        y = 0.2126 * r + 0.7152 * g + 0.0722 * bl
        z = (0.0193 * r + 0.1192 * g + 0.9505 * bl) / 1.08883
        f = lambda t: t ** (1 / 3) if t > (6 / 29) ** 3 else t / (3 * (6 / 29) ** 2) + 4 / 29
        fx, fy, fz = f(x), f(y), f(z)
        return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)
    return sum((p - q) ** 2 for p, q in zip(lab(a), lab(b))) ** 0.5


if __name__ == "__main__":
    unittest.main(verbosity=2)
