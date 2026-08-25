import type { Box, CourtConfig, Team } from '../types'
import { boxAnchor } from './boxes'

export type Point = [number, number]

/** Apply a row-major 3x3 homography to a point. */
export function project(h: number[][], [x, y]: Point): Point {
  const w = h[2][0] * x + h[2][1] * y + h[2][2]
  if (w === 0) return [NaN, NaN]
  return [
    (h[0][0] * x + h[0][1] * y + h[0][2]) / w,
    (h[1][0] * x + h[1][1] * y + h[1][2]) / w,
  ]
}

/** Source pixels to court metres, origin at the near-left corner. */
export function imageToCourt(pt: Point, court: CourtConfig | null): Point | null {
  if (!court) return null
  const c = project(court.image_to_court, pt)
  return Number.isFinite(c[0]) && Number.isFinite(c[1]) ? c : null
}

/** Court metres back to source pixels. */
export function courtToImage(pt: Point, court: CourtConfig | null): Point | null {
  if (!court) return null
  const i = project(court.court_to_image, pt)
  return Number.isFinite(i[0]) && Number.isFinite(i[1]) ? i : null
}

// Slack on the boundary test, in metres. A foot point is quantised by detection
// noise and the painted lines have real width, so an exact test would flicker
// for a player standing on the line, and flicker reads downstream as a player
// leaving and returning. Pinned to the pipeline's BOUNDARY_SLACK_M by
// scripts/test_overlay_contract.py.
export const BOUNDARY_SLACK_M = 0.1

/**
 * In play if the foot point is inside the paint, give or take the boundary
 * slack.
 *
 * The calibration's `margin_m` band is deliberately not accepted here. That
 * band is the court-adjacent ring a player is *seen leaving through* — and it
 * is also exactly where the eliminated queue up and where the officials stand,
 * so admitting it put the whole sideline on the roster. Use `inMargin` when the
 * question is "on their way out", not "in play".
 */
export function isOnCourt(pt: Point, court: CourtConfig | null): boolean {
  const c = imageToCourt(pt, court)
  if (!c || !court) return false
  const s = BOUNDARY_SLACK_M
  const { width, length } = court.court_metres
  return c[0] >= -s && c[0] <= width + s && c[1] >= -s && c[1] <= length + s
}

/** Court-adjacent but out of play — the ring a crossing is observed in. */
export function inMargin(pt: Point, court: CourtConfig | null): boolean {
  const c = imageToCourt(pt, court)
  if (!c || !court) return false
  const m = court.margin_m
  const { width, length } = court.court_metres
  const near = c[0] >= -m && c[0] <= width + m && c[1] >= -m && c[1] <= length + m
  return near && !isOnCourt(pt, court)
}

/**
 * The camera is elevated and end-on, and the calibration puts the origin on the
 * near baseline, so a point's court y alone decides the half. This holds no
 * matter how the centre line slants in the picture.
 */
export function teamAtPoint(pt: Point, court: CourtConfig | null): Team | null {
  const c = imageToCourt(pt, court)
  if (!c || !court) return null
  return c[1] < court.centre_line_m ? 'near' : 'far'
}

export function inferTeam(box: Box, court: CourtConfig | null): Team | null {
  return teamAtPoint(boxAnchor(box), court)
}

/** A calibration is only usable if both homographies and the court size are present. */
export function isUsableCourt(court: Partial<CourtConfig> | null): court is CourtConfig {
  const square = (h: unknown) =>
    Array.isArray(h) && h.length === 3 && h.every((r) => Array.isArray(r) && r.length === 3)
  return !!court
    && square(court.image_to_court) && square(court.court_to_image)
    && typeof court.centre_line_m === 'number'
    && typeof court.margin_m === 'number'
    && !!court.court_metres
}
