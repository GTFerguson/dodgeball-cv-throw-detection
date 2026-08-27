import { describe, expect, it } from 'vitest'
import type { PlacedBox, ThrowEvent } from '../types'
import { newEvent } from '../types'
import { CATCH_VALUE, defenceRate, hitRate, impact, rankPlayers, tally, thrownAt } from './tally'
import type { RosterParticipant } from '../types'

// A box "is" a participant by its frame here: the roster lookup is the caller's,
// and the tally only has to credit what it answers.
const at = (frame: number): PlacedBox => ({
  box: { x1: 0, y1: 0, x2: 1, y2: 1 }, frame, source: 'snapped', adjusted: false, pose_run: null,
})
const who: Record<number, string> = { 1: 'near-7', 2: 'far-13', 3: 'near-7', 9: 'far-2' }
const participantOf = (p: PlacedBox) => who[p.frame] ?? null

const throwAt = (id: string, frame: number, outcome: ThrowEvent['outcome'], targetFrame: number | null): ThrowEvent => ({
  ...newEvent(id, frame, 'throw'),
  status: outcome ? 'closed' : 'open',
  outcome,
  thrower: at(frame),
  target: targetFrame == null ? null : at(targetFrame),
})

describe('tally', () => {
  it('credits a throw to its thrower and its outcome to its target', () => {
    const t = tally([throwAt('a', 1, 'hit', 2)], participantOf)
    expect(t.get('near-7')).toMatchObject({ throws: 1, outcomes: { hit: 1 } })
    expect(t.get('far-13')).toMatchObject({ throws: 0, against: { hit: 1 } })
    expect(t.get('near-7')!.events.map((l) => l.role)).toEqual(['thrower'])
    expect(t.get('far-13')!.events.map((l) => l.role)).toEqual(['target'])
  })

  it('counts a throw in flight as a throw with no outcome yet', () => {
    const t = tally([throwAt('a', 1, null, null)], participantOf)
    expect(t.get('near-7')).toMatchObject({ throws: 1, outcomes: { hit: 0, unresolved: 0 } })
  })

  it('keeps passes and fakes apart from throws', () => {
    const pass: ThrowEvent = { ...newEvent('p', 1, 'pass'), thrower: at(1), target: at(9) }
    const fake: ThrowEvent = { ...newEvent('f', 3, 'fake'), thrower: at(3) }
    const t = tally([pass, fake], participantOf)
    expect(t.get('near-7')).toMatchObject({ throws: 0, passes: 1, fakes: 1 })
    expect(t.get('far-2')).toMatchObject({ received: 1, against: { hit: 0, catch: 0, block: 0 } })
  })

  it('leaves out a box the roster cannot place rather than guess', () => {
    const t = tally([throwAt('a', 5, 'catch', 2)], participantOf)
    expect(t.has('near-7')).toBe(false)
    expect(t.get('far-13')).toMatchObject({ against: { catch: 1 } })
  })

  it('lists events in frame order whatever order the file holds them', () => {
    const t = tally([throwAt('b', 3, 'miss', null), throwAt('a', 1, 'block', 2)], participantOf)
    expect(t.get('near-7')!.events.map((l) => l.frame)).toEqual([1, 3])
  })

  it('states a hit rate over throws whose outcome is known', () => {
    const t = tally([
      throwAt('a', 1, 'hit', 2), throwAt('b', 3, 'unresolved', null), throwAt('c', 1, 'catch', 9),
    ], participantOf)
    expect(hitRate(t.get('near-7')!)).toEqual({ hits: 1, of: 2 })
    expect(hitRate(t.get('far-13')!)).toBeNull()
  })
})

describe('rankPlayers', () => {
  const person = (id: string, number: number | null, start: number): RosterParticipant => ({
    id, role: 'player', team: 'near', number, track_ids: [], start_frame: start, end_frame: start + 1,
    core_in_play_by_set: [[0, 30]], core_in_play_frames: 30, played_sets: [0], played: true, excess: false,
  })
  const players = [person('near-7', 7, 0), person('player-t9', null, 5), person('near-2', 2, 3)]
  const tallies = tally([
    throwAt('a', 1, 'hit', null), throwAt('b', 3, 'miss', null),
    throwAt('c', 11, 'hit', null), throwAt('d', 9, 'hit', null),
  ], (p) => ({ 1: 'near-2', 3: 'near-2', 11: 'near-2', 9: 'player-t9' } as Record<number, string>)[p.frame] ?? null)

  it('keeps the roster order by default', () => {
    expect(rankPlayers(players, tallies, 'roster').map((p) => p.id)).toEqual(['near-7', 'player-t9', 'near-2'])
  })

  it('ranks by throws, most first, and holds roster order between equals', () => {
    expect(rankPlayers(players, tallies, 'throws').map((p) => p.id)).toEqual(['near-2', 'player-t9', 'near-7'])
  })

  it('ranks by hit rate with the unknown last', () => {
    // near-2 is 2 of 3 and rateable; player-t9's 1 of 1 is under the floor and
    // near-7 has thrown nothing, so both fall back to roster order behind it.
    expect(rankPlayers(players, tallies, 'hit rate').map((p) => p.id)).toEqual(['near-2', 'near-7', 'player-t9'])
  })

  it('will not rank a perfect record made of one throw above a real one', () => {
    // player-t9 threw once and hit: a rate of 1.0 that means nothing yet.
    const order = rankPlayers(players, tallies, 'hit rate').map((p) => p.id)
    expect(order.indexOf('near-2')).toBeLessThan(order.indexOf('player-t9'))
  })

  it('ranks by impact, and leaves out anyone no event reached', () => {
    // Every throw above resolved with no target the roster could place, so the
    // only impact on the board is the throwers' own: near-2 +2, player-t9 +1.
    expect(rankPlayers(players, tallies, 'impact').map((p) => p.id)).toEqual(['near-2', 'player-t9', 'near-7'])
  })
})

describe('impact', () => {
  // near-7 throws, far-13 is thrown at. Frame 2 is far-13 for every target.
  const ledger = (...events: ThrowEvent[]) => tally(events, participantOf)

  it('scores a hit as one opponent out, for the thrower and against the target', () => {
    const t = ledger(throwAt('a', 1, 'hit', 2))
    expect(impact(t.get('near-7')!)).toMatchObject({ offence: 1, defence: 0, net: 1 })
    expect(impact(t.get('far-13')!)).toMatchObject({ offence: 0, defence: -1, net: -1 })
  })

  it('scores a catch as the thrower out and a teammate back', () => {
    const t = ledger(throwAt('a', 1, 'catch', 2))
    expect(impact(t.get('near-7')!)).toMatchObject({ offence: -CATCH_VALUE, net: -CATCH_VALUE })
    expect(impact(t.get('far-13')!)).toMatchObject({ defence: CATCH_VALUE, net: CATCH_VALUE })
  })

  it('scores a block, a miss and a dodge at nothing, because nobody went out', () => {
    const t = ledger(throwAt('a', 1, 'block', 2), throwAt('b', 3, 'miss', 2), throwAt('c', 5, 'miss', null))
    expect(impact(t.get('near-7')!).net).toBe(0)
    expect(impact(t.get('far-13')!).net).toBe(0)
  })

  it('adds offence and defence for a player who did both', () => {
    // Threw two hits and had one of their throws caught; caught one, took one.
    const t = ledger(
      throwAt('a', 1, 'hit', 2), throwAt('b', 1, 'hit', 2), throwAt('c', 1, 'catch', 2),
      throwAt('d', 2, 'catch', 1), throwAt('e', 2, 'hit', 1),
    )
    const i = impact(t.get('near-7')!)
    expect(i.offence).toBe(2 - CATCH_VALUE)
    expect(i.defence).toBe(CATCH_VALUE - 1)
    expect(i.net).toBe(i.offence + i.defence)
  })

  it('counts throws made and throws faced as the involvements behind a net', () => {
    const t = ledger(throwAt('a', 1, 'hit', 2), throwAt('b', 2, 'miss', 1))
    expect(impact(t.get('near-7')!).involvements).toBe(2)
  })

  it('leaves a throw still in flight out of the ledger', () => {
    const t = ledger(throwAt('a', 1, null, null))
    expect(impact(t.get('near-7')!)).toMatchObject({ net: 0, involvements: 1 })
  })
})

describe('dodges and defence', () => {
  it('counts a miss that named a target as that player dodging it', () => {
    const t = tally([throwAt('a', 1, 'miss', 2)], participantOf)
    expect(t.get('far-13')!.against).toMatchObject({ dodge: 1, hit: 0 })
  })

  it('does not credit a dodge for a miss that reached nobody', () => {
    const t = tally([throwAt('a', 1, 'miss', null)], participantOf)
    expect(t.get('near-7')!.against.dodge).toBe(0)
    expect(t.has('far-13')).toBe(false)
  })

  it('counts every throw that reached a player as one they faced', () => {
    const t = tally([
      throwAt('a', 1, 'hit', 2), throwAt('b', 1, 'catch', 2),
      throwAt('c', 1, 'block', 2), throwAt('d', 1, 'miss', 2), throwAt('e', 1, 'miss', null),
    ], participantOf)
    expect(thrownAt(t.get('far-13')!)).toBe(4)
  })

  it('rates a defence by what was survived, however it was survived', () => {
    const t = tally([
      throwAt('a', 1, 'hit', 2), throwAt('b', 1, 'catch', 2),
      throwAt('c', 1, 'block', 2), throwAt('d', 1, 'miss', 2),
    ], participantOf)
    expect(defenceRate(t.get('far-13')!)).toEqual({ survived: 3, of: 4 })
  })

  it('has nothing to say about a defence never tested', () => {
    const t = tally([throwAt('a', 1, 'miss', null)], participantOf)
    expect(defenceRate(t.get('near-7')!)).toBeNull()
  })
})
