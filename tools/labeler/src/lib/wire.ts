import type { Team } from '../types'

// COCO-17 limbs and torso. The face keypoints are dropped: at far-court scale
// they are a smudge, and the arm chain is what a wind-up is read from.
export const SKELETON: [number, number][] = [
  [5, 7], [7, 9], [6, 8], [8, 10], [5, 6], [5, 11], [6, 12], [11, 12],
  [11, 13], [13, 15], [12, 14], [14, 16],
]

export const KEYPOINT_MIN_CONF = 0.3

export const WIRE_TOKEN: Record<Team, string> = {
  near: '--wire-near',
  far: '--wire-far',
}

// Relative luminance above which a wire takes the dark casing. Placed between
// the two wires rather than at mid-grey, so each takes the casing that actually
// opposes it.
export const CASING_PIVOT = 0.25

/** Relative luminance of a #rrggbb colour, WCAG 2.x definition. */
export function luminance(colour: string): number {
  const m = /^#?([0-9a-f]{6})$/i.exec(colour.trim())
  if (!m) return 0
  const n = parseInt(m[1], 16)
  const channel = (v: number) => {
    const c = v / 255
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
  }
  return 0.2126 * channel((n >> 16) & 255)
    + 0.7152 * channel((n >> 8) & 255)
    + 0.0722 * channel(n & 255)
}

/**
 * The casing token to draw under a wire.
 *
 * A skeleton crosses a jersey, black shorts and pale floor within one limb, so
 * no single wire colour is legible over all of it. The casing is what makes it
 * legible, which means the wire's hue never has to be chosen for contrast and
 * is free to carry team alone. Taking the casing from the *wire* rather than
 * from the kit is what keeps that true when the teams swap ends, or when a clip
 * has two dark kits and there is no light one to oppose.
 */
export function casingToken(wire: string): string {
  return luminance(wire) > CASING_PIVOT ? '--wire-casing-dark' : '--wire-casing-light'
}
