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
