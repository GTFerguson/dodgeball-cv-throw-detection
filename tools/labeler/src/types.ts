// Which half of the court a player is standing in. The camera is fixed and
// end-on, so "near" and "far" are directly observable from the footage and stay
// stable for the whole half — no roster or jersey model is needed to name a side.
export type Team = 'near' | 'far'

// What a candidate turned out to be. Decided by where the ball went rather than
// by what the thrower appeared to intend: a live ball eliminates an opponent
// whatever was meant by it, and destination is the only one of the two that can
// be observed at all. Null means the destination has not been decided — an event
// still in the air, or one closed without it ever being seen.
export type EventKind = 'fake' | 'pass' | 'throw'

export const EVENT_KINDS: EventKind[] = ['fake', 'pass', 'throw']

// Kinds with no ball outcome to wait for. An event of one of these is born
// closed and never joins the in-flight ring.
export const TERMINAL_KINDS: EventKind[] = ['fake', 'pass']

export type Outcome = 'hit' | 'catch' | 'block' | 'miss' | 'unresolved'

// Outcomes that identify a player the ball reached, and therefore require a
// target box. A miss reached nobody; an unresolved outcome was not observed.
export const TARGETED_OUTCOMES: Outcome[] = ['hit', 'catch', 'block']

export const OUTCOMES: Outcome[] = ['hit', 'catch', 'block', 'miss', 'unresolved']

export type RefSignal = 'seen' | 'not_seen' | 'not_visible'

export const REF_SIGNALS: RefSignal[] = ['seen', 'not_seen', 'not_visible']

// A throw stays open from its release until something happens to the ball. Open
// is a state, not the absence of an outcome: a throw whose outcome was never
// observed is closed with `unresolved`, and must not be confused with one the
// annotator has yet to resolve.
export type EventStatus = 'open' | 'closed'

export type BoxSource = 'snapped' | 'drawn'

// Four numbers in source pixels, x1 < x2 and y1 < y2. Nothing here can hold a
// reference to a detection: a snapped box copies the numbers out of the pose run
// and owes it nothing afterwards, so re-running the detector cannot change what
// a label means.
export interface Box {
  x1: number
  y1: number
  x2: number
  y2: number
}

// The pose run that was on screen when a box was placed. Kept for tracing
// annotator bias later; nothing in evaluation reads it.
export interface PoseRunRef {
  run_id: string
  model: string
  weights_sha256: string
  imgsz: number
}

export interface PlacedBox {
  box: Box
  frame: number
  source: BoxSource
  adjusted: boolean
  pose_run: PoseRunRef | null
}

export type TeamSource = 'inferred' | 'override'

export interface ThrowEvent {
  id: string
  status: EventStatus
  kind: EventKind | null
  release_frame: number
  start_frame: number | null
  end_frame: number | null
  thrower: PlacedBox | null
  team: Team | null
  team_source: TeamSource
  outcome: Outcome | null
  target: PlacedBox | null
  release_visible: boolean
  outcome_visible: boolean
  ref_signal: RefSignal | null
  uncertain: boolean
  note: string
}

// One set of live play: from the opening rush to the set ending. Throws outside
// every interval do not count, and the derived metric is computed per set.
export interface LivePlayInterval {
  id: string
  start_frame: number
  end_frame: number | null
}

// A set start as scripts/detect_set_start.py found it. The three statuses are
// kept apart rather than collapsed to a boolean because they mean different
// things to an annotator: a confirmed start is a frame to check, a layout with
// no whistle is a place the clip ran out, and an unconfirmed one is a whistle
// nothing followed.
export type SetStatus = 'confirmed' | 'no_whistle' | 'unconfirmed'

export interface DetectedSet {
  status: SetStatus
  /** The whistle frame. Null unless the set was confirmed. */
  start_frame: number | null
  start_s: number | null
  whistle_prominence_db: number | null
  /** Where the teams broke for the balls — confirmation, not the start time. */
  sprint_frame: number | null
  /** Where the ball layout first broke: the fallback start when audio fails. */
  first_ball_moves_frame: number | null
  armed: {
    start_frame: number
    end_frame: number
    max_balls: number
    max_spread_m: number
  }
  notes: string[]
}

export interface SetTimelineFile {
  schema_version: number
  video: string
  clip_sha256: string
  pose_run: string
  fps: number
  frame_count: number
  clip_offset_s: number
  thresholds: Record<string, number>
  sets: DetectedSet[]
}

export interface VideoInfo {
  name: string
  fps: number
  width: number
  height: number
  frames: number | null
  duration: number | null
}

export interface LabelFile {
  schema_version: 2
  video: string
  fps: number
  width: number
  height: number
  annotator: string
  created: string
  updated: string
  events: ThrowEvent[]
  live_play: LivePlayInterval[]
}

// The court as a camera calibration: a homography between source pixels and the
// court's own metres, fitted from the painted lines. Metres are what the tool
// reasons in — "on court" is a distance from the paint, not a pixel test, so it
// stays meaningful at both ends of a court where near players are twice the size
// of far ones.
export interface CourtConfig {
  video: string
  frame_size: [number, number]
  court_metres: { width: number; length: number }
  /** Court y of the centre line, in metres from the near baseline. */
  centre_line_m: number
  /** How far outside the paint still counts as in play, in metres. */
  margin_m: number
  /** Row-major 3x3 homographies. Court space has its origin at the near-left corner. */
  image_to_court: number[][]
  court_to_image: number[][]
  /** The four court corners in source pixels, near-left first, clockwise. */
  corners_image: [number, number][]
  /** Painted lines running across the court, as observed image y and court y. */
  cross_lines: { image_y: number; court_y: number }[]
}

// One person on one frame, as the pose run recorded them.
export interface PoseDetection {
  box: [number, number, number, number]
  conf: number
  kpts: [number, number, number][]
}

export interface PoseManifest {
  schema_version: number
  run_id: string
  created: string
  video: string
  clip_sha256: string
  fps: number
  frame_count: number
  frame_size: [number, number]
  model: string
  weights_sha256: string
  imgsz: number
  conf: number
  iou: number
  device: string
  keypoint_names: string[]
  chunk_frames: number
  chunks: { file: string; start_frame: number; end_frame: number; frames: number }[]
}

export type PoseChunk = Record<string, PoseDetection[]>

export function newEvent(
  id: string, release_frame: number, kind: EventKind | null,
): ThrowEvent {
  return {
    id,
    // A fake and a pass are terminal: they are born closed, because there is no
    // ball outcome to wait for.
    status: kind != null && TERMINAL_KINDS.includes(kind) ? 'closed' : 'open',
    kind,
    release_frame,
    start_frame: null,
    end_frame: null,
    thrower: null,
    team: null,
    team_source: 'inferred',
    outcome: null,
    target: null,
    release_visible: true,
    outcome_visible: true,
    ref_signal: null,
    uncertain: false,
    note: '',
  }
}

// What an event is still missing before it can be trusted in the truth set.
export function missingFields(e: ThrowEvent): string[] {
  const missing: string[] = []
  if (e.thrower == null) missing.push('thrower')
  if (e.team == null) missing.push('team')
  if (e.status === 'open') missing.push('outcome')
  if (e.outcome != null && TARGETED_OUTCOMES.includes(e.outcome) && e.target == null) {
    missing.push('target')
  }
  return missing
}
