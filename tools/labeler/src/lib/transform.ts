// The one mapping between source pixels and the pixels on screen. Drawing and
// hit-testing both go through it, so a box can never be drawn somewhere the
// cursor cannot grab it — including under the magnifier, which is expressed as
// another transform of the same shape rather than as a separate drawing path.

export interface ViewTransform {
  imageWidth: number
  imageHeight: number
  viewWidth: number
  viewHeight: number
  /** Multiplier on top of the fit-to-view scale. */
  zoom: number
  panX: number
  panY: number
}

export interface Lens {
  x: number
  y: number
  radius: number
  scale: number
}

export const MIN_ZOOM = 1
export const MAX_ZOOM = 16
export const LENS_RADIUS = 110
// Far-court players are roughly a third the height of near-court ones, so the
// lens has to make up that difference for a box to be adjustable at the same
// honesty as a near-court one.
export const LENS_SCALE = 3

export function createTransform(
  imageWidth: number, imageHeight: number, viewWidth: number, viewHeight: number,
): ViewTransform {
  return { imageWidth, imageHeight, viewWidth, viewHeight, zoom: 1, panX: 0, panY: 0 }
}

/** Scale at which the whole image just fits the view — the zoom = 1 baseline. */
export function fitScale(t: ViewTransform): number {
  if (!t.imageWidth || !t.imageHeight) return 1
  return Math.min(t.viewWidth / t.imageWidth, t.viewHeight / t.imageHeight)
}

export function scaleOf(t: ViewTransform): number {
  return fitScale(t) * t.zoom
}

export function toView(t: ViewTransform, x: number, y: number): [number, number] {
  const s = scaleOf(t)
  return [
    (x - t.imageWidth / 2) * s + t.viewWidth / 2 + t.panX,
    (y - t.imageHeight / 2) * s + t.viewHeight / 2 + t.panY,
  ]
}

export function toImage(t: ViewTransform, vx: number, vy: number): [number, number] {
  const s = scaleOf(t)
  return [
    (vx - t.viewWidth / 2 - t.panX) / s + t.imageWidth / 2,
    (vy - t.viewHeight / 2 - t.panY) / s + t.imageHeight / 2,
  ]
}

export function clampZoom(zoom: number): number {
  return Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, zoom))
}

/** Zoom keeping the source pixel under (vx, vy) exactly where it is. */
export function zoomAt(t: ViewTransform, vx: number, vy: number, factor: number): ViewTransform {
  const zoom = clampZoom(t.zoom * factor)
  if (zoom === t.zoom) return t
  const [ix, iy] = toImage(t, vx, vy)
  const next = { ...t, zoom, panX: 0, panY: 0 }
  const s = scaleOf(next)
  return {
    ...next,
    panX: vx - ((ix - t.imageWidth / 2) * s + t.viewWidth / 2),
    panY: vy - ((iy - t.imageHeight / 2) * s + t.viewHeight / 2),
  }
}

export function panBy(t: ViewTransform, dx: number, dy: number): ViewTransform {
  return { ...t, panX: t.panX + dx, panY: t.panY + dy }
}

export function resetView(t: ViewTransform): ViewTransform {
  return { ...t, zoom: 1, panX: 0, panY: 0 }
}

export function resize(t: ViewTransform, viewWidth: number, viewHeight: number): ViewTransform {
  return { ...t, viewWidth, viewHeight }
}

export function isInsideLens(lens: Lens, vx: number, vy: number): boolean {
  return Math.hypot(vx - lens.x, vy - lens.y) <= lens.radius
}

/**
 * The transform in force inside the magnifier: the same view scaled about the
 * lens centre, so the source pixel under the cursor does not move when the lens
 * opens and the annotator adjusts the box they were already looking at.
 */
export function lensTransform(t: ViewTransform, lens: Lens): ViewTransform {
  return zoomAt(t, lens.x, lens.y, lens.scale)
}

/**
 * The transform that governs a point on screen. Everything that converts between
 * screen and source — drawing the lens contents, hit-testing, dragging — asks
 * this rather than deciding for itself, which is what keeps the lens honest.
 */
export function transformAt(
  t: ViewTransform, lens: Lens | null, vx: number, vy: number,
): ViewTransform {
  if (lens && isInsideLens(lens, vx, vy)) return lensTransform(t, lens)
  return t
}
