import type {
  Box, Candidate, CandidateFile, CandidateReview, CandidateVerdict, PoseManifest, ThrowEvent,
} from '../types'
import { newEvent } from '../types'
import { makeBox, poseRunRef } from './boxes'
import type { EventState } from './events'
import { iou } from './roster'

/**
 * Turning a proposed throw into ground truth, or recording that it is not one.
 *
 * The detector proposes a frame and a thrower; a person decides. The rules are
 * the ones set-start review established, applied to a claim that comes a
 * hundred times a clip instead of twice:
 *
 * A rejection is recorded, not left as an absence. "Not accepted" and "not
 * looked at" are the same silence in a file and different claims about the clip,
 * and only one of them belongs in a precision denominator.
 *
 * Accepting a proposal that already has a labelled throw under it agrees with
 * that throw rather than adding a second — so a blind pass followed by a
 * reconciliation pass works. The annotator's frame stays theirs; the detector's
 * frame is recorded beside it.
 *
 * Every event an acceptance creates says so (`source: 'model'`) and keeps the
 * proposed frame after any correction, because truth accepted from a detector is
 * anchored to it, and the anchoring has to be measurable rather than assumed.
 */

/** How far a proposal may sit from a release to be about the same throw. The
 *  evaluation tolerance, so agreement here means agreement there. */
export const MATCH_TOLERANCE_FRAMES = 6

/** How much a proposal's box must overlap a labelled thrower, or a review's
 *  box a proposal, to be the same player. Two players at the same frame
 *  overlap far less than this. */
export const MATCH_MIN_IOU = 0.5

export interface CandidateState {
  events: ThrowEvent[]
  selectedId: string | null
  reviews: CandidateReview[]
}

export type JudgeResult =
  | { ok: true; state: CandidateState; message: string }
  | { ok: false; reason: string }

/** A verdict belongs to the proposal it judged: that frame, that player — by
 *  where they stood, so a re-run that renumbers every track changes nothing. */
export function judges(review: CandidateReview, c: Candidate): boolean {
  return review.frame === c.frame && iou(review.box, candidateBox(c)) >= MATCH_MIN_IOU
}

function candidateBox(c: Candidate): Box {
  const [x1, y1, x2, y2] = c.box
  return makeBox(x1, y1, x2, y2)
}

export function reviewFor(reviews: CandidateReview[], c: Candidate): CandidateReview | null {
  return reviews.find((r) => judges(r, c)) ?? null
}

export function verdictFor(reviews: CandidateReview[], c: Candidate): CandidateVerdict | null {
  return reviewFor(reviews, c)?.verdict ?? null
}

/** Verdicts on proposals this detection run no longer makes — the annotator's
 *  work to redo, surfaced rather than silently dropped. */
export function staleReviews(
  reviews: CandidateReview[], file: CandidateFile | null,
): CandidateReview[] {
  const proposals = file?.candidates ?? []
  return reviews.filter((r) => !proposals.some((c) => judges(r, c)))
}

/** The proposal a keypress at this frame is about: the nearest within tolerance. */
export function candidateNear(
  file: CandidateFile | null, frame: number, tolerance = MATCH_TOLERANCE_FRAMES,
): Candidate | null {
  let best: Candidate | null = null
  for (const c of file?.candidates ?? []) {
    const d = Math.abs(c.frame - frame)
    if (d > tolerance) continue
    if (!best || d < Math.abs(best.frame - frame)) best = c
  }
  return best
}

export interface DrawnProposal {
  candidate: Candidate
  /** Cased, filled and chipped: the one the annotator is being asked to look at. */
  loud: boolean
}

/**
 * Which proposals a frame shows, and which one is loud.
 *
 * The one being looked at is the selected card's proposal, or the nearest
 * unjudged one when nothing is selected. A selected proposal is drawn whatever
 * its verdict - a rejection the annotator clicked to reconsider has to appear -
 * but only while the frame is within tolerance of it. Past that nothing is
 * loud: a player who throws several times in a row would otherwise wear the
 * older throw's loud box on the frame of the newer one, while the keys still
 * classified the older card. The rest are the unjudged ones within tolerance;
 * judged neighbours have been dealt with and would only compete for the eye.
 * The loud one comes last so it draws on top.
 */
export function proposalsToDraw(
  file: CandidateFile | null, reviews: CandidateReview[], frame: number,
  selected: Candidate | null,
): DrawnProposal[] {
  const unjudged = candidatesNear(file, frame).filter((c) => verdictFor(reviews, c) == null)
  const loud = selected
    ? (Math.abs(selected.frame - frame) <= MATCH_TOLERANCE_FRAMES ? selected : null)
    : unjudged.slice().sort((a, b) => Math.abs(a.frame - frame) - Math.abs(b.frame - frame))[0] ?? null
  const quiet = unjudged.filter((c) => !(loud && c.frame === loud.frame && c.track_id === loud.track_id))
  const out: DrawnProposal[] = quiet.map((candidate) => ({ candidate, loud: false }))
  if (loud) out.push({ candidate: loud, loud: true })
  return out
}

/** Proposals within tolerance of a frame, for drawing every box that claims it. */
export function candidatesNear(
  file: CandidateFile | null, frame: number, tolerance = MATCH_TOLERANCE_FRAMES,
): Candidate[] {
  return (file?.candidates ?? []).filter((c) => Math.abs(c.frame - frame) <= tolerance)
}

/**
 * The next proposal nobody has judged, in the given direction from a frame.
 *
 * Strictly beyond the frame, so pressing "next" from a proposal moves off it
 * even when it is still unreviewed; wraps, so the last one leads back to the
 * first rather than nowhere.
 */
export function nextUnreviewed(
  file: CandidateFile | null, reviews: CandidateReview[], frame: number, dir: 1 | -1,
): Candidate | null {
  const pending = (file?.candidates ?? [])
    .filter((c) => verdictFor(reviews, c) == null)
    .sort((a, b) => a.frame - b.frame)
  if (!pending.length) return null
  const ahead = dir === 1
    ? pending.filter((c) => c.frame > frame)
    : pending.filter((c) => c.frame < frame).reverse()
  return ahead[0] ?? (dir === 1 ? pending[0] : pending[pending.length - 1])
}

export function unreviewedCount(file: CandidateFile | null, reviews: CandidateReview[]): number {
  return (file?.candidates ?? []).filter((c) => verdictFor(reviews, c) == null).length
}

/** The labelled throw a proposal is about, if the annotator already has one:
 *  same moment, same player. */
export function eventFor(events: ThrowEvent[], c: Candidate): ThrowEvent | null {
  const near = events.filter((e) => Math.abs(e.release_frame - c.frame) <= MATCH_TOLERANCE_FRAMES)
  const same = near.filter((e) => e.thrower && iou(e.thrower.box, candidateBox(c)) >= MATCH_MIN_IOU)
  if (!same.length) return null
  return same.sort((a, b) => Math.abs(a.release_frame - c.frame) - Math.abs(b.release_frame - c.frame))[0]
}

/**
 * Whether an event is still exactly what accepting created — nothing the
 * annotator added would be lost by taking it away again.
 */
export function isBare(e: ThrowEvent): boolean {
  return e.source === 'model'
    && e.status === 'open'
    && e.kind == null
    && e.outcome == null
    && e.target == null
    && e.start_frame == null
    && e.end_frame == null
    && e.release_frame === e.proposed_frame
    && !(e.thrower?.adjusted ?? false)
    && e.team_source === 'inferred'
    && !e.uncertain
    && e.note === ''
}

/** The event an acceptance opens: a release at the proposed frame with the
 *  proposed thrower snapped, and its origin written on it. */
export function eventFromCandidate(
  id: string, c: Candidate, manifest: PoseManifest | null,
): ThrowEvent {
  const [x1, y1, x2, y2] = c.box
  return {
    ...newEvent(id, c.frame, null),
    source: 'model',
    proposed_frame: c.frame,
    thrower: {
      box: makeBox(x1, y1, x2, y2),
      frame: c.frame,
      source: 'snapped',
      adjusted: false,
      pose_run: manifest ? poseRunRef(manifest) : null,
    },
    team: c.team,
    team_source: 'inferred',
  }
}

export interface JudgeIds {
  review: string
  event: string
}

/**
 * Give a verdict on a proposal, the way the keys do it.
 *
 * Accept: opens a release from the proposal, or agrees with a throw already
 * labelled there; accepting again is a no-op, because the event is the thing to
 * edit now. Reject: records the rejection; on an accepted proposal it takes the
 * event back only while the event is still bare, and refuses otherwise, since
 * labels the annotator added are not the detector's to lose; rejecting again
 * clears the rejection.
 */
export function judgeCandidate(
  state: CandidateState, c: Candidate, verdict: CandidateVerdict,
  ids: JudgeIds, now: string, manifest: PoseManifest | null,
): JudgeResult {
  const previous = reviewFor(state.reviews, c)
  const others = state.reviews.filter((r) => !judges(r, c))
  const stamp = (v: CandidateVerdict | null, eventId: string | null): CandidateReview => ({
    id: previous?.id ?? ids.review, frame: c.frame, box: candidateBox(c),
    verdict: v, event_id: eventId, note: previous?.note ?? '', reviewed: now,
  })

  if (verdict === 'accepted') {
    if (previous?.verdict === 'accepted') {
      return { ok: false, reason: 'already accepted — edit the event, or ⇧R to take it back' }
    }
    const existing = eventFor(state.events, c)
    if (existing) {
      const events = state.events.map((e) => (
        e.id === existing.id ? { ...e, proposed_frame: c.frame } : e
      ))
      return {
        ok: true,
        state: { events, selectedId: existing.id, reviews: [...others, stamp('accepted', existing.id)] },
        message: `agrees with your throw at ${existing.release_frame}`,
      }
    }
    const event = eventFromCandidate(ids.event, c, manifest)
    return {
      ok: true,
      state: {
        events: [...state.events, event],
        selectedId: event.id,
        reviews: [...others, stamp('accepted', event.id)],
      },
      message: `release opened at ${c.frame} from the proposal`,
    }
  }

  // Rejecting.
  if (previous?.verdict === 'rejected') {
    // A note outlives the verdict it was written under.
    const reviews = previous.note ? [...others, stamp(null, null)] : others
    return { ok: true, state: { ...state, reviews }, message: 'verdict cleared' }
  }
  let events = state.events
  let selectedId = state.selectedId
  if (previous?.verdict === 'accepted' && previous.event_id) {
    const event = state.events.find((e) => e.id === previous.event_id)
    if (event && event.source === 'model') {
      if (!isBare(event)) {
        return { ok: false, reason: 'the event has labels on it — delete it first if it is wrong' }
      }
      events = state.events.filter((e) => e.id !== event.id)
      if (selectedId === event.id) selectedId = null
    } else if (event) {
      // A hand-labelled throw the acceptance agreed with keeps its label; only
      // the detector's claim on it is withdrawn.
      events = state.events.map((e) => (e.id === event.id ? { ...e, proposed_frame: null } : e))
    }
  }
  return {
    ok: true,
    state: { events, selectedId, reviews: [...others, stamp('rejected', null)] },
    message: 'proposal rejected',
  }
}

/** Write a note on a proposal, with or without a verdict on it yet. */
export function noteCandidate(
  reviews: CandidateReview[], c: Candidate, note: string, id: string, now: string,
): CandidateReview[] {
  const previous = reviewFor(reviews, c)
  const others = reviews.filter((r) => !judges(r, c))
  if (!note && !previous?.verdict) return others
  return [...others, {
    id: previous?.id ?? id, frame: c.frame, box: candidateBox(c),
    verdict: previous?.verdict ?? null, event_id: previous?.event_id ?? null,
    note, reviewed: previous?.verdict ? previous.reviewed : now,
  }]
}

export function toCandidateState(state: EventState, reviews: CandidateReview[]): CandidateState {
  return { events: state.events, selectedId: state.selectedId, reviews }
}

/** How far the annotator moved an accepted release off the proposed frame, or
 *  null where the event was never proposed. */
export function anchorDrift(e: ThrowEvent): number | null {
  return e.proposed_frame == null ? null : e.release_frame - e.proposed_frame
}

/** What the model track can say about proposals, for its caption. */
export function proposalSummary(file: CandidateFile | null, reviews: CandidateReview[]): string {
  if (!file) return 'no throws proposed — run scripts/detect_candidates.py'
  const n = file.candidates.length
  const done = n - unreviewedCount(file, reviews)
  return `${n} throws proposed · ${done} reviewed`
}
