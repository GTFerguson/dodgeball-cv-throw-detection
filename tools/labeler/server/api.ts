import type { Plugin } from 'vite'
import fs from 'node:fs'
import path from 'node:path'
import { execFileSync } from 'node:child_process'
import type { ServerResponse } from 'node:http'
import { resolveWithin, writeFileAtomic } from './paths'

// Footage, labels, pose runs and court geometry all live in the repo's data/
// directory. Footage is served read-only by Vite's static handler; everything
// else is read and written through this middleware so annotations land in the
// repo without a separate backend process.
const DATA_DIR = path.resolve(__dirname, '../../../data')
const FOOTAGE_DIR = path.join(DATA_DIR, 'footage')
const LABELS_DIR = path.join(DATA_DIR, 'labels')
const POSE_DIR = path.join(DATA_DIR, 'pose')
const COURT_DIR = path.join(DATA_DIR, 'court')
const SETS_DIR = path.join(DATA_DIR, 'sets')
const CANDIDATES_DIR = path.join(DATA_DIR, 'candidates')
const ROSTER_DIR = path.join(DATA_DIR, 'roster')
const VIDEO_EXT = /\.(mp4|webm|mkv|mov)$/i

export { DATA_DIR }

// The browser cannot read a container's frame rate, and frame-accurate labelling
// depends on it, so it is probed server-side once per file.
function probe(file: string) {
  try {
    const out = execFileSync(
      'ffprobe',
      ['-v', 'error', '-select_streams', 'v:0',
       '-show_entries', 'stream=avg_frame_rate,r_frame_rate,width,height,nb_frames,duration',
       '-of', 'json', file],
      { encoding: 'utf8' },
    )
    const s = JSON.parse(out).streams?.[0] ?? {}
    const [n, d] = String(s.avg_frame_rate || s.r_frame_rate || '25/1').split('/').map(Number)
    const fps = d ? n / d : n
    const duration = Number(s.duration) || null
    const frames = Number(s.nb_frames) || (duration ? Math.round(duration * fps) : null)
    return { fps, width: s.width, height: s.height, frames, duration }
  } catch {
    return null
  }
}

function json(res: ServerResponse, body: unknown, status = 200): void {
  res.statusCode = status
  res.setHeader('content-type', 'application/json')
  res.end(JSON.stringify(body))
}

function notFound(res: ServerResponse): void {
  res.statusCode = 404
  res.setHeader('content-type', 'application/json')
  res.end('null')
}

function sendFile(res: ServerResponse, file: string | null): void {
  if (!file || !fs.existsSync(file) || !fs.statSync(file).isFile()) return notFound(res)
  res.setHeader('content-type', 'application/json')
  res.end(fs.readFileSync(file))
}

function readBody(req: { on: (ev: string, fn: (c?: unknown) => void) => void }): Promise<string> {
  return new Promise((resolve, reject) => {
    let body = ''
    req.on('data', (c) => (body += c))
    req.on('end', () => resolve(body))
    req.on('error', reject)
  })
}

// A stored JSON document addressed by one path segment, under one root. Labels
// and court geometry are the same shape of endpoint; only the root differs.
async function documentEndpoint(
  root: string, key: string, req: { method?: string } & Parameters<typeof readBody>[0],
  res: ServerResponse,
): Promise<void> {
  const file = resolveWithin(root, `${key}.json`)
  if (!file) return notFound(res)

  if (req.method === 'GET') return sendFile(res, file)

  if (req.method === 'PUT') {
    try {
      writeFileAtomic(file, JSON.stringify(JSON.parse(await readBody(req)), null, 2) + '\n')
      json(res, { ok: true })
    } catch (err) {
      json(res, { error: String(err) }, 400)
    }
    return
  }

  res.statusCode = 405
  res.end()
}

function poseRuns(stem: string): unknown[] {
  const dir = resolveWithin(POSE_DIR, stem)
  if (!dir || !fs.existsSync(dir)) return []
  return fs.readdirSync(dir, { withFileTypes: true })
    .filter((e) => e.isDirectory())
    .map((e) => path.join(dir, e.name, 'manifest.json'))
    .filter((m) => fs.existsSync(m))
    .map((m) => JSON.parse(fs.readFileSync(m, 'utf8')))
}

// How many events the default annotator has on a clip, so the picker can say
// which footage carries the truth set. A clip with no label file reads null and
// is offered as empty rather than looking like labels that vanished.
function labelledCount(videoName: string): number | null {
  const stem = videoName.replace(/\.[^.]+$/, '')
  try {
    const raw = fs.readFileSync(path.join(LABELS_DIR, `${stem}.json`), 'utf8')
    const events = JSON.parse(raw).events
    return Array.isArray(events) ? events.length : null
  } catch {
    return null
  }
}

export function labelApi(): Plugin {
  return {
    name: 'label-api',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const url = new URL(req.url ?? '/', 'http://localhost')
        const seg = url.pathname.split('/').filter(Boolean).map(decodeURIComponent)
        if (seg[0] !== 'api') return next()

        if (seg[1] === 'footage' && seg.length === 2 && req.method === 'GET') {
          fs.mkdirSync(FOOTAGE_DIR, { recursive: true })
          const files = fs.readdirSync(FOOTAGE_DIR).filter((f) => VIDEO_EXT.test(f)).sort()
          return json(res, files.map((name) => ({
            name, ...probe(path.join(FOOTAGE_DIR, name)), labelled: labelledCount(name),
          })))
        }

        if (seg[1] === 'labels' && seg.length === 3) {
          void documentEndpoint(LABELS_DIR, seg[2], req, res)
          return
        }

        if (seg[1] === 'court' && seg.length === 3) {
          void documentEndpoint(COURT_DIR, seg[2], req, res)
          return
        }

        // Read-only: set starts are produced by scripts/detect_set_start.py and
        // shown as the model's claim. The tool must never write them, or the
        // track it is compared against would be one the annotator had edited.
        if (seg[1] === 'sets' && seg.length === 3 && req.method === 'GET') {
          return sendFile(res, resolveWithin(SETS_DIR, `${seg[2]}.json`))
        }

        // Read-only for the same reason: proposals are the model's claim, and a
        // verdict on them lives in the label file, never in the proposals.
        if (seg[1] === 'candidates' && seg.length === 3 && req.method === 'GET') {
          return sendFile(res, resolveWithin(CANDIDATES_DIR, `${seg[2]}.json`))
        }

        // The roster names who is who; the names file beside it is hand-authored
        // and the only source of a player's name. Both read-only here.
        if (seg[1] === 'roster' && seg.length === 3 && req.method === 'GET') {
          return sendFile(res, resolveWithin(ROSTER_DIR, `${seg[2]}.json`))
        }
        if (seg[1] === 'roster' && seg.length === 4 && seg[3] === 'names' && req.method === 'GET') {
          return sendFile(res, resolveWithin(ROSTER_DIR, `${seg[2]}.names.json`))
        }

        if (seg[1] === 'pose' && seg.length === 3 && req.method === 'GET') {
          return json(res, poseRuns(seg[2]))
        }

        if (seg[1] === 'pose' && seg.length === 5 && req.method === 'GET') {
          return sendFile(res, resolveWithin(POSE_DIR, seg[2], seg[3], seg[4]))
        }

        next()
      })
    },
  }
}
