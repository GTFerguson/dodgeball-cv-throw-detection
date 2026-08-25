import type { EventKind, Outcome, RefSignal, Team, ThrowEvent } from '../types'
import { EVENT_KINDS, OUTCOMES, REF_SIGNALS, TERMINAL_KINDS, missingFields } from '../types'
import { kindAfterOutcome } from '../lib/events'
import type { PlacementTarget } from '../lib/keys'
import { Eyebrow, Kbd, Pill, signalOf } from './ui'

interface Props {
  event: ThrowEvent | null
  frame: number
  focus: PlacementTarget
  armed: boolean
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

export function EventPanel({ event, frame, focus, armed, noteRef, onChange, onFocus }: Props) {
  if (!event) {
    return (
      <div className="px-3 py-4 border-b border-rule text-[12px] text-ink-mute leading-relaxed">
        No event selected. <Kbd>T</Kbd> opens a release at this frame, <Kbd>F</Kbd> marks a fake.
      </div>
    )
  }

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
    return (
      <button
        onClick={() => onFocus(target)}
        className={`flex items-center gap-2 text-left px-1 py-0.5 rounded text-[12px] w-full ${
          focus === target ? 'bg-surface-2' : ''
        }`}
      >
        <span className="w-[68px] text-ink-mute">{target}</span>
        {placed ? (
          <span className="font-mono text-[11px] tabular-nums text-ink">
            {Math.round(placed.box.x1)},{Math.round(placed.box.y1)}–
            {Math.round(placed.box.x2)},{Math.round(placed.box.y2)}
            <span className="text-ink-mute"> @{placed.frame}</span>
            <span className="ml-1.5 text-ink-faint">
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
    <div className="border-b border-rule">
      <Eyebrow count={<span className="font-mono">{event.id}</span>}>Selected</Eyebrow>

      <div className="px-3 pb-3 flex flex-col gap-2">
        <Pill signal={signalOf(event)} />

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
            <button
              key={k}
              onClick={() => onChange(kindPatch(k))}
              className={`${CHOICE} ${event.kind === k ? ON : OFF}`}
            >{k}</button>
          ))}
          {event.kind == null && (
            <span className="text-[10.5px] text-ink-faint">destination undecided</span>
          )}
        </div>

        {event.kind !== 'fake' && (
          <div className="flex items-center gap-1.5 flex-wrap text-[12px]">
            <span className="w-[52px] text-ink-mute">outcome</span>
            {OUTCOMES.map((o: Outcome) => (
              <button
                key={o}
                onClick={() => onChange({
                  outcome: o, status: 'closed', kind: kindAfterOutcome(event.kind, o),
                })}
                className={`${CHOICE} ${event.outcome === o ? ON : OFF}`}
              >{o}</button>
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
