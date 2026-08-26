import { isUsableCourt } from './court'
import type {
  CandidateFile, CourtConfig, LabelFile, NamesFile, PoseChunk, PoseManifest, RosterFile,
  SetTimelineFile, VideoInfo,
} from '../types'

export function videoStem(videoName: string): string {
  return videoName.replace(/\.[^.]+$/, '')
}

export function labelKey(videoName: string, annotator: string): string {
  const stem = videoStem(videoName)
  return annotator === 'default' ? stem : `${stem}.${annotator}`
}

async function getJson<T>(url: string): Promise<T | null> {
  const res = await fetch(url)
  if (res.status === 404) return null
  if (!res.ok) throw new Error(`${url}: ${res.status}`)
  return res.json()
}

async function putJson(url: string, body: unknown): Promise<void> {
  const res = await fetch(url, {
    method: 'PUT',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`${url}: ${res.status}`)
}

export async function listFootage(): Promise<VideoInfo[]> {
  return (await getJson<VideoInfo[]>('/api/footage')) ?? []
}

export async function loadLabels(key: string): Promise<LabelFile | null> {
  const raw = await getJson<LabelFile>(`/api/labels/${encodeURIComponent(key)}`)
  return raw && upgradeLabels(raw)
}

// A file written before set starts or throws could be reviewed is read as what
// it was: every start and every event placed by hand with no detector behind
// it, and no detection judged either way. Filling the new fields on load rather
// than at every read site keeps the rest of the tool from having to know two
// shapes.
//
// Candidate reviews once named their proposal by the tracker's id. A review
// with no box cannot be matched to anything the tool can see, so it is dropped
// here rather than carried as a verdict on nothing; the files that had such
// reviews were rewritten with boxes when the id was retired.
export function upgradeLabels(file: LabelFile): LabelFile {
  return {
    ...file,
    schema_version: LABEL_SCHEMA_VERSION,
    events: (file.events ?? []).map((e) => ({
      ...e,
      source: e.source ?? 'manual',
      proposed_frame: e.proposed_frame ?? null,
    })),
    live_play: (file.live_play ?? []).map((iv) => ({
      ...iv,
      start_source: iv.start_source ?? 'manual',
      detected_start_frame: iv.detected_start_frame ?? null,
    })),
    set_reviews: file.set_reviews ?? [],
    candidate_reviews: (file.candidate_reviews ?? [])
      .filter((r) => r.box != null)
      .map((r) => ({ ...r, note: r.note ?? '' })),
  }
}

export async function saveLabels(key: string, file: LabelFile): Promise<void> {
  return putJson(`/api/labels/${encodeURIComponent(key)}`, file)
}

export async function listPoseRuns(stem: string): Promise<PoseManifest[]> {
  return (await getJson<PoseManifest[]>(`/api/pose/${encodeURIComponent(stem)}`)) ?? []
}

export async function loadPoseChunk(
  stem: string, runId: string, file: string,
): Promise<PoseChunk> {
  const url = `/api/pose/${encodeURIComponent(stem)}/${encodeURIComponent(runId)}/${encodeURIComponent(file)}`
  const chunk = await getJson<PoseChunk>(url)
  if (!chunk) throw new Error(`missing pose chunk ${file}`)
  return chunk
}

// The court is produced by the calibration step, not by this tool. A file that
// is missing or of an older shape means "no court": the overlay draws nothing and
// no player keys are assigned, rather than a crash that takes the page with it.
export async function loadCourt(stem: string): Promise<CourtConfig | null> {
  const raw = await getJson<Partial<CourtConfig>>(`/api/court/${encodeURIComponent(stem)}`)
  return isUsableCourt(raw) ? raw : null
}

// Set starts come from the detection step, not from this tool. Absent means the
// model track has nothing to show yet, which is a state the timeline draws
// rather than an error: labelling works fine without it.
export async function loadSets(stem: string): Promise<SetTimelineFile | null> {
  const raw = await getJson<SetTimelineFile>(`/api/sets/${encodeURIComponent(stem)}`)
  return raw && Array.isArray(raw.sets) ? raw : null
}


// Throw candidates come from the detection step too. Absent means nothing was
// proposed, which the tool says rather than treats as an error: labelling from
// nothing is slower, not wrong.
export async function loadCandidates(stem: string): Promise<CandidateFile | null> {
  const raw = await getJson<CandidateFile>(`/api/candidates/${encodeURIComponent(stem)}`)
  return raw && Array.isArray(raw.candidates) ? raw : null
}

// Who is who comes from the identity pass; names beside it are hand-authored.
// Either may be absent, in which case rows say less rather than fail.
export async function loadRoster(stem: string): Promise<RosterFile | null> {
  const raw = await getJson<RosterFile>(`/api/roster/${encodeURIComponent(stem)}`)
  return raw && Array.isArray(raw.tracks) ? raw : null
}

export async function loadNames(stem: string): Promise<NamesFile | null> {
  const raw = await getJson<NamesFile>(`/api/roster/${encodeURIComponent(stem)}/names`)
  return raw && typeof raw.near === 'object' ? raw : null
}

export const LABEL_SCHEMA_VERSION = 5

export function newLabelFile(info: VideoInfo, annotator: string): LabelFile {
  const now = new Date().toISOString()
  return {
    schema_version: LABEL_SCHEMA_VERSION,
    video: info.name,
    fps: info.fps,
    width: info.width,
    height: info.height,
    annotator,
    created: now,
    updated: now,
    events: [],
    live_play: [],
    set_reviews: [],
    candidate_reviews: [],
  }
}
