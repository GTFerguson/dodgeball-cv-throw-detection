import { describe, expect, it } from 'vitest'
import {
  createTransform, isInsideLens, lensTransform, panBy, resetView, scaleOf,
  toImage, toView, transformAt, zoomAt, type Lens,
} from './transform'

const base = createTransform(1920, 1080, 1200, 700)
const lens: Lens = { x: 400, y: 300, radius: 110, scale: 3 }

const points: [number, number][] = [[0, 0], [1920, 1080], [960, 540], [137.5, 902.25]]

describe('image and screen round-trip', () => {
  it('round-trips at rest', () => {
    for (const [x, y] of points) {
      const [vx, vy] = toView(base, x, y)
      const [ix, iy] = toImage(base, vx, vy)
      expect(ix).toBeCloseTo(x, 6)
      expect(iy).toBeCloseTo(y, 6)
    }
  })

  it('round-trips under zoom and pan', () => {
    const t = panBy(zoomAt(base, 500, 200, 4), -137, 62)
    for (const [x, y] of points) {
      const [vx, vy] = toView(t, x, y)
      const [ix, iy] = toImage(t, vx, vy)
      expect(ix).toBeCloseTo(x, 6)
      expect(iy).toBeCloseTo(y, 6)
    }
  })

  it('centres the image when it is at rest', () => {
    expect(toView(base, 960, 540)).toEqual([600, 350])
  })

  it('fits the image inside the view', () => {
    expect(scaleOf(base)).toBeCloseTo(1200 / 1920, 6)
  })
})

describe('zooming', () => {
  it('keeps the source pixel under the cursor in place', () => {
    const before = toImage(base, 812, 455)
    const after = toImage(zoomAt(base, 812, 455, 3.7), 812, 455)
    expect(after[0]).toBeCloseTo(before[0], 6)
    expect(after[1]).toBeCloseTo(before[1], 6)
  })

  it('clamps and stops rather than drifting once clamped', () => {
    let t = base
    for (let i = 0; i < 40; i++) t = zoomAt(t, 100, 100, 2)
    expect(t.zoom).toBe(16)
    expect(zoomAt(t, 500, 500, 2)).toBe(t)
  })

  it('never zooms below the fit scale', () => {
    expect(zoomAt(base, 100, 100, 0.01).zoom).toBe(1)
  })

  it('resets to a centred, unzoomed view', () => {
    const t = resetView(panBy(zoomAt(base, 300, 300, 5), 40, 40))
    expect(t).toEqual(base)
  })
})

describe('magnifier', () => {
  it('is the same transform, scaled about the lens centre', () => {
    const lt = lensTransform(base, lens)
    expect(lt.zoom).toBeCloseTo(base.zoom * lens.scale, 6)
    const before = toImage(base, lens.x, lens.y)
    const after = toImage(lt, lens.x, lens.y)
    expect(after[0]).toBeCloseTo(before[0], 6)
    expect(after[1]).toBeCloseTo(before[1], 6)
  })

  it('governs points inside the lens and only those', () => {
    expect(isInsideLens(lens, 400, 300)).toBe(true)
    expect(isInsideLens(lens, 400, 411)).toBe(false)
    expect(transformAt(base, lens, 405, 305)).not.toBe(base)
    expect(transformAt(base, lens, 900, 600)).toBe(base)
    expect(transformAt(base, null, 400, 300)).toBe(base)
  })

  it('resolves a screen point the same way for drawing and for hit-testing', () => {
    const at = transformAt(base, lens, 430, 320)
    const [ix, iy] = toImage(at, 430, 320)
    expect(toView(at, ix, iy)[0]).toBeCloseTo(430, 6)
    expect(toView(at, ix, iy)[1]).toBeCloseTo(320, 6)
  })
})
