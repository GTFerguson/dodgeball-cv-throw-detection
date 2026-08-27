import { useMemo, useState } from 'react'
import type { RosterParticipant, SetTimelineFile, Team, ThrowEvent } from '../types'
import { OUTCOMES } from '../types'
import { formatSeconds } from '../lib/frames'
import type { RosterIndex } from '../lib/roster'
import { setMarks } from '../lib/sets'
import {
  defenceRate, hitRate, impact, rankPlayers, RANKS, thrownAt,
  type Rank, type Tally, type TallyLine,
} from '../lib/tally'
import { Eyebrow, Pill, signalOf } from './ui'

interface Props {
  index: RosterIndex
  sets: SetTimelineFile | null
  frame: number
  fps: number
  /** What the labels say each player did, by participant id. */
  tallies: Map<string, Tally>
  /** The player key that would snap a box on this player on the frame on
   *  screen, if they are on it and in play. */
  keyOf: (p: RosterParticipant) => string | null
  /** The player the stage is showing, if the annotator asked for one. */
  spotlight: string | null
  onSpotlight: (p: RosterParticipant) => void
  onSelectEvent: (e: ThrowEvent) => void
}

type SetChoice = 'any' | number
type TeamChoice = 'any' | Team

/**
 * Who played, as a list. One row per person the identity pass saw on the court
 * while a set was live; the twelve with a number read lead, and the fragments
 * it could not name follow, because "this person played" is true of them even
 * when "who" has no answer. Filtered by set and by side, ranked by what the
 * labels say they did, and each row opens into that record.
 *
 * Nothing here is edited. A wrong join is a rule to fix in the identity pass,
 * not a row to correct, so the list is display and says what the roster says.
 */
export function Roster({
  index, sets, frame, fps, tallies, keyOf, spotlight, onSpotlight, onSelectEvent,
}: Props) {
  const [set, setSet] = useState<SetChoice>('any')
  const [team, setTeam] = useState<TeamChoice>('any')
  const [rank, setRank] = useState<Rank>('roster')
  const [open, setOpen] = useState<string | null>(null)

  const setChoices = useMemo(
    () => setMarks(sets).map((m, i) => ({ i, label: `set ${i + 1}`, timed: m.timed })).filter((s) => s.timed),
    [sets],
  )
  const everyone = useMemo(() => index.played(), [index])
  const excess = useMemo(() => index.excess(), [index])
  const players = useMemo(() => rankPlayers(
    index.played(team === 'any' ? undefined : team, set === 'any' ? undefined : set), tallies, rank,
  ), [index, team, set, tallies, rank])

  const select = 'flex-1 min-w-0 bg-surface border border-rule-strong rounded px-1.5 py-1 text-[11px] text-ink-mute'

  return (
    <div className="flex flex-col min-h-0 flex-1">
      <div className="flex items-center gap-1.5 px-3 py-2 border-b border-rule">
        <select
          value={set === 'any' ? 'any' : String(set)}
          onChange={(e) => setSet(e.target.value === 'any' ? 'any' : Number(e.target.value))}
          className={select}
          title="Which set"
        >
          <option value="any">Played any set</option>
          {setChoices.map((s) => <option key={s.i} value={s.i}>{s.label}</option>)}
        </select>
        <select value={team} onChange={(e) => setTeam(e.target.value as TeamChoice)} className={select} title="Which side">
          <option value="any">Both sides</option>
          <option value="near">near</option>
          <option value="far">far</option>
        </select>
        <select value={rank} onChange={(e) => setRank(e.target.value as Rank)} className={select} title="Ranked by">
          {RANKS.map((r) => <option key={r} value={r}>{r === 'roster' ? 'Roster order' : `by ${r}`}</option>)}
        </select>
      </div>

      <Eyebrow count={players.length === everyone.length ? `all ${everyone.length}` : `${players.length} of ${everyone.length}`}>
        Players
      </Eyebrow>

      <div className="overflow-y-auto overflow-x-hidden flex-1 min-h-0 px-3 pb-3 bg-surface-3/40">
        {index.empty ? (
          <p className="px-3 py-8 text-center text-[12px] text-ink-mute leading-relaxed">
            No roster for this clip — run scripts/identify_players.py.
          </p>
        ) : players.length === 0 ? (
          <p className="px-3 py-8 text-center text-[12px] text-ink-mute leading-relaxed">
            Nobody matches this filter.
          </p>
        ) : (
          players.map((p) => (
            <Row
              key={p.id}
              player={p}
              name={index.nameOf(p.team, p.number)}
              playerKey={keyOf(p)}
              onScreen={index.trackOnFrame(p.id, frame) != null}
              tally={tallies.get(p.id) ?? null}
              fps={fps}
              open={open === p.id}
              spotlit={spotlight === p.id}
              onToggle={() => setOpen((o) => (o === p.id ? null : p.id))}
              onSpotlight={() => onSpotlight(p)}
              onSelectEvent={onSelectEvent}
            />
          ))
        )}
        {excess.length > 0 && (
          <p className="mt-3 px-1 text-[10.5px] text-ink-mute leading-relaxed">
            {excess.length} {excess.length === 1 ? 'piece' : 'pieces'} not counted: in play while the side already
            had six on the floor — a second track on one player, or a misrole. In the roster as excess.
          </p>
        )}
      </div>
    </div>
  )
}

/** `#7 Chalmers`, `#13`, or `no number read` for a fragment - as much as is known. */
export function nameLine(p: RosterParticipant, name: string | null): string {
  if (p.number == null) return 'no number read'
  return name ? `#${p.number} ${name}` : `#${p.number}`
}

interface RowProps {
  player: RosterParticipant
  name: string | null
  playerKey: string | null
  onScreen: boolean
  tally: Tally | null
  fps: number
  open: boolean
  spotlit: boolean
  onToggle: () => void
  onSpotlight: () => void
  onSelectEvent: (e: ThrowEvent) => void
}

/**
 * One person. Who they are · which side · when they were on the floor, and at
 * the right what the labels have them throwing. The name is a button: it takes
 * the stage to them, on this frame if they are on it and at their first frame
 * in play if not. The rest of the row opens the record underneath.
 */
function Row({
  player, name, playerKey, onScreen, tally, fps, open, spotlit, onToggle, onSpotlight, onSelectEvent,
}: RowProps) {
  const span = `${formatSeconds(player.start_frame / fps)}–${formatSeconds(player.end_frame / fps)}`
  return (
    <div
      data-player={player.id}
      role="button"
      aria-expanded={open}
      onClick={onToggle}
      className={`mt-2.5 rounded-md border border-l-[3px] px-3 py-2 cursor-pointer shadow-panel
        ${open ? 'bg-surface-2 border-rule-strong border-l-ink' : 'bg-surface border-rule border-l-rule-strong hover:border-rule-strong'}`}
    >
      <div className="grid grid-cols-[1fr_auto] gap-2 items-center">
        <span className="min-w-0 leading-4">
          <button
            onClick={(e) => { e.stopPropagation(); onSpotlight() }}
            aria-pressed={spotlit}
            title={onScreen ? 'Show on the frame' : 'Go to their first frame in play'}
            className={`text-[12px] font-medium rounded px-1 -mx-1 ${
              spotlit ? 'bg-ink text-surface' : player.number == null ? 'text-ink-mute hover:bg-surface-2' : 'text-ink hover:bg-surface-2'
            }`}
          >
            {playerKey && <span className="font-mono mr-1.5">{playerKey.toUpperCase()}</span>}
            {nameLine(player, name)}
          </button>
          <span className="block text-[10.5px] text-ink-mute mt-0.5">
            {player.team ?? 'side unknown'}
            <span className="font-mono tabular-nums"> · {span}</span>
            {onScreen && <span> · on screen</span>}
          </span>
        </span>
        {tally ? <Scoreboard tally={tally} /> : <span className="text-[11px] text-ink-mute">no events</span>}
      </div>

      {open && <Record player={player} tally={tally} fps={fps} onSelectEvent={onSelectEvent} />}
    </div>
  )
}

/**
 * The three numbers a card is read for: what their play was worth, how often
 * their throws found someone, and how often a throw at them failed to.
 *
 * Impact leads because it is the only one of the three in a unit the sport
 * cares about - players eliminated, which is what wins a set - and the two
 * rates follow as the context for it, not folded into it. Both are shown as
 * fractions rather than percentages so a record states its own sample size: at
 * a set of twenty-nine throws, `1/1` and `4/7` are not the same claim and a
 * pair of percentages would say they were.
 *
 * Nothing here is coloured. A signal colour means an outcome class, and good
 * or bad is not one - the sign on the impact is what says which way it went.
 */
function Scoreboard({ tally }: { tally: Tally }) {
  const i = impact(tally)
  const hit = hitRate(tally)
  const def = defenceRate(tally)
  return (
    <span className="flex items-start gap-2.5 text-right">
      <Stat value={i.involvements > 0 ? signed(i.net) : '—'} label="impact" lead />
      <Stat value={hit ? `${hit.hits}/${hit.of}` : '—'} label="hit" />
      <Stat value={def ? `${def.survived}/${def.of}` : '—'} label="def" />
    </span>
  )
}

/** One scoreboard cell: the number, and what it is. */
function Stat({ value, label, lead }: { value: string; label: string; lead?: boolean }) {
  return (
    <span className="block leading-4">
      <span className={`block font-mono tabular-nums ${lead ? 'text-[13px] text-ink' : 'text-[11px] text-ink-mute'}`}>
        {value}
      </span>
      <span className="block text-[9px] uppercase tracking-[.08em] text-ink-mute">{label}</span>
    </span>
  )
}

/** `+2`, `0`, `-1` — the sign is the whole point, so a positive keeps its. */
function signed(n: number): string {
  return n > 0 ? `+${n}` : String(n)
}

/**
 * What the labels say this person did, with the scope of every number beside
 * it: thrown, and thrown at, are two records of one player and are kept apart.
 */
function Record({ player, tally, fps, onSelectEvent }: {
  player: RosterParticipant; tally: Tally | null; fps: number; onSelectEvent: (e: ThrowEvent) => void
}) {
  const played = player.played_sets.map((s) => `set ${s + 1}`).join(', ')
  const tracks = `${player.track_ids.length} ${player.track_ids.length === 1 ? 'track' : 'tracks'}`
  return (
    <div onClick={(e) => e.stopPropagation()} className="mt-2 pt-2 border-t border-surface-3 flex flex-col gap-2 text-[11px] cursor-default">
      <div className="text-ink-mute">played {played || 'no set'} · {tracks}</div>

      {!tally ? (
        <div className="text-ink-mute">not in any labelled event</div>
      ) : (
        <>
          <Line label="threw">
            <Count n={tally.throws} what="throws" />
            {OUTCOMES.map((o) => tally.outcomes[o] > 0 && (
              <Pill key={o} signal={o}>{o} {tally.outcomes[o]}</Pill>
            ))}
            {tally.passes > 0 && <Pill signal="pass">pass {tally.passes}</Pill>}
            {tally.fakes > 0 && <Pill signal="fake">fake {tally.fakes}</Pill>}
          </Line>
          <Line label="thrown at">
            {thrownAt(tally) + tally.received === 0
              ? <span className="text-ink-mute">never</span>
              : (
                <>
                  {tally.against.hit > 0 && <Pill signal="hit">hit {tally.against.hit}</Pill>}
                  {tally.against.catch > 0 && <Pill signal="catch">catch {tally.against.catch}</Pill>}
                  {tally.against.block > 0 && <Pill signal="block">block {tally.against.block}</Pill>}
                  {tally.against.dodge > 0 && <Pill signal="miss">dodged {tally.against.dodge}</Pill>}
                  {tally.received > 0 && <Pill signal="pass">received {tally.received}</Pill>}
                </>
              )}
          </Line>
          <Ledger tally={tally} />
          <ul className="flex flex-col gap-0.5 mt-0.5">
            {tally.events.map((l) => <EventLine key={`${l.eventId}-${l.role}`} line={l} fps={fps} onSelect={onSelectEvent} />)}
          </ul>
        </>
      )}
    </div>
  )
}

/**
 * How the impact was made, in the unit it is counted in.
 *
 * The two halves are shown because they are the two ways a player changes the
 * count and a net hides which one they did: +1 off and 0 def is a thrower, 0
 * off and +1 def is someone who caught. The involvement count is beside it for
 * the reason a fraction is used elsewhere - a net of +2 from three involvements
 * and one from twelve are different players, and the number alone cannot say so.
 */
function Ledger({ tally }: { tally: Tally }) {
  const i = impact(tally)
  if (i.involvements === 0) return null
  return (
    <Line label="worth">
      <span className="font-mono tabular-nums text-ink">{signed(i.net)}</span>
      <span className="text-ink-mute">{Math.abs(i.net) === 1 ? 'player' : 'players'}</span>
      <span className="font-mono tabular-nums text-ink-mute">
        ({signed(i.offence)} throwing, {signed(i.defence)} thrown at)
      </span>
      <span className="text-ink-mute">
        over {i.involvements} {i.involvements === 1 ? 'involvement' : 'involvements'}
      </span>
    </Line>
  )
}

function Line({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      <span className="w-14 text-ink-mute">{label}</span>
      {children}
    </div>
  )
}

function Count({ n, what }: { n: number; what: string }) {
  return <span className="font-mono tabular-nums text-ink">{n} {n === 1 ? what.replace(/s$/, '') : what}</span>
}

/** One event this person was in: its frame, which end of it they were, what it was. */
function EventLine({ line, fps, onSelect }: { line: TallyLine; fps: number; onSelect: (e: ThrowEvent) => void }) {
  return (
    <li>
      <button
        onClick={() => onSelect(line.event)}
        title="Select this event"
        className="w-full grid grid-cols-[48px_1fr_auto] gap-2 items-center text-left rounded px-1 -mx-1 py-0.5 hover:bg-surface-3"
      >
        <span className="font-mono tabular-nums text-ink leading-4">
          {line.frame}
          <span className="block text-[9.5px] text-ink-faint">{formatSeconds(line.frame / fps)}</span>
        </span>
        <span className="text-ink-mute">{line.role === 'thrower' ? 'threw' : 'thrown at'}</span>
        <Pill signal={signalOf(line.event)} />
      </button>
    </li>
  )
}
