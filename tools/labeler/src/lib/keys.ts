import type { Outcome, RefSignal, SetVerdict } from '../types'
import { FAR_KEYS, NEAR_KEYS } from './players'

// Which box a player key will fill. While one is armed the player keys own the
// keyboard, which is what lets `T` mean both "open a throw" and "far-court
// player 5": the second keypress of a two-keypress event is always a player key,
// so there is never a frame where both readings are available.
export type PlacementTarget = 'thrower' | 'target'

export type ToggleField = 'release_visible' | 'outcome_visible' | 'uncertain'

export type Command =
  | { type: 'playPause' }
  | { type: 'step'; frames: number }
  | { type: 'seek'; seconds: number }
  | { type: 'seekEdge'; edge: 'start' | 'end' }
  | { type: 'speed'; dir: 1 | -1 }
  | { type: 'mute' }
  | { type: 'resetView' }
  | { type: 'openRelease' }
  | { type: 'openFake' }
  | { type: 'markPass' }
  | { type: 'outcome'; outcome: Outcome }
  | { type: 'snapPlayer'; playerKey: string }
  | { type: 'cycleOpen'; dir: 1 | -1 }
  // The bounds of one throw. Named for the moments they mark, because "set
  // start" in this sport is the whistle that opens a set and has nothing to do
  // with either of them.
  | { type: 'windupStart' }
  | { type: 'resolutionEnd' }
  | { type: 'judgeSet'; verdict: SetVerdict }
  | { type: 'cyclePlacement' }
  | { type: 'toggle'; field: ToggleField }
  | { type: 'cycleTeam' }
  | { type: 'cycleRefSignal' }
  | { type: 'editNote' }
  | { type: 'liveStart' }
  | { type: 'liveEnd' }
  | { type: 'nudge'; dx: number; dy: number }
  | { type: 'deleteEvent' }
  | { type: 'restoreDeleted' }
  | { type: 'cancel' }

export interface KeyEventLike {
  key: string
  shiftKey: boolean
  ctrlKey: boolean
  metaKey: boolean
}

export interface KeyContext {
  /** Set while a player key would fill a box. */
  placing: PlacementTarget | null
  /** Set when a box is selected, which gives the arrow keys to nudging. */
  boxFocused: boolean
}

const OUTCOME_KEYS: Record<string, Outcome> = {
  h: 'hit', c: 'catch', b: 'block', m: 'miss', u: 'unresolved',
}

export const REF_SIGNAL_CYCLE: (RefSignal | null)[] = [null, 'seen', 'not_seen', 'not_visible']

const PLAYER_KEYS = new Set([...NEAR_KEYS, ...FAR_KEYS])

// Nudging is for the last pixel of a box, so the small step is a source pixel
// and the large one is still small enough to land inside a far-court player.
const NUDGE_SMALL = 1
const NUDGE_LARGE = 10

export function resolveKey(e: KeyEventLike, ctx: KeyContext): Command | null {
  if (e.ctrlKey || e.metaKey) {
    return e.key.toLowerCase() === 'z' ? { type: 'restoreDeleted' } : null
  }

  const key = e.key
  const lower = key.toLowerCase()

  if (key === 'Tab') return { type: 'cycleOpen', dir: e.shiftKey ? -1 : 1 }
  if (key === 'Escape') return { type: 'cancel' }

  const arrow: Record<string, [number, number]> = {
    ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1],
  }
  if (key in arrow) {
    const [ux, uy] = arrow[key]
    if (ctx.boxFocused) {
      const step = e.shiftKey ? NUDGE_LARGE : NUDGE_SMALL
      return { type: 'nudge', dx: ux * step, dy: uy * step }
    }
    if (uy !== 0) return null
    return { type: 'seek', seconds: ux * (e.shiftKey ? 5 : 1) }
  }

  // A pending placement takes the whole keyboard: the player rows are unshifted
  // letters and digits that otherwise mean other things.
  if (ctx.placing && PLAYER_KEYS.has(lower) && !e.shiftKey) {
    return { type: 'snapPlayer', playerKey: lower }
  }

  switch (key) {
    case ' ': return { type: 'playPause' }
    case ',': return { type: 'step', frames: -1 }
    case '.': return { type: 'step', frames: 1 }
    case '[': return { type: 'step', frames: -10 }
    case ']': return { type: 'step', frames: 10 }
    case 'Home': return { type: 'seekEdge', edge: 'start' }
    case 'End': return { type: 'seekEdge', edge: 'end' }
    case '-': return { type: 'speed', dir: -1 }
    case '=': return { type: 'speed', dir: 1 }
    case '0': return { type: 'resetView' }
    case 'Delete': case 'Backspace': return { type: 'deleteEvent' }
    case 'M': return { type: 'mute' }
    // Shifted, because a verdict on a detection is a rarer act than any of the
    // labelling keys and must not be one keypress away from a mistyped outcome.
    case 'A': return { type: 'judgeSet', verdict: 'accepted' }
    case 'R': return { type: 'judgeSet', verdict: 'rejected' }
  }

  if (lower in OUTCOME_KEYS && !e.shiftKey) {
    return { type: 'outcome', outcome: OUTCOME_KEYS[lower] }
  }

  if (e.shiftKey) return null

  switch (lower) {
    case 't': return { type: 'openRelease' }
    case 'f': return { type: 'openFake' }
    case 'p': return { type: 'markPass' }
    case 's': return { type: 'windupStart' }
    case 'e': return { type: 'resolutionEnd' }
    case 'g': return { type: 'cyclePlacement' }
    case 'v': return { type: 'toggle', field: 'release_visible' }
    case 'o': return { type: 'toggle', field: 'outcome_visible' }
    case 'a': return { type: 'toggle', field: 'uncertain' }
    case 'd': return { type: 'cycleTeam' }
    case 'x': return { type: 'cycleRefSignal' }
    case 'n': return { type: 'editNote' }
    case 'l': return { type: 'liveStart' }
    case 'k': return { type: 'liveEnd' }
  }

  return null
}
