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

// Slack on the boundary test, as a budget of ankle-keypoint error in pixels.
//
// A foot point is quantised by detection noise and the painted lines have real
// width, so an exact test would flicker for a player standing on the line, and
// flicker reads downstream as a player leaving and returning. A flat slack in
// metres could not do it: the camera is end-on, so a metre along the court costs
// several times fewer pixels at the far baseline than at the near one, and a
// tolerance that was comfortable near the camera was under the keypoint's own
// wobble at the far end. Spending it in pixels puts it where the pixels are
// scarce. Pinned to the pipeline's ANKLE_SLACK_PX by
// scripts/test_overlay_contract.py.
export const ANKLE_SLACK_PX = 8

// A ceiling on what that budget can buy, for a point projecting near the horizon
// where metres-per-pixel runs away. Kept well inside the calibration's margin
// band so the in-play test cannot reach the ring that means court-adjacent.
export const MAX_BOUNDARY_SLACK_M = 0.75

/**
 * The boundary slack in metres at an image point, measured where it is spent:
 * one image row up from the point, in court metres.
 */
export function slackAt(pt: Point, court: CourtConfig | null): number {
  const here = imageToCourt(pt, court)
  const up = imageToCourt([pt[0], pt[1] - 1], court)
  if (!here || !up) return NaN
  return Math.min(ANKLE_SLACK_PX * Math.abs(up[1] - here[1]), MAX_BOUNDARY_SLACK_M)
}

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
  // A NaN slack fails every comparison, which puts a point projecting through
  // the horizon off court rather than everywhere at once.
  const s = slackAt(pt, court)
  const { width, length } = court.court_metres
  return c[0] >= -s && c[0] <= width + s && c[1] >= -s && c[1] <= length + s
}

// How far either side of a frame a player is still counted as in play, having
// been seen on court there. Pinned to the pipeline's IN_PLAY_HOLD_FRAMES by
// scripts/test_overlay_contract.py.
//
// Symmetric rather than a timeout, deliberately. A causal "still counts for a
// second after they were last seen" rule makes in-play depend on the direction
// the clip was played, so the same frame would show a different roster depending
// on whether the annotator scrubbed forwards or backwards onto it. What is drawn
// on a frame has to be a function of that frame and nothing else.
export const IN_PLAY_HOLD_FRAMES = 25

// How close a nearby frame's on-court player must be to count as the same person.
//
// The tool has no tracks - it recomputes everything per frame on purpose - so it
// approximates identity by proximity, where the pipeline uses ByteTrack. That is
// sound for the case the hold exists to fix: a player flickering at the baseline
// is standing still. A player who covers more than this in a second is sprinting
// through mid-court, where the boundary is not in question.
export const HOLD_RADIUS_M = 1.5

/** Whether a point counts as in play, given where players were on nearby frames.
 *
 * A player standing on the baseline crosses it constantly - reaching, turning, or
 * simply being detected a few centimetres further back - and each crossing reads
 * as a departure and a return. Stepping out for a moment is not leaving the game.
 */
export function heldOnCourt(
  pt: Point, court: CourtConfig | null, nearby: Point[],
): boolean {
  if (isOnCourt(pt, court)) return true
  const here = imageToCourt(pt, court)
  if (!here) return false
  return nearby.some((other) => Math.hypot(other[0] - here[0], other[1] - here[1])
    <= HOLD_RADIUS_M)
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
