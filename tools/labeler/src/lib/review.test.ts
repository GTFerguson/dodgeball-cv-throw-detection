import { describe, expect, it } from 'vitest'
import type { DetectedSet, LivePlayInterval, SetTimelineFile } from '../types'
import { markLiveStart } from './events'
import {
  acceptableFrame, anchorDrift, applyVerdict, detectionAt, staleReviews, toggleVerdict,
  verdictFor, type ReviewState,
} from './review'

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

const empty: ReviewState = { reviews: [], livePlay: [] }
const ids = { review: 'r1', interval: 'i1' }
const NOW = '2026-08-25T10:00:00.000Z'

const accept = (state: ReviewState, set: DetectedSet, id = ids) =>
  applyVerdict(state, set, 'accepted', id, NOW)!
const reject = (state: ReviewState, set: DetectedSet, id = ids) =>
  applyVerdict(state, set, 'rejected', id, NOW)!

describe('accepting a detected start', () => {
  it('opens live play at the frame the detector timed', () => {
    const set = confirmed(433, 135)
    const { livePlay } = accept(empty, set)
    expect(livePlay).toEqual([{
      id: 'i1', start_frame: 433, end_frame: null,
      start_source: 'model', detected_start_frame: 433,
    }])
  })

  it('leaves the end open, because the detector never claimed one', () => {
    expect(accept(empty, confirmed(433, 135)).livePlay[0].end_frame).toBeNull()
  })

  it('records the verdict against the window it judged, not a file position', () => {
    const set = confirmed(433, 135)
    const [review] = accept(empty, set).reviews
    expect(review).toMatchObject({
      armed_start_frame: 135, armed_end_frame: 493, detected_frame: 433,
      verdict: 'accepted', interval_id: 'i1',
    })
  })

  it('refuses a window the detector never timed', () => {
    // Its reported frame is where the layout broke, which is later than the
    // start by the reaction and the run. Accepting it would write that in.
    expect(applyVerdict(empty, layoutOnly(4920), 'accepted', ids, NOW)).toBeNull()
    expect(acceptableFrame(layoutOnly(4920))).toBeNull()
  })
})

describe('a start already marked by hand', () => {
  const set = confirmed(433, 135)
  const manual: ReviewState = {
    reviews: [],
    livePlay: markLiveStart([], 'mine', 431),
  }

  it('is agreed with rather than duplicated', () => {
    const { livePlay } = accept(manual, set)
    expect(livePlay).toHaveLength(1)
    expect(livePlay[0]).toMatchObject({ id: 'mine', start_frame: 431, start_source: 'manual' })
  })

  it('keeps the annotator on their own frame and the detector on its own', () => {
    const { livePlay } = accept(manual, set)
    expect(anchorDrift(livePlay[0])).toBe(-2)
  })

  it('survives the acceptance being taken back', () => {
    const accepted = accept(manual, set)
    const cleared = applyVerdict(accepted, set, null, ids, NOW)!
    expect(cleared.livePlay).toHaveLength(1)
    expect(cleared.livePlay[0].detected_start_frame).toBeNull()
    expect(cleared.reviews).toEqual([])
  })
})

describe('taking a verdict back', () => {
  const set = confirmed(433, 135)

  it('removes the interval the acceptance created', () => {
    const cleared = applyVerdict(accept(empty, set), set, null, ids, NOW)!
    expect(cleared.livePlay).toEqual([])
    expect(cleared.reviews).toEqual([])
  })

  it('happens when the same verdict is pressed twice', () => {
    const accepted = toggleVerdict(empty, set, 'accepted', ids, NOW)!
    const off = toggleVerdict(accepted, set, 'accepted', ids, NOW)!
    expect(verdictFor(off.reviews, set)).toBeNull()
  })

  it('does not happen when the other verdict is pressed', () => {
    const accepted = toggleVerdict(empty, set, 'accepted', ids, NOW)!
    const flipped = toggleVerdict(accepted, set, 'rejected', ids, NOW)!
    expect(verdictFor(flipped.reviews, set)).toBe('rejected')
    expect(flipped.livePlay).toEqual([])
    expect(flipped.reviews).toHaveLength(1)
  })
})

describe('rejection', () => {
  it('is written down, so it cannot be read as not yet looked at', () => {
    const set = layoutOnly(4920)
    const { reviews, livePlay } = reject(empty, set)
    expect(reviews).toHaveLength(1)
    expect(reviews[0]).toMatchObject({ verdict: 'rejected', interval_id: null })
    expect(livePlay).toEqual([])
    expect(verdictFor([], set)).toBeNull()
  })
})

describe('ground truth is not the accepted subset', () => {
  it('keeps a hand-marked start the detector never proposed', () => {
    const missed = markLiveStart([], 'mine', 2400)
    const state: ReviewState = { reviews: [], livePlay: missed }
    const after = reject(state, layoutOnly(4920))
    expect(after.livePlay).toEqual(missed)
    expect(after.livePlay[0]).toMatchObject({
      start_source: 'manual', detected_start_frame: null,
    })
  })

  it('reports no drift for a start that was never accepted from a detection', () => {
    const [hand] = markLiveStart([], 'mine', 2400) as LivePlayInterval[]
    expect(anchorDrift(hand)).toBeNull()
  })
})

describe('a re-run of the detector', () => {
  const set = confirmed(433, 135)

  it('strands a verdict whose window has moved', () => {
    const { reviews } = accept(empty, set)
    const moved = timeline(confirmed(433, 140))
    expect(staleReviews(reviews, moved)).toEqual(reviews)
    expect(verdictFor(reviews, moved.sets[0])).toBeNull()
  })

  it('keeps one whose window is unchanged', () => {
    const { reviews } = accept(empty, set)
    expect(staleReviews(reviews, timeline(set))).toEqual([])
  })
})

describe('the detection a keypress means', () => {
  const clip = timeline(confirmed(433, 135), layoutOnly(4920))

  it('is the window the playhead is inside', () => {
    expect(detectionAt(clip, 300)?.start_frame).toBe(433)
    expect(detectionAt(clip, 5000)?.status).toBe('no_whistle')
  })

  it('is nothing between windows', () => {
    expect(detectionAt(clip, 2000)).toBeNull()
    expect(detectionAt(null, 300)).toBeNull()
  })
})
