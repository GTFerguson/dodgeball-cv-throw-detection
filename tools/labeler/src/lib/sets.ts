import type {
  DetectedSet, LivePlayInterval, SetReview, SetTimelineFile, SetVerdict,
} from '../types'
import { verdictFor } from './review'

/**
 * What the detector claims, reduced to what the timeline draws.
 *
 * A set start is a moment, not a throw, so it is not a dot on the outcome scale:
 * it gets its own mark and its own track position. The three statuses are drawn
 * apart because they are different claims — a confirmed start is a frame the
 * annotator can check, and a layout with no whistle is the detector saying it
 * saw the setup and nothing more.
 */
export interface SetMark {
  id: string
  /** Where the mark sits. The whistle for a confirmed start, the layout otherwise. */
  frame: number
  status: DetectedSet['status']
  /** Whether `frame` is the start itself or only where the evidence began. */
  timed: boolean
  /** The annotator's judgement, or null while the claim is still unreviewed. */
  verdict: SetVerdict | null
  label: string
}

export function frameToSeconds(frame: number, fps: number): number {
  return fps > 0 ? frame / fps : 0
}

/**
 * One mark per armed window.
 *
 * An unconfirmed or whistle-less window still gets a mark. Dropping it would let
 * the timeline imply the detector found nothing there, when what it found was
 * balls laid out and no whistle to go with them.
 */
export function setMarks(
  timeline: SetTimelineFile | null, reviews: SetReview[] = [],
): SetMark[] {
  if (!timeline) return []
  return timeline.sets.map((set, i) => {
    const confirmed = set.status === 'confirmed' && set.start_frame != null
    const verdict = verdictFor(reviews, set)
    const ending = set.end
      ? set.end.source === 'hit'
        ? `, ends on the hit at frame ${set.end.frame}`
        : `, ends by frame ${set.end.frame} (${set.end.side} down to one, then the floor fills)`
      : ''
    const claim = confirmed
      ? `set ${i + 1} starts · whistle at frame ${set.start_frame}${ending}`
      : `set ${i + 1} · balls laid out at frame ${set.armed.start_frame}, no start detected`
    return {
      id: `set-${i}`,
      frame: confirmed ? (set.start_frame as number) : set.armed.start_frame,
      status: set.status,
      timed: confirmed,
      verdict,
      label: verdict ? `${claim} — ${verdict}` : `${claim} — not yet reviewed`,
    }
  })
}

/**
 * Live play as the detector has it, in the shape the timeline already shades.
 *
 * A set with a detected end runs to it. Otherwise it runs to the next ball
 * layout, because play has stopped by the time the balls are being laid out
 * again - an upper bound, later than the end by the huddle - and the last such
 * interval takes a null end, which the timeline draws as running to the clip
 * end exactly as an unfinished hand-marked interval does.
 *
 * Intervals are numbered by the set's index in the timeline as written, layouts
 * that never got a whistle included — the numbering the marks, the roster's
 * `played_sets` and the identity pass all use — so `detected-live-2` is the
 * interval of the mark `set-2`, not the third interval that happened to exist.
 */
export function detectedLivePlay(timeline: SetTimelineFile | null): LivePlayInterval[] {
  if (!timeline) return []
  const layouts = timeline.sets.map((s) => s.armed.start_frame).sort((a, b) => a - b)
  return timeline.sets.flatMap((s, setIndex) => {
    if (s.status !== 'confirmed' || s.start_frame == null) return []
    const start = s.start_frame
    const next = layouts.find((f) => f > start)
    return [{
      id: `detected-live-${setIndex}`,
      start_frame: start,
      end_frame: s.end?.frame ?? next ?? null,
      start_source: 'model' as const,
      detected_start_frame: start,
    }]
  })
}

/** The index into `sets` an interval from `detectedLivePlay` belongs to. */
export function setIndexOf(interval: LivePlayInterval): number {
  return Number(interval.id.slice('detected-live-'.length))
}

/** Whether the detector produced anything to draw for this clip. */
export function hasDetection(timeline: SetTimelineFile | null): boolean {
  return setMarks(timeline).length > 0
}

/** What the model track is currently able to claim, for the track's caption. */
export function detectionSummary(timeline: SetTimelineFile | null): string {
  const marks = setMarks(timeline)
  if (!marks.length) return 'no set starts detected — run scripts/detect_set_start.py'
  const confirmed = marks.filter((m) => m.timed).length
  const partial = marks.length - confirmed
  const ended = (timeline?.sets ?? []).filter((s) => s.end).length
  const parts = [`${confirmed} set ${confirmed === 1 ? 'start' : 'starts'}`]
  if (ended) parts.push(`${ended} ${ended === 1 ? 'end' : 'ends'}`)
  if (partial) parts.push(`${partial} ball layout without one`)
  return parts.join(' · ')
}

/** Which set a frame falls in, as its index into the timeline's `sets` — the
 *  number the roster's `played_sets` holds — or null outside live play. */
export function detectedSetAt(timeline: SetTimelineFile | null, frame: number): number | null {
  for (const iv of detectedLivePlay(timeline)) {
    if (frame >= iv.start_frame && (iv.end_frame == null || frame <= iv.end_frame)) {
      return setIndexOf(iv)
    }
  }
  return null
}

export interface LiveBadge {
  text: string
  /** Whose claim the badge is making, which decides how it is coloured. */
  source: 'label' | 'model'
}

/**
 * What to say about live play at a frame, or null to say nothing.
 *
 * "Outside live play" collapsed two different statements: *you have not marked
 * this frame*, which is about the label file, and *no set is in progress*, which
 * is about the match. With nothing marked they are indistinguishable and the
 * badge sat on permanently, reading as a claim about the footage that it had no
 * grounds to make.
 *
 * They are separated here, and the tool never claims the second without evidence
 * for it: with no detection and no marked intervals, all it can honestly report
 * is that live play has not been marked.
 */
export function livePlayBadge(
  marked: LivePlayInterval[], timeline: SetTimelineFile | null, frame: number,
): LiveBadge | null {
  const inMarked = marked.some(
    (i) => frame >= i.start_frame && (i.end_frame == null || frame <= i.end_frame),
  )
  if (inMarked) return null

  const set = detectedSetAt(timeline, frame)
  // Shown counted from 1, as the timeline marks are.
  if (set != null) return { text: `set ${set + 1} · not marked`, source: 'model' }
  if (hasDetection(timeline)) return { text: 'no set in progress', source: 'model' }
  if (marked.length) return { text: 'outside live play', source: 'label' }
  return { text: 'live play not marked', source: 'label' }
}
