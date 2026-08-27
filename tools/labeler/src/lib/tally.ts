import type { Outcome, PlacedBox, RosterParticipant, ThrowEvent } from '../types'
import { OUTCOMES } from '../types'

/**
 * What the labels say each player did.
 *
 * Labels store boxes, never identity, so a player's record is assembled at read
 * time: each event's thrower and target boxes are resolved to a participant
 * through the roster, and the event is counted for that person under the role
 * they had in it. Nothing here is stored, so a re-run of the identity pass
 * changes every player's record and not one label.
 *
 * Only closed events are counted for their outcome; a throw still in flight is
 * a throw, with nothing yet to say about where it went.
 */
export interface Tally {
  /** Throws released, whatever became of them. */
  throws: number
  /** Where those throws went, once known. */
  outcomes: Record<Outcome, number>
  passes: number
  fakes: number
  /** Thrown at: hit by a throw, caught one, blocked one, evaded one. The
   *  mirror of `outcomes` from the far side of the court.
   *
   *  A dodge is a miss that named a target: rule 16.1 makes a valid attempt one
   *  that passes within a metre of a player, so a miss with a target box is a
   *  throw that reached this player and did not put them out. A miss with no
   *  target reached nobody and is nobody's dodge. */
  against: { hit: number; catch: number; block: number; dodge: number }
  /** Passes received. */
  received: number
  /** Every event this player was in, in frame order, for the breakdown to list. */
  events: TallyLine[]
}

export interface TallyLine {
  eventId: string
  frame: number
  role: 'thrower' | 'target'
  event: ThrowEvent
}

export function emptyTally(): Tally {
  return {
    throws: 0,
    outcomes: Object.fromEntries(OUTCOMES.map((o) => [o, 0])) as Record<Outcome, number>,
    passes: 0,
    fakes: 0,
    against: { hit: 0, catch: 0, block: 0, dodge: 0 },
    received: 0,
    events: [],
  }
}

/** Throws whose outcome is known, and how many of them were hits. */
export function hitRate(t: Tally): { hits: number; of: number } | null {
  const of = t.throws - t.outcomes.unresolved
  return of > 0 ? { hits: t.outcomes.hit, of } : null
}

/**
 * What a catch is worth, in players.
 *
 * Two, not one: rule 23.1 puts the thrower out, and the catch also returns a
 * teammate to the court, which is a second body in a game won by being the side
 * with bodies left. The return is observed in the footage rather than quoted in
 * [[wdbf-rules]], which is why it is a constant here and not a literal in the
 * sum - see docs/reference/player-impact-metrics.md.
 */
export const CATCH_VALUE = 2

/**
 * What a player's play was worth, in players eliminated.
 *
 * The unit is the win condition's own: rule 10.2.1 wins a set by eliminating a
 * side, so the value of an act is what it does to the count of live players.
 * That makes every weight a reading of the rulebook rather than a choice - a
 * hit removes one opponent, a catch removes the thrower and returns a teammate,
 * and a block, a miss, a pass and a fake remove nobody and are worth nothing.
 *
 * Offence is what they did with the ball, defence what they did with one thrown
 * at them, and the two are the same unit and so may be added. A dodge scores
 * zero here, correctly - nobody went out - and is counted in `defenceRate`
 * instead, where surviving is what is being measured.
 */
export interface Impact {
  /** Opponents put out by their throws, net of the throws of theirs that were
   *  caught - each of which put them out and returned an opponent. */
  offence: number
  /** Players put out by what they did with a throw aimed at them, net of the
   *  times they were the one put out. */
  defence: number
  net: number
  /** Throws made plus throws faced: the opportunities the net came from, so a
   *  net can be read against how much play produced it. */
  involvements: number
}

export function impact(t: Tally): Impact {
  const offence = t.outcomes.hit - CATCH_VALUE * t.outcomes.catch
  const defence = CATCH_VALUE * t.against.catch - t.against.hit
  return { offence, defence, net: offence + defence, involvements: t.throws + thrownAt(t) }
}

/** Throws that reached this player: ones that put them out, and ones they
 *  survived. A miss with no target reached nobody and is not counted. */
export function thrownAt(t: Tally): number {
  const a = t.against
  return a.hit + a.catch + a.block + a.dodge
}

/** Throws faced and survived - dodged, caught or blocked. */
export function defenceRate(t: Tally): { survived: number; of: number } | null {
  const of = thrownAt(t)
  return of > 0 ? { survived: of - t.against.hit, of } : null
}

/**
 * The fewest throws a rate may be ranked on.
 *
 * A display threshold, not a term in the metric: one throw for one hit is a
 * perfect record and sorts above every real one, and a table whose top row is
 * an artefact of a single event teaches the reader the wrong thing. Rates are
 * still shown for anyone at any count - as a fraction, which says its own
 * sample size - and it is only the ordering that waits for three.
 */
export const MIN_RATED = 3

/**
 * Every player's record from the label file, keyed by participant id.
 *
 * `participantOf` is the roster lookup, and it answers null for a box it
 * cannot place - the pose chunk for that frame is not loaded yet, or the box
 * overlaps no detection - in which case the event is left out of everyone's
 * record rather than credited to the wrong person.
 */
export function tally(
  events: ThrowEvent[], participantOf: (placed: PlacedBox) => string | null,
): Map<string, Tally> {
  const out = new Map<string, Tally>()
  const record = (id: string) => {
    let t = out.get(id)
    if (!t) out.set(id, (t = emptyTally()))
    return t
  }
  for (const e of [...events].sort((a, b) => a.release_frame - b.release_frame)) {
    const thrower = e.thrower ? participantOf(e.thrower) : null
    const target = e.target ? participantOf(e.target) : null
    if (thrower) {
      const t = record(thrower)
      t.events.push({ eventId: e.id, frame: e.release_frame, role: 'thrower', event: e })
      if (e.kind === 'fake') t.fakes += 1
      else if (e.kind === 'pass') t.passes += 1
      else if (e.kind === 'throw') {
        t.throws += 1
        if (e.status === 'closed' && e.outcome) t.outcomes[e.outcome] += 1
      }
    }
    if (target) {
      const t = record(target)
      t.events.push({ eventId: e.id, frame: e.release_frame, role: 'target', event: e })
      if (e.kind === 'pass') t.received += 1
      else if (e.kind === 'throw' && e.status === 'closed') {
        if (e.outcome === 'hit' || e.outcome === 'catch' || e.outcome === 'block') {
          t.against[e.outcome] += 1
        } else if (e.outcome === 'miss') t.against.dodge += 1
      }
    }
  }
  return out
}

export type Rank = 'roster' | 'impact' | 'throws' | 'hit rate' | 'defence'
export const RANKS: Rank[] = ['roster', 'impact', 'throws', 'hit rate', 'defence']

/**
 * The list in the order a rank asks for. Stable, so players a rank cannot tell
 * apart keep the roster's own order, and those it has nothing to say about -
 * no throws to rate - sit last rather than first.
 *
 * A rate under `MIN_RATED` is not ranked at all rather than ranked on one
 * event: a player with a single throw is unranked here and still shows their
 * record on the card.
 */
export function rankPlayers(
  players: RosterParticipant[], tallies: Map<string, Tally>, rank: Rank,
): RosterParticipant[] {
  if (rank === 'roster') return players
  const score = (p: RosterParticipant): number | null => {
    const t = tallies.get(p.id)
    if (!t) return null
    if (rank === 'throws') return t.throws
    if (rank === 'impact') return impact(t).involvements > 0 ? impact(t).net : null
    const rate = rank === 'hit rate' ? hitRate(t) : defenceRate(t)
    if (!rate) return null
    const [n, of] = rank === 'hit rate'
      ? [(rate as { hits: number }).hits, rate.of]
      : [(rate as { survived: number }).survived, rate.of]
    return of >= MIN_RATED ? n / of : null
  }
  return players
    .map((p, i) => ({ p, i, s: score(p) }))
    .sort((a, b) => {
      if (a.s == null && b.s == null) return a.i - b.i
      if (a.s == null) return 1
      if (b.s == null) return -1
      return b.s - a.s || a.i - b.i
    })
    .map((x) => x.p)
}
