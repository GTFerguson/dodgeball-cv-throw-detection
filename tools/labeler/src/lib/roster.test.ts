import { describe, expect, it } from 'vitest'
import type { NamesFile, PoseDetection, RosterFile } from '../types'
import type { PlayerSlot } from './players'
import { RosterIndex, describe as say, keyFor } from './roster'

const roster: RosterFile = {
  schema_version: 2, video: 'clip.mp4', clip_sha256: 'abc', pose_run: 'r1',
  participants: [
    { id: 'near-7', role: 'player', team: 'near', number: 7, track_ids: [56] },
    { id: 'player-t73', role: 'player', team: 'far', number: null, track_ids: [73] },
    { id: 'official-t8', role: 'official', team: 'near', number: null, track_ids: [8] },
  ],
  tracks: [
    { id: 56, participant: 'near-7', role: 'player', team: 'near', number: 7,
      start_frame: 0, end_frame: 10, in_play: [[0, 10]], detections: [[5, 0], [6, 0]] },
    // Stepped off at frame 5 and held there by the roster's own window ending at 4.
    { id: 73, participant: 'player-t73', role: 'player', team: 'far', number: null,
      start_frame: 0, end_frame: 10, in_play: [[0, 4], [6, 10]], detections: [[5, 1]] },
    // An official standing on the paint: in play by geometry, never a player.
    { id: 8, participant: 'official-t8', role: 'official', team: 'near', number: null,
      start_frame: 0, end_frame: 10, in_play: [[0, 10]], detections: [[5, 2]] },
  ],
}
const names: NamesFile = {
  schema_version: 1, video: 'clip.mp4', source: 'hand', near: { '7': 'Chalmers' }, far: {},
}
const det = (box: [number, number, number, number]): PoseDetection => ({ box, conf: 0.9, kpts: [] })
const frame5 = [det([800, 400, 900, 700]), det([200, 100, 260, 250])]
const slot = (key: string, box: [number, number, number, number]): PlayerSlot => ({
  key, team: 'near', box: { x1: box[0], y1: box[1], x2: box[2], y2: box[3] },
  foot: [0, 0], detection: det(box), index: 0,
})

describe('who a box is', () => {
  const index = new RosterIndex(roster, names)

  it('names the track behind a detection', () => {
    expect(index.whoByIndex(5, 0)).toMatchObject({ participant: 'near-7', number: 7, name: 'Chalmers', team: 'near' })
    expect(index.whoByIndex(5, 1)).toMatchObject({ participant: 'player-t73', number: null, name: null })
  })

  it('finds the detection a labelled box was snapped from, or drawn over', () => {
    const who = index.whoByBox(5, { x1: 805, y1: 402, x2: 898, y2: 696 }, frame5)
    expect(who.number).toBe(7)
    const nobody = index.whoByBox(5, { x1: 0, y1: 0, x2: 50, y2: 50 }, frame5)
    expect(nobody.participant).toBeNull()
  })

  it('says nothing rather than something wrong when the frame is not loaded', () => {
    expect(index.whoByBox(5, { x1: 805, y1: 402, x2: 898, y2: 696 }, null).participant).toBeNull()
  })

  it('carries the player key that would snap the box on screen', () => {
    const slots = [slot('3', [800, 400, 900, 700])]
    expect(index.whoByBox(5, { x1: 805, y1: 402, x2: 898, y2: 696 }, frame5, slots).key).toBe('3')
    expect(keyFor(slots, { x1: 0, y1: 0, x2: 10, y2: 10 })).toBeNull()
  })

  it('reads in play off the track, not the frame geometry', () => {
    expect(index.inPlay(56, 5)).toBe(true)
    expect(index.inPlay(73, 4)).toBe(true)
    expect(index.inPlay(73, 5)).toBe(false)
    expect(index.inPlay(73, 6)).toBe(true)
    expect(index.inPlay(999, 5)).toBe(false)
  })

  it('admits only players in play to the key row', () => {
    expect(index.isPlayerInPlay(5, 0)).toBe(true)   // near-7, in play
    expect(index.isPlayerInPlay(5, 1)).toBe(false)  // t73, out at 5
    expect(index.isPlayerInPlay(5, 2)).toBe(false)  // an official, however placed
    expect(index.isPlayerInPlay(5, 3)).toBe(false)  // untracked
    expect(new RosterIndex(null, null).isPlayerInPlay(5, 0)).toBe(false)
  })

  it('follows a track from frame to frame', () => {
    expect(index.detectionOf(56, 5)).toBe(0)
    expect(index.detectionOf(56, 6)).toBe(0)
    expect(index.detectionOf(56, 7)).toBeNull()
    expect(index.detectionOf(999, 5)).toBeNull()
  })

  it('follows a placed box to where its player is on another frame', () => {
    const frame6 = [det([820, 410, 920, 710])]
    const placed = { x1: 805, y1: 402, x2: 898, y2: 696 }
    expect(index.follow(5, placed, frame5, 6, frame6)).toEqual({ x1: 820, y1: 410, x2: 920, y2: 710 })
    expect(index.follow(5, placed, frame5, 5, frame5)).toEqual(placed)
    expect(index.follow(5, placed, frame5, 7, [])).toBeNull()
    expect(index.follow(5, placed, null, 6, frame6)).toBeNull()
  })

  it('works without a roster or names at all', () => {
    const bare = new RosterIndex(null, null)
    expect(bare.empty).toBe(true)
    expect(bare.whoByIndex(5, 0).participant).toBeNull()
  })
})

describe('describing someone', () => {
  it('reads as key, number, name - as much as is known', () => {
    expect(say({ participant: 'near-7', team: 'near', number: 7, name: 'Chalmers', key: '3' })).toBe('3 #7 Chalmers')
    expect(say({ participant: 'near-7', team: 'near', number: 7, name: null, key: null })).toBe('#7')
    expect(say({ participant: 'player-t73', team: 'far', number: null, name: null, key: 'q' })).toBe('Q')
    expect(say({ participant: 'player-t73', team: 'far', number: null, name: null, key: null })).toBe('player-t73')
    expect(say({ participant: null, team: null, number: null, name: null, key: null })).toBe('—')
  })
})
