import { describe, expect, it } from 'vitest'
import type { PoseDetection, PoseManifest } from '../types'
import {
  boxAnchor, clampBox, cursorForHit, hitTestBox, makeBox, nudgeBox, resizeBox,
  snapToDetection, translateBox, withBox,
} from './boxes'
import { createTransform, toView } from './transform'

const t = createTransform(1920, 1080, 1200, 700)
const box = makeBox(800, 400, 900, 700)

const at = (x: number, y: number) => toView(t, x, y)

describe('construction', () => {
  it('normalises corners whichever way it is dragged', () => {
    expect(makeBox(900, 700, 800, 400)).toEqual(makeBox(800, 400, 900, 700))
  })

  it('anchors on the feet, not the centre', () => {
    expect(boxAnchor(box)).toEqual([850, 700])
  })
})

describe('hit-testing', () => {
  it('finds each corner handle', () => {
    const corners: [number, number][] = [[800, 400], [900, 400], [900, 700], [800, 700]]
    corners.forEach(([x, y], i) => {
      const [vx, vy] = at(x, y)
      expect(hitTestBox(box, t, vx, vy)).toEqual({ kind: 'corner', corner: i })
    })
  })

  it('prefers a corner over the body where they overlap', () => {
    const [vx, vy] = at(800, 400)
    expect(hitTestBox(box, t, vx + 2, vy + 2)).toEqual({ kind: 'corner', corner: 0 })
  })

  it('finds the body', () => {
    const [vx, vy] = at(850, 550)
    expect(hitTestBox(box, t, vx, vy)).toEqual({ kind: 'body' })
  })

  it('reports empty space outside the box', () => {
    const [vx, vy] = at(400, 200)
    expect(hitTestBox(box, t, vx, vy)).toEqual({ kind: 'empty' })
  })

  it('shows what a click would grab', () => {
    expect(cursorForHit({ kind: 'corner', corner: 0 })).toBe('nwse-resize')
    expect(cursorForHit({ kind: 'corner', corner: 1 })).toBe('nesw-resize')
    expect(cursorForHit({ kind: 'body' })).toBe('move')
    expect(cursorForHit({ kind: 'empty' })).toBe('crosshair')
  })
})

describe('editing', () => {
  it('anchors the opposite corner on a resize', () => {
    const { box: next } = resizeBox(box, 0, 820, 450)
    expect(next).toEqual(makeBox(820, 450, 900, 700))
  })

  it('reports the corner still under the cursor when the drag flips the box', () => {
    const { box: next, corner } = resizeBox(box, 0, 980, 900)
    expect(next).toEqual(makeBox(900, 700, 980, 900))
    expect(corner).toBe(2)
  })

  it('refuses to collapse a box to nothing', () => {
    const { box: next } = resizeBox(box, 0, 900, 700)
    expect(next.x2 - next.x1).toBeGreaterThan(0)
    expect(next.y2 - next.y1).toBeGreaterThan(0)
  })

  it('moves without resizing', () => {
    const moved = translateBox(box, 10, -20)
    expect(moved).toEqual(makeBox(810, 380, 910, 680))
  })

  it('clamps a nudge to the frame', () => {
    const edge = makeBox(0, 0, 50, 50)
    expect(nudgeBox(edge, -10, -10, 1920, 1080)).toEqual(edge)
    const far = makeBox(1870, 1030, 1920, 1080)
    expect(nudgeBox(far, 10, 10, 1920, 1080)).toEqual(far)
  })

  it('keeps a nudge inside the frame from anywhere', () => {
    const n = nudgeBox(makeBox(5, 5, 55, 55), -10, -10, 1920, 1080)
    expect(n).toEqual(makeBox(0, 0, 50, 50))
  })

  it('pins a box larger than the frame rather than shrinking it', () => {
    const huge = makeBox(-100, -100, 2100, 1200)
    const pinned = clampBox(huge, 1920, 1080)
    expect(pinned).toEqual(makeBox(0, 0, 2200, 1300))
  })
})

describe('boxes are stored by value', () => {
  const manifest = {
    run_id: 'r1', model: 'm.pt', weights_sha256: 'abc', imgsz: 1920,
  } as PoseManifest

  const detection = (): PoseDetection => ({ box: [10, 20, 30, 40], conf: 0.9, kpts: [] })

  it('copies the numbers out of the detection', () => {
    const det = detection()
    const placed = snapToDetection(det, 42, manifest)
    det.box[0] = 999
    expect(placed.box).toEqual(makeBox(10, 20, 30, 40))
  })

  it('records where the box came from and the run that suggested it', () => {
    const placed = snapToDetection(detection(), 42, manifest)
    expect(placed).toMatchObject({
      frame: 42,
      source: 'snapped',
      adjusted: false,
      pose_run: { run_id: 'r1', model: 'm.pt', weights_sha256: 'abc', imgsz: 1920 },
    })
  })

  it('marks a box adjusted once the annotator moves it', () => {
    const placed = snapToDetection(detection(), 42, manifest)
    expect(withBox(placed, translateBox(placed.box, 1, 0)).adjusted).toBe(true)
  })

  it('places a box with no pose run on screen', () => {
    expect(snapToDetection(detection(), 42, null).pose_run).toBeNull()
  })
})
