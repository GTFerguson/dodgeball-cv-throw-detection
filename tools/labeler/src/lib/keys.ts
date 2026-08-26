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
  | { type: 'seekEdge'; edge: 'start' | 'end' }
  | { type: 'speed'; dir: 1 | -1 }
  | { type: 'mute' }
  | { type: 'resetView' }
  | { type: 'openRelease' }
  | { type: 'openFake' }
  | { type: 'markPass' }
  | { type: 'markFake' }
  | { type: 'outcome'; outcome: Outcome }
  | { type: 'snapPlayer'; playerKey: string }
  | { type: 'cycleOpen'; dir: 1 | -1 }
  // The bounds of one throw. Named for the moments they mark, because "set
  // start" in this sport is the whistle that opens a set and has nothing to do
  // with either of them.
  | { type: 'windupStart' }
  | { type: 'resolutionEnd' }
  // One pair of verdict keys for every claim the model makes. Which claim is
  // resolved by where the playhead is: a proposed throw within a few frames,
  // otherwise the detected set window the frame falls in.
  | { type: 'judge'; verdict: SetVerdict }
  // Walk the event stream: the next or previous card in view becomes the
  // selected one and the playhead goes to it.
  | { type: 'walk'; dir: 1 | -1 }
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
  /** Set while a placed box is being adjusted, which gives the arrow keys to
   *  nudging; otherwise up and down walk the stream and left and right seek. */
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
const ARROW_STEP_LARGE = 5

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
    if (uy !== 0) return { type: 'walk', dir: uy === 1 ? 1 : -1 }
    // A frame at a time: the release is a one-frame decision, and a second is
    // 25 of them. Shifted is the reach for finding the moment, not naming it.
    return { type: 'step', frames: ux * (e.shiftKey ? ARROW_STEP_LARGE : 1) }
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
    // F opens a new fake at the frame; shifted, it says the selected event -
    // most often one just accepted from a proposal - was a fake all along.
    case 'F': return { type: 'markFake' }
    case 'A': return { type: 'judge', verdict: 'accepted' }
    case 'R': return { type: 'judge', verdict: 'rejected' }
    // The shifted step keys walk the stream too, as the unshifted ones walk frames.
    case '>': return { type: 'walk', dir: 1 }
    case '<': return { type: 'walk', dir: -1 }
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
