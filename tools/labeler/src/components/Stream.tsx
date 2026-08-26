import { memo, useEffect, useRef } from 'react'
import type { CandidateVerdict, Outcome, SetVerdict, ThrowEvent } from '../types'
import { OUTCOMES, missingFields } from '../types'
import type { PlacementTarget } from '../lib/keys'
import { anchorDrift as setDrift } from '../lib/review'
import { describe, type Who } from '../lib/roster'
import type { KindFilter, Sources, StateFilter, StreamRow } from '../lib/stream'
import { judgeable, sidesOf } from '../lib/stream'
import { formatSeconds } from '../lib/frames'
import { EventEditor } from './EventEditor'
import { Eyebrow, Kbd, Pill, SignalChoice, signalOf } from './ui'

export interface RowWho {
  thrower: Who | null
  target: Who | null
}

/** What the selected card needs to be the event's editor. */
export interface Editing {
  frame: number
  focus: PlacementTarget
  armed: boolean
  noteRef: React.RefObject<HTMLInputElement | null>
  onChange: (patch: Partial<ThrowEvent>) => void
  onFocus: (target: PlacementTarget) => void
}

interface Props {
  rows: StreamRow[]
  total: number
  sources: Sources
  onSources: (s: Sources) => void
  kind: KindFilter
  onKind: (k: KindFilter) => void
  state: StateFilter
  onState: (s: StateFilter) => void
  selectedRowId: string | null
  /** The row the list scrolls to keep in view. */
  nearestRowId: string | null
  /** How close each row is to the playhead, 0 to 1; emphasis scales with it. */
  proximity: (row: StreamRow) => number
  fps: number
  whoOf: (row: StreamRow) => RowWho
  /** The note written on a proposal's review, if any. */
  noteOf: (row: StreamRow) => string
  editing: Editing
  onSelect: (row: StreamRow) => void
  onJudge: (row: StreamRow, verdict: SetVerdict) => void
  /** Accept a proposal and say what it was, in one move. */
  onClassify: (row: StreamRow, what: Classification) => void
  onNote: (row: StreamRow, note: string) => void
  onDelete: (event: ThrowEvent) => void
}

export type Classification = 'fake' | 'pass' | Outcome

/**
 * The one list. Labels and the model's claims are both events at frames, so
 * they share it, switched on and off as sources rather than as views. It follows
 * the playhead - the card nearest the frame on screen is kept in view, and every
 * card within a second is lit in proportion to how close it is, so simultaneous
 * throws light up together - while the selected card, the one the keys edit,
 * moves only when you move it: stepping frames to find a release must not
 * change what H lands on.
 *
 * The card is where an event gets its kind, outcome and target. The selected
 * card opens into the editor; nothing about an event is edited anywhere else.
 */
export function Stream({
  rows, total, sources, onSources, kind, onKind, state, onState, selectedRowId, nearestRowId,
  proximity, fps, whoOf, noteOf, editing, onSelect, onJudge, onClassify, onNote, onDelete,
}: Props) {
  const listRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!nearestRowId) return
    const el = listRef.current?.querySelector<HTMLElement>(`[data-row="${nearestRowId}"]`)
    // Centred, so the cards either side of the nearest - a coordinated attack's
    // other throws - are in view with it.
    el?.scrollIntoView({ block: 'center' })
  }, [nearestRowId])

  const select = 'flex-1 min-w-0 bg-surface border border-rule-strong rounded px-1.5 py-1 text-[11px] text-ink-mute'

  return (
    <div className="flex flex-col min-h-0 flex-1">
      <div className="flex items-center gap-1.5 px-3 py-2 border-b border-rule">
        <SourceToggle
          on={sources.labels} label="Labels" tone="ink"
          onClick={() => onSources({ ...sources, labels: !sources.labels })}
        />
        <SourceToggle
          on={sources.model} label="Model" tone="model"
          onClick={() => onSources({ ...sources, model: !sources.model })}
        />
        <select value={kind} onChange={(e) => onKind(e.target.value as KindFilter)} className={select}>
          <option value="all">All events</option>
          <option value="open">in flight</option>
          <option value="fake">fake</option>
          <option value="pass">pass</option>
          <option value="throw">throw</option>
          {OUTCOMES.map((o) => <option key={o} value={o}>{o}</option>)}
          <option value="sets">set starts</option>
        </select>
        <select value={state} onChange={(e) => onState(e.target.value as StateFilter)} className={select}>
          <option value="all">Any state</option>
          <option value="unreviewed">unreviewed</option>
          <option value="uncertain">uncertain</option>
          <option value="incomplete">incomplete</option>
        </select>
      </div>

      <Eyebrow count={`${rows.length}/${total}`}>Events</Eyebrow>

      <div ref={listRef} className="overflow-y-auto overflow-x-hidden flex-1 min-h-0 px-3 pb-3 bg-surface-3/40">
        {rows.length === 0 ? (
          <p className="px-3 py-8 text-center text-[12px] text-ink-mute leading-relaxed">
            {total === 0
              ? <>Nothing yet. <Kbd>T</Kbd> opens a release at this frame, <Kbd>F</Kbd> a fake.</>
              : 'Nothing matches this filter.'}
          </p>
        ) : (
          rows.map((row) => (
            <Card
              key={row.id}
              row={row}
              who={whoOf(row)}
              note={noteOf(row)}
              fps={fps}
              selected={row.id === selectedRowId}
              nearest={row.id === nearestRowId}
              proximity={proximity(row)}
              editing={editing}
              onClick={() => onSelect(row)}
              onJudge={(v) => onJudge(row, v)}
              onClassify={(what) => onClassify(row, what)}
              onNote={(text) => onNote(row, text)}
              onDelete={row.event ? () => onDelete(row.event!) : null}
            />
          ))
        )}
      </div>
    </div>
  )
}

function SourceToggle({ on, label, tone, onClick }: {
  on: boolean; label: string; tone: 'ink' | 'model'; onClick: () => void
}) {
  const active = tone === 'ink' ? 'bg-ink border-ink text-surface' : 'bg-model text-surface border-model'
  return (
    <button
      aria-pressed={on}
      onClick={onClick}
      className={`px-2 py-1 rounded border text-[11px] font-medium leading-none ${
        on ? active : 'bg-surface border-rule-strong text-ink-mute hover:bg-surface-2'
      }`}
    >{label}</button>
  )
}

/** A neighbour near the playhead lifts by a transform; the selected card, by layout. */
const NEAR_SCALE = 0.05
/** How far the selected card reaches into the list's gutter on each side, in px. */
const SELECTED_REACH = 5
/** Clearance above and below the selected card, in px, past the list's usual gap. */
const SELECTED_GAP = 14

interface CardProps {
  row: StreamRow
  who: RowWho
  note: string
  fps: number
  selected: boolean
  nearest: boolean
  proximity: number
  editing: Editing
  onClick: () => void
  onJudge: (verdict: SetVerdict) => void
  onClassify: (what: Classification) => void
  onNote: (note: string) => void
  onDelete: (() => void) | null
}

/**
 * One card, whichever side it comes from. Frame · side · who threw → who it
 * reached · what it is, with the evidence underneath. The left edge names the
 * source: ink for a label, the model's blue for a claim nobody has judged, faint
 * for a rejected one. A verdict is a glyph, not a word - it is one bit, and the
 * word was eating the row. Selected, the card opens into the editor.
 */
const Card = memo(function Card({
  row, who, note, fps, selected, nearest, proximity, editing, onClick, onJudge, onClassify, onNote,
  onDelete,
}: CardProps) {
  const sides = sidesOf(row)
  const edge = row.verdict === 'rejected'
    ? 'border-l-rule-strong'
    : sides.labels ? 'border-l-ink' : 'border-l-model'
  const near = proximity > 0
  // Emphasis is lift, not colour - colour is semantic here. A card near the
  // playhead grows, its border darkens towards ink and it casts a shadow, all
  // in proportion to closeness, so two throws a few frames apart are both lifted
  // and the one under the playhead most. The selected card is lifted above all
  // of them wherever the playhead is: it is the one being edited, and it must
  // never sit smaller than a neighbour that happens to be nearer the frame. It
  // grows in layout rather than by transform - out into the gutter and taller,
  // with room above and below - so its neighbours move aside instead of being
  // covered.
  const pct = Math.round(proximity * 100)
  const lift: React.CSSProperties = selected ? {
    margin: `${SELECTED_GAP}px -${SELECTED_REACH}px ${SELECTED_GAP}px`,
    padding: '11px 15px',
    boxShadow: '0 6px 18px rgba(0,0,0,0.22)',
    position: 'relative',
    zIndex: 20,
  } : near ? {
    transform: `scale(${1 + NEAR_SCALE * proximity})`,
    transformOrigin: 'center',
    borderColor: `color-mix(in srgb, var(--ink) ${Math.round(pct * 0.7)}%, var(--rule))`,
    boxShadow: `0 ${1 + 5 * proximity}px ${4 + 14 * proximity}px rgba(0,0,0,${0.06 + 0.16 * proximity})`,
    background: `color-mix(in srgb, var(--surface-2) ${pct}%, var(--surface))`,
    position: 'relative',
    zIndex: 1 + Math.round(proximity * 10),
  } : {}
  const emphasis = selected ? 1 : proximity
  const grow = selected || near ? { fontSize: `${12 + 2 * emphasis}px` } : undefined
  const open = selected && row.event != null
  const showVerdict = (judgeable(row) && row.verdict == null) || (selected && sides.model)
  // A proposal with no event yet is classified straight from its card: choosing
  // what it was accepts it and labels it in one move.
  const classify = selected && row.proposal != null && row.event == null && row.verdict !== 'rejected'

  return (
    <div
      data-row={row.id}
      onClick={onClick}
      style={lift}
      className={`mt-2.5 rounded-md border border-l-[3px] px-3 py-2 cursor-pointer shadow-panel
        transition-[transform,box-shadow,border-color,margin,padding] duration-150
        ${edge} ${selected ? 'bg-surface-2 border-rule-strong ring-1 ring-ink' : 'bg-surface border-rule hover:border-rule-strong'}`}
    >
      <div className="grid grid-cols-[48px_1fr_auto] gap-2 items-center" style={grow}>
        <span className={`font-mono text-[1em] tabular-nums leading-4 ${emphasis > 0.5 ? 'font-semibold' : near ? 'font-medium' : ''}`}>
          {row.frame}
          <span className={`block text-[9.5px] font-normal ${nearest ? 'text-ink-mute' : 'text-ink-faint'}`}>
            {formatSeconds(row.frame / fps)}
          </span>
        </span>

        <span className="min-w-0 text-[1em] leading-4">
          {row.kind === 'set' ? <SetLine row={row} /> : <ThrowLine row={row} who={who} />}
        </span>

        <span className="flex items-center gap-1.5">
          {row.event && <Pill signal={signalOf(row.event)} />}
          {sides.model && <Verdict verdict={row.verdict} />}
        </span>
      </div>

      {showVerdict && (
        <div className="mt-1.5 flex items-center gap-1.5">
          <Choice
            tone="yes" on={row.verdict === 'accepted'} shortcut="⇧A" onClick={() => onJudge('accepted')}
            disabled={row.set != null && row.set.status !== 'confirmed'}
          >Accept</Choice>
          <Choice tone="no" on={row.verdict === 'rejected'} shortcut="⇧R" onClick={() => onJudge('rejected')}>
            Reject
          </Choice>
          {row.set && row.set.status !== 'confirmed' && (
            <span className="text-[10.5px] text-ink-faint">no start timed · <Kbd>L</Kbd> places one</span>
          )}
        </div>
      )}

      {classify && (
        <div onClick={(e) => e.stopPropagation()} className="mt-2 pt-2 border-t border-surface-2 flex flex-col gap-1.5">
          <div className="flex items-center gap-1.5 flex-wrap text-[11.5px]">
            <span className="w-12 text-ink-mute">it was</span>
            <SignalChoice signal="fake" on={false} shortcut="⇧F" onClick={() => onClassify('fake')} />
            <SignalChoice signal="pass" on={false} shortcut="P" onClick={() => onClassify('pass')} />
          </div>
          <div className="flex items-center gap-1.5 flex-wrap text-[11.5px]">
            <span className="w-12 text-ink-mute">throw</span>
            {OUTCOMES.map((o) => (
              <SignalChoice key={o} signal={o} on={false} shortcut={o[0].toUpperCase()} onClick={() => onClassify(o)} />
            ))}
          </div>
        </div>
      )}
      {selected && row.proposal && row.event == null && (
        <input
          ref={editing.noteRef}
          value={note}
          onChange={(e) => onNote(e.target.value)}
          onClick={(e) => e.stopPropagation()}
          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === 'Escape') { e.currentTarget.blur(); e.stopPropagation() } }}
          placeholder={row.verdict === 'rejected' ? 'Why not a throw (N)' : 'Note (N)'}
          className="mt-2 w-full bg-surface border border-rule-strong rounded px-2 py-1.5 text-[12px] placeholder:text-ink-faint"
        />
      )}
      {!selected && note && (
        <p className="mt-1 text-[10.5px] text-ink-mute italic truncate">“{note}”</p>
      )}
      {open && row.event && (
        <EventEditor
          event={row.event}
          frame={editing.frame}
          focus={editing.focus}
          armed={editing.armed}
          who={who}
          noteRef={editing.noteRef}
          onChange={editing.onChange}
          onFocus={editing.onFocus}
        />
      )}
      {open && onDelete && (
        <div className="mt-2 flex">
          <button
            onClick={(e) => { e.stopPropagation(); onDelete() }}
            className="ml-auto text-ink-faint hover:text-hit text-[11px]"
            title="Delete (del)"
            aria-label="Delete event"
          >delete</button>
        </div>
      )}
    </div>
  )
})

function ThrowLine({ row, who }: { row: StreamRow; who: RowWho }) {
  const e = row.event
  const c = row.proposal
  const team = e?.team ?? c?.team ?? null
  const missing = e ? missingFields(e) : []
  const drift = e && c ? e.release_frame - c.frame : 0
  return (
    <>
      <span className="flex items-center gap-1.5 min-w-0">
        <span className="text-ink-mute">{team ?? '—'}</span>
        <span className="text-ink font-medium truncate">{who.thrower ? describe(who.thrower) : '—'}</span>
        {e?.target && (
          <>
            <span className="text-ink-faint">→</span>
            <span className="text-ink truncate">{who.target ? describe(who.target) : 'target'}</span>
          </>
        )}
        {e && <Flags event={e} />}
      </span>
      <span className="block text-[10.5px] text-ink-faint truncate mt-0.5">
        {c && !e && <>wrist {c.score.toFixed(0)} · {c.participant}</>}
        {c && e && <>proposed @{c.frame}{drift ? ` · moved ${Math.abs(drift)} ${drift > 0 ? 'later' : 'earlier'}` : ''}</>}
        {e && !c && e.source === 'model' && <>from a proposal @{e.proposed_frame}</>}
        {e && !c && e.source === 'manual' && <>by hand</>}
        {missing.length > 0 && (
          <span className="text-open"> · needs {missing.join(', ')}</span>
        )}
      </span>
    </>
  )
}

function SetLine({ row }: { row: StreamRow }) {
  const set = row.set
  const iv = row.interval
  const timed = set ? set.status === 'confirmed' : false
  const drift = iv ? setDrift(iv) : null
  return (
    <>
      <span className="flex items-center gap-1.5">
        <span className="text-ink font-medium">
          {set ? `set ${row.setIndex} start` : 'your set start'}
        </span>
        {set && !timed && <span className="text-ink-mute">· balls laid out, no start timed</span>}
        {iv && <span className="text-ink-mute">· live play from {iv.start_frame}{iv.end_frame != null ? ` to ${iv.end_frame}` : ''}</span>}
      </span>
      <span className="block text-[10.5px] text-ink-faint truncate mt-0.5">
        {set?.whistle_prominence_db != null && <>whistle {set.whistle_prominence_db.toFixed(1)} dB · </>}
        {set?.sprint_frame != null && <>break at {set.sprint_frame} · </>}
        {set && <>{set.armed.max_balls} balls over {set.armed.max_spread_m.toFixed(1)} m, laid out {set.armed.start_frame}–{set.armed.end_frame}</>}
        {drift ? <> · moved {Math.abs(drift)} {drift > 0 ? 'later' : 'earlier'}</> : null}
      </span>
    </>
  )
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

/**
 * A verdict is one bit and a state of not-yet, so it is a glyph: accepted takes
 * ink, rejected is struck and faint, unreviewed is a hollow ring in the model's
 * colour - the same ring the timeline draws for the claim.
 */
function Verdict({ verdict }: { verdict: SetVerdict | CandidateVerdict | null }) {
  const title = verdict ?? 'not yet reviewed'
  if (verdict === 'accepted') {
    return <span title={title} aria-label={title} className="text-ink text-[13px] leading-none">✓</span>
  }
  if (verdict === 'rejected') {
    return <span title={title} aria-label={title} className="text-ink-faint text-[13px] leading-none">✕</span>
  }
  return (
    <span title={title} aria-label={title} className="inline-block w-[9px] h-[9px] rounded-full border-[1.5px] border-model" />
  )
}

// A verdict is yes or no, and the two buttons wear it: accept in the catch
// green, reject in the hit red, soft until pressed. The design system keeps
// colour semantic; here the semantics are exactly good and bad.
const VERDICT_TONE = {
  yes: { off: 'bg-catch-soft text-catch border-transparent enabled:hover:border-catch', on: 'bg-catch text-surface border-catch' },
  no: { off: 'bg-hit-soft text-hit border-transparent enabled:hover:border-hit', on: 'bg-hit text-surface border-hit' },
}

function Choice({ tone, on, shortcut, disabled, onClick, children }: {
  tone: 'yes' | 'no'; on: boolean; shortcut: string; disabled?: boolean; onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      onClick={(e) => { e.stopPropagation(); onClick() }}
      aria-pressed={on}
      disabled={disabled}
      className={`px-2 py-[3px] rounded text-[11px] font-medium border disabled:opacity-40 disabled:cursor-not-allowed ${
        on ? VERDICT_TONE[tone].on : VERDICT_TONE[tone].off
      }`}
    >
      {children}
      <span className={`ml-1.5 font-mono text-[10px] ${on ? 'opacity-70' : 'opacity-60'}`}>{shortcut}</span>
    </button>
  )
}
