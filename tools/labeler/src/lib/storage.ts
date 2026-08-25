import { isUsableCourt } from './court'
import type {
  CourtConfig, LabelFile, PoseChunk, PoseManifest, SetTimelineFile, VideoInfo,
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
  return raw && upgrade(raw)
}

// A file written before set starts could be reviewed is read as what it was:
// every start placed by hand with no detector behind it, and no detection
// judged either way. Filling the new fields on load rather than at every read
// site keeps the rest of the tool from having to know two shapes.
function upgrade(file: LabelFile): LabelFile {
  return {
    ...file,
    schema_version: LABEL_SCHEMA_VERSION,
    live_play: (file.live_play ?? []).map((iv) => ({
      ...iv,
      start_source: iv.start_source ?? 'manual',
      detected_start_frame: iv.detected_start_frame ?? null,
    })),
    set_reviews: file.set_reviews ?? [],
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


export const LABEL_SCHEMA_VERSION = 3

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
  }
}
