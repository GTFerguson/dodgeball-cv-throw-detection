import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from 'react'
import type { Box, CourtConfig, PoseDetection } from '../types'
import { courtToImage } from '../lib/court'

const css = (name: string) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim()

/** Canvas cannot parse var(); tokens reach it resolved. */
const resolve = (colour: string) =>
  colour.startsWith('var(') ? css(colour.slice(4, -1)) : colour

/** Overlay strokes sit over footage, so tokens are drawn at a chosen opacity. */
function alpha(hex: string, a: number): string {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex)
  if (!m) return hex
  const n = parseInt(m[1], 16)
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`
}
import { timeToFrame } from '../lib/frames'
import type { PlayerSlot } from '../lib/players'
import {
  cursorForHit, hitTestBox, makeBox, resizeBox, translateBox, type BoxHit, type Corner,
  HANDLE_DRAW_PX,
} from '../lib/boxes'
import {
  LENS_RADIUS, LENS_SCALE, createTransform, lensTransform, panBy,
  resetView, resize, toImage, toView, transformAt, zoomAt, type Lens, type ViewTransform,
} from '../lib/transform'
import { KEYPOINT_MIN_CONF, SKELETON, WIRE_TOKEN, casingToken } from '../lib/wire'

// Text over footage: the key badge and every box label share one chip height
// and face, so a badge and the label beside it read as one line.
const CHIP_FONT = '600 13px "IBM Plex Mono", monospace'
const CHIP_H = 18
/** Between a chip and the box edge it sits above, and between two chips. */
const CHIP_GAP = 3
const KEY_BADGE_W = 22
/** A followed box carries a green dot on its chip: the player is being held
 *  through the roster's track, and the box is theirs now rather than then. */
const FOLLOW_DOT_R = 3.5

const WHEEL_ZOOM_STEP = 1.15

/** Something to draw on the frame. The stage is handed these rather than
 *  reaching into label or pose state, so what it can draw is not fixed here. */
export interface OverlayBox {
  box: Box
  label: string
  color: string
  /** The box is where the roster says this player is now, not where it was
   *  placed; shown as a dot on the chip rather than a word. */
  following?: boolean
  /** The box the mouse and the arrow keys are editing. */
  active: boolean
  /** Drawn to be found at a glance - cased, filled, labelled on a chip - for a
   *  claim the annotator is being asked to look at rather than one they placed. */
  loud?: boolean
}

/** What the overlay draws. Each is a separate claim about the frame, and being
 *  able to take one away is how you check it against the picture underneath. */
export interface Layers {
  court: boolean
  skeletons: boolean
  keys: boolean
  boxes: boolean
  ghosts: boolean
}

export const ALL_LAYERS: Layers = {
  court: true, skeletons: true, keys: true, boxes: true, ghosts: true,
}

export interface StageHandle {
  el: HTMLVideoElement | null
  resetView: () => void
}

interface Props {
  src: string
  fps: number
  width: number
  height: number
  players: PlayerSlot[]
  /** Detections with no player key — drawn faintly so the pose run is visibly
   *  loaded before a court polygon exists to filter it. */
  ghosts: PoseDetection[]
  boxes: OverlayBox[]
  court: CourtConfig | null
  layers: Layers
  onFrame: (frame: number) => void
  onPlayState: (playing: boolean) => void
  onDuration: (seconds: number) => void
  onActiveBoxChange: (box: Box) => void
  onDrawBox: (box: Box) => void
}

type Drag =
  | { kind: 'corner'; corner: Corner }
  | { kind: 'body'; grabX: number; grabY: number; box: Box }
  | { kind: 'draw'; x: number; y: number }
  | { kind: 'pan'; x: number; y: number; panX: number; panY: number }

/**
 * The picture and everything drawn on it. The video element is transport only —
 * the frame it presents is drawn into the canvas inside its own frame callback,
 * so the overlay is painted from the same frame the annotator is looking at, and
 * one transform governs the picture, the overlay and the mouse alike.
 */
export const Stage = forwardRef<StageHandle, Props>(function Stage(props, ref) {
  const {
    src, fps, width, height, players, ghosts, boxes, court, layers,
    onFrame, onPlayState, onDuration, onActiveBoxChange, onDrawBox,
  } = props

  const videoRef = useRef<HTMLVideoElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const wrapRef = useRef<HTMLDivElement>(null)

  const [transform, setTransform] = useState<ViewTransform>(() =>
    createTransform(width, height, 1, 1))
  const [cursor, setCursor] = useState<[number, number] | null>(null)
  const [shiftHeld, setShiftHeld] = useState(false)
  const [drag, setDrag] = useState<Drag | null>(null)
  const [pending, setPending] = useState<Box | null>(null)
  const [hover, setHover] = useState<BoxHit>({ kind: 'empty' })

  // Draw reads the latest props and view state through refs: the frame callback
  // outlives any one render, and a stale closure there would paint the overlay
  // for a frame that is no longer on screen.
  const scene = useRef({ transform, players, ghosts, boxes, court, layers, cursor, shiftHeld, pending })
  scene.current = { transform, players, ghosts, boxes, court, layers, cursor, shiftHeld, pending }

  const lens = (): Lens | null =>
    scene.current.shiftHeld && scene.current.cursor
      ? { x: scene.current.cursor[0], y: scene.current.cursor[1], radius: LENS_RADIUS, scale: LENS_SCALE }
      : null

  useImperativeHandle(ref, () => ({
    get el() { return videoRef.current },
    resetView: () => setTransform((t) => resetView(t)),
  }), [])

  const viewPoint = (e: { clientX: number; clientY: number }): [number, number] => {
    const rect = canvasRef.current!.getBoundingClientRect()
    return [e.clientX - rect.left, e.clientY - rect.top]
  }

  // ── drawing ──────────────────────────────────────────────────────────────

  const drawScene = useCallback((ctx: CanvasRenderingContext2D, t: ViewTransform) => {
    const s = scene.current
    const at = (x: number, y: number) => toView(t, x, y)

    // The court margin and a dragged box can both project outside the picture.
    // Clipping to the frame keeps the overlay describing pixels that exist.
    ctx.save()
    ctx.beginPath()
    const [cx0, cy0] = at(0, 0)
    const [cx1, cy1] = at(width, height)
    ctx.rect(cx0, cy0, cx1 - cx0, cy1 - cy0)
    ctx.clip()

    if (s.court && s.layers.court) {
      const c = s.court
      const fit = css('--sig-model')
      const { width: cw, length: cl } = c.court_metres
      // Straight lines stay straight under a homography, so two court-space
      // points describe each painted line however the camera slants it.
      const seg = (x1: number, y1: number, x2: number, y2: number) => {
        const a = courtToImage([x1, y1], c)
        const b = courtToImage([x2, y2], c)
        if (!a || !b) return
        ctx.beginPath()
        ctx.moveTo(...at(a[0], a[1]))
        ctx.lineTo(...at(b[0], b[1]))
        ctx.stroke()
      }

      // The margin is what "on court" actually tests against, so it is drawn.
      const m = c.margin_m
      ctx.strokeStyle = alpha(fit, 0.30)
      ctx.lineWidth = 1
      ctx.setLineDash([5, 5])
      seg(-m, -m, cw + m, -m); seg(-m, cl + m, cw + m, cl + m)
      seg(-m, -m, -m, cl + m); seg(cw + m, -m, cw + m, cl + m)
      ctx.setLineDash([])

      ctx.strokeStyle = alpha(fit, 0.55)
      ctx.lineWidth = 1.5
      seg(0, 0, cw, 0); seg(0, cl, cw, cl)
      seg(0, 0, 0, cl); seg(cw, 0, cw, cl)
      for (const line of c.cross_lines) {
        if (line.court_y <= 0 || line.court_y >= cl) continue
        seg(0, line.court_y, cw, line.court_y)
      }

      ctx.strokeStyle = alpha(fit, 0.9)
      ctx.lineWidth = 2
      seg(0, c.centre_line_m, cw, c.centre_line_m)
    }

    const traceSkeleton = (kpts: PoseDetection['kpts']) => {
      ctx.beginPath()
      for (const [a, b] of SKELETON) {
        const ka = kpts[a]
        const kb = kpts[b]
        if (!ka || !kb || ka[2] < KEYPOINT_MIN_CONF || kb[2] < KEYPOINT_MIN_CONF) continue
        ctx.moveTo(...at(ka[0], ka[1]))
        ctx.lineTo(...at(kb[0], kb[1]))
      }
      ctx.stroke()
    }

    const ink = css('--ink')
    const paper = css('--surface')

    if (s.layers.ghosts) {
      for (const det of s.ghosts) {
        ctx.strokeStyle = alpha(css('--wire-off'), 0.26)
        ctx.lineWidth = 1
        traceSkeleton(det.kpts)
      }
    }

    // Where key badges were drawn, so box labels can step aside from them.
    const badgeCorners: [number, number][] = []
    for (const slot of s.players) {
      if (!s.layers.skeletons && !s.layers.keys) break
      if (s.layers.skeletons) {
      // Casing first, then the wire over it. The casing is what makes a stroke
      // survive crossing a jersey, black shorts and pale floor within one limb,
      // which is what frees the wire's hue to mean team and nothing else.
      const wire = css(WIRE_TOKEN[slot.team])
      ctx.lineCap = 'round'
      ctx.strokeStyle = alpha(css(casingToken(wire)), 0.85)
      ctx.lineWidth = 3.4
      traceSkeleton(slot.detection.kpts)
      ctx.strokeStyle = wire
      ctx.lineWidth = 1.6
      traceSkeleton(slot.detection.kpts)
      }

      // The wire and the key row both carry the team, so the badge stays achromatic.
      if (slot.key && s.layers.keys) {
        const [vx, vy] = at(slot.box.x1, slot.box.y1)
        badgeCorners.push([vx, vy])
        ctx.fillStyle = paper
        ctx.strokeStyle = alpha(ink, 0.35)
        ctx.lineWidth = 1
        ctx.beginPath()
        ctx.roundRect(vx, vy - CHIP_H - CHIP_GAP, KEY_BADGE_W, CHIP_H, 2)
        ctx.fill()
        ctx.stroke()
        ctx.fillStyle = ink
        ctx.font = CHIP_FONT
        ctx.textAlign = 'center'
        ctx.textBaseline = 'middle'
        ctx.fillText(slot.key.toUpperCase(), vx + KEY_BADGE_W / 2, vy - CHIP_GAP - CHIP_H / 2)
        ctx.textAlign = 'start'
        ctx.textBaseline = 'alphabetic'
      }
    }

    const pendingBox: OverlayBox[] = s.pending ? [{ box: s.pending, label: '', color: css('--sig-open'), active: true }] : []
    for (const b of s.layers.boxes ? [...s.boxes, ...pendingBox] : []) {
      const [x1, y1] = at(b.box.x1, b.box.y1)
      const [x2, y2] = at(b.box.x2, b.box.y2)
      const boxColour = resolve(b.color)
      if (b.loud) {
        // A proposal has to be found before it can be judged, on a frame full
        // of skeletons in team colours: a soft fill, a white casing under a
        // heavy stroke, and the label on a chip rather than bare text.
        ctx.fillStyle = alpha(boxColour, 0.14)
        ctx.fillRect(x1, y1, x2 - x1, y2 - y1)
        ctx.strokeStyle = 'rgba(255,255,255,0.9)'
        ctx.lineWidth = 5
        ctx.strokeRect(x1, y1, x2 - x1, y2 - y1)
        ctx.strokeStyle = boxColour
        ctx.lineWidth = 2.5
        ctx.strokeRect(x1, y1, x2 - x1, y2 - y1)
      } else {
        ctx.strokeStyle = 'rgba(255,255,255,0.7)'
        ctx.lineWidth = b.active ? 4 : 3
        ctx.setLineDash(b.active ? [] : [4, 3])
        ctx.strokeRect(x1, y1, x2 - x1, y2 - y1)
        ctx.strokeStyle = boxColour
        ctx.lineWidth = b.active ? 2 : 1.4
        ctx.strokeRect(x1, y1, x2 - x1, y2 - y1)
        ctx.setLineDash([])
      }
      if (b.label) {
        // Every label sits on a chip: bare text on video is unreadable over a
        // pale floor or a white jersey. A loud box fills the chip in its own
        // colour; a quiet one is paper under coloured text, like the key badge.
        // A player's key badge owns the corner above the box, so the chip steps
        // right of it and the two read as one line: `Q proposed @525`.
        ctx.font = CHIP_FONT
        const w = ctx.measureText(b.label).width + 12 + (b.following ? FOLLOW_DOT_R * 2 + 6 : 0)
        const badged = badgeCorners.some(([bx, by]) => Math.abs(bx - x1) < 4 && Math.abs(by - y1) < 4)
        const lx = x1 + (badged ? KEY_BADGE_W + CHIP_GAP : 0)
        // Above the box, unless that is off the top of the frame.
        const ly = y1 - CHIP_H - CHIP_GAP >= 0 ? y1 - CHIP_H - CHIP_GAP : y1 + CHIP_GAP
        ctx.fillStyle = b.loud ? boxColour : paper
        ctx.strokeStyle = b.loud ? 'rgba(255,255,255,0.9)' : alpha(ink, 0.35)
        ctx.lineWidth = 1
        ctx.beginPath()
        ctx.roundRect(lx, ly, w, CHIP_H, 2)
        ctx.fill()
        ctx.stroke()
        ctx.fillStyle = b.loud ? '#fff' : boxColour
        ctx.textBaseline = 'middle'
        ctx.fillText(b.label, lx + 6, ly + CHIP_H / 2)
        ctx.textBaseline = 'alphabetic'
        if (b.following) {
          ctx.fillStyle = css('--sig-catch')
          ctx.beginPath()
          ctx.arc(lx + w - 6 - FOLLOW_DOT_R, ly + CHIP_H / 2, FOLLOW_DOT_R, 0, Math.PI * 2)
          ctx.fill()
        }
      }
      if (b.active) {
        ctx.fillStyle = boxColour
        for (const [cx, cy] of [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]) {
          ctx.fillRect(cx - HANDLE_DRAW_PX, cy - HANDLE_DRAW_PX, HANDLE_DRAW_PX * 2, HANDLE_DRAW_PX * 2)
        }
      }
    }
    ctx.restore()
  }, [])

  const draw = useCallback(() => {
    const canvas = canvasRef.current
    const video = videoRef.current
    if (!canvas || !video) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    const t = scene.current.transform

    const dpr = window.devicePixelRatio || 1
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, t.viewWidth, t.viewHeight)

    const paint = (tt: ViewTransform) => {
      const [ox, oy] = toView(tt, 0, 0)
      const [ex, ey] = toView(tt, t.imageWidth, t.imageHeight)
      if (video.readyState >= 2) ctx.drawImage(video, ox, oy, ex - ox, ey - oy)
      drawScene(ctx, tt)
    }

    paint(t)

    // The magnifier is the same scene under a different transform rather than a
    // pixel copy, so a box drawn inside it is exactly where the mouse says it is.
    const l = lens()
    if (l) {
      ctx.save()
      ctx.beginPath()
      ctx.arc(l.x, l.y, l.radius, 0, Math.PI * 2)
      ctx.clip()
      ctx.fillStyle = '#000'
      ctx.fillRect(l.x - l.radius, l.y - l.radius, l.radius * 2, l.radius * 2)
      paint(lensTransform(t, l))
      ctx.restore()
      ctx.beginPath()
      ctx.arc(l.x, l.y, l.radius, 0, Math.PI * 2)
      ctx.strokeStyle = 'rgba(255,255,255,0.4)'
      ctx.lineWidth = 1.5
      ctx.stroke()
    }
  }, [drawScene])

  // Redraw whenever anything drawable changes, not only on a new frame — a
  // paused annotator adjusting a box must see it move.
  useEffect(() => { draw() })

  useEffect(() => {
    const wrap = wrapRef.current
    const canvas = canvasRef.current
    if (!wrap || !canvas) return
    const fit = () => {
      const dpr = window.devicePixelRatio || 1
      const w = wrap.clientWidth
      const h = wrap.clientHeight
      canvas.width = Math.round(w * dpr)
      canvas.height = Math.round(h * dpr)
      setTransform((t) => resize(t, w, h))
    }
    fit()
    const ro = new ResizeObserver(fit)
    ro.observe(wrap)
    return () => ro.disconnect()
  }, [])

  useEffect(() => {
    setTransform((t) => ({ ...t, imageWidth: width, imageHeight: height }))
  }, [width, height])

  // ── transport ────────────────────────────────────────────────────────────

  useEffect(() => {
    const video = videoRef.current
    if (!video) return

    let handle = 0
    const rvfc = typeof video.requestVideoFrameCallback === 'function'

    // `timeupdate` fires a few times a second and is useless for frame stepping;
    // the frame callback fires once per presented frame, seeks included, so the
    // reported index is what is on screen rather than what was asked for.
    const tick = (_now: number, meta: VideoFrameCallbackMetadata) => {
      onFrame(timeToFrame(meta.mediaTime, fps))
      draw()
      handle = video.requestVideoFrameCallback(tick)
    }
    const fallback = () => { onFrame(timeToFrame(video.currentTime, fps)); draw() }

    if (rvfc) handle = video.requestVideoFrameCallback(tick)
    else video.addEventListener('timeupdate', fallback)

    const onPlay = () => onPlayState(true)
    const onPause = () => onPlayState(false)
    const onMeta = () => { onDuration(video.duration || 0); fallback() }

    video.addEventListener('play', onPlay)
    video.addEventListener('pause', onPause)
    video.addEventListener('loadedmetadata', onMeta)
    video.addEventListener('seeked', fallback)

    return () => {
      if (rvfc) video.cancelVideoFrameCallback(handle)
      else video.removeEventListener('timeupdate', fallback)
      video.removeEventListener('play', onPlay)
      video.removeEventListener('pause', onPause)
      video.removeEventListener('loadedmetadata', onMeta)
      video.removeEventListener('seeked', fallback)
    }
  }, [fps, onFrame, onPlayState, onDuration, draw])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => setShiftHeld(e.shiftKey)
    window.addEventListener('keydown', onKey)
    window.addEventListener('keyup', onKey)
    return () => {
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('keyup', onKey)
    }
  }, [])

  // ── mouse ────────────────────────────────────────────────────────────────

  const activeBox = boxes.find((b) => b.active)?.box ?? null

  const onWheel = (e: React.WheelEvent) => {
    const [vx, vy] = viewPoint(e)
    setTransform((t) => zoomAt(t, vx, vy, e.deltaY < 0 ? WHEEL_ZOOM_STEP : 1 / WHEEL_ZOOM_STEP))
  }

  const onMouseDown = (e: React.MouseEvent) => {
    const [vx, vy] = viewPoint(e)
    if (e.button === 1 || e.ctrlKey) {
      setDrag({ kind: 'pan', x: e.clientX, y: e.clientY, panX: transform.panX, panY: transform.panY })
      return
    }
    if (e.button !== 0) return
    const t = transformAt(transform, lens(), vx, vy)
    const [ix, iy] = toImage(t, vx, vy)

    const hit = activeBox ? hitTestBox(activeBox, t, vx, vy) : { kind: 'empty' as const }
    if (hit.kind === 'corner') setDrag({ kind: 'corner', corner: hit.corner })
    else if (hit.kind === 'body') setDrag({ kind: 'body', grabX: ix, grabY: iy, box: activeBox! })
    else setDrag({ kind: 'draw', x: ix, y: iy })
  }

  const onMouseMove = (e: React.MouseEvent) => {
    const [vx, vy] = viewPoint(e)
    setCursor([vx, vy])

    if (drag?.kind === 'pan') {
      setTransform((t) => panBy({ ...t, panX: drag.panX, panY: drag.panY }, e.clientX - drag.x, e.clientY - drag.y))
      return
    }

    const t = transformAt(transform, lens(), vx, vy)
    const [ix, iy] = toImage(t, vx, vy)

    if (!drag) {
      setHover(activeBox ? hitTestBox(activeBox, t, vx, vy) : { kind: 'empty' })
      return
    }
    if (drag.kind === 'corner' && activeBox) {
      const next = resizeBox(activeBox, drag.corner, ix, iy)
      setDrag({ kind: 'corner', corner: next.corner })
      onActiveBoxChange(next.box)
    } else if (drag.kind === 'body') {
      onActiveBoxChange(translateBox(drag.box, ix - drag.grabX, iy - drag.grabY))
    } else if (drag.kind === 'draw') {
      setPending(makeBox(drag.x, drag.y, ix, iy))
    }
  }

  const endDrag = () => {
    if (drag?.kind === 'draw' && pending) onDrawBox(pending)
    setPending(null)
    setDrag(null)
  }

  const cursorStyle = drag?.kind === 'pan' ? 'grabbing'
    : cursorForHit(hover)

  return (
    <div ref={wrapRef} className="relative w-full h-full bg-surface-3 overflow-hidden">
      {/* Transport only: the frame it decodes is drawn into the canvas above it,
          so there is one picture and one transform rather than two to keep in step. */}
      <video
        ref={videoRef}
        src={src}
        className="absolute inset-0 w-full h-full opacity-0 pointer-events-none"
        playsInline
        controls={false}
        preload="auto"
      />
      <canvas
        ref={canvasRef}
        className="absolute inset-0 w-full h-full"
        style={{ cursor: cursorStyle }}
        onWheel={onWheel}
        onMouseDown={onMouseDown}
        onMouseMove={onMouseMove}
        onMouseUp={endDrag}
        onMouseLeave={() => { endDrag(); setCursor(null) }}
        onContextMenu={(e) => e.preventDefault()}
      />
    </div>
  )
})
