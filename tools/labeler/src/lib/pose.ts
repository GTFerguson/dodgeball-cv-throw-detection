import type { PoseChunk, PoseDetection, PoseManifest } from '../types'

export type ChunkEntry = PoseManifest['chunks'][number]

export function chunkFor(manifest: PoseManifest, frame: number): ChunkEntry | null {
  return manifest.chunks.find((c) => frame >= c.start_frame && frame < c.end_frame) ?? null
}

/** A frame present with no detections was processed and had nobody in it; a
 *  frame absent was never processed. The two must not be confused, because one
 *  is a statement about the detector and the other is a gap in coverage. */
export function detectionsAt(chunk: PoseChunk, frame: number): PoseDetection[] | null {
  return chunk[String(frame)] ?? null
}

/**
 * Chunks held in memory as they are visited. Labelling walks the clip roughly in
 * order, so a chunk fetched for one throw serves the next few; nothing is evicted
 * because a whole clip's runs are a handful of chunks.
 */
export class PoseCache {
  private chunks = new Map<string, PoseChunk>()
  private pending = new Set<string>()

  constructor(
    readonly manifest: PoseManifest,
    private readonly fetchChunk: (file: string) => Promise<PoseChunk>,
    private readonly onLoaded: () => void,
  ) {}

  /** Detections on a frame, or null while the chunk holding it is still loading. */
  detections(frame: number): PoseDetection[] | null {
    const entry = chunkFor(this.manifest, frame)
    if (!entry) return null
    const chunk = this.chunks.get(entry.file)
    if (chunk) return detectionsAt(chunk, frame)
    this.request(entry.file)
    return null
  }

  private request(file: string): void {
    if (this.pending.has(file)) return
    this.pending.add(file)
    this.fetchChunk(file)
      .then((chunk) => {
        this.chunks.set(file, chunk)
        this.onLoaded()
      })
      .catch(() => {})
      .finally(() => this.pending.delete(file))
  }
}
