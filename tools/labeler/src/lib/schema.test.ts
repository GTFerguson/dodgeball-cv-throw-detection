import { describe, expect, it } from 'vitest'
import type { LabelFile, PoseManifest, ThrowEvent, VideoInfo } from '../types'
import { missingFields, newEvent } from '../types'
import { snapToDetection } from './boxes'
import { chunkFor, detectionsAt } from './pose'
import { labelKey, newLabelFile, videoStem } from './storage'

const info: VideoInfo = {
  name: 'clip.mp4', fps: 25, width: 1920, height: 1080, frames: 5250, duration: 210,
}

const manifest = {
  run_id: 'r1', model: 'm.pt', weights_sha256: 'abc', imgsz: 1920,
} as PoseManifest

function fullEvent(): ThrowEvent {
  return {
    ...newEvent('e1', 1214, 'throw'),
    status: 'closed',
    start_frame: 1201,
    end_frame: 1230,
    thrower: snapToDetection({ box: [800, 400, 900, 700], conf: 0.9, kpts: [] }, 1214, manifest),
    team: 'near',
    team_source: 'override',
    outcome: 'hit',
    target: snapToDetection({ box: [400, 300, 460, 480], conf: 0.8, kpts: [] }, 1230, manifest),
    release_visible: true,
    outcome_visible: false,
    ref_signal: 'seen',
    uncertain: true,
    note: 'graze on the shoulder',
  }
}

describe('label file', () => {
  it('is written at schema version 2', () => {
    expect(newLabelFile(info, 'default').schema_version).toBe(2)
  })

  it('round-trips through the wire unchanged', () => {
    const file: LabelFile = {
      ...newLabelFile(info, 'second'),
      events: [fullEvent(), newEvent('f1', 900, 'fake'), newEvent('p1', 950, 'pass')],
      live_play: [{ id: 'l1', start_frame: 450, end_frame: 5100 }],
    }
    expect(JSON.parse(JSON.stringify(file))).toEqual(file)
  })

  it('carries every field the label is defined by', () => {
    expect(Object.keys(fullEvent()).sort()).toEqual([
      'end_frame', 'id', 'kind', 'note', 'outcome', 'outcome_visible',
      'ref_signal', 'release_frame', 'release_visible', 'start_frame', 'status',
      'target', 'team', 'team_source', 'thrower', 'uncertain',
    ])
  })

  it('stores a box as four numbers, its frame and its provenance — never a detection', () => {
    const thrower = fullEvent().thrower!
    expect(Object.keys(thrower).sort())
      .toEqual(['adjusted', 'box', 'frame', 'pose_run', 'source'])
    expect(Object.keys(thrower.box).sort()).toEqual(['x1', 'x2', 'y1', 'y2'])
  })

  it('stores nothing that evaluation would recompute', () => {
    const keys = Object.keys(fullEvent())
    for (const derived of ['eliminated', 'players_remaining', 'attribution', 'track_id']) {
      expect(keys).not.toContain(derived)
    }
  })

  it('gives a second pass its own file', () => {
    expect(labelKey('clip.mp4', 'default')).toBe('clip')
    expect(labelKey('clip.mp4', 'second')).toBe('clip.second')
    expect(videoStem('clip.mp4')).toBe('clip')
  })
})

describe('completeness', () => {
  it('reports what an open throw still needs', () => {
    expect(missingFields(newEvent('a', 10, null))).toEqual(['thrower', 'team', 'outcome'])
  })

  it('requires a target only where the ball reached someone', () => {
    const base = { ...fullEvent(), target: null }
    expect(missingFields({ ...base, outcome: 'hit' })).toEqual(['target'])
    expect(missingFields({ ...base, outcome: 'miss' })).toEqual([])
    expect(missingFields({ ...base, outcome: 'unresolved' })).toEqual([])
  })

  it('asks nothing of a fake beyond its thrower', () => {
    const fake = { ...newEvent('f', 10, 'fake'), team: 'near' as const }
    expect(missingFields(fake)).toEqual(['thrower'])
  })

  it('asks nothing of a pass beyond its thrower: the receiver is not the metric', () => {
    const pass = { ...newEvent('p', 10, 'pass'), team: 'near' as const }
    expect(missingFields(pass)).toEqual(['thrower'])
  })
})

describe('pose chunks', () => {
  const chunks = {
    chunks: [
      { file: 'frames_00000.json', start_frame: 0, end_frame: 1000, frames: 1000 },
      { file: 'frames_01000.json', start_frame: 1000, end_frame: 2000, frames: 1000 },
    ],
  } as PoseManifest

  it('sends each frame to exactly one chunk', () => {
    expect(chunkFor(chunks, 0)?.file).toBe('frames_00000.json')
    expect(chunkFor(chunks, 999)?.file).toBe('frames_00000.json')
    expect(chunkFor(chunks, 1000)?.file).toBe('frames_01000.json')
    expect(chunkFor(chunks, 2000)).toBeNull()
  })

  it('separates a frame with nobody in it from a frame never processed', () => {
    expect(detectionsAt({ '5': [] }, 5)).toEqual([])
    expect(detectionsAt({ '5': [] }, 6)).toBeNull()
  })
})
