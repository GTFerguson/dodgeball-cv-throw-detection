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

// Where an event came from. One accepted from a proposal is anchored to the
// detector that proposed it, and that has to survive into the file for the same
// reason a live-play start's source does: a bias that is recorded can be
// reported, and one that is not is indistinguishable from no bias at all.
export type EventSource = 'manual' | 'model'

export interface ThrowEvent {
  id: string
  status: EventStatus
  kind: EventKind | null
  source: EventSource
  /** The frame the detector proposed, kept unchanged when the annotator moves
   *  the release, so the correction made is measurable afterwards. Null for an
   *  event the detector never proposed. */
  proposed_frame: number | null
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

// Where a live-play start came from. Ground truth accepted from a detector is
// anchored to that detector, so which starts were placed blind and which were
// accepted has to survive into the file: a bias that is recorded can be reported,
// and one that is not is indistinguishable from no bias at all.
export type LiveStartSource = 'manual' | 'model'

// One set of live play: from the opening rush to the set ending. Throws outside
// every interval do not count, and the derived metric is computed per set.
export interface LivePlayInterval {
  id: string
  start_frame: number
  end_frame: number | null
  start_source: LiveStartSource
  /** What the detector claimed for this start, kept unchanged when the annotator
   *  moves the frame, so the correction it made is measurable afterwards. */
  detected_start_frame: number | null
}

// The annotator's judgement on one detected set start.
//
// Rejection is recorded rather than left as an absence, because an absence
// cannot be told apart from a detection nobody has looked at yet, and that
// difference is the precision denominator. A verdict names the armed window it
// judged rather than a position in the detector's output: re-running detection
// with other thresholds moves the windows, and a verdict that no longer matches
// one has to surface as stale rather than silently attach to another set.
export type SetVerdict = 'accepted' | 'rejected'

export interface SetReview {
  id: string
  armed_start_frame: number
  armed_end_frame: number
  /** The start frame the detector claimed, or null where it claimed a window only. */
  detected_frame: number | null
  verdict: SetVerdict
  /** The live-play interval an accepted start belongs to. Null for a rejection.
   *  The accepted frame itself lives on that interval and nowhere else, so the
   *  two can never drift apart. */
  interval_id: string | null
  reviewed: string
}

// A throwing motion as scripts/detect_candidates.py proposed it: a frame and a
// thrower, nothing more. Release, destination and outcome are the annotator's.
export interface Candidate {
  frame: number
  track_id: number
  participant: string
  team: Team | null
  score: number
  detection_index: number
  box: [number, number, number, number]
}

export interface CandidateFile {
  schema_version: number
  video: string
  clip_sha256: string
  pose_run: string
  fps: number
  thresholds: Record<string, number>
  candidates: Candidate[]
}

// The annotator's judgement on one proposed throw. Kept for a rejection as much
// as for an acceptance, for the reason a set review is; and named by the frame
// and the box the detector proposed rather than by a position in its output, so
// a re-run that proposes differently leaves the verdict stale rather than moved.
// The box and not the track: a track id is the tracker's, renumbered by every
// re-run, where the player was where they were.
export type CandidateVerdict = 'accepted' | 'rejected'

export interface CandidateReview {
  id: string
  frame: number
  /** The proposed thrower's box on that frame, as the proposal carried it. */
  box: Box
  /** Null is a proposal with a note but no verdict yet - still unreviewed. */
  verdict: CandidateVerdict | null
  /** The event an acceptance created or agreed with. Null otherwise. */
  event_id: string | null
  /** Why it was rejected, or the nuance a verdict cannot carry - written for
   *  whoever reads the file next, so a judgement is more than one bit. */
  note: string
  reviewed: string
}

// Who is who, as scripts/identify_players.py decided it: every tracker span
// with a role and a side, and the person each span belongs to. The tool reads
// it to say who a box is; it never writes identity into a label.
export type RosterRole = 'player' | 'official' | 'unknown'

export interface RosterTrack {
  id: number
  participant: string
  role: RosterRole
  team: Team | null
  number: number | null
  start_frame: number
  end_frame: number
  /** Inclusive frame intervals where the player counted as in play: on the
   *  paint, or within the hold window of having been. */
  in_play: [number, number][]
  /** (frame, index into the pose run's detections on that frame). */
  detections: [number, number][]
}

export interface RosterParticipant {
  id: string
  role: RosterRole
  team: Team | null
  number: number | null
  track_ids: number[]
  start_frame: number
  end_frame: number
  /** In-play frames inside each set's live core, as [set index, frames],
   *  summed over their tracks - the evidence for `played_sets`. */
  core_in_play_by_set: [number, number][]
  /** The same over every set. */
  core_in_play_frames: number
  /** The sets they were on the court for while live, as indices into the set
   *  timeline's `sets` - one less than the "set N" the timeline marks say. */
  played_sets: number[]
  /** On the court while any set was live. Narrower than `role === 'player'`,
   *  which also holds the bench and the queue in team kit. */
  played: boolean
  /** In play when its side already had six on the floor: a second track on
   *  one player, or a misrole. A player by role, never one who played. */
  excess: boolean
}

export interface RosterFile {
  schema_version: number
  video: string
  clip_sha256: string
  pose_run: string
  participants: RosterParticipant[]
  tracks: RosterTrack[]
}

// Names are hand-authored beside the roster: the reader reads digits, and a
// name is read by eye off the jersey. Keyed by side then number.
export interface NamesFile {
  schema_version: number
  video: string
  source: string
  near: Record<string, string>
  far: Record<string, string>
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
  /** Where the set ended, once scripts/detect_set_end.py has run. */
  end?: DetectedEnd | null
}

// A set ends on the hit that puts out the last player of a side. `hit` is
// that moment; `floor` is the last frame one side was down to a single player
// before the court filled - a bound the true end lies at or before, and the
// hit window is where a hit the outcome stage missed has to be.
export interface DetectedEnd {
  frame: number
  end_s: number
  source: 'hit' | 'floor'
  side: Team
  last_stand: [number, number]
  flood_frame: number
  hit_frame: number | null
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
  schema_version: 5
  video: string
  fps: number
  width: number
  height: number
  annotator: string
  created: string
  updated: string
  events: ThrowEvent[]
  live_play: LivePlayInterval[]
  set_reviews: SetReview[]
  candidate_reviews: CandidateReview[]
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
    source: 'manual',
    proposed_frame: null,
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
