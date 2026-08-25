import { describe, expect, it } from 'vitest'
import type { DetectedSet, SetTimelineFile } from '../types'
import { detectedLivePlay, detectionSummary, hasDetection, setMarks } from './sets'

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
