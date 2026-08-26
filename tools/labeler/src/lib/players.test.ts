import { describe, expect, it } from 'vitest'
import type { CourtConfig, PoseDetection } from '../types'
import { footPoint, makeBox } from './boxes'
import {
  courtToImage, heldOnCourt, imageToCourt, inMargin, inferTeam, isOnCourt, isUsableCourt,
  slackAt, teamAtPoint,
} from './court'
import { playerSlots, slotForKey } from './players'

// The calibration fitted for this project's clip. A real homography is used
// rather than a synthetic one so the tests exercise the perspective the tool
// actually sees: the near baseline spans most of the frame, the far one about
// a third of it, and a metre is worth very different numbers of pixels at each.
const court: CourtConfig = {
  video: 'clip.mp4',
  frame_size: [1920, 1080],
  court_metres: { width: 9, length: 18 },
  centre_line_m: 9,
  margin_m: 1.5,
  image_to_court: [
    [0.021945829826872754, 0.015220468421071326, -17.681183320002084],
    [1.0833262728572813e-18, -0.040712839668781364, 42.79288707488165],
    [1.744721840291384e-19, 0.0030175474611080994, 1.0],
  ],
  court_to_image: [
    [45.5667435630753, 18.397681709471637, 18.384030401223963],
    [-1.7124423633395188e-15, -5.887811031529425, 251.95643259048114],
    [-2.7827531627563153e-18, 0.017766749229675877, 0.23970950652673972],
  ],
  corners_image: [
    [76.69, 1051.09], [1787.52, 1051.09], [1357.69, 260.9], [624.73, 260.9],
  ],
  cross_lines: [
    { image_y: 260.9, court_y: 18 },
    { image_y: 494.55, court_y: 9.091 },
    { image_y: 1051.09, court_y: 0 },
  ],
}

/** Feet at a court position, as a detection box 1.8 m tall in image space. */
function playerAt(courtX: number, courtY: number): PoseDetection {
  const [fx, fy] = courtToImage([courtX, courtY], court)!
  const head = courtToImage([courtX, courtY], court)!
  // Height in pixels shrinks with distance; approximate it from the local scale.
  const [, nearFy] = courtToImage([courtX, courtY + 0.5], court)!
  const h = Math.abs(fy - nearFy) * 12
  return { box: [head[0] - h * 0.14, fy - h, fx + h * 0.14, fy], conf: 0.9, kpts: [] }
}

describe('court calibration', () => {
  it('round-trips a point through both homographies', () => {
    const [cx, cy] = imageToCourt([900, 700], court)!
    const [ix, iy] = courtToImage([cx, cy], court)!
    expect(ix).toBeCloseTo(900, 6)
    expect(iy).toBeCloseTo(700, 6)
  })

  it('puts the court corners where the calibration says they are', () => {
    expect(imageToCourt(court.corners_image[0], court)![0]).toBeCloseTo(0, 3)
    expect(imageToCourt(court.corners_image[0], court)![1]).toBeCloseTo(0, 3)
    expect(imageToCourt(court.corners_image[1], court)![0]).toBeCloseTo(9, 3)
    expect(imageToCourt(court.corners_image[2], court)![1]).toBeCloseTo(18, 3)
  })

  it('counts the paint as in play and the margin band as out of it', () => {
    // The band is where the eliminated queue and the officials stand. Counting
    // it as in play is what put the whole sideline on the roster.
    expect(isOnCourt(courtToImage([4.5, 9], court)!, court)).toBe(true)
    expect(isOnCourt(courtToImage([-1, 9], court)!, court)).toBe(false)
    expect(isOnCourt(courtToImage([-2, 9], court)!, court)).toBe(false)
    expect(isOnCourt(courtToImage([4.5, 20], court)!, court)).toBe(false)
  })

  it('keeps a player standing on the line on court', () => {
    // The paint has width and a foot point is quantised, so an exact test would
    // flicker — and flicker reads downstream as a player leaving and returning.
    const slack = slackAt(courtToImage([0, 9], court)!, court)
    expect(isOnCourt(courtToImage([-slack / 2, 9], court)!, court)).toBe(true)
    expect(isOnCourt(courtToImage([9 + slack / 2, 9], court)!, court)).toBe(true)
  })

  it('holds a player who steps off the line and comes back', () => {
    // The flicker this exists to stop: a player at the baseline is detected a
    // few centimetres behind it for a moment. Nothing about them left the game.
    const justOut = courtToImage([4.5, -0.5], court)!
    expect(isOnCourt(justOut, court)).toBe(false)
    expect(heldOnCourt(justOut, court, [[4.5, 0.2]])).toBe(true)
  })

  it('does not hold someone standing well clear of any player', () => {
    // An official on the sideline is near the court but never near a player who
    // was on it, so the hold must not sweep them onto the roster.
    const outside = courtToImage([4.5, -1.2], court)!
    expect(heldOnCourt(outside, court, [[4.5, 0.9]])).toBe(false)
  })

  it('holds nobody when no player was on court nearby', () => {
    const justOut = courtToImage([4.5, -0.5], court)!
    expect(heldOnCourt(justOut, court, [])).toBe(false)
  })

  it('separates the crossing band from both the court and the crowd', () => {
    expect(inMargin(courtToImage([4.5, 9], court)!, court)).toBe(false)
    expect(inMargin(courtToImage([-1, 9], court)!, court)).toBe(true)
    expect(inMargin(courtToImage([-2, 9], court)!, court)).toBe(false)
  })

  it('splits the halves at the centre line, near end first', () => {
    expect(teamAtPoint(courtToImage([4.5, 3], court)!, court)).toBe('near')
    expect(teamAtPoint(courtToImage([4.5, 15], court)!, court)).toBe('far')
  })

  it('infers a team from where the thrower is standing, not from the box centre', () => {
    // A near-court player mid-jump: the box centre rises past the centre line
    // in the picture while the feet stay on the near half.
    const [fx, fy] = courtToImage([4.5, 8], court)!
    expect(inferTeam(makeBox(fx - 30, fy - 400, fx + 30, fy), court)).toBe('near')
  })

  it('declines to guess without a court', () => {
    expect(teamAtPoint([900, 800], null)).toBeNull()
    expect(inferTeam(makeBox(0, 0, 10, 10), null)).toBeNull()
    expect(isOnCourt([900, 800], null)).toBe(false)
  })

  it('rejects a court file that is missing its geometry', () => {
    expect(isUsableCourt(null)).toBe(false)
    expect(isUsableCourt({ video: 'clip.mp4' })).toBe(false)
    expect(isUsableCourt({ ...court, image_to_court: [[1, 0, 0]] })).toBe(false)
    expect(isUsableCourt(court)).toBe(true)
  })
})

describe('player keys', () => {
  it('numbers the near team left to right and letters the far team', () => {
    const slots = playerSlots(
      [playerAt(7, 4), playerAt(2, 4), playerAt(6, 14), playerAt(1, 14)],
      court,
    )
    expect(slots.filter((s) => s.team === 'near').map((s) => s.key)).toEqual(['1', '2'])
    expect(slots.filter((s) => s.team === 'far').map((s) => s.key)).toEqual(['q', 'w'])
    // Key 1 is the leftmost near player in the picture, which is court x 2.
    const one = slotForKey(slots, '1')!
    expect(imageToCourt([(one.box.x1 + one.box.x2) / 2, one.box.y2], court)![0]).toBeCloseTo(2, 1)
  })

  it('breaks a horizontal tie by y, reading down the picture', () => {
    // Two players directly one behind the other in the picture. A shared court x
    // would not do it — the camera shears x with depth — so these are placed by
    // image column instead, which is what the tie-break actually sees.
    const nearer: PoseDetection = { box: [860, 700, 940, 900], conf: 0.9, kpts: [] }
    const further: PoseDetection = { box: [860, 540, 940, 700], conf: 0.9, kpts: [] }
    const slots = playerSlots([nearer, further], court)
    expect(slotForKey(slots, '1')!.box.y2).toBe(700)
    expect(slotForKey(slots, '2')!.box.y2).toBe(900)
  })

  it('is stable for detections that tie on both anchors', () => {
    const both = [playerAt(4.5, 5), playerAt(4.5, 5)]
    const first = playerSlots(both, court)
    expect(playerSlots(both, court)).toEqual(first)
  })

  it('drops the crowd, the bench and the sideline queues', () => {
    // Feet at court (-2.6, 7.4) and (13.6, 12.7) — both well past the margin.
    const sideline: PoseDetection = { box: [70, 380, 130, 560], conf: 0.9, kpts: [] }
    const bench: PoseDetection = { box: [1840, 250, 1900, 380], conf: 0.9, kpts: [] }
    const slots = playerSlots([playerAt(4.5, 5), sideline, bench], court)
    expect(slots).toHaveLength(1)
    expect(slots[0].key).toBe('1')
  })

  it('takes the roster\'s word over the geometry when it is given', () => {
    // Index 1 stands on the paint but is not in play - an official, or the
    // queue on a crowded sideline; index 2 is a metre outside the line but the
    // roster holds them. Keys follow the roster and still run left to right.
    const detections = [playerAt(7, 4), playerAt(2, 4), playerAt(-1, 7), playerAt(1, 14)]
    const inPlay = new Set([0, 2, 3])
    const slots = playerSlots(detections, court, [], (i) => inPlay.has(i))
    expect(slots.map((s) => s.index).sort()).toEqual([0, 2, 3])
    expect(slotForKey(slots, '1')!.index).toBe(2)
    expect(slotForKey(slots, '2')!.index).toBe(0)
    expect(slotForKey(slots, 'q')!.index).toBe(3)
  })

  it('drops someone standing just off the touchline', () => {
    // The case the margin band used to admit: a metre outside the sideline,
    // which is where the eliminated queue and the officials stand.
    const queued = playerAt(-1, 7)
    expect(playerSlots([playerAt(4.5, 5), queued], court)).toHaveLength(1)
  })

  it('places a diving player by their ankles, not by the bottom of the box', () => {
    // Prone at the centre line: the box bottom is where the body ends, which is
    // metres up-court of the feet and lands in the wrong half.
    const [ax, ay] = courtToImage([4.5, 8.5], court)!
    const prone: PoseDetection = {
      box: [ax - 140, ay - 200, ax + 140, ay - 120],
      conf: 0.9,
      kpts: Array.from({ length: 17 }, (_, i) =>
        (i === 15 || i === 16 ? [ax, ay, 0.9] : [0, 0, 0]) as [number, number, number]),
    }
    expect(footPoint(prone)).toEqual([ax, ay])
    expect(playerSlots([prone], court)[0].team).toBe('near')
  })

  it('falls back to the box when neither ankle is trustworthy', () => {
    const occluded: PoseDetection = {
      box: [800, 400, 1000, 720],
      conf: 0.9,
      kpts: Array.from({ length: 17 }, (_, i) =>
        (i === 15 || i === 16 ? [880, 500, 0.05] : [0, 0, 0]) as [number, number, number]),
    }
    expect(footPoint(occluded)).toEqual([900, 720])
  })

  it('runs out of keys rather than reusing them', () => {
    const seven = Array.from({ length: 7 }, (_, i) => playerAt(1 + i * 1.1, 4))
    const slots = playerSlots(seven, court)
    expect(slots.map((s) => s.key)).toEqual(['1', '2', '3', '4', '5', '6', null])
  })

  it('assigns nothing without a court to filter by', () => {
    expect(playerSlots([playerAt(4.5, 5)], null)).toEqual([])
  })
})
