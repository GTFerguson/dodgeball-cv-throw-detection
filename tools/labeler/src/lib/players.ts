import type { Box, CourtConfig, PoseDetection, Team } from '../types'
import { footPoint, makeBox } from './boxes'
import { isOnCourt, teamAtPoint } from './court'

// Six a side. The near team sits on the number row and the far team on the row
// above it, so both hands stay where they are for a two-keypress event.
export const NEAR_KEYS = ['1', '2', '3', '4', '5', '6']
export const FAR_KEYS = ['q', 'w', 'e', 'r', 't', 'y']

export const PLAYER_KEYS: Record<Team, string[]> = { near: NEAR_KEYS, far: FAR_KEYS }

export interface PlayerSlot {
  /** The key that snaps this player's box, or null past the end of the key row. */
  key: string | null
  team: Team
  box: Box
  /** Where this player meets the floor — what the court tests were applied to. */
  foot: [number, number]
  detection: PoseDetection
  /** Position in the frame's detection list, so ordering is total. */
  index: number
}

/**
 * Assign player keys to the skeletons standing on court, left to right per team.
 *
 * "On court" is the paint plus the boundary slack, not the calibration's margin
 * band — the band is where the eliminated queue and the officials stand.
 *
 * Keys are a placement aid for one frame and carry no identity: they are
 * recomputed from scratch on every frame, so a player who crosses a team-mate
 * swaps keys with them. That is deliberate — tracking would be a second system
 * to be wrong, and the label stores the box, not the key.
 *
 * Order is by the foot point's x, then its y, then the detection's own position
 * in the list. Two players at the same x are ordered by y ascending, which reads
 * far-to-near down the picture; the third term only exists so the order is
 * total and the same detections always produce the same keys.
 */
export function playerSlots(
  detections: PoseDetection[], court: CourtConfig | null,
): PlayerSlot[] {
  const onCourt: PlayerSlot[] = []
  detections.forEach((det, index) => {
    const [x1, y1, x2, y2] = det.box
    const box = makeBox(x1, y1, x2, y2)
    const foot = footPoint(det)
    if (!isOnCourt(foot, court)) return
    const team = teamAtPoint(foot, court)
    if (team == null) return
    onCourt.push({ key: null, team, box, foot, detection: det, index })
  })

  const slots: PlayerSlot[] = []
  for (const team of ['near', 'far'] as Team[]) {
    const keys = PLAYER_KEYS[team]
    onCourt
      .filter((s) => s.team === team)
      .sort((a, b) => a.foot[0] - b.foot[0] || a.foot[1] - b.foot[1] || a.index - b.index)
      .forEach((slot, i) => slots.push({ ...slot, key: keys[i] ?? null }))
  }
  return slots
}

export function slotForKey(slots: PlayerSlot[], key: string): PlayerSlot | null {
  return slots.find((s) => s.key === key) ?? null
}
