import type {
  Candidate, CandidateFile, CandidateReview, CandidateVerdict, DetectedSet, EventKind,
  LivePlayInterval, Outcome, SetReview, SetTimelineFile, SetVerdict, ThrowEvent,
} from '../types'
import { EVENT_KINDS, missingFields } from '../types'
import { reviewFor, verdictFor as proposalVerdict } from './candidates'
import { acceptableFrame, reviewFor as setReviewFor } from './review'

/**
 * One stream of moments, from two sources.
 *
 * Labels and detections are both events at frames, and the list shows whichever
 * of them are switched on, merged in time. There is no third "compare" view:
 * both on *is* the comparison, because an accepted proposal and the throw it
 * became are the same moment and collapse into one row, while everything else
 * stays single-sided - a label with no model beside it is a miss, a model row
 * with no label is unreviewed or rejected.
 */
export type RowKind = 'event' | 'proposal' | 'matched' | 'set'

export interface StreamRow {
  id: string
  kind: RowKind
  /** Where the row sits in time: the label's frame where there is one. */
  frame: number
  event: ThrowEvent | null
  proposal: Candidate | null
  set: DetectedSet | null
  setIndex: number | null
  interval: LivePlayInterval | null
  verdict: SetVerdict | CandidateVerdict | null
}

export interface Sources {
  labels: boolean
  model: boolean
}

export const proposalRowId = (c: Candidate) => `p-${c.frame}-${c.track_id}`
export const eventRowId = (e: ThrowEvent) => `e-${e.id}`
export const setRowId = (s: DetectedSet) => `s-${s.armed.start_frame}-${s.armed.end_frame}`
export const intervalRowId = (iv: LivePlayInterval) => `l-${iv.id}`

export function buildRows(
  events: ThrowEvent[],
  candidates: CandidateFile | null,
  candidateReviews: CandidateReview[],
  sets: SetTimelineFile | null,
  setReviews: SetReview[],
  livePlay: LivePlayInterval[],
): StreamRow[] {
  const rows: StreamRow[] = []

  // Proposals, collapsing into the event an acceptance created or agreed with.
  const claimed = new Set<string>()
  for (const c of candidates?.candidates ?? []) {
    const review = reviewFor(candidateReviews, c)
    const event = review?.verdict === 'accepted' && review.event_id
      ? events.find((e) => e.id === review.event_id) ?? null
      : null
    if (event) {
      claimed.add(event.id)
      rows.push({
        id: eventRowId(event), kind: 'matched', frame: event.release_frame,
        event, proposal: c, set: null, setIndex: null, interval: null, verdict: 'accepted',
      })
    } else {
      rows.push({
        id: proposalRowId(c), kind: 'proposal', frame: c.frame,
        event: null, proposal: c, set: null, setIndex: null, interval: null,
        verdict: proposalVerdict(candidateReviews, c),
      })
    }
  }
  for (const e of events) {
    if (claimed.has(e.id)) continue
    rows.push({
      id: eventRowId(e), kind: 'event', frame: e.release_frame,
      event: e, proposal: null, set: null, setIndex: null, interval: null, verdict: null,
    })
  }

  // Set starts: the detector's, collapsing into the interval an acceptance
  // opened or agreed with; then the annotator's own with no detection under them.
  const claimedIntervals = new Set<string>()
  ;(sets?.sets ?? []).forEach((set, i) => {
    const review = setReviewFor(setReviews, set)
    const interval = review?.interval_id
      ? livePlay.find((iv) => iv.id === review.interval_id) ?? null
      : null
    if (interval) claimedIntervals.add(interval.id)
    rows.push({
      id: setRowId(set), kind: 'set',
      frame: interval?.start_frame ?? acceptableFrame(set) ?? set.armed.start_frame,
      event: null, proposal: null, set, setIndex: i + 1, interval,
      verdict: review?.verdict ?? null,
    })
  })
  for (const iv of livePlay) {
    if (claimedIntervals.has(iv.id)) continue
    rows.push({
      id: intervalRowId(iv), kind: 'set', frame: iv.start_frame,
      event: null, proposal: null, set: null, setIndex: null, interval: iv, verdict: null,
    })
  }

  return rows.sort((a, b) => a.frame - b.frame || a.id.localeCompare(b.id))
}

/** Whether a row is the model's claim, the annotator's, or both. */
export function sidesOf(row: StreamRow): Sources {
  return {
    labels: row.event != null || (row.kind === 'set' && row.interval != null),
    model: row.proposal != null || row.set != null,
  }
}

export type KindFilter = 'all' | 'open' | EventKind | Outcome | 'sets'
export type StateFilter = 'all' | 'unreviewed' | 'uncertain' | 'incomplete'

const isKind = (f: KindFilter): f is EventKind => (EVENT_KINDS as string[]).includes(f)

/** Rows from the sources switched on that pass both filters. */
export function visibleRows(
  rows: StreamRow[], sources: Sources, kind: KindFilter, state: StateFilter,
): StreamRow[] {
  return rows.filter((row) => {
    const sides = sidesOf(row)
    if (!((sources.labels && sides.labels) || (sources.model && sides.model))) return false

    if (kind === 'sets') return row.kind === 'set'
    if (kind !== 'all' && row.kind === 'set') return false
    const e = row.event
    if (kind === 'open' && e?.status !== 'open') return false
    if (isKind(kind) && e?.kind !== kind) return false
    if (kind !== 'all' && kind !== 'open' && !isKind(kind) && e?.outcome !== kind) return false

    if (state === 'unreviewed' && !(sides.model && row.verdict == null)) return false
    if (state === 'uncertain' && !e?.uncertain) return false
    if (state === 'incomplete' && !(e && missingFields(e).length > 0)) return false
    return true
  })
}

/**
 * How close a row is to the playhead, 0 to 1. Emphasis scales with it rather
 * than landing on one row, because a coordinated attack releases two or three
 * balls within a few hundred milliseconds and all of them are what you are
 * looking at. A second either side is the window: past that a row is context.
 */
export const EMPHASIS_WINDOW_FRAMES = 25

export function proximity(row: StreamRow, frame: number): number {
  return Math.max(0, 1 - Math.abs(row.frame - frame) / EMPHASIS_WINDOW_FRAMES)
}

/** The row closest in time to a frame - the one the list keeps in view. */
export function nearestRow(rows: StreamRow[], frame: number): StreamRow | null {
  let best: StreamRow | null = null
  for (const row of rows) {
    if (!best || Math.abs(row.frame - frame) < Math.abs(best.frame - frame)) best = row
  }
  return best
}

/**
 * The next row in the given direction, wrapping. From a selected row it is the
 * adjacent card - the walk is through the list, so stepping frames to find a
 * release, or two cards sharing a frame, cannot make a press skip one. With
 * nothing selected in the list, it is the first row strictly beyond the frame.
 */
export function nextRow(
  rows: StreamRow[], selectedId: string | null, frame: number, dir: 1 | -1,
): StreamRow | null {
  if (!rows.length) return null
  const at = selectedId == null ? -1 : rows.findIndex((r) => r.id === selectedId)
  if (at >= 0) return rows[(at + dir + rows.length) % rows.length]
  const ahead = dir === 1
    ? rows.filter((r) => r.frame > frame)
    : [...rows].reverse().filter((r) => r.frame < frame)
  return ahead[0] ?? (dir === 1 ? rows[0] : rows[rows.length - 1])
}

/** Whether a verdict can be given on a row: only the model's claims take one. */
export function judgeable(row: StreamRow | null): boolean {
  return row != null && (row.proposal != null || row.set != null)
}
