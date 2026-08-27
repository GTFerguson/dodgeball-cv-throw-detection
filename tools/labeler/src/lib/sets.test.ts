import { describe, expect, it } from 'vitest'
import type { DetectedEnd, DetectedSet, LivePlayInterval, SetTimelineFile } from '../types'
import {
  detectedLivePlay, detectedSetAt, detectionSummary, hasDetection, livePlayBadge, setIndexOf, setMarks,
} from './sets'

const confirmed = (start: number, armed: number): DetectedSet => ({
  status: 'confirmed',
  start_frame: start,
  start_s: start / 25,
  whistle_prominence_db: 37.4,
  sprint_frame: start + 23,
  first_ball_moves_frame: start + 59,
  armed: { start_frame: armed, end_frame: start + 60, max_balls: 6, max_spread_m: 8 },
  notes: [],
})

const layoutOnly = (armed: number): DetectedSet => ({
  status: 'no_whistle',
  start_frame: null,
  start_s: null,
  whistle_prominence_db: null,
  sprint_frame: null,
  first_ball_moves_frame: null,
  armed: { start_frame: armed, end_frame: armed + 300, max_balls: 6, max_spread_m: 8 },
  notes: ['balls laid out but no whistle before the layout broke or the clip ended'],
})

const timeline = (...sets: DetectedSet[]): SetTimelineFile => ({
  schema_version: 1,
  video: 'clip.mp4',
  clip_sha256: 'abc',
  pose_run: 'run',
  fps: 25,
  frame_count: 5250,
  clip_offset_s: 360,
  thresholds: {},
  sets,
})

describe('marks', () => {
  it('puts a confirmed start on its whistle frame', () => {
    const [mark] = setMarks(timeline(confirmed(433, 135)))
    expect(mark).toMatchObject({ frame: 433, timed: true, status: 'confirmed' })
  })

  it('carries the annotator\'s verdict, so a judged claim is not redrawn as a fresh one', () => {
    const set = confirmed(433, 135)
    const review = {
      id: 'r1', armed_start_frame: 135, armed_end_frame: 493, detected_frame: 433,
      verdict: 'accepted' as const, interval_id: 'i1', reviewed: '2026-08-25T10:00:00.000Z',
    }
    expect(setMarks(timeline(set), [review])[0]).toMatchObject({ verdict: 'accepted' })
    expect(setMarks(timeline(set))[0].verdict).toBeNull()
    expect(setMarks(timeline(set))[0].label).toContain('not yet reviewed')
  })

  it('still marks a layout that never produced a start', () => {
    const [mark] = setMarks(timeline(layoutOnly(4920)))
    expect(mark).toMatchObject({ frame: 4920, timed: false, status: 'no_whistle' })
  })

  it('says which frame a mark is standing on', () => {
    const [start, layout] = setMarks(timeline(confirmed(433, 135), layoutOnly(4920)))
    expect(start.label).toContain('frame 433')
    expect(layout.label).toContain('no start detected')
  })

  it('draws nothing when there is no detection', () => {
    expect(setMarks(null)).toEqual([])
    expect(hasDetection(null)).toBe(false)
  })
})

describe('live play', () => {
  it('runs a set from its start to the next ball layout', () => {
    const [interval] = detectedLivePlay(timeline(confirmed(433, 135), layoutOnly(4920)))
    expect(interval).toMatchObject({ start_frame: 433, end_frame: 4920 })
  })

  it('leaves the last set open rather than inventing an end', () => {
    const [interval] = detectedLivePlay(timeline(confirmed(433, 135)))
    expect(interval.end_frame).toBeNull()
  })

  it('gives no interval to a layout that never started', () => {
    expect(detectedLivePlay(timeline(layoutOnly(4920)))).toEqual([])
  })

  it('numbers a set by its place in the timeline, whistle-less layouts included', () => {
    // The roster records played_sets by the same index, so a layout that never
    // started still takes a number: this confirmed set is set-1, not set-0.
    const sets = timeline(layoutOnly(50), confirmed(433, 135), layoutOnly(4920))
    const [interval] = detectedLivePlay(sets)
    expect(interval.id).toBe('detected-live-1')
    expect(setIndexOf(interval)).toBe(1)
    expect(setMarks(sets)[1].id).toBe('set-1')
    expect(detectedSetAt(sets, 1000)).toBe(1)
    expect(detectedSetAt(sets, 100)).toBeNull()
    expect(detectedSetAt(sets, 4921)).toBeNull()
    expect(detectedSetAt(null, 1000)).toBeNull()
  })
})

describe('a detected end', () => {
  const ended = (start: number, armed: number, end: Partial<DetectedEnd>): DetectedSet => ({
    ...confirmed(start, armed),
    end: {
      frame: 4660, end_s: 186.4, source: 'floor', side: 'far',
      last_stand: [4051, 4660], flood_frame: 4722, hit_frame: null, ...end,
    },
  })

  it('closes the set there instead of at the next layout', () => {
    const [iv] = detectedLivePlay(timeline(ended(433, 135, {}), layoutOnly(4920)))
    expect(iv.end_frame).toBe(4660)
  })

  it('says how the end was read', () => {
    const [floor] = setMarks(timeline(ended(433, 135, {})))
    expect(floor.label).toContain('ends by frame 4660 (far down to one, then the floor fills)')
    const [hit] = setMarks(timeline(ended(433, 135, { source: 'hit', frame: 4655, hit_frame: 4655 })))
    expect(hit.label).toContain('ends on the hit at frame 4655')
  })

  it('is counted in the summary', () => {
    expect(detectionSummary(timeline(ended(433, 135, {}), layoutOnly(4920))))
      .toBe('1 set start · 1 end · 1 ball layout without one')
  })

  it('puts the frames after it outside the set', () => {
    const tl = timeline(ended(433, 135, {}), layoutOnly(4920))
    expect(livePlayBadge([], tl, 4700)).toEqual({ text: 'no set in progress', source: 'model' })
    expect(livePlayBadge([], tl, 4600)).toEqual({ text: 'set 1 · not marked', source: 'model' })
  })
})

describe('summary', () => {
  it('counts starts and layouts separately', () => {
    expect(detectionSummary(timeline(confirmed(433, 135), layoutOnly(4920))))
      .toBe('1 set start · 1 ball layout without one')
  })

  it('says how to produce one when there is none', () => {
    expect(detectionSummary(null)).toContain('detect_set_start.py')
  })
})

describe('live play badge', () => {
  const detected = timeline(confirmed(433, 135), layoutOnly(4920))
  const hand = (start: number, end: number | null): LivePlayInterval => ({
    id: 'a', start_frame: start, end_frame: end,
    start_source: 'manual', detected_start_frame: null,
  })
  const marked = [hand(400, 4000)]

  it('says nothing inside an interval the annotator marked', () => {
    expect(livePlayBadge(marked, detected, 1000)).toBeNull()
  })

  it('names the detected set when the annotator has not marked it', () => {
    expect(livePlayBadge([], detected, 1000))
      .toEqual({ text: 'set 1 · not marked', source: 'model' })
  })

  it('reports no set in progress only where a set is known to be absent', () => {
    expect(livePlayBadge([], detected, 10))
      .toEqual({ text: 'no set in progress', source: 'model' })
  })

  it('claims nothing about the match without detection to support it', () => {
    expect(livePlayBadge([], null, 10))
      .toEqual({ text: 'live play not marked', source: 'label' })
  })

  it('speaks for the labels once intervals exist but detection does not', () => {
    expect(livePlayBadge(marked, null, 4500))
      .toEqual({ text: 'outside live play', source: 'label' })
  })

  it('prefers what the annotator marked over what was detected', () => {
    // Frame 4500 is outside the detected set but inside a marked interval that
    // runs past it; the annotator's claim wins.
    expect(livePlayBadge([hand(400, 5000)], detected, 4950))
      .toBeNull()
  })
})
