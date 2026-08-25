import type { Box, PoseDetection, PoseManifest, PoseRunRef, PlacedBox } from '../types'
import { toView, type ViewTransform } from './transform'

// Corner handles are grabbed in screen space, so a far-court box stays as easy
// to adjust as a near-court one once the magnifier is open.
export const HANDLE_HIT_PX = 9
export const HANDLE_DRAW_PX = 4
// A box with no area cannot be hit again, so a resize refuses to collapse one.
export const MIN_BOX_PX = 2

/** Corner order: 0 top-left, 1 top-right, 2 bottom-right, 3 bottom-left. */
export type Corner = 0 | 1 | 2 | 3

export type BoxHit =
  | { kind: 'corner'; corner: Corner }
  | { kind: 'body' }
  | { kind: 'empty' }

export function makeBox(ax: number, ay: number, bx: number, by: number): Box {
  return {
    x1: Math.min(ax, bx),
    y1: Math.min(ay, by),
    x2: Math.max(ax, bx),
    y2: Math.max(ay, by),
  }
}

export function boxWidth(b: Box): number {
  return b.x2 - b.x1
}

export function boxHeight(b: Box): number {
  return b.y2 - b.y1
}

/** Bottom centre — the feet. The point that says which half of the court a
 *  player is standing in, unlike the box centre, which drifts up on a jump. */
export function boxAnchor(b: Box): [number, number] {
  return [(b.x1 + b.x2) / 2, b.y2]
}

// COCO-17 indices. The pose manifest records the layout so this never has to be
// assumed; these are the two it is read from.
const LEFT_ANKLE = 15
const RIGHT_ANKLE = 16

// Below this an ankle keypoint is a guess, and a guessed ankle places a player
// somewhere they are not. The box is a worse estimator but a more honest one.
export const ANKLE_MIN_CONF = 0.3

/**
 * Where a detected person meets the floor.
 *
 * `boxAnchor` is only the feet for someone standing. Players dive and lie prone
 * constantly — most of all at the centre line, where they lunge for balls — and
 * for those the box bottom is wherever the body happens to end, which places
 * them metres from where they are. Ankle keypoints survive that; the box is the
 * fallback for when neither ankle is visible at all.
 *
 * `foot_point` in src/court.py is the same function on the pipeline side, and
 * scripts/test_overlay_contract.py holds the two thresholds together.
 */
export function footPoint(det: PoseDetection): [number, number] {
  const kpts = det.kpts ?? []
  const ankles = [kpts[LEFT_ANKLE], kpts[RIGHT_ANKLE]]
    .filter((a): a is [number, number, number] => !!a && a[2] >= ANKLE_MIN_CONF)
  if (ankles.length > 0) {
    return [
      ankles.reduce((t, a) => t + a[0], 0) / ankles.length,
      ankles.reduce((t, a) => t + a[1], 0) / ankles.length,
    ]
  }
  const [x1, , x2, y2] = det.box
  return [(x1 + x2) / 2, y2]
}

export function cornerPoints(b: Box): [number, number][] {
  return [[b.x1, b.y1], [b.x2, b.y1], [b.x2, b.y2], [b.x1, b.y2]]
}

export function hitTestBox(b: Box, t: ViewTransform, vx: number, vy: number): BoxHit {
  const corners = cornerPoints(b).map(([x, y]) => toView(t, x, y))
  for (let i = 0; i < corners.length; i++) {
    if (Math.hypot(vx - corners[i][0], vy - corners[i][1]) <= HANDLE_HIT_PX) {
      return { kind: 'corner', corner: i as Corner }
    }
  }
  const [x1, y1] = toView(t, b.x1, b.y1)
  const [x2, y2] = toView(t, b.x2, b.y2)
  if (vx >= x1 && vx <= x2 && vy >= y1 && vy <= y2) return { kind: 'body' }
  return { kind: 'empty' }
}

/** Resize with the opposite corner anchored. Dragging past the anchor flips the
 *  box, so the corner being held is reported back rather than assumed. */
export function resizeBox(
  b: Box, corner: Corner, ix: number, iy: number,
): { box: Box; corner: Corner } {
  const [ax, ay] = cornerPoints(b)[(corner + 2) % 4]
  const dx = ix >= ax ? Math.max(ix, ax + MIN_BOX_PX) : Math.min(ix, ax - MIN_BOX_PX)
  const dy = iy >= ay ? Math.max(iy, ay + MIN_BOX_PX) : Math.min(iy, ay - MIN_BOX_PX)
  const box = makeBox(ax, ay, dx, dy)
  const left = dx === box.x1
  const top = dy === box.y1
  const next: Corner = top ? (left ? 0 : 1) : left ? 3 : 2
  return { box, corner: next }
}

export function translateBox(b: Box, dx: number, dy: number): Box {
  return { x1: b.x1 + dx, y1: b.y1 + dy, x2: b.x2 + dx, y2: b.y2 + dy }
}

/** Slide the box back inside the frame without changing its size. A box larger
 *  than the frame keeps its size and pins to the top-left, because shrinking one
 *  would silently edit a label the annotator only meant to move. */
export function clampBox(b: Box, width: number, height: number): Box {
  let dx = Math.min(0, width - b.x2)
  let dy = Math.min(0, height - b.y2)
  dx += Math.max(0, -(b.x1 + dx))
  dy += Math.max(0, -(b.y1 + dy))
  return translateBox(b, dx, dy)
}

export function nudgeBox(b: Box, dx: number, dy: number, width: number, height: number): Box {
  return clampBox(translateBox(b, dx, dy), width, height)
}

export function cursorForHit(hit: BoxHit): string {
  if (hit.kind === 'body') return 'move'
  if (hit.kind === 'empty') return 'crosshair'
  return hit.corner === 0 || hit.corner === 2 ? 'nwse-resize' : 'nesw-resize'
}

export function poseRunRef(manifest: PoseManifest): PoseRunRef {
  return {
    run_id: manifest.run_id,
    model: manifest.model,
    weights_sha256: manifest.weights_sha256,
    imgsz: manifest.imgsz,
  }
}

/**
 * Copy a detection's box into a label. The four numbers are read out here and
 * nothing about the detection travels with them, so re-running the detector
 * cannot change what an existing label means.
 */
export function snapToDetection(
  det: PoseDetection, frame: number, manifest: PoseManifest | null,
): PlacedBox {
  const [x1, y1, x2, y2] = det.box
  return {
    box: makeBox(x1, y1, x2, y2),
    frame,
    source: 'snapped',
    adjusted: false,
    pose_run: manifest ? poseRunRef(manifest) : null,
  }
}

export function drawnBox(box: Box, frame: number, manifest: PoseManifest | null): PlacedBox {
  return {
    box,
    frame,
    source: 'drawn',
    adjusted: false,
    pose_run: manifest ? poseRunRef(manifest) : null,
  }
}

/** Every edit after placement marks the box adjusted — that flag is what
 *  separates a box the annotator accepted from one they took responsibility for. */
export function withBox(placed: PlacedBox, box: Box): PlacedBox {
  return { ...placed, box, adjusted: true }
}
