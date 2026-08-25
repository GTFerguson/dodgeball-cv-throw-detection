import { Pause, Play, ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight, Volume2, VolumeX } from 'lucide-react'
import { formatFrameTime } from '../lib/frames'
import { Kbd } from './ui'

interface Props {
  playing: boolean
  frame: number
  totalFrames: number
  fps: number
  speed: number
  muted: boolean
  onPlayPause: () => void
  onSeekFrame: (frame: number) => void
  onStep: (frames: number) => void
  onSpeed: (speed: number) => void
  onMute: () => void
}

export const SPEEDS = [0.25, 0.5, 1, 1.5, 2]

// Every binding the tool has, permanently on screen. A keyboard-driven tool whose
// keys live behind a shortcut teaches nobody, and the annotator's hands do not
// leave the keys long enough to go looking.
const KEYS: [string, string[]][] = [
  ['event', ['T release', 'F fake', 'P pass', 'H C B M U outcome', 'Tab cycle open', 'S E start/end']],
  ['place', ['1–6 near', 'Q–Y far', 'G thrower/target', 'drag corner · body · empty', '← ↑ → ↓ nudge']],
  ['flags', ['D team', 'V release seen', 'O outcome seen', 'X referee', 'A uncertain', 'N note']],
  ['clip', ['L K live play', 'Del delete', 'Ctrl+Z restore', 'Esc cancel']],
  ['view', ['wheel zoom', 'ctrl+drag pan', 'shift magnify', '0 reset']],
]

export function InstrumentBar({
  playing, frame, totalFrames, fps, speed, muted,
  onPlayPause, onSeekFrame, onStep, onSpeed, onMute,
}: Props) {
  const pct = totalFrames ? (frame / totalFrames) * 100 : 0
  const scrub = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!totalFrames) return
    const rect = e.currentTarget.getBoundingClientRect()
    onSeekFrame(Math.round(((e.clientX - rect.left) / rect.width) * totalFrames))
  }
  const btn = 'w-8 h-7 grid place-items-center border border-rule-strong rounded bg-surface text-ink hover:bg-surface-2'

  return (
    <div className="flex-none border-t border-rule pt-2.5 mt-2 select-none">
      <div
        className="h-1.5 rounded-full bg-surface-3 cursor-pointer mb-2.5"
        onClick={scrub}
        title="Seek"
      >
        <div className="h-full rounded-full bg-ink-mute" style={{ width: `${pct}%` }} />
      </div>

      <div className="flex items-center gap-5 flex-wrap">
        <div className="flex items-baseline gap-2.5">
          <span className="font-mono tabular-nums text-[34px] font-medium leading-none tracking-[-.02em]">
            {String(frame).padStart(5, '0')}
          </span>
          <span className="font-mono text-[13px] text-ink-mute">{formatFrameTime(frame, fps)}</span>
          <span className="font-mono text-[11px] text-ink-faint">/{totalFrames}</span>
        </div>

        <div className="flex gap-1">
          <button className={btn} onClick={() => onStep(-10)} title="Back 10 frames ([)"><ChevronsLeft className="w-4 h-4" /></button>
          <button className={btn} onClick={() => onStep(-1)} title="Back 1 frame (,)"><ChevronLeft className="w-4 h-4" /></button>
          <button className={btn} onClick={onPlayPause} title="Play / pause (space)">
            {playing ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4" />}
          </button>
          <button className={btn} onClick={() => onStep(1)} title="Forward 1 frame (.)"><ChevronRight className="w-4 h-4" /></button>
          <button className={btn} onClick={() => onStep(10)} title="Forward 10 frames (])"><ChevronsRight className="w-4 h-4" /></button>
          <button className={btn} onClick={onMute} title="Mute (shift+M)">
            {muted ? <VolumeX className="w-4 h-4" /> : <Volume2 className="w-4 h-4" />}
          </button>
        </div>

        <div className="flex gap-1">
          {SPEEDS.map((s) => (
            <button
              key={s}
              onClick={() => onSpeed(s)}
              className={`px-2 h-7 rounded border text-[11px] font-medium ${
                speed === s
                  ? 'bg-ink border-ink text-surface'
                  : 'bg-surface border-rule-strong text-ink-mute hover:bg-surface-2'
              }`}
            >
              {s}×
            </button>
          ))}
        </div>
      </div>

      <div className="flex flex-wrap gap-x-5 gap-y-1.5 mt-2.5 pt-2.5 border-t border-surface-2">
        {KEYS.map(([group, items]) => (
          <div key={group} className="flex items-center gap-2">
            <span className="text-[10px] font-semibold uppercase tracking-[.09em] text-ink-faint w-10">{group}</span>
            <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-ink-mute">
              {items.map((item) => {
                const [k, ...rest] = item.split(' ')
                return (
                  <span key={item} className="flex items-center gap-1.5">
                    <Kbd>{k}</Kbd>{rest.join(' ')}
                  </span>
                )
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
