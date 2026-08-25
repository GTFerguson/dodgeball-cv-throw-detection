import { isUsableCourt } from './court'
import type {
  CourtConfig, LabelFile, PoseChunk, PoseManifest, VideoInfo,
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
  return getJson<LabelFile>(`/api/labels/${encodeURIComponent(key)}`)
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


export function newLabelFile(info: VideoInfo, annotator: string): LabelFile {
  const now = new Date().toISOString()
  return {
    schema_version: 2,
    video: info.name,
    fps: info.fps,
    width: info.width,
    height: info.height,
    annotator,
    created: now,
    updated: now,
    events: [],
    live_play: [],
  }
}
