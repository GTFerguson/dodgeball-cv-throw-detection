import type { Box, NamesFile, PoseDetection, RosterFile, RosterParticipant, RosterTrack, Team } from '../types'
import type { PlayerSlot } from './players'

/**
 * Who a box is, for display.
 *
 * Labels store boxes and never identity, so identity is looked up at read time:
 * a box on a frame is matched to the pose detection it was snapped from, the
 * roster says which track that detection belongs to, and the track carries the
 * person. Nothing here is written back; a re-run of the identity pass changes
 * what a row says and not what a label means.
 */
export interface Who {
  participant: string | null
  team: Team | null
  number: number | null
  name: string | null
  /** The player key that snaps this box on the frame on screen, if it is on screen. */
  key: string | null
}

export const NOBODY: Who = { participant: null, team: null, number: null, name: null, key: null }

/** How much a label's box must overlap a detection to have been snapped from
 *  it, or drawn over it. Two players on one frame overlap far less. */
export const MATCH_MIN_IOU = 0.5

export function iou(a: Box, b: Box): number {
  const w = Math.min(a.x2, b.x2) - Math.max(a.x1, b.x1)
  const h = Math.min(a.y2, b.y2) - Math.max(a.y1, b.y1)
  if (w <= 0 || h <= 0) return 0
  const inter = w * h
  const union = (a.x2 - a.x1) * (a.y2 - a.y1) + (b.x2 - b.x1) * (b.y2 - b.y1) - inter
  return union > 0 ? inter / union : 0
}

export class RosterIndex {
  private byFrame = new Map<number, Map<number, RosterTrack>>()
  private byTrack = new Map<number, Map<number, number>>()
  private tracks = new Map<number, RosterTrack>()
  private participants = new Map<string, RosterParticipant>()

  constructor(private roster: RosterFile | null, private names: NamesFile | null) {
    for (const p of roster?.participants ?? []) this.participants.set(p.id, p)
    for (const t of roster?.tracks ?? []) {
      this.tracks.set(t.id, t)
      const frames = new Map<number, number>()
      this.byTrack.set(t.id, frames)
      for (const [frame, index] of t.detections) {
        let at = this.byFrame.get(frame)
        if (!at) this.byFrame.set(frame, (at = new Map()))
        at.set(index, t)
        frames.set(frame, index)
      }
    }
  }

  /** Where a track's player is on a frame: the index of their detection there,
   *  or null when the tracker did not hold them on that frame. */
  detectionOf(trackId: number, frame: number): number | null {
    return this.byTrack.get(trackId)?.get(frame) ?? null
  }

  get empty(): boolean {
    return this.roster == null
  }

  /** Whether a track's player counted as in play on a frame. The identity
   *  pass decides this once over the whole track, with the boundary slack
   *  and the hold window already spent, so the tool does not re-derive it
   *  from geometry. */
  inPlay(trackId: number, frame: number): boolean {
    const track = this.tracks.get(trackId)
    return track != null && track.in_play.some(([a, b]) => a <= frame && frame <= b)
  }

  /** Whether the detection at `index` on `frame` is a player in play there:
   *  the test that decides who gets a player key when the roster is present. */
  isPlayerInPlay(frame: number, index: number): boolean {
    const track = this.trackAt(frame, index)
    return track != null && track.role === 'player' && this.inPlay(track.id, frame)
  }

  track(id: number): RosterTrack | null {
    return this.tracks.get(id) ?? null
  }

  participant(id: string): RosterParticipant | null {
    return this.participants.get(id) ?? null
  }

  /** Who was on the court while a set was live - any set, or the one at
   *  `set` (an index into the timeline's `sets`) - on one side or both: the
   *  identity pass's decision, mirroring `Roster.played`. Numbered players
   *  first, then the fragments it could not name, each in frame order. */
  played(team?: Team, set?: number): RosterParticipant[] {
    return [...this.participants.values()]
      .filter((p) => p.played && (team == null || p.team === team)
        && (set == null || p.played_sets.includes(set)))
      .sort((a, b) => Number(a.number == null) - Number(b.number == null) || a.start_frame - b.start_frame)
  }

  /** The pieces the identity pass could not count as anyone: in play while
   *  their side already had its six on the floor. */
  excess(): RosterParticipant[] {
    return [...this.participants.values()].filter((p) => p.excess)
  }

  /** The track that holds a participant on a frame, or null when none of
   *  theirs does - they are off screen, or the tracker lost them. */
  trackOnFrame(participantId: string, frame: number): RosterTrack | null {
    const p = this.participants.get(participantId)
    for (const id of p?.track_ids ?? []) {
      if (this.byTrack.get(id)?.has(frame)) return this.tracks.get(id) ?? null
    }
    return null
  }

  /** The first frame a participant counted as in play, or null if they never
   *  did - where to take the stage to show someone who is not on screen now. */
  firstInPlay(participantId: string): number | null {
    const p = this.participants.get(participantId)
    let first: number | null = null
    for (const id of p?.track_ids ?? []) {
      for (const [a] of this.tracks.get(id)?.in_play ?? []) {
        if (first == null || a < first) first = a
      }
    }
    return first
  }

  /** The track a pose detection belongs to, by its position on its frame. */
  trackAt(frame: number, index: number): RosterTrack | null {
    return this.byFrame.get(frame)?.get(index) ?? null
  }

  nameOf(team: Team | null, number: number | null): string | null {
    if (!team || number == null) return null
    return this.names?.[team]?.[String(number)] ?? null
  }

  whoIsTrack(track: RosterTrack | null, slots: PlayerSlot[] = [], box: Box | null = null): Who {
    const key = box ? keyFor(slots, box) : null
    if (!track) return { ...NOBODY, key }
    return {
      participant: track.participant,
      team: track.team,
      number: track.number,
      name: this.nameOf(track.team, track.number),
      key,
    }
  }

  /** Who a detection is, by frame and index. */
  whoByIndex(frame: number, index: number, slots: PlayerSlot[] = [], box: Box | null = null): Who {
    return this.whoIsTrack(this.trackAt(frame, index), slots, box)
  }

  /** The detection on a frame a box best overlaps, or -1 for none. */
  static matchIndex(box: Box, detections: PoseDetection[]): number {
    let best = -1
    let bestIou = MATCH_MIN_IOU
    detections.forEach((d, i) => {
      const [x1, y1, x2, y2] = d.box
      const score = iou(box, { x1, y1, x2, y2 })
      if (score >= bestIou) { best = i; bestIou = score }
    })
    return best
  }

  /** The track behind a labelled box: the detection on its frame it best
   *  overlaps, then that detection's track. */
  trackByBox(frame: number, box: Box, detections: PoseDetection[] | null): RosterTrack | null {
    if (!detections) return null
    const index = RosterIndex.matchIndex(box, detections)
    return index < 0 ? null : this.trackAt(frame, index)
  }

  /**
   * Who a labelled box is. Null detections - the pose chunk for the frame is
   * not loaded - give a name-less answer rather than a wrong one.
   */
  whoByBox(frame: number, box: Box, detections: PoseDetection[] | null, slots: PlayerSlot[] = []): Who {
    return this.whoIsTrack(this.trackByBox(frame, box, detections), slots, box)
  }

  /** Where a track's player is on a frame, as a box, or null when the tracker
   *  did not hold them there or the frame's detections are not loaded. */
  boxOfTrack(trackId: number, frame: number, detectionsNow: PoseDetection[] | null): Box | null {
    const index = this.detectionOf(trackId, frame)
    const d = index != null ? detectionsNow?.[index] : null
    if (!d) return null
    const [x1, y1, x2, y2] = d.box
    return { x1, y1, x2, y2 }
  }

  /**
   * A placed box, followed to another frame.
   *
   * A label stores a box at its frame and nothing else, so on any other frame
   * the player has moved out of it. For drawing, the box is matched to the
   * detection it was placed over, that detection's track is followed to the
   * frame on screen, and the track's box there is what is shown. The label is
   * untouched; this is display, and it says so by returning null - draw the
   * stored box - whenever the follow cannot be made.
   */
  follow(
    placedFrame: number, box: Box, detectionsThen: PoseDetection[] | null,
    frame: number, detectionsNow: PoseDetection[] | null,
  ): Box | null {
    if (frame === placedFrame) return box
    const track = this.trackByBox(placedFrame, box, detectionsThen)
    return track ? this.boxOfTrack(track.id, frame, detectionsNow) : null
  }
}

/** The key that snaps this box among the slots on screen, if any. */
export function keyFor(slots: PlayerSlot[], box: Box): string | null {
  let best: PlayerSlot | null = null
  let bestIou = MATCH_MIN_IOU
  for (const s of slots) {
    const score = iou(box, s.box)
    if (score >= bestIou) { best = s; bestIou = score }
  }
  return best?.key ?? null
}

/** `Q #27 Sarault`, or as much of it as is known; `—` for nobody at all. */
export function describe(who: Who): string {
  const parts: string[] = []
  if (who.key) parts.push(who.key.toUpperCase())
  if (who.number != null) parts.push(`#${who.number}`)
  if (who.name) parts.push(who.name)
  if (!parts.length && who.participant) parts.push(who.participant)
  return parts.join(' ') || '—'
}
