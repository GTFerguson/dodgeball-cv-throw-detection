import type { EventKind, Outcome, RefSignal, Team, ThrowEvent } from '../types'
import { EVENT_KINDS, OUTCOMES, REF_SIGNALS, TERMINAL_KINDS, missingFields } from '../types'
import { kindAfterOutcome } from '../lib/events'
import type { PlacementTarget } from '../lib/keys'
import { describe, type Who } from '../lib/roster'
import { Kbd, SignalChoice } from './ui'

export interface EditorProps {
  event: ThrowEvent
  frame: number
  focus: PlacementTarget
  armed: boolean
  /** Who the thrower and target boxes are, looked up from the roster. */
  who: { thrower: Who | null; target: Who | null }
  noteRef: React.RefObject<HTMLInputElement | null>
  onChange: (patch: Partial<ThrowEvent>) => void
  onFocus: (target: PlacementTarget) => void
}

// A terminal kind resolves the event and drops any outcome, which could only
// have been a claim about a ball that reached the far side.
function kindPatch(kind: EventKind): Partial<ThrowEvent> {
  return TERMINAL_KINDS.includes(kind)
    ? { kind, status: 'closed', outcome: null }
    : { kind }
}

const CHOICE = 'px-2 py-[3px] rounded text-[11px] border'
const ON = 'bg-ink border-ink text-surface'
const OFF = 'bg-surface border-rule-strong text-ink-mute hover:bg-surface-2'

/**
 * The form an event is edited in. It lives inside the event's own card in the
 * stream - the card is where an event gets its kind, outcome and target, not a
 * panel somewhere else - so it carries no header of its own.
 */
export function EventEditor({ event, frame, focus, armed, who, noteRef, onChange, onFocus }: EditorProps) {
  const missing = missingFields(event)

  const frameRow = (label: string, k: string, value: number | null) => (
    <div className="flex items-center gap-2 text-[12px]">
      <Kbd>{k}</Kbd>
      <span className="w-14 text-ink-mute">{label}</span>
      <span className={`font-mono tabular-nums ${
        value == null ? 'text-ink-faint' : value === frame ? 'text-ink font-medium' : 'text-ink'
      }`}>{value ?? '—'}</span>
    </div>
  )

  const boxRow = (target: PlacementTarget) => {
    const placed = event[target]
    const person = who[target]
    return (
      <button
        onClick={(e) => { e.stopPropagation(); onFocus(target) }}
        className={`flex items-center gap-2 text-left px-1 py-0.5 rounded text-[12px] w-full ${
          focus === target ? 'bg-surface-2' : ''
        }`}
      >
        <span className="w-[68px] text-ink-mute">{target}</span>
        {placed ? (
          <span className="text-[11.5px] text-ink">
            <span className="font-medium">{person ? describe(person) : '—'}</span>
            <span className="font-mono text-[10.5px] tabular-nums text-ink-mute"> @{placed.frame}</span>
            <span className="ml-1.5 text-[10.5px] text-ink-faint">
              {placed.source}{placed.adjusted ? '+adj' : ''}
            </span>
          </span>
        ) : (
          <span className="text-[11px] text-ink-faint">
            {focus === target && armed ? 'press a player key or drag' : 'unset'}
          </span>
        )}
      </button>
    )
  }

  return (
    <div onClick={(e) => e.stopPropagation()} className="pt-2 mt-2 border-t border-surface-2">
      <div className="flex flex-col gap-2">
        <div className="flex flex-col gap-1">
          {frameRow('start', 'S', event.start_frame)}
          {frameRow('release', 'T', event.release_frame)}
          {frameRow('end', 'E', event.end_frame)}
        </div>

        <div className="flex flex-col gap-0.5 pt-1 border-t border-surface-2">
          {boxRow('thrower')}
          {boxRow('target')}
        </div>

        <div className="flex items-center gap-2 flex-wrap text-[12px] pt-1 border-t border-surface-2">
          <Kbd>D</Kbd>
          <span className="w-10 text-ink-mute">team</span>
          {(['near', 'far'] as Team[]).map((t) => (
            <button
              key={t}
              onClick={() => onChange({ team: t, team_source: 'override' })}
              className={`${CHOICE} ${event.team === t ? ON : OFF}`}
            >{t}</button>
          ))}
          <span className="text-[10.5px] text-ink-faint">{event.team_source}</span>
        </div>

        <div className="flex items-center gap-1.5 flex-wrap text-[12px]">
          <Kbd>P</Kbd>
          <span className="w-10 text-ink-mute">kind</span>
          {EVENT_KINDS.map((k: EventKind) => (
            <SignalChoice
              key={k}
              signal={k === 'throw' ? (event.outcome ?? 'open') : k}
              on={event.kind === k}
              shortcut={k === 'fake' ? '⇧F' : k === 'pass' ? 'P' : undefined}
              onClick={() => onChange(kindPatch(k))}
            >{k}</SignalChoice>
          ))}
          {event.kind == null && (
            <span className="text-[10.5px] text-ink-faint">destination undecided</span>
          )}
        </div>

        {event.kind !== 'fake' && (
          <div className="flex items-center gap-1.5 flex-wrap text-[12px]">
            <span className="w-[52px] text-ink-mute">outcome</span>
            {OUTCOMES.map((o: Outcome) => (
              <SignalChoice
                key={o}
                signal={o}
                on={event.outcome === o}
                shortcut={o[0].toUpperCase()}
                onClick={() => onChange({
                  outcome: o, status: 'closed', kind: kindAfterOutcome(event.kind, o),
                })}
              />
            ))}
          </div>
        )}

        <div className="flex items-center gap-1.5 flex-wrap text-[12px]">
          <Kbd>X</Kbd>
          <span className="w-10 text-ink-mute">referee</span>
          {REF_SIGNALS.map((r: RefSignal) => (
            <button
              key={r}
              onClick={() => onChange({ ref_signal: event.ref_signal === r ? null : r })}
              className={`${CHOICE} ${event.ref_signal === r ? ON : OFF}`}
            >{r.replace('_', ' ')}</button>
          ))}
        </div>

        <div className="flex items-center gap-3 flex-wrap text-[11.5px] text-ink-mute">
          {([
            ['release_visible', 'V', 'release seen'],
            ['outcome_visible', 'O', 'outcome seen'],
            ['uncertain', 'A', 'uncertain'],
          ] as const).map(([field, k, label]) => (
            <label key={field} className="flex items-center gap-1.5 cursor-pointer">
              <input
                type="checkbox"
                checked={event[field]}
                onChange={(e) => onChange({ [field]: e.target.checked })}
                className="accent-[var(--ink)]"
              />
              <Kbd>{k}</Kbd> {label}
            </label>
          ))}
        </div>

        <input
          ref={noteRef}
          value={event.note}
          onChange={(e) => onChange({ note: e.target.value })}
          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === 'Escape') { e.currentTarget.blur(); e.stopPropagation() } }}
          placeholder="Note (N)"
          className="bg-surface border border-rule-strong rounded px-2 py-1.5 text-[12px] placeholder:text-ink-faint"
        />

        {missing.length > 0 && (
          <p className="text-[11px] text-open">Still needed: {missing.join(', ')}</p>
        )}
      </div>
    </div>
  )
}
