import type {
  DetectedSet, LivePlayInterval, SetReview, SetTimelineFile, SetVerdict,
} from '../types'
import { detectionSummary } from '../lib/sets'
import { acceptableFrame, anchorDrift, reviewFor, staleReviews, verdictFor } from '../lib/review'
import { formatSeconds } from '../lib/frames'
import { Eyebrow, Kbd } from './ui'

interface Props {
  timeline: SetTimelineFile | null
  reviews: SetReview[]
  livePlay: LivePlayInterval[]
  fps: number
  onJudge: (set: DetectedSet, verdict: SetVerdict) => void
  onSeek: (frame: number) => void
}

/**
 * What the detector claims about set starts, and the annotator's verdict on each.
 *
 * It sits above the label panel because that is the order the work happens in and
 * the order the timeline reads in — the model's claim, then yours. Every claim is
 * listed with the evidence behind it rather than a confidence number: the
 * question a reviewer is answering is whether frame 433 is the whistle, and a
 * whistle 37 dB over the room with the teams breaking 23 frames later is what
 * answers it.
 */
export function SetPanel({ timeline, reviews, livePlay, fps, onJudge, onSeek }: Props) {
  const sets = timeline?.sets ?? []
  const stale = staleReviews(reviews, timeline)

  if (!sets.length) {
    return (
      <div className="flex-none px-3 py-2.5 border-b border-rule text-[11.5px] text-ink-mute">
        {detectionSummary(timeline)}
      </div>
    )
  }

  const reviewed = sets.filter((s) => verdictFor(reviews, s) != null).length

  return (
    <div className="flex-none border-b border-rule">
      <Eyebrow count={`${reviewed}/${sets.length} reviewed`}>Model · set starts</Eyebrow>
      <div className="flex flex-col gap-1.5 px-2 pb-2">
      {sets.map((set, i) => (
        <SetCard
          key={`${set.armed.start_frame}-${set.armed.end_frame}`}
          set={set}
          index={i}
          review={reviewFor(reviews, set)}
          livePlay={livePlay}
          fps={fps}
          onJudge={onJudge}
          onSeek={onSeek}
        />
      ))}
      </div>
      {stale.length > 0 && (
        <p className="px-3 pb-2 text-[11px] text-open leading-relaxed">
          {stale.length} {stale.length === 1 ? 'verdict was' : 'verdicts were'} given on windows
          this detection run no longer has. They judged something else and need giving again.
        </p>
      )}
    </div>
  )
}

interface CardProps {
  set: DetectedSet
  index: number
  review: SetReview | null
  livePlay: LivePlayInterval[]
  fps: number
  onJudge: (set: DetectedSet, verdict: SetVerdict) => void
  onSeek: (frame: number) => void
}

function SetCard({ set, index, review, livePlay, fps, onJudge, onSeek }: CardProps) {
  const start = acceptableFrame(set)
  const at = start ?? set.armed.start_frame
  const verdict = review?.verdict ?? null
  const interval = review?.interval_id
    ? livePlay.find((iv) => iv.id === review.interval_id) ?? null
    : null

  return (
    <div
      onClick={() => onSeek(at)}
      title={`Jump to frame ${at}`}
      className={`px-2 py-2 rounded cursor-pointer border border-l-[3px] ${ACCENT[verdict ?? 'unreviewed']}`}
    >
      <div className="flex items-center gap-2">
        <span className="font-mono text-[12px] tabular-nums font-medium">{at}</span>
        <span className="text-[11px] text-ink-mute font-mono">{formatSeconds(at / fps)}</span>
        <span className="text-[11.5px] text-ink-mute">set {index + 1}</span>
        <VerdictTag verdict={verdict} />
      </div>

      <p className="mt-1 text-[11px] text-ink-mute leading-relaxed">
        {start == null ? 'no start timed · ' : ''}
        {set.whistle_prominence_db != null && (
          <>whistle {set.whistle_prominence_db.toFixed(1)} dB · </>
        )}
        {set.sprint_frame != null && <>break at {set.sprint_frame} · </>}
        {set.armed.max_balls} balls over {set.armed.max_spread_m.toFixed(1)} m,
        laid out {set.armed.start_frame}–{set.armed.end_frame}
      </p>

      {set.notes.map((note, n) => (
        <p key={n} className="mt-0.5 text-[11px] text-ink-faint leading-relaxed">{note}</p>
      ))}

      {interval && <AnchorNote interval={interval} />}

      <div className="mt-1.5 flex items-center gap-1.5">
        <Verdict
          verdict="accepted"
          current={verdict}
          shortcut="⇧A"
          disabled={start == null}
          label={start == null
            ? `Set ${index + 1} has no detected start to accept`
            : `Accept set ${index + 1} start at frame ${start}`}
          title={start == null
            ? 'Nothing to accept: the detector timed no start in this window. Place one by hand with L.'
            : `Make frame ${start} the start of this set`}
          onClick={() => onJudge(set, 'accepted')}
        />
        <Verdict
          verdict="rejected"
          current={verdict}
          shortcut="⇧R"
          label={`Reject the set ${index + 1} claim at frame ${at}`}
          title="Record that this claim is wrong"
          onClick={() => onJudge(set, 'rejected')}
        />
        {start == null && (
          <span className="ml-auto text-[10.5px] text-ink-faint">
            <Kbd>L</Kbd> marks one by hand
          </span>
        )}
      </div>
    </div>
  )
}

/**
 * A card per claim, separated and accented, because two detections stacked in one
 * block read as one paragraph about one set. The accent carries the same thing
 * the timeline's pennant does: still the model's claim, now the annotator's, or
 * rejected and no longer worth ink.
 */
const ACCENT: Record<SetVerdict | 'unreviewed', string> = {
  unreviewed: 'bg-surface border-rule border-l-model hover:bg-surface-2',
  accepted: 'bg-surface-2 border-rule-strong border-l-ink',
  rejected: 'bg-transparent border-rule border-l-rule-strong hover:bg-surface-2',
}

/** What accepting produced, once it exists: whose frame ground truth ended up
 *  with, and how far it sits from the frame the detector proposed. */
function AnchorNote({ interval }: { interval: LivePlayInterval }) {
  const drift = anchorDrift(interval)
  if (interval.start_source === 'manual') {
    return (
      <p className="mt-1 text-[11px] text-ink-mute leading-relaxed">
        Agrees with your own start at frame <span className="font-mono">{interval.start_frame}</span>
        {drift ? `, ${Math.abs(drift)} frames ${drift > 0 ? 'later' : 'earlier'}` : ''}.
      </p>
    )
  }
  return (
    <p className="mt-1 text-[11px] text-ink-mute leading-relaxed">
      Live play opens at frame <span className="font-mono">{interval.start_frame}</span>
      {drift ? ` — moved ${Math.abs(drift)} frames ${drift > 0 ? 'later' : 'earlier'}` : ''}.
      {' '}<Kbd>K</Kbd> ends the set.
    </p>
  )
}

/**
 * Accepted is drawn in ink and rejected in the faint tone, because an accepted
 * start has stopped being the model's claim and become the annotator's, while a
 * rejected one stays the model's and is struck through. Unreviewed keeps the
 * model's own blue: it is still nobody's but the detector's.
 */
function VerdictTag({ verdict }: { verdict: SetVerdict | null }) {
  const style = verdict === 'accepted'
    ? 'bg-ink text-surface border-ink'
    : verdict === 'rejected'
      ? 'bg-transparent text-ink-faint border-rule-strong line-through'
      : 'bg-model-soft text-model border-transparent'
  return (
    <span className={`ml-auto border px-1.5 py-[3px] rounded text-[10px] font-semibold
      uppercase tracking-[.05em] ${style}`}>
      {verdict ?? 'unreviewed'}
    </span>
  )
}

// Every card carries the same two words, so the visible label cannot be the
// accessible one: "Accept" on its own names two different set starts on the same
// screen and identifies neither.
function Verdict({ verdict, current, shortcut, disabled, label, title, onClick }: {
  verdict: SetVerdict
  current: SetVerdict | null
  shortcut: string
  disabled?: boolean
  label: string
  title: string
  onClick: () => void
}) {
  const on = current === verdict
  return (
    <button
      onClick={(e) => { e.stopPropagation(); onClick() }}
      disabled={disabled}
      aria-pressed={on}
      aria-label={label}
      title={title}
      className={`px-2 py-[3px] rounded text-[11px] border disabled:opacity-40
        disabled:cursor-not-allowed ${
        on
          ? 'bg-ink border-ink text-surface'
          : 'bg-surface border-rule-strong text-ink-mute enabled:hover:bg-surface-2'
      }`}
    >
      {verdict === 'accepted' ? 'Accept' : 'Reject'}
      <span className={`ml-1.5 font-mono text-[10px] ${on ? 'opacity-70' : 'text-ink-faint'}`}>
        {shortcut}
      </span>
    </button>
  )
}
