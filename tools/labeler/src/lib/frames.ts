// Seeking to the exact presentation timestamp of a frame is unreliable across
// browsers (rounding can land on the previous frame). Seeking to the midpoint of
// the frame's interval always displays the intended frame.
export function frameToSeekTime(frame: number, fps: number): number {
  return (frame + 0.5) / fps
}

export function timeToFrame(time: number, fps: number): number {
  return Math.floor(time * fps + 1e-4)
}

export function formatFrameTime(frame: number, fps: number): string {
  const totalSeconds = frame / fps
  const mins = Math.floor(totalSeconds / 60)
  const secs = Math.floor(totalSeconds % 60)
  const sub = frame - Math.floor(totalSeconds) * fps
  return `${mins}:${secs.toString().padStart(2, '0')}.${Math.round(sub).toString().padStart(2, '0')}`
}

export function clampFrame(frame: number, totalFrames: number): number {
  return Math.max(0, Math.min(frame, Math.max(totalFrames - 1, 0)))
}

/** Clock time for a ruler tick, where sub-second precision would be noise. */
export function formatSeconds(seconds: number): string {
  const mins = Math.floor(seconds / 60)
  const secs = Math.floor(seconds % 60)
  return `${mins}:${secs.toString().padStart(2, '0')}`
}
