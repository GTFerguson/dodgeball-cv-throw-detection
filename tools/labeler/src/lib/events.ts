import type {
  EventKind, LivePlayInterval, LiveStartSource, Outcome, ThrowEvent,
} from '../types'
import { newEvent } from '../types'

/**
 * Throws in the order they were opened, plus which one an outcome key will
 * close. Insertion order is the state's own ordering and is not the display
 * order: a coordinated attack is labelled by scrubbing back and forth, so
 * release frames arrive out of sequence, and "the most recently opened throw"
 * has to mean what the annotator just did, not what happens earliest in the clip.
 */
export interface EventState {
  events: ThrowEvent[]
  selectedId: string | null
}

export const emptyState: EventState = { events: [], selectedId: null }

export function selectedEvent(state: EventState): ThrowEvent | null {
  return state.events.find((e) => e.id === state.selectedId) ?? null
}

export function openEvents(state: EventState): ThrowEvent[] {
  return state.events.filter((e) => e.status === 'open')
}

export function displayOrder(events: ThrowEvent[]): ThrowEvent[] {
  return [...events].sort((a, b) => a.release_frame - b.release_frame)
}

/**
 * A release opens at its release frame and stays open until its destination and
 * outcome are known. It is not yet a throw: a pass looks identical up to this
 * moment, and everything that separates the two happens afterwards.
 */
export function openRelease(state: EventState, id: string, frame: number): EventState {
  const event = newEvent(id, frame, null)
  return { events: [...state.events, event], selectedId: id }
}

/**
 * Move the selected event's release to a frame. The peak the proposal found is
 * the whip, not the release, and an accepted proposal keeps its `proposed_frame`,
 * so the correction stays measurable. Nothing selected means nothing to move.
 */
export function moveRelease(state: EventState, frame: number): EventState | null {
  const target = selectedEvent(state)
  if (!target) return null
  return updateEvent(state, target.id, { release_frame: frame })
}

/** A fake is a wind-up with no release: it is born closed and never resolves. */
export function openFake(state: EventState, id: string, frame: number): EventState {
  const event = newEvent(id, frame, 'fake')
  return { events: [...state.events, event], selectedId: id }
}

/**
 * An outcome describes what happened to a ball that reached the far side, so
 * recording one also settles the destination: the event was a throw.
 * `unresolved` is the exception — it says nothing was observed, so it makes no
 * claim about where the ball went either. It leaves an undecided event undecided
 * rather than silently counting it as a throw, and retracts a pass, which it
 * contradicts.
 */
export function kindAfterOutcome(current: EventKind | null, outcome: Outcome): EventKind | null {
  if (outcome !== 'unresolved') return 'throw'
  return current === 'pass' ? null : current
}

// A fake never released a ball and so has nothing left to resolve. A pass does:
// destination is the decision most often revised, because the ball is seen to
// cross a beat after the annotator has called it.
function isResolvable(e: ThrowEvent): boolean {
  return e.status === 'open' || e.kind === 'pass'
}

// Attention moves to whatever is still in the air; with nothing left open the
// just-resolved event stays selected so it can be corrected.
function resolve(
  state: EventState, target: ThrowEvent, patch: Partial<ThrowEvent>,
): EventState {
  const events = state.events.map((e) => (e.id === target.id ? { ...e, ...patch } : e))
  const stillOpen = events.filter((e) => e.status === 'open')
  const next = stillOpen.length ? stillOpen[stillOpen.length - 1].id : target.id
  return { events, selectedId: next }
}

/**
 * Close the selected event with an outcome. Returns null when there is nothing
 * to close — no selection, an already-resolved throw, or a fake — so the caller
 * can say why rather than silently doing nothing.
 */
export function closeThrow(
  state: EventState, outcome: Outcome, endFrame: number | null = null,
): EventState | null {
  const target = selectedEvent(state)
  if (!target || !isResolvable(target)) return null
  return resolve(state, target, {
    status: 'closed',
    kind: kindAfterOutcome(target.kind, outcome),
    outcome,
    end_frame: endFrame ?? target.end_frame,
  })
}

/**
 * Record that the ball stayed on the thrower's own side. A pass is terminal, and
 * it has no ball outcome: an outcome already recorded could only have been a
 * claim about a ball that crossed, so it is cleared.
 */
export function markPass(
  state: EventState, endFrame: number | null = null,
): EventState | null {
  const target = selectedEvent(state)
  if (!target || target.kind === 'fake') return null
  return resolve(state, target, {
    status: 'closed',
    kind: 'pass',
    outcome: null,
    end_frame: endFrame ?? target.end_frame,
  })
}

/**
 * Record that the selected event was a wind-up with no release. A fake is
 * terminal and reached nobody, so an outcome or a target already recorded could
 * only have described a ball that was never thrown: both are cleared. Nothing
 * selected is the one refusal.
 */
export function markFake(state: EventState): EventState | null {
  const target = selectedEvent(state)
  if (!target) return null
  return resolve(state, target, {
    status: 'closed',
    kind: 'fake',
    outcome: null,
    target: null,
  })
}

/** Walk the open throws — the coordinated-attack case, two or three in the air. */
export function cycleOpen(state: EventState, dir: 1 | -1): EventState {
  const open = openEvents(state)
  if (open.length === 0) return state
  const at = open.findIndex((e) => e.id === state.selectedId)
  const next = at === -1
    ? (dir === 1 ? 0 : open.length - 1)
    : (at + dir + open.length) % open.length
  return { ...state, selectedId: open[next].id }
}

export function updateEvent(
  state: EventState, id: string, patch: Partial<ThrowEvent>,
): EventState {
  return {
    ...state,
    events: state.events.map((e) => (e.id === id ? { ...e, ...patch } : e)),
  }
}

export function deleteEvent(state: EventState, id: string): EventState {
  const events = state.events.filter((e) => e.id !== id)
  return { events, selectedId: state.selectedId === id ? null : state.selectedId }
}

export function restoreEvent(state: EventState, event: ThrowEvent): EventState {
  return { events: [...state.events, event], selectedId: event.id }
}

// ── live play ──────────────────────────────────────────────────────────────

/**
 * Open a set at this frame.
 *
 * `origin` says whose claim the start is. A start placed by hand and one
 * accepted from the detector are the same instant to everything downstream, and
 * they are not the same evidence: only the first was arrived at without seeing
 * what the model said.
 */
export function markLiveStart(
  intervals: LivePlayInterval[], id: string, frame: number,
  origin: LiveStartOrigin = MANUAL_START,
): LivePlayInterval[] {
  const interval: LivePlayInterval = { id, start_frame: frame, end_frame: null, ...origin }
  return [...intervals, interval].sort((a, b) => a.start_frame - b.start_frame)
}

export interface LiveStartOrigin {
  start_source: LiveStartSource
  detected_start_frame: number | null
}

export const MANUAL_START: LiveStartOrigin = {
  start_source: 'manual', detected_start_frame: null,
}

/** Close the latest interval that is still open, or the one containing the frame. */
export function markLiveEnd(
  intervals: LivePlayInterval[], frame: number,
): LivePlayInterval[] | null {
  const open = intervals.filter((i) => i.end_frame == null && i.start_frame <= frame)
  if (open.length === 0) return null
  const target = open[open.length - 1]
  return intervals.map((i) => (i.id === target.id ? { ...i, end_frame: frame } : i))
}

/** The set a frame falls inside, or null outside live play. */
export function intervalAt(
  intervals: LivePlayInterval[], frame: number,
): LivePlayInterval | null {
  return intervals.find(
    (i) => frame >= i.start_frame && (i.end_frame == null || frame <= i.end_frame),
  ) ?? null
}

export function isLive(intervals: LivePlayInterval[], frame: number): boolean {
  return intervalAt(intervals, frame) != null
}

/** Which set a frame falls in, counting intervals in time order from 1, or null
 *  outside live play. The derived metric is reported per set. */
export function setIndexAt(intervals: LivePlayInterval[], frame: number): number | null {
  const ordered = [...intervals].sort((a, b) => a.start_frame - b.start_frame)
  for (let i = 0; i < ordered.length; i++) {
    const iv = ordered[i]
    if (frame >= iv.start_frame && (iv.end_frame == null || frame <= iv.end_frame)) return i + 1
  }
  return null
}
