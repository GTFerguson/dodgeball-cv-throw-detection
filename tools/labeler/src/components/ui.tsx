import type { Outcome, ThrowEvent } from '../types'

/**
 * Colour is semantic only: a token here means an outcome class, a live state, or
 * whose claim a mark represents. Nothing in the chrome is tinted, so a coloured
 * pixel always carries information.
 */
export type Signal = Outcome | 'fake' | 'pass' | 'open'

export function signalOf(event: ThrowEvent): Signal {
  if (event.kind === 'fake') return 'fake'
  if (event.kind === 'pass') return 'pass'
  if (event.status === 'open' || !event.outcome) return 'open'
  return event.outcome
}

/** CSS variable for a signal's deep tone, for canvas and SVG. */
export const SIGNAL_VAR: Record<Signal, string> = {
  hit: 'var(--sig-hit)',
  catch: 'var(--sig-catch)',
  block: 'var(--sig-block)',
  miss: 'var(--sig-miss)',
  unresolved: 'var(--ink-faint)',
  // Only outcomes carry an outcome colour, and a pass has no outcome: the ball
  // never reached the far side for anything to happen to it.
  pass: 'var(--ink-faint)',
  fake: 'var(--sig-open)',
  open: 'var(--sig-open)',
}

const PILL: Record<Signal, string> = {
  hit: 'bg-hit-soft text-hit border-transparent',
  catch: 'bg-catch-soft text-catch border-transparent',
  block: 'bg-block-soft text-block border-transparent',
  miss: 'bg-miss-soft text-miss border-transparent',
  // Absence of knowledge is shown as absence of ink.
  unresolved: 'bg-transparent text-ink-faint border-dashed border-rule-strong',
  pass: 'bg-transparent text-ink-faint border-rule-strong',
  fake: 'bg-transparent text-open border-open',
  open: 'bg-open-soft text-open border-transparent',
}

export function Pill({ signal, children }: { signal: Signal; children?: React.ReactNode }) {
  return (
    <span
      className={`border px-1.5 py-[3px] rounded text-[10px] font-semibold uppercase tracking-[.05em] whitespace-nowrap ${PILL[signal]}`}
    >
      {children ?? (signal === 'open' ? 'in flight' : signal)}
    </span>
  )
}

export function Kbd({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="font-mono text-[10.5px] leading-none px-1.5 py-[3px] rounded bg-surface border border-rule-strong border-b-2 text-ink">
      {children}
    </kbd>
  )
}

export function Eyebrow({ children, count }: { children: React.ReactNode; count?: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2 px-3 py-2 text-[10.5px] font-semibold uppercase tracking-[.09em] text-ink-faint">
      {children}
      {count != null && <span className="ml-auto font-mono text-[11px] text-ink-mute">{count}</span>}
    </div>
  )
}

// A choice that means an outcome or a kind wears that signal's colour, soft
// until chosen and full once it is - the same tones as the pill it produces, so
// what you press and what you get read as one thing.
const CHOICE_OFF: Record<Signal, string> = {
  hit: 'bg-hit-soft text-hit border-transparent hover:border-hit',
  catch: 'bg-catch-soft text-catch border-transparent hover:border-catch',
  block: 'bg-block-soft text-block border-transparent hover:border-block',
  miss: 'bg-miss-soft text-miss border-transparent hover:border-miss',
  unresolved: 'bg-transparent text-ink-faint border-dashed border-rule-strong hover:border-ink',
  pass: 'bg-transparent text-ink-mute border-rule-strong hover:border-ink',
  fake: 'bg-transparent text-open border-open hover:bg-open-soft',
  open: 'bg-open-soft text-open border-transparent',
}

const CHOICE_ON: Record<Signal, string> = {
  hit: 'bg-hit text-surface border-hit',
  catch: 'bg-catch text-surface border-catch',
  block: 'bg-block text-surface border-block',
  miss: 'bg-miss text-surface border-miss',
  unresolved: 'bg-ink text-surface border-ink border-dashed',
  pass: 'bg-ink text-surface border-ink',
  fake: 'bg-open text-surface border-open',
  open: 'bg-open text-surface border-open',
}

export function SignalChoice({ signal, on, shortcut, onClick, children }: {
  signal: Signal
  on: boolean
  shortcut?: string
  onClick: () => void
  children?: React.ReactNode
}) {
  return (
    <button
      onClick={(e) => { e.stopPropagation(); onClick() }}
      aria-pressed={on}
      className={`px-2 py-[3px] rounded text-[11px] font-medium border ${on ? CHOICE_ON[signal] : CHOICE_OFF[signal]}`}
    >
      {children ?? signal}
      {shortcut && (
        <span className={`ml-1.5 font-mono text-[10px] ${on ? 'opacity-70' : 'opacity-60'}`}>{shortcut}</span>
      )}
    </button>
  )
}

