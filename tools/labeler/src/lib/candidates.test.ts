import { describe, expect, it } from 'vitest'
import type { Candidate, CandidateFile, CandidateReview, PoseManifest, ThrowEvent } from '../types'
import { newEvent } from '../types'
import { snapToDetection, withBox } from './boxes'
import {
  candidateNear, eventFor, isBare, judgeCandidate, nextUnreviewed, noteCandidate,
  proposalSummary, proposalsToDraw, staleReviews, verdictFor, type CandidateState,
} from './candidates'

const manifest = {
  run_id: 'r1', model: 'm.pt', weights_sha256: 'abc', imgsz: 1920,
} as PoseManifest

const proposal = (frame: number, track = 17, box: Candidate['box'] = [800, 400, 900, 700]): Candidate => ({
  frame, track_id: track, participant: `player-t${track}`, team: 'far', score: 80,
  detection_index: 0, box,
})

const file = (...cs: Candidate[]): CandidateFile => ({
  schema_version: 1, video: 'clip.mp4', clip_sha256: 'abc', pose_run: 'r1', fps: 25,
  thresholds: { min_score: 30 }, candidates: cs,
})

const BOX = { x1: 800, y1: 400, x2: 900, y2: 700 }
const ids = { review: 'rv1', event: 'ev1' }
const now = '2026-08-26T10:00:00.000Z'
const empty: CandidateState = { events: [], selectedId: null, reviews: [] }

describe('accepting a proposal', () => {
  it('opens a release at the proposed frame with the proposed thrower', () => {
    const r = judgeCandidate(empty, proposal(1411), 'accepted', ids, now, manifest)
    expect(r.ok).toBe(true)
    if (!r.ok) return
    const [e] = r.state.events
    expect(e.release_frame).toBe(1411)
    expect(e.status).toBe('open')
    expect(e.kind).toBeNull()
    expect(e.thrower?.box).toEqual({ x1: 800, y1: 400, x2: 900, y2: 700 })
    expect(e.thrower?.source).toBe('snapped')
    expect(e.thrower?.pose_run?.run_id).toBe('r1')
    expect(e.team).toBe('far')
    expect(r.state.selectedId).toBe(e.id)
  })

  it('records where the event came from and what was proposed', () => {
    const r = judgeCandidate(empty, proposal(1411), 'accepted', ids, now, manifest)
    if (!r.ok) throw new Error(r.reason)
    expect(r.state.events[0].source).toBe('model')
    expect(r.state.events[0].proposed_frame).toBe(1411)
    expect(r.state.reviews).toEqual([{
      id: 'rv1', frame: 1411, box: BOX, verdict: 'accepted', event_id: 'ev1', note: '', reviewed: now,
    }])
  })

  it('agrees with a throw the annotator already has there instead of adding one', () => {
    const mine: ThrowEvent = {
      ...newEvent('mine', 1409, null),
      thrower: snapToDetection({ box: [805, 402, 898, 696], conf: 0.9, kpts: [] }, 1409, manifest),
    }
    const r = judgeCandidate({ ...empty, events: [mine] }, proposal(1411), 'accepted', ids, now, manifest)
    if (!r.ok) throw new Error(r.reason)
    expect(r.state.events).toHaveLength(1)
    expect(r.state.events[0].release_frame).toBe(1409)
    expect(r.state.events[0].source).toBe('manual')
    expect(r.state.events[0].proposed_frame).toBe(1411)
    expect(r.state.reviews[0].event_id).toBe('mine')
  })

  it('does not mistake a different player at the same moment for the same throw', () => {
    const other: ThrowEvent = {
      ...newEvent('other', 1411, null),
      thrower: snapToDetection({ box: [200, 400, 300, 700], conf: 0.9, kpts: [] }, 1411, manifest),
    }
    const r = judgeCandidate({ ...empty, events: [other] }, proposal(1411), 'accepted', ids, now, manifest)
    if (!r.ok) throw new Error(r.reason)
    expect(r.state.events).toHaveLength(2)
  })

  it('is a no-op the second time', () => {
    const once = judgeCandidate(empty, proposal(1411), 'accepted', ids, now, manifest)
    if (!once.ok) throw new Error(once.reason)
    const twice = judgeCandidate(once.state, proposal(1411), 'accepted', ids, now, manifest)
    expect(twice.ok).toBe(false)
  })
})

describe('rejecting a proposal', () => {
  it('is recorded, so unreviewed and rejected are never the same absence', () => {
    const r = judgeCandidate(empty, proposal(577), 'rejected', ids, now, manifest)
    if (!r.ok) throw new Error(r.reason)
    expect(r.state.events).toEqual([])
    expect(verdictFor(r.state.reviews, proposal(577))).toBe('rejected')
    expect(r.state.reviews[0].event_id).toBeNull()
  })

  it('pressed again takes the rejection back', () => {
    const once = judgeCandidate(empty, proposal(577), 'rejected', ids, now, manifest)
    if (!once.ok) throw new Error(once.reason)
    const twice = judgeCandidate(once.state, proposal(577), 'rejected', ids, now, manifest)
    if (!twice.ok) throw new Error(twice.reason)
    expect(twice.state.reviews).toEqual([])
  })

  it('takes back a bare event an acceptance created', () => {
    const acc = judgeCandidate(empty, proposal(1411), 'accepted', ids, now, manifest)
    if (!acc.ok) throw new Error(acc.reason)
    const rej = judgeCandidate(acc.state, proposal(1411), 'rejected', ids, now, manifest)
    if (!rej.ok) throw new Error(rej.reason)
    expect(rej.state.events).toEqual([])
    expect(rej.state.selectedId).toBeNull()
    expect(verdictFor(rej.state.reviews, proposal(1411))).toBe('rejected')
  })

  it('refuses to lose labels the annotator added to an accepted event', () => {
    const acc = judgeCandidate(empty, proposal(1411), 'accepted', ids, now, manifest)
    if (!acc.ok) throw new Error(acc.reason)
    const enriched = { ...acc.state, events: acc.state.events.map((e) => ({ ...e, outcome: 'hit' as const, status: 'closed' as const })) }
    const rej = judgeCandidate(enriched, proposal(1411), 'rejected', ids, now, manifest)
    expect(rej.ok).toBe(false)
  })

  it('withdraws only the claim from a hand-labelled throw it had agreed with', () => {
    const mine: ThrowEvent = {
      ...newEvent('mine', 1409, null),
      thrower: snapToDetection({ box: [805, 402, 898, 696], conf: 0.9, kpts: [] }, 1409, manifest),
    }
    const acc = judgeCandidate({ ...empty, events: [mine] }, proposal(1411), 'accepted', ids, now, manifest)
    if (!acc.ok) throw new Error(acc.reason)
    const rej = judgeCandidate(acc.state, proposal(1411), 'rejected', ids, now, manifest)
    if (!rej.ok) throw new Error(rej.reason)
    expect(rej.state.events).toHaveLength(1)
    expect(rej.state.events[0].proposed_frame).toBeNull()
  })
})

describe('what counts as bare', () => {
  const accepted = () => {
    const r = judgeCandidate(empty, proposal(1411), 'accepted', ids, now, manifest)
    if (!r.ok) throw new Error(r.reason)
    return r.state.events[0]
  }

  it('is exactly what accepting created', () => {
    expect(isBare(accepted())).toBe(true)
  })

  it('stops being bare once the release is moved, the box adjusted or anything labelled', () => {
    const e = accepted()
    expect(isBare({ ...e, release_frame: 1413 })).toBe(false)
    expect(isBare({ ...e, thrower: withBox(e.thrower!, e.thrower!.box) })).toBe(false)
    expect(isBare({ ...e, note: 'graze' })).toBe(false)
    expect(isBare({ ...e, kind: 'pass', status: 'closed' })).toBe(false)
  })

  it('never applies to a hand-labelled event', () => {
    expect(isBare(newEvent('m', 10, null))).toBe(false)
  })
})

describe('finding proposals', () => {
  const f = file(proposal(100), proposal(120, 3), proposal(300))

  it('picks the nearest proposal within tolerance of a frame', () => {
    expect(candidateNear(f, 104)?.frame).toBe(100)
    expect(candidateNear(f, 116)?.frame).toBe(120)
    expect(candidateNear(f, 200)).toBeNull()
  })

  it('walks to the next unreviewed proposal and wraps', () => {
    const reviews: CandidateReview[] = [{
      id: 'r', frame: 120, box: BOX, verdict: 'rejected', event_id: null, note: '', reviewed: now,
    }]
    expect(nextUnreviewed(f, reviews, 100, 1)?.frame).toBe(300)
    expect(nextUnreviewed(f, reviews, 300, 1)?.frame).toBe(100)
    expect(nextUnreviewed(f, reviews, 100, -1)?.frame).toBe(300)
    expect(nextUnreviewed(f, [], 0, 1)?.frame).toBe(100)
    expect(nextUnreviewed(null, [], 0, 1)).toBeNull()
  })

  it('matches a labelled throw by moment and player', () => {
    const mine: ThrowEvent = {
      ...newEvent('mine', 98, null),
      thrower: snapToDetection({ box: [800, 400, 900, 700], conf: 0.9, kpts: [] }, 98, manifest),
    }
    expect(eventFor([mine], proposal(100))?.id).toBe('mine')
    expect(eventFor([mine], proposal(110))).toBeNull()
    expect(eventFor([{ ...mine, thrower: null }], proposal(100))).toBeNull()
  })

  it('reports verdicts on proposals a re-run no longer makes as stale', () => {
    const reviews: CandidateReview[] = [
      { id: 'a', frame: 100, box: BOX, verdict: 'accepted', event_id: 'e', note: '', reviewed: now },
      { id: 'b', frame: 999, box: BOX, verdict: 'rejected', event_id: null, note: '', reviewed: now },
      // Right frame, someone else's box.
      { id: 'c', frame: 100, box: { x1: 200, y1: 400, x2: 300, y2: 700 }, verdict: 'rejected', event_id: null, note: '', reviewed: now },
    ]
    expect(staleReviews(reviews, f).map((r) => r.id)).toEqual(['b', 'c'])
  })

  it('keeps a verdict through a re-run that renumbers the track', () => {
    const r = judgeCandidate(empty, proposal(100, 17), 'rejected', ids, now, manifest)
    if (!r.ok) throw new Error(r.reason)
    // Same throw, same box give or take a detector's pixel, new tracker id.
    const rerun = proposal(100, 341, [802, 398, 901, 703])
    expect(verdictFor(r.state.reviews, rerun)).toBe('rejected')
    expect(verdictFor(r.state.reviews, proposal(100, 17, [200, 400, 300, 700]))).toBeNull()
    expect(staleReviews(r.state.reviews, file(rerun))).toEqual([])
  })

  it('captions the model track with what there is to review', () => {
    expect(proposalSummary(null, [])).toMatch(/detect_candidates/)
    expect(proposalSummary(f, [])).toBe('3 throws proposed · 0 reviewed')
  })
})

describe('notes on a proposal', () => {
  it('can be written before any verdict, and leave the proposal unreviewed', () => {
    const reviews = noteCandidate([], proposal(577), 'lying down, arm over head', 'n1', now)
    expect(reviews).toHaveLength(1)
    expect(reviews[0]).toMatchObject({ verdict: null, note: 'lying down, arm over head' })
    expect(verdictFor(reviews, proposal(577))).toBeNull()
  })

  it('rides along with a verdict given afterwards', () => {
    const noted = noteCandidate([], proposal(577), 'prone', 'n1', now)
    const r = judgeCandidate({ ...empty, reviews: noted }, proposal(577), 'rejected', ids, now, manifest)
    if (!r.ok) throw new Error(r.reason)
    expect(r.state.reviews[0]).toMatchObject({ verdict: 'rejected', note: 'prone' })
  })

  it('outlives a verdict that is taken back', () => {
    const rej = judgeCandidate(empty, proposal(577), 'rejected', ids, now, manifest)
    if (!rej.ok) throw new Error(rej.reason)
    const noted = noteCandidate(rej.state.reviews, proposal(577), 'prone', 'n1', now)
    const cleared = judgeCandidate({ ...empty, reviews: noted }, proposal(577), 'rejected', ids, now, manifest)
    if (!cleared.ok) throw new Error(cleared.reason)
    expect(cleared.state.reviews[0]).toMatchObject({ verdict: null, note: 'prone' })
  })

  it('an emptied note with no verdict leaves nothing behind', () => {
    const noted = noteCandidate([], proposal(577), 'prone', 'n1', now)
    expect(noteCandidate(noted, proposal(577), '', 'n2', now)).toEqual([])
  })
})


describe('what the stage draws for proposals', () => {
  const rejected = (c: Candidate): CandidateReview => ({
    id: `rv-${c.frame}`, frame: c.frame, box: { x1: c.box[0], y1: c.box[1], x2: c.box[2], y2: c.box[3] }, verdict: 'rejected', event_id: null, note: '', reviewed: now,
  })
  const drawn = (out: ReturnType<typeof proposalsToDraw>) =>
    out.map((d) => `${d.candidate.frame}${d.loud ? '!' : ''}`)

  it('draws a rejected proposal the annotator selected, loud', () => {
    const c = proposal(525)
    expect(drawn(proposalsToDraw(file(c), [rejected(c)], 525, c))).toEqual(['525!'])
  })

  it('draws nothing loud once the frame has left the selected proposal', () => {
    // The same player throws again at 560. With 525 still selected, its loud
    // box must not land on them there, and 560 must not look selected either.
    const chosen = proposal(525, 17), later = proposal(560, 17)
    expect(drawn(proposalsToDraw(file(chosen, later), [], 560, chosen))).toEqual(['560'])
    expect(drawn(proposalsToDraw(file(chosen, later), [], 530, chosen))).toEqual(['525!'])
  })

  it('hides judged neighbours nobody is looking at', () => {
    const judged = proposal(525, 17), open = proposal(527, 19)
    expect(drawn(proposalsToDraw(file(judged, open), [rejected(judged)], 525, null))).toEqual(['527!'])
  })

  it('makes the nearest unjudged proposal loud when nothing is selected, and draws it last', () => {
    const far = proposal(520, 17), close = proposal(527, 19)
    expect(drawn(proposalsToDraw(file(far, close), [], 526, null))).toEqual(['520', '527!'])
  })

  it('lets a selected proposal outrank a nearer unjudged one', () => {
    const chosen = proposal(520, 17), nearer = proposal(526, 19)
    expect(drawn(proposalsToDraw(file(chosen, nearer), [], 526, chosen))).toEqual(['526', '520!'])
  })

  it('draws nothing beyond tolerance with nothing selected', () => {
    expect(proposalsToDraw(file(proposal(500)), [], 525, null)).toEqual([])
  })
})
