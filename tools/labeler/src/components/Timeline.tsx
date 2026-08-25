import { useEffect, useRef, useState } from 'react'
import type { LivePlayInterval, ThrowEvent } from '../types'
import { formatSeconds } from '../lib/frames'
import { SIGNAL_VAR, signalOf, type Signal } from './ui'

interface Props {
  events: ThrowEvent[]
  livePlay: LivePlayInterval[]
  frame: number
  totalFrames: number
  fps: number
  selectedId: string | null
  onSeek: (frame: number) => void
  onSelect: (id: string) => void
}

const TRACK_H = 26
const TRACK_Y = 22
const RULER_Y = TRACK_Y + TRACK_H + 16
const HEIGHT = RULER_Y + 14
const GUTTER = 52
const RIGHT = 12

/**
 * One dot per throw, at the release frame — the frame every tolerance is measured
 * against. The shaded band is live play, because a throw outside it does not count.
 *
 * The track is named and legended rather than left as an abstract axis: the first
 * version encoded the same data more elegantly and nobody could read it.
 */
export function Timeline({
  events, livePlay, frame, totalFrames, fps, selectedId, onSeek, onSelect,
}: Props) {
  const wrapRef = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(900)

  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const ro = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  if (!totalFrames) return null

  const x = (f: number) => GUTTER + (f / totalFrames) * (width - GUTTER - RIGHT)
  const mid = TRACK_Y + TRACK_H / 2

  const seekFromEvent = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect()
    const px = ((e.clientX - rect.left) / rect.width) * width
    const f = ((px - GUTTER) / (width - GUTTER - RIGHT)) * totalFrames
    onSeek(Math.max(0, Math.min(Math.round(f), totalFrames)))
  }

  const ticks: number[] = []
  const step = Math.max(1, Math.round(totalFrames / 8 / (fps * 30)) * fps * 30 || fps * 30)
  for (let f = 0; f <= totalFrames; f += step) ticks.push(f)

  return (
    <div ref={wrapRef} className="flex-none bg-surface border border-rule rounded-md px-3 pt-2.5 pb-2">
      <div className="flex items-baseline gap-2.5 mb-1">
        <span className="text-[10.5px] font-semibold uppercase tracking-[.08em] text-ink-faint">Timeline</span>
        <span className="text-[11px] text-ink-mute">
          One dot per throw, at the release frame. Shaded band is live play.
        </span>
      </div>

      <svg
        viewBox={`0 0 ${width} ${HEIGHT}`}
        height={HEIGHT}
        className="block w-full cursor-pointer"
        onClick={seekFromEvent}
        role="img"
        aria-label="Throw timeline"
      >
        <text
          x={0} y={mid + 1} fill="var(--ink-faint)" fontSize="10" fontWeight="600"
          letterSpacing=".08em" dominantBaseline="middle"
        >YOU</text>
        <text
          x={0} y={mid + 12} fill="var(--ink-faint)" fontSize="8.5" dominantBaseline="middle"
        >labels</text>

        <rect
          x={x(0)} y={TRACK_Y} width={x(totalFrames) - x(0)} height={TRACK_H}
          fill="var(--surface)" stroke="var(--rule)" strokeWidth={1} rx={2}
        />
        {livePlay.map((iv) => (
          <rect
            key={iv.id}
            x={x(iv.start_frame)} y={TRACK_Y}
            width={Math.max(x(iv.end_frame ?? totalFrames) - x(iv.start_frame), 1)}
            height={TRACK_H} fill="var(--surface-2)"
          />
        ))}

        {events.map((e) => {
          const sig = signalOf(e)
          const cx = x(e.release_frame)
          return (
            <g
              key={e.id}
              onClick={(ev) => { ev.stopPropagation(); onSelect(e.id); onSeek(e.release_frame) }}
              className="cursor-pointer"
            >
              <title>{`frame ${e.release_frame} · ${sig === 'open' ? 'in flight' : sig}`}</title>
              <Mark cx={cx} cy={mid} signal={sig} />
              {e.id === selectedId && (
                <circle cx={cx} cy={mid} r={9.5} fill="none" stroke="var(--ink)" strokeWidth={1.6} />
              )}
            </g>
          )
        })}

        <line x1={x(frame)} y1={TRACK_Y - 9} x2={x(frame)} y2={TRACK_Y + TRACK_H + 5}
          stroke="var(--ink)" strokeWidth={1.5} pointerEvents="none" />
        <path d={`M${x(frame) - 5},${TRACK_Y - 11} L${x(frame) + 5},${TRACK_Y - 11} L${x(frame)},${TRACK_Y - 4} Z`}
          fill="var(--ink)" pointerEvents="none" />

        <line x1={x(0)} y1={RULER_Y} x2={x(totalFrames)} y2={RULER_Y} stroke="var(--rule)" strokeWidth={1} />
        {ticks.map((f) => (
          <g key={f}>
            <line x1={x(f)} y1={RULER_Y} x2={x(f)} y2={RULER_Y + 4} stroke="var(--rule-strong)" strokeWidth={1} />
            <text
              x={x(f)} y={RULER_Y + 13} fill="var(--ink-faint)" fontSize="9.5"
              fontFamily="IBM Plex Mono, monospace" textAnchor={f === 0 ? 'start' : 'middle'}
            >{formatSeconds(f / fps)}</text>
          </g>
        ))}
      </svg>

      <div className="flex flex-wrap items-center gap-3.5 pt-2 mt-1.5 border-t border-surface-2">
        {(['hit', 'catch', 'block', 'miss', 'unresolved', 'pass', 'fake', 'open'] as Signal[]).map((s) => (
          <span key={s} className="flex items-center gap-1.5 text-[11px] text-ink-mute">
            <svg width="12" height="12" aria-hidden="true"><Mark cx={6} cy={6} signal={s} r={4.4} /></svg>
            {s === 'open' ? 'in flight' : s}
          </span>
        ))}
      </div>
    </div>
  )
}

/** No fill means no throw: a fake is an outline, a pass a grey one, unresolved a
 *  dashed one. Only a ball that crossed gets a filled dot. */
function Mark({ cx, cy, signal, r = 4.8 }: { cx: number; cy: number; signal: Signal; r?: number }) {
  const colour = SIGNAL_VAR[signal]
  if (signal === 'unresolved') {
    return <circle cx={cx} cy={cy} r={r} fill="var(--surface)" stroke={colour} strokeWidth={1.5} strokeDasharray="2.4 2.2" />
  }
  if (signal === 'fake' || signal === 'pass') {
    return <circle cx={cx} cy={cy} r={r} fill="var(--surface)" stroke={colour} strokeWidth={1.9} />
  }
  return <circle cx={cx} cy={cy} r={r} fill={colour} />
}
