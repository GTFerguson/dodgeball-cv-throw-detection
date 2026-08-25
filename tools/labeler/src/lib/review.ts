import type {
  DetectedSet, LivePlayInterval, SetReview, SetTimelineFile, SetVerdict,
} from '../types'
import { intervalAt, markLiveStart } from './events'

/**
 * Turning a detected set start into ground truth.
 *
 * The detector proposes; this is where a person decides. Three things follow
 * from that and shape everything here:
 *
 * A verdict is kept for a rejection as much as for an acceptance. "Not accepted"
 * and "not looked at" are the same absence in the file and completely different
 * claims about the clip, and only one of them belongs in a precision denominator.
 *
 * Ground truth cannot be the accepted subset of the detections, or recall is one
 * by construction. A start the detector never proposed is marked by hand, and
 * accepting attaches to a hand-marked start when one is already there rather
 * than adding a second — so a blind pass followed by a reconciliation pass works
 * without producing two starts for one set.
 *
 * The accepted frame lives on the live-play interval and only there. A review
 * points at the interval instead of copying its frame, so nothing can drift.
 */
export interface ReviewState {
  reviews: SetReview[]
  livePlay: LivePlayInterval[]
}

export interface ReviewIds {
  review: string
  interval: string
}

/** A verdict belongs to the armed window it judged, not to a position in the file. */
export function judges(review: SetReview, set: DetectedSet): boolean {
  return review.armed_start_frame === set.armed.start_frame
    && review.armed_end_frame === set.armed.end_frame
}

export function reviewFor(reviews: SetReview[], set: DetectedSet): SetReview | null {
  return reviews.find((r) => judges(r, set)) ?? null
}

export function verdictFor(reviews: SetReview[], set: DetectedSet): SetVerdict | null {
  return reviewFor(reviews, set)?.verdict ?? null
}

/**
 * Verdicts that no longer match any detected window.
 *
 * A re-run with different thresholds moves the windows, and a judgement made
 * against the old ones is not transferable — the set it described may not even
 * be a window any more. Surfacing those is the point: they are the annotator's
 * work to redo, and silently dropping them would hide that the review is stale.
 */
export function staleReviews(
  reviews: SetReview[], timeline: SetTimelineFile | null,
): SetReview[] {
  const sets = timeline?.sets ?? []
  return reviews.filter((r) => !sets.some((s) => judges(r, s)))
}

/** The detection a keypress at this frame is about: the window it falls inside. */
export function detectionAt(
  timeline: SetTimelineFile | null, frame: number,
): DetectedSet | null {
  return timeline?.sets.find(
    (s) => frame >= s.armed.start_frame && frame <= s.armed.end_frame,
  ) ?? null
}

/**
 * The frame an acceptance would make ground truth, or null where there is none.
 *
 * A window with no whistle in it carries no start time — the frame the detector
 * reports there is where the ball layout broke, which is later than the start by
 * the reaction and the run to the line. Accepting it as a start would write that
 * lag into ground truth, so it cannot be accepted at all: it is rejected, or the
 * start is placed by hand.
 */
export function acceptableFrame(set: DetectedSet): number | null {
  return set.status === 'confirmed' ? set.start_frame : null
}

/**
 * Record a verdict, or clear it by passing null.
 *
 * Returns null when the verdict cannot be given — accepting a window the
 * detector never timed — so the caller can say why rather than doing nothing.
 */
export function applyVerdict(
  state: ReviewState, set: DetectedSet, verdict: SetVerdict | null,
  ids: ReviewIds, now: string,
): ReviewState | null {
  const frame = acceptableFrame(set)
  if (verdict === 'accepted' && frame == null) return null

  const previous = reviewFor(state.reviews, set)
  const reviews = state.reviews.filter((r) => !judges(r, set))
  let livePlay = detachInterval(state.livePlay, previous)

  if (verdict == null) return { reviews, livePlay }

  let intervalId: string | null = null
  if (verdict === 'accepted' && frame != null) {
    // An interval already covering the detected frame is the annotator's own
    // start for this set. Accepting agrees with it; it does not move it, and the
    // frame stays theirs.
    const existing = intervalAt(livePlay, frame)
    intervalId = existing?.id ?? ids.interval
    livePlay = existing
      ? livePlay.map((iv) => (
        iv.id === existing.id ? { ...iv, detected_start_frame: frame } : iv
      ))
      : markLiveStart(livePlay, ids.interval, frame, {
        start_source: 'model',
        detected_start_frame: frame,
        // The end is left open on purpose. The detector bounds a set by the next
        // ball layout, which is later than the last elimination that really ends
        // it, and accepting a start is not accepting that bound.
      })
  }

  const review: SetReview = {
    id: previous?.id ?? ids.review,
    armed_start_frame: set.armed.start_frame,
    armed_end_frame: set.armed.end_frame,
    detected_frame: set.start_frame,
    verdict,
    interval_id: intervalId,
    reviewed: now,
  }
  return { reviews: [...reviews, review], livePlay }
}

/** Pressing a verdict that is already given takes it back to unreviewed. */
export function toggleVerdict(
  state: ReviewState, set: DetectedSet, verdict: SetVerdict,
  ids: ReviewIds, now: string,
): ReviewState | null {
  const current = verdictFor(state.reviews, set)
  return applyVerdict(state, set, current === verdict ? null : verdict, ids, now)
}

/**
 * Undo what an acceptance added.
 *
 * An interval the acceptance created goes with it. One the annotator had marked
 * by hand stays — withdrawing agreement with the detector is not withdrawing
 * their own start — and only the detector's claim is peeled back off it.
 */
function detachInterval(
  livePlay: LivePlayInterval[], previous: SetReview | null,
): LivePlayInterval[] {
  const id = previous?.interval_id
  if (!id) return livePlay
  const interval = livePlay.find((iv) => iv.id === id)
  if (!interval) return livePlay
  return interval.start_source === 'model'
    ? livePlay.filter((iv) => iv.id !== id)
    : livePlay.map((iv) => (iv.id === id ? { ...iv, detected_start_frame: null } : iv))
}

/** How far the annotator moved an accepted start off the frame the detector gave
 *  it, or null where it was never accepted from one. */
export function anchorDrift(interval: LivePlayInterval): number | null {
  return interval.detected_start_frame == null
    ? null
    : interval.start_frame - interval.detected_start_frame
}
