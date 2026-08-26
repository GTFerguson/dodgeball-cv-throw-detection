import { describe, expect, it } from 'vitest'
import type {
  Candidate, CandidateFile, CandidateReview, DetectedSet, LivePlayInterval, SetReview,
  SetTimelineFile, ThrowEvent,
} from '../types'
import { newEvent } from '../types'
import { EMPHASIS_WINDOW_FRAMES, buildRows, judgeable, nearestRow, nextRow, proximity, sidesOf, visibleRows } from './stream'

const proposal = (frame: number, track = 17): Candidate => ({
  frame, track_id: track, participant: `player-t${track}`, team: 'far', score: 80,
  detection_index: 0, box: [800, 400, 900, 700],
})
const file = (...cs: Candidate[]): CandidateFile => ({
  schema_version: 1, video: 'clip.mp4', clip_sha256: 'abc', pose_run: 'r1', fps: 25,
  thresholds: {}, candidates: cs,
})
const confirmedSet: DetectedSet = {
  status: 'confirmed', start_frame: 433, start_s: 17.32, whistle_prominence_db: 37.4,
  sprint_frame: 456, first_ball_moves_frame: 492,
  armed: { start_frame: 135, end_frame: 490, max_balls: 6, max_spread_m: 8 }, notes: [],
}
const timeline: SetTimelineFile = {
  schema_version: 1, video: 'clip.mp4', clip_sha256: 'abc', pose_run: 'r1', fps: 25,
  frame_count: 5250, clip_offset_s: 360, thresholds: {}, sets: [confirmedSet],
}
const now = '2026-08-26T10:00:00.000Z'

describe('building the stream', () => {
  it('merges labels and claims in time order', () => {
    const rows = buildRows([newEvent('a', 900, null)], file(proposal(1411), proposal(500)), [], timeline, [], [])
    expect(rows.map((r) => [r.frame, r.kind])).toEqual([
      [433, 'set'], [500, 'proposal'], [900, 'event'], [1411, 'proposal'],
    ])
  })

  it('collapses an accepted proposal and its event into one row at the label frame', () => {
    const e: ThrowEvent = { ...newEvent('a', 1413, null), source: 'model', proposed_frame: 1411 }
    const reviews: CandidateReview[] = [{
      id: 'r', frame: 1411, box: { x1: 800, y1: 400, x2: 900, y2: 700 }, verdict: 'accepted', event_id: 'a', note: '', reviewed: now,
    }]
    const rows = buildRows([e], file(proposal(1411)), reviews, null, [], [])
    expect(rows).toHaveLength(1)
    expect(rows[0]).toMatchObject({ kind: 'matched', frame: 1413, verdict: 'accepted' })
    expect(sidesOf(rows[0])).toEqual({ labels: true, model: true })
  })

  it('keeps a rejected proposal as its own row with the verdict on it', () => {
    const reviews: CandidateReview[] = [{
      id: 'r', frame: 577, box: { x1: 800, y1: 400, x2: 900, y2: 700 }, verdict: 'rejected', event_id: null, note: '', reviewed: now,
    }]
    const [row] = buildRows([], file(proposal(577)), reviews, null, [], [])
    expect(row).toMatchObject({ kind: 'proposal', verdict: 'rejected' })
    expect(sidesOf(row)).toEqual({ labels: false, model: true })
  })

  it('collapses an accepted set start with the interval it opened', () => {
    const interval: LivePlayInterval = {
      id: 'l1', start_frame: 435, end_frame: null, start_source: 'model', detected_start_frame: 433,
    }
    const reviews: SetReview[] = [{
      id: 's', armed_start_frame: 135, armed_end_frame: 490, detected_frame: 433,
      verdict: 'accepted', interval_id: 'l1', reviewed: now,
    }]
    const rows = buildRows([], null, [], timeline, reviews, [interval])
    expect(rows).toHaveLength(1)
    expect(rows[0]).toMatchObject({ kind: 'set', frame: 435, verdict: 'accepted' })
    expect(sidesOf(rows[0])).toEqual({ labels: true, model: true })
  })

  it('shows a hand-marked set start the detector never proposed', () => {
    const interval: LivePlayInterval = {
      id: 'l2', start_frame: 2000, end_frame: null, start_source: 'manual', detected_start_frame: null,
    }
    const rows = buildRows([], null, [], null, [], [interval])
    expect(rows[0]).toMatchObject({ kind: 'set', frame: 2000, set: null })
    expect(sidesOf(rows[0])).toEqual({ labels: true, model: false })
  })
})

describe('filtering the stream', () => {
  const e: ThrowEvent = { ...newEvent('a', 900, 'throw'), status: 'closed', outcome: 'hit', uncertain: true }
  const rows = buildRows([e, newEvent('b', 950, null)], file(proposal(1411)), [], timeline, [], [])

  it('switches sources on and off', () => {
    expect(visibleRows(rows, { labels: true, model: false }, 'all', 'all').map((r) => r.frame)).toEqual([900, 950])
    expect(visibleRows(rows, { labels: false, model: true }, 'all', 'all').map((r) => r.frame)).toEqual([433, 1411])
    expect(visibleRows(rows, { labels: false, model: false }, 'all', 'all')).toEqual([])
  })

  it('narrows by kind, outcome and state', () => {
    const both = { labels: true, model: true }
    expect(visibleRows(rows, both, 'hit', 'all').map((r) => r.frame)).toEqual([900])
    expect(visibleRows(rows, both, 'open', 'all').map((r) => r.frame)).toEqual([950])
    expect(visibleRows(rows, both, 'sets', 'all').map((r) => r.frame)).toEqual([433])
    expect(visibleRows(rows, both, 'all', 'unreviewed').map((r) => r.frame)).toEqual([433, 1411])
    expect(visibleRows(rows, both, 'all', 'uncertain').map((r) => r.frame)).toEqual([900])
    expect(visibleRows(rows, both, 'all', 'incomplete').map((r) => r.frame)).toEqual([900, 950])
  })
})

describe('following the playhead', () => {
  const rows = buildRows([], file(proposal(100), proposal(300), proposal(500)), [], null, [], [])

  it('finds the row nearest a frame', () => {
    expect(nearestRow(rows, 260)?.frame).toBe(300)
    expect(nearestRow([], 260)).toBeNull()
  })

  it('lights every row within a second, most for the closest', () => {
    const at = (f: number) => proximity(rows[0], f)   // row at frame 100
    expect(at(100)).toBe(1)
    expect(at(100 + EMPHASIS_WINDOW_FRAMES / 2)).toBeCloseTo(0.5)
    expect(at(100 + EMPHASIS_WINDOW_FRAMES)).toBe(0)
    expect(at(0)).toBe(0)
  })

  it('walks strictly past the frame and wraps', () => {
    expect(nextRow(rows, 100, 1)?.frame).toBe(300)
    expect(nextRow(rows, 500, 1)?.frame).toBe(100)
    expect(nextRow(rows, 100, -1)?.frame).toBe(500)
    expect(nextRow(rows, 301, -1)?.frame).toBe(300)
  })

  it('only the model\'s claims take a verdict', () => {
    expect(judgeable(rows[0])).toBe(true)
    expect(judgeable(buildRows([newEvent('a', 1, null)], null, [], null, [], [])[0])).toBe(false)
    expect(judgeable(null)).toBe(false)
  })
})
