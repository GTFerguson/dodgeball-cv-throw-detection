import type { DetectedSet, LivePlayInterval, SetTimelineFile } from '../types'

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
export function setMarks(timeline: SetTimelineFile | null): SetMark[] {
  if (!timeline) return []
  return timeline.sets.map((set, i) => {
    const confirmed = set.status === 'confirmed' && set.start_frame != null
    return {
      id: `set-${i}`,
      frame: confirmed ? (set.start_frame as number) : set.armed.start_frame,
      status: set.status,
      timed: confirmed,
      label: confirmed
        ? `set ${i + 1} starts · whistle at frame ${set.start_frame}`
        : `set ${i + 1} · balls laid out at frame ${set.armed.start_frame}, no start detected`,
    }
  })
}

/**
 * Live play as the detector has it, in the shape the timeline already shades.
 *
 * A set runs from its start to the next ball layout, because play has stopped by
 * the time the balls are being laid out again. That end is an upper bound - a set
 * really ends on its last elimination, which nothing detects yet - so the last
 * interval takes a null end, which the timeline draws as running to the clip end
 * exactly as an unfinished hand-marked interval does.
 */
export function detectedLivePlay(timeline: SetTimelineFile | null): LivePlayInterval[] {
  if (!timeline) return []
  const layouts = timeline.sets.map((s) => s.armed.start_frame).sort((a, b) => a - b)
  return timeline.sets
    .filter((s) => s.status === 'confirmed' && s.start_frame != null)
    .map((s, i) => {
      const start = s.start_frame as number
      const next = layouts.find((f) => f > start)
      return { id: `detected-live-${i}`, start_frame: start, end_frame: next ?? null }
    })
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
  const parts = [`${confirmed} set ${confirmed === 1 ? 'start' : 'starts'}`]
  if (partial) parts.push(`${partial} ball layout without one`)
  return parts.join(' · ')
}
