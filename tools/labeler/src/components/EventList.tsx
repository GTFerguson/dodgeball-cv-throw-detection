import { memo, useMemo, useState } from 'react'
import type { EventKind, Outcome, ThrowEvent } from '../types'
import { EVENT_KINDS, OUTCOMES, missingFields } from '../types'
import { Eyebrow, Pill, signalOf } from './ui'

interface RowProps {
  event: ThrowEvent
  selected: boolean
  onClick: () => void
  onDelete: () => void
}

/** Terse and consistent, so a row reads at a glance without a key. */
function Flags({ event }: { event: ThrowEvent }) {
  const marks: [string, string, string][] = []
  if (event.uncertain) marks.push(['!', 'Uncertain', 'text-open font-bold'])
  if (!event.release_visible) marks.push(['◌', 'Release not visible', 'text-ink-faint'])
  if (!event.outcome_visible) marks.push(['◌', 'Outcome not visible', 'text-ink-faint'])
  if (event.ref_signal === 'seen') marks.push(['§', 'Referee signal seen', 'text-ink-faint'])
  if (!marks.length) return null
  return (
    <span className="flex gap-1 text-[11px]">
      {marks.map(([glyph, title, cls], i) => (
        <span key={i} title={title} className={cls}>{glyph}</span>
      ))}
    </span>
  )
}

const Row = memo(function Row({ event, selected, onClick, onDelete }: RowProps) {
  const missing = missingFields(event)
  return (
    <div
      onClick={onClick}
      className={`grid grid-cols-[52px_1fr_auto] gap-2 items-center px-3 py-1.5 cursor-pointer
        border-l-[3px] border-b border-b-surface-2 group
        ${selected ? 'bg-surface-2 border-l-ink' : 'border-l-transparent hover:bg-surface-2'}`}
    >
      <span className="font-mono text-[12px] tabular-nums">{event.release_frame}</span>
      <span className="flex items-center gap-1.5 text-[11.5px] text-ink-mute min-w-0">
        <span>{event.team ?? '—'}</span>
        {event.target && <span className="text-ink-faint">→</span>}
        {event.target && <span>target</span>}
        <Flags event={event} />
        {missing.length > 0 && (
          <span className="text-[10.5px] text-open truncate" title={`missing: ${missing.join(', ')}`}>
            {missing.length} missing
          </span>
        )}
      </span>
      <span className="flex items-center gap-1.5">
        <Pill signal={signalOf(event)} />
        <button
          onClick={(e) => { e.stopPropagation(); onDelete() }}
          className="text-ink-faint hover:text-hit text-[11px] opacity-0 group-hover:opacity-100"
          title="Delete (del)"
          aria-label="Delete event"
        >✕</button>
      </span>
    </div>
  )
})

type Filter = 'all' | 'open' | EventKind | Outcome

const isKind = (f: Filter): f is EventKind => (EVENT_KINDS as string[]).includes(f)

interface Props {
  events: ThrowEvent[]
  selectedId: string | null
  onSelect: (e: ThrowEvent) => void
  onDelete: (e: ThrowEvent) => void
}

export function EventList({ events, selectedId, onSelect, onDelete }: Props) {
  const [outcome, setOutcome] = useState<Filter>('all')
  const [flag, setFlag] = useState<'all' | 'uncertain' | 'incomplete'>('all')

  const filtered = useMemo(
    () =>
      events.filter((e) => {
        if (outcome === 'open' && e.status !== 'open') return false
        if (isKind(outcome) && e.kind !== outcome) return false
        if (outcome !== 'all' && outcome !== 'open' && !isKind(outcome)
            && e.outcome !== outcome) return false
        if (flag === 'uncertain' && !e.uncertain) return false
        if (flag === 'incomplete' && missingFields(e).length === 0) return false
        return true
      }),
    [events, outcome, flag],
  )

  const open = events.filter((e) => e.status === 'open')
  const select = 'flex-1 min-w-0 bg-surface border border-rule-strong rounded px-1.5 py-1 text-[11px] text-ink-mute'

  return (
    <div className="flex flex-col min-h-0 flex-1">
      {open.length > 0 && (
        <div className="border-b border-rule">
          <Eyebrow count={open.length}>In flight</Eyebrow>
          <div className="px-2 pb-2 flex flex-col gap-1.5">
            {open.map((e) => (
              <div
                key={e.id}
                onClick={() => onSelect(e)}
                className={`flex items-center gap-2 px-2 py-2 rounded cursor-pointer bg-open-soft
                  border border-open-soft border-l-[3px] border-l-open
                  ${e.id === selectedId ? 'ring-1 ring-inset ring-open' : ''}`}
              >
                <span className="font-mono text-[12px] font-medium tabular-nums">{e.release_frame}</span>
                <span className="text-[11.5px] text-ink-mute">{e.team ?? 'team unset'}</span>
                <span className="ml-auto text-[10px] font-semibold uppercase tracking-[.07em] text-open">open</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="flex gap-1.5 px-3 py-2 border-b border-rule">
        <select value={outcome} onChange={(e) => setOutcome(e.target.value as Filter)} className={select}>
          <option value="all">All events</option>
          <option value="open">in flight</option>
          <option value="fake">fake</option>
          <option value="pass">pass</option>
          <option value="throw">throw</option>
          {OUTCOMES.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
        <select value={flag} onChange={(e) => setFlag(e.target.value as typeof flag)} className={select}>
          <option value="all">Any state</option>
          <option value="uncertain">uncertain</option>
          <option value="incomplete">incomplete</option>
        </select>
      </div>

      <Eyebrow count={`${filtered.length}/${events.length}`}>Events</Eyebrow>

      <div className="overflow-y-auto flex-1 min-h-0">
        {filtered.length === 0 ? (
          <p className="px-3 py-8 text-center text-[12px] text-ink-mute">
            {events.length === 0
              ? 'No throws yet. Scrub to a release and press T.'
              : 'Nothing matches this filter.'}
          </p>
        ) : (
          filtered.map((e) => (
            <Row
              key={e.id}
              event={e}
              selected={e.id === selectedId}
              onClick={() => onSelect(e)}
              onDelete={() => onDelete(e)}
            />
          ))
        )}
      </div>
    </div>
  )
}
