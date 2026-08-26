import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type {
  Box, Candidate, CandidateFile, CandidateVerdict, CourtConfig, DetectedSet, LabelFile,
  NamesFile, PoseManifest, RefSignal, RosterFile, SetTimelineFile, SetVerdict, Team, ThrowEvent,
  VideoInfo,
} from './types'
import { REF_SIGNALS, TARGETED_OUTCOMES } from './types'
import { clampFrame, frameToSeekTime } from './lib/frames'
import {
  closeThrow, cycleOpen, deleteEvent, displayOrder, markFake, markLiveEnd, markLiveStart,
  markPass, moveRelease, openFake, openRelease, restoreEvent, selectedEvent, updateEvent, type EventState,
} from './lib/events'
import {
  detectionAt, toggleVerdict, verdictFor, type ReviewState,
} from './lib/review'
import { judgeCandidate, noteCandidate, reviewFor as proposalReviewFor, proposalsToDraw, toCandidateState } from './lib/candidates'
import { RosterIndex } from './lib/roster'
import {
  buildRows, judgeable, nearestRow, nextRow, proximity, visibleRows, type KindFilter,
  type Sources, type StateFilter, type StreamRow,
} from './lib/stream'
import { drawnBox, nudgeBox, snapToDetection, withBox } from './lib/boxes'
import { inferTeam, IN_PLAY_HOLD_FRAMES } from './lib/court'
import { heldPositions, playerSlots, slotForKey } from './lib/players'
import { livePlayBadge } from './lib/sets'
import { PoseCache } from './lib/pose'
import { resolveKey, type Command, type PlacementTarget } from './lib/keys'
import {
  labelKey, listFootage, listPoseRuns, loadCandidates, loadCourt, loadLabels, loadNames,
  loadPoseChunk, loadRoster, loadSets, newLabelFile, saveLabels, videoStem,
} from './lib/storage'
import { ALL_LAYERS, Stage, type Layers, type OverlayBox, type StageHandle } from './components/Stage'
import { SIGNAL_VAR as SIGNAL_CSS, signalOf } from './components/ui'
import { InstrumentBar, SPEEDS } from './components/InstrumentBar'
import { Timeline } from './components/Timeline'
import { Stream, type RowWho } from './components/Stream'

const AUTOSAVE_MS = 800

const LAYER_CHIPS: [keyof Layers, string][] = [
  ['skeletons', 'Skeletons'],
  ['keys', 'Player keys'],
  ['court', 'Court'],
  ['boxes', 'Boxes'],
  ['ghosts', 'Off-court'],
]

type SaveState = 'clean' | 'dirty' | 'saving' | 'saved' | 'error'

function newId() {
  return Math.random().toString(36).slice(2, 10)
}

export default function App() {
  const params = useMemo(() => new URLSearchParams(location.search), [])
  const videoName = params.get('video')
  const annotator = params.get('annotator') ?? 'default'

  const [videos, setVideos] = useState<VideoInfo[] | null>(null)
  useEffect(() => { listFootage().then(setVideos).catch(() => setVideos([])) }, [])

  const info = videos?.find((v) => v.name === videoName) ?? null

  if (!videoName || (videos && !info)) return <Picker videos={videos} annotator={annotator} />
  if (!info) return <div className="p-6 text-ink-mute">Loading…</div>
  return <Labeler key={info.name + annotator} info={info} annotator={annotator} />
}

function Picker({ videos, annotator }: { videos: VideoInfo[] | null; annotator: string }) {
  return (
    <div className="p-8 max-w-xl">
      <h1 className="text-lg font-semibold tracking-[-.015em] mb-1">Throw Labeler</h1>
      <p className="text-[13px] text-ink-mute mb-5 leading-relaxed">
        Footage is read from <code className="font-mono text-ink">data/footage/</code> and labels
        are written to <code className="font-mono text-ink">data/labels/</code> as you work.
        Add <code className="font-mono text-ink">?annotator=name</code> for a separate file, which
        is how a blind second pass keeps clear of the first.
      </p>
      {videos == null ? (
        <p className="text-ink-mute text-[13px]">Scanning data/footage…</p>
      ) : videos.length === 0 ? (
        <p className="text-ink-mute text-[13px]">
          No footage found. Run <code className="font-mono text-ink">scripts/download_footage.sh</code> first.
        </p>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {videos.map((v) => (
            <li key={v.name}>
              <a
                className="block px-3 py-2.5 rounded-md bg-surface border border-rule hover:border-rule-strong shadow-panel"
                href={`?video=${encodeURIComponent(v.name)}${annotator !== 'default' ? `&annotator=${encodeURIComponent(annotator)}` : ''}`}
              >
                <span className="font-medium">{v.name}</span>
                <span className="ml-2.5 text-[11px] text-ink-mute font-mono">
                  {v.width}×{v.height} · {v.fps.toFixed(2)} fps · {v.frames ?? '?'} frames
                </span>
              </a>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function Labeler({ info, annotator }: { info: VideoInfo; annotator: string }) {
  const fps = info.fps
  const stem = videoStem(info.name)
  const key = labelKey(info.name, annotator)

  const stageRef = useRef<StageHandle>(null)
  const noteRef = useRef<HTMLInputElement>(null)

  const [file, setFile] = useState<LabelFile | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [saveState, setSaveState] = useState<SaveState>('clean')
  const [frame, setFrame] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [duration, setDuration] = useState(info.duration ?? 0)
  const [speed, setSpeed] = useState(1)
  const [muted, setMuted] = useState(true)
  const [lastDeleted, setLastDeleted] = useState<ThrowEvent | null>(null)
  const [toast, setToast] = useState<string | null>(null)

  // Which box the next player key, mouse drag or arrow nudge acts on, and
  // whether the player rows currently own the keyboard.
  const [focus, setFocus] = useState<PlacementTarget>('thrower')
  const [armed, setArmed] = useState(false)

  const [court, setCourt] = useState<CourtConfig | null>(null)
  const [sets, setSets] = useState<SetTimelineFile | null>(null)
  const [candidates, setCandidates] = useState<CandidateFile | null>(null)
  const [roster, setRoster] = useState<RosterFile | null>(null)
  const [names, setNames] = useState<NamesFile | null>(null)
  // The row the keys act on, as distinct from the row nearest the playhead.
  const [selectedRowId, setSelectedRowId] = useState<string | null>(null)
  const [sources, setSources] = useState<Sources>({ labels: true, model: true })
  const [kindFilter, setKindFilter] = useState<KindFilter>('all')
  const [stateFilter, setStateFilter] = useState<StateFilter>('all')
  const [layers, setLayers] = useState<Layers>(ALL_LAYERS)

  const [runs, setRuns] = useState<PoseManifest[]>([])
  const [runId, setRunId] = useState<string | null>(null)
  const [poseVersion, setPoseVersion] = useState(0)

  const totalFrames = info.frames ?? Math.round(duration * fps)
  const events = useMemo(() => file?.events ?? [], [file])
  const livePlay = useMemo(() => file?.live_play ?? [], [file])
  const reviews = useMemo(() => file?.set_reviews ?? [], [file])
  const candidateReviews = useMemo(() => file?.candidate_reviews ?? [], [file])
  const state: EventState = useMemo(() => ({ events, selectedId }), [events, selectedId])
  // A dot in the model's colour is what separates "the detector places you in a
  // set" from "your labels do", which the old single-state badge could not say.
  const liveBadge = useMemo(
    () => livePlayBadge(livePlay, sets, frame), [livePlay, sets, frame],
  )
  const selected = selectedEvent(state)

  const flash = useCallback((msg: string) => {
    setToast(msg)
    setTimeout(() => setToast(null), 900)
  }, [])

  // ── load / autosave ──────────────────────────────────────────────────────

  useEffect(() => {
    loadLabels(key).then((f) => setFile(f ?? newLabelFile(info, annotator)))
  }, [key, info, annotator])

  useEffect(() => { loadCourt(stem).then(setCourt).catch(() => setCourt(null)) }, [stem])

  useEffect(() => { loadSets(stem).then(setSets).catch(() => setSets(null)) }, [stem])

  useEffect(() => {
    loadCandidates(stem).then(setCandidates).catch(() => setCandidates(null))
    loadRoster(stem).then(setRoster).catch(() => setRoster(null))
    loadNames(stem).then(setNames).catch(() => setNames(null))
  }, [stem])

  useEffect(() => {
    listPoseRuns(stem).then((r) => {
      setRuns(r)
      setRunId((id) => id ?? r[0]?.run_id ?? null)
    }).catch(() => setRuns([]))
  }, [stem])

  useEffect(() => {
    if (!file || saveState !== 'dirty') return
    const t = setTimeout(async () => {
      setSaveState('saving')
      try {
        await saveLabels(key, { ...file, updated: new Date().toISOString() })
        setSaveState('saved')
      } catch {
        setSaveState('error')
      }
    }, AUTOSAVE_MS)
    return () => clearTimeout(t)
  }, [file, saveState, key])

  const apply = useCallback((next: EventState) => {
    setFile((f) => (f ? { ...f, events: next.events } : f))
    setSelectedId(next.selectedId)
    setSelectedRowId(next.selectedId ? `e-${next.selectedId}` : null)
    setSaveState('dirty')
  }, [])

  const patchSelected = useCallback((patch: Partial<ThrowEvent>) => {
    if (!selectedId) return
    apply(updateEvent(state, selectedId, patch))
  }, [apply, state, selectedId])

  const setLive = useCallback((live: LabelFile['live_play']) => {
    setFile((f) => (f ? { ...f, live_play: live } : f))
    setSaveState('dirty')
  }, [])

  // A verdict writes to both halves of the file at once: the review log, and the
  // live-play interval an accepted start opens. They are saved together because
  // a review pointing at an interval that was never written is a broken file.
  const judge = useCallback((set: DetectedSet, verdict: SetVerdict) => {
    const before: ReviewState = { reviews, livePlay }
    const next = toggleVerdict(
      before, set, verdict,
      { review: newId(), interval: newId() }, new Date().toISOString(),
    )
    if (!next) return flash('the detector timed no start here — mark one with L')
    setFile((f) => (f ? { ...f, set_reviews: next.reviews, live_play: next.livePlay } : f))
    setSaveState('dirty')
    const given = verdictFor(next.reviews, set)
    flash(given ? `set start ${given}` : 'verdict cleared')
  }, [reviews, livePlay, flash])

  // ── pose ─────────────────────────────────────────────────────────────────

  const manifest = useMemo(() => runs.find((r) => r.run_id === runId) ?? null, [runs, runId])
  const cacheRef = useRef<PoseCache | null>(null)

  useEffect(() => {
    cacheRef.current = manifest
      ? new PoseCache(
          manifest,
          (chunkFile) => loadPoseChunk(stem, manifest.run_id, chunkFile),
          () => setPoseVersion((v) => v + 1),
        )
      : null
    setPoseVersion((v) => v + 1)
  }, [manifest, stem])

  const detections = useMemo(
    () => { void poseVersion; return cacheRef.current?.detections(frame) ?? [] },
    [frame, poseVersion],
  )
  // The frames the in-play hold looks at. Sampled rather than every frame in the
  // window: a player who is standing still is standing still at frame f-20 as
  // well as f-19, and fifty lookups per render buys nothing over ten.
  const nearby = useMemo(() => {
    void poseVersion
    const cache = cacheRef.current
    if (!cache || !court) return []
    const frames = []
    for (let d = -IN_PLAY_HOLD_FRAMES; d <= IN_PLAY_HOLD_FRAMES; d += 5) {
      if (d === 0 || frame + d < 0) continue
      const at = cache.detections(frame + d)
      if (at) frames.push(at)
    }
    return heldPositions(frames, court)
  }, [frame, court, poseVersion])

  // With a roster, who is a player in play is its call and not the geometry's;
  // without one, the geometry stands in.
  const rosterIndex = useMemo(() => new RosterIndex(roster, names), [roster, names])
  const players = useMemo(
    () => playerSlots(
      detections, court, nearby,
      rosterIndex.empty ? undefined : (i) => rosterIndex.isPlayerInPlay(frame, i),
    ),
    [detections, court, nearby, rosterIndex, frame],
  )
  const offCourt = useMemo(() => {
    if (!court) return detections
    const kept = new Set(players.map((p) => p.index))
    return detections.filter((_, i) => !kept.has(i))
  }, [detections, players, court])

  // ── transport ────────────────────────────────────────────────────────────

  const video = () => stageRef.current?.el ?? null

  const seekFrame = useCallback((f: number) => {
    const v = video()
    if (!v) return
    const clamped = clampFrame(f, totalFrames)
    v.pause()
    v.currentTime = frameToSeekTime(clamped, fps)
    setFrame(clamped)
  }, [fps, totalFrames])

  const step = useCallback((n: number) => {
    const v = video()
    if (!v) return
    seekFrame(Math.round(v.currentTime * fps - 0.5) + n)
  }, [fps, seekFrame])

  const playPause = useCallback(() => {
    const v = video()
    if (!v) return
    if (v.paused) v.play().catch(() => {})
    else v.pause()
  }, [])

  const changeSpeed = useCallback((s: number) => {
    const v = video()
    if (v) v.playbackRate = s
    setSpeed(s)
  }, [])

  useEffect(() => { const v = video(); if (v) v.muted = muted }, [muted])

  // A verdict on a proposal writes the review and, on acceptance, the event it
  // opened - saved together, because a review pointing at an event that was
  // never written is a broken file.
  const judgeProposal = useCallback((c: Candidate, verdict: CandidateVerdict) => {
    const result = judgeCandidate(
      toCandidateState(state, candidateReviews), c, verdict,
      { review: newId(), event: newId() }, new Date().toISOString(), manifest,
    )
    if (!result.ok) return flash(result.reason)
    setFile((f) => (f ? { ...f, events: result.state.events, candidate_reviews: result.state.reviews } : f))
    setSelectedId(result.state.selectedId)
    setSelectedRowId(result.state.selectedId ? `e-${result.state.selectedId}` : `p-${c.frame}-${c.track_id}`)
    setSaveState('dirty')
    if (verdict === 'accepted' && result.state.selectedId) {
      // The thrower is placed; what the annotator does next is decide the outcome.
      setFocus('thrower')
      setArmed(false)
    }
    flash(result.message)
  }, [state, candidateReviews, manifest, flash])

  // A proposal that is selected takes a classification directly: the outcome
  // or kind key accepts it and applies in one move, because "accept, then say
  // what it was" is a step the annotator should never have to take.
  const classifyProposal = useCallback((c: Candidate, then: (s: EventState) => EventState | null) => {
    const accepted = judgeCandidate(
      toCandidateState(state, candidateReviews), c, 'accepted',
      { review: newId(), event: newId() }, new Date().toISOString(), manifest,
    )
    if (!accepted.ok) return flash(accepted.reason)
    const opened: EventState = { events: accepted.state.events, selectedId: accepted.state.selectedId }
    const next = then(opened) ?? opened
    setFile((f) => (f ? { ...f, events: next.events, candidate_reviews: accepted.state.reviews } : f))
    setSelectedId(next.selectedId)
    setSelectedRowId(next.selectedId ? `e-${next.selectedId}` : null)
    setSaveState('dirty')
    return true
  }, [state, candidateReviews, manifest, flash])

  // ── the stream ───────────────────────────────────────────────────────────

  const rows = useMemo(
    () => buildRows(events, candidates, candidateReviews, sets, reviews, livePlay),
    [events, candidates, candidateReviews, sets, reviews, livePlay],
  )
  const visible = useMemo(
    () => visibleRows(rows, sources, kindFilter, stateFilter),
    [rows, sources, kindFilter, stateFilter],
  )
  const nearest = useMemo(() => nearestRow(visible, frame), [visible, frame])
  const selectedRow = useMemo(
    () => rows.find((r) => r.id === selectedRowId) ?? null, [rows, selectedRowId],
  )

  const selectRow = useCallback((row: StreamRow) => {
    setSelectedRowId(row.id)
    setSelectedId(row.event?.id ?? null)
    seekFrame(row.frame)
  }, [seekFrame])

  const walk = useCallback((dir: 1 | -1) => {
    const next = nextRow(visible, frame, dir)
    if (!next) return flash('nothing in the list')
    selectRow(next)
  }, [visible, frame, selectRow, flash])

  // Who a row's boxes are, looked up rather than stored: the roster names the
  // track behind the detection a box was snapped from, and the player key is
  // whatever would snap it on the frame on screen.
  const whoOf = useCallback((row: StreamRow): RowWho => {
    void poseVersion
    const cache = cacheRef.current
    const slotsFor = (f: number) => (f === frame ? players : [])
    if (row.proposal && !row.event) {
      const c = row.proposal
      const [x1, y1, x2, y2] = c.box
      return {
        thrower: rosterIndex.whoByIndex(c.frame, c.detection_index, slotsFor(c.frame), { x1, y1, x2, y2 }),
        target: null,
      }
    }
    const e = row.event
    if (!e) return { thrower: null, target: null }
    const lookup = (placed: ThrowEvent['thrower']) => placed
      ? rosterIndex.whoByBox(placed.frame, placed.box, cache?.detections(placed.frame) ?? null, slotsFor(placed.frame))
      : null
    return { thrower: lookup(e.thrower), target: lookup(e.target) }
  }, [rosterIndex, players, frame, poseVersion])

  // ── boxes ────────────────────────────────────────────────────────────────

  // Placing a thrower says which half of the court the throw came from, so the
  // team follows it unless the annotator has said otherwise.
  const placeBox = useCallback((target: PlacementTarget, placed: ThrowEvent['thrower']) => {
    if (!selected || !placed) return
    const patch: Partial<ThrowEvent> = { [target]: placed }
    if (target === 'thrower' && selected.team_source !== 'override') {
      patch.team = inferTeam(placed.box, court)
    }
    apply(updateEvent(state, selected.id, patch))
    setArmed(false)
  }, [selected, court, apply, state])

  const editActiveBox = useCallback((box: Box) => {
    const placed = selected?.[focus]
    if (!selected || !placed) return
    const patch: Partial<ThrowEvent> = { [focus]: withBox(placed, box) }
    if (focus === 'thrower' && selected.team_source !== 'override') {
      patch.team = inferTeam(box, court)
    }
    apply(updateEvent(state, selected.id, patch))
  }, [selected, focus, court, apply, state])

  const onDrawBox = useCallback((box: Box) => {
    if (!selected) { flash('no event selected'); return }
    placeBox(focus, drawnBox(box, frame, manifest))
    flash(`${focus} drawn`)
  }, [selected, focus, frame, manifest, placeBox, flash])


  // ── commands ─────────────────────────────────────────────────────────────

  const run = useCallback((cmd: Command) => {
    const fakeSelection = () => {
      if (!selected && selectedRow?.proposal) {
        return classifyProposal(selectedRow.proposal, markFake) && flash('fake')
      }
      const next = markFake(state)
      if (!next) return flash('no event selected')
      apply(next)
      setArmed(false)
      return flash('fake')
    }
    switch (cmd.type) {
      case 'playPause': return playPause()
      case 'step': return step(cmd.frames)
      case 'seekEdge': return seekFrame(cmd.edge === 'start' ? 0 : totalFrames - 1)
      case 'speed': {
        const i = SPEEDS.indexOf(speed)
        return changeSpeed(SPEEDS[Math.max(0, Math.min(SPEEDS.length - 1, i + cmd.dir))])
      }
      case 'mute': return setMuted((m) => !m)
      case 'resetView': return stageRef.current?.resetView()

      case 'openRelease': {
        // The card names `T` beside the release frame, as `S` and `E` sit beside
        // theirs, so with a card selected `T` sets that frame. A new release
        // opens only when nothing is selected.
        const moved = moveRelease(state, frame)
        if (moved) {
          apply(moved)
          return flash(`release moved to ${frame}`)
        }
        apply(openRelease(state, newId(), frame))
        setFocus('thrower')
        setArmed(true)
        return flash(`release opened at ${frame}`)
      }
      case 'openFake': {
        // With a card selected, `f` is about that card, the way the outcome
        // keys are. A new fake opens only when there is nothing to mark, so a
        // key pressed over a selected throw cannot leave it behind and start a
        // second, empty event at the playhead.
        if (selected || selectedRow?.proposal) return fakeSelection()
        apply(openFake(state, newId(), frame))
        setFocus('thrower')
        setArmed(true)
        return flash(`fake at ${frame}`)
      }
      case 'markPass': {
        // A pass has a receiver the way a hit has a target, so the next player
        // key places it - the same hand movement as the targeted outcomes.
        if (!selected && selectedRow?.proposal) {
          if (!classifyProposal(selectedRow.proposal, (s) => markPass(s, frame))) return
          setFocus('target')
          setArmed(true)
          return flash('pass')
        }
        const next = markPass(state, frame)
        // A fake released no ball, so it has no destination to record.
        if (!next) return flash('no event selected, or the selection is a fake')
        apply(next)
        setFocus('target')
        setArmed(true)
        return flash('pass')
      }
      case 'markFake':
        return fakeSelection()
      case 'outcome': {
        if (!selected && selectedRow?.proposal) {
          const done = classifyProposal(selectedRow.proposal, (s) => closeThrow(s, cmd.outcome, frame))
          if (!done) return
          const wantsTarget = TARGETED_OUTCOMES.includes(cmd.outcome)
          setFocus(wantsTarget ? 'target' : 'thrower')
          setArmed(wantsTarget)
          return flash(cmd.outcome)
        }
        const next = closeThrow(state, cmd.outcome, frame)
        if (!next) return flash('no open throw selected')
        apply(next)
        const wantsTarget = TARGETED_OUTCOMES.includes(cmd.outcome)
        setFocus(wantsTarget ? 'target' : 'thrower')
        setArmed(wantsTarget)
        return flash(cmd.outcome)
      }
      case 'cycleOpen': {
        const next = cycleOpen(state, cmd.dir)
        if (next === state) return flash('no open throws')
        apply(next)
        const ev = selectedEvent(next)
        if (ev) seekFrame(ev.release_frame)
        return
      }
      case 'snapPlayer': {
        const slot = slotForKey(players, cmd.playerKey)
        if (!slot) return flash(`no player on ${cmd.playerKey.toUpperCase()}`)
        placeBox(focus, snapToDetection(slot.detection, frame, manifest))
        return flash(`${focus} = ${cmd.playerKey.toUpperCase()}`)
      }
      case 'cyclePlacement': {
        const next: PlacementTarget = focus === 'thrower' ? 'target' : 'thrower'
        setFocus(next)
        setArmed(true)
        return flash(`placing ${next}`)
      }
      case 'windupStart': return patchSelected({ start_frame: frame })
      case 'resolutionEnd': return patchSelected({ end_frame: frame })
      case 'judge': {
        // The selected row if it is the model's claim; otherwise the nearest
        // row in view, provided it is close enough to be what you are looking at.
        const row = judgeable(selectedRow) ? selectedRow
          : judgeable(nearest) && nearest && (nearest.set || Math.abs(nearest.frame - frame) <= 6) ? nearest
          : null
        if (!row) return flash('no detection selected to judge')
        if (row.proposal) return judgeProposal(row.proposal, cmd.verdict)
        if (row.set) return judge(row.set, cmd.verdict)
        return
      }
      case 'walk': return walk(cmd.dir)
      case 'toggle': return selected && patchSelected({ [cmd.field]: !selected[cmd.field] })
      case 'cycleTeam': {
        if (!selected) return
        const order: (Team | null)[] = ['near', 'far', null]
        const at = selected.team_source === 'override' ? order.indexOf(selected.team) : -1
        const team = order[(at + 1) % order.length]
        return patchSelected(team == null
          ? { team: inferTeam(selected.thrower?.box ?? { x1: 0, y1: 0, x2: 0, y2: 0 }, court), team_source: 'inferred' }
          : { team, team_source: 'override' })
      }
      case 'cycleRefSignal': {
        if (!selected) return
        const cycle: (RefSignal | null)[] = [null, ...REF_SIGNALS]
        return patchSelected({ ref_signal: cycle[(cycle.indexOf(selected.ref_signal) + 1) % cycle.length] })
      }
      case 'editNote': return noteRef.current?.focus()
      case 'liveStart': {
        setLive(markLiveStart(livePlay, newId(), frame))
        return flash(`live play from ${frame}`)
      }
      case 'liveEnd': {
        const next = markLiveEnd(livePlay, frame)
        if (!next) return flash('no open set')
        setLive(next)
        return flash(`live play to ${frame}`)
      }
      case 'nudge': {
        const placed = selected?.[focus]
        if (!placed) return
        return editActiveBox(nudgeBox(placed.box, cmd.dx, cmd.dy, info.width, info.height))
      }
      case 'deleteEvent': {
        if (!selected) return
        apply(deleteEvent(state, selected.id))
        setLastDeleted(selected)
        return flash('deleted (ctrl+z to restore)')
      }
      case 'restoreDeleted': {
        if (!lastDeleted) return
        apply(restoreEvent(state, lastDeleted))
        setLastDeleted(null)
        return flash('restored')
      }
      case 'cancel': {
        if (armed) return setArmed(false)
        setSelectedId(null)
        return setSelectedRowId(null)
      }
    }
  }, [
    playPause, step, seekFrame, changeSpeed, apply, patchSelected, placeBox,
    editActiveBox, setLive, judge, flash, state, selected, players, focus, frame, manifest,
    court, livePlay, judgeProposal, classifyProposal, walk, selectedRow, nearest, lastDeleted, speed,
    totalFrames, armed, info.width, info.height,
  ])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)) return
      const cmd = resolveKey(e, {
        placing: armed ? focus : null,
        boxFocused: armed && selected?.[focus] != null,
      })
      if (!cmd) return
      e.preventDefault()
      run(cmd)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [run, armed, focus, selected])

  // ── overlay ──────────────────────────────────────────────────────────────

  // Every box on the frame is drawn by one rule: on the frame it was placed,
  // where it was placed; on any other frame, where the roster says that player
  // is now, falling back to the stored box when the follow cannot be made. The
  // label is never touched - a box is edited only on its own frame.
  const overlayBoxes: OverlayBox[] = useMemo(() => {
    void poseVersion
    const cache = cacheRef.current
    const now = cache?.detections(frame) ?? null
    const out: OverlayBox[] = []

    // One proposal is the one being looked at - the selected card's, or the
    // nearest with nothing selected - and it alone is drawn loud and labelled
    // `proposed`. Others in the same second stay visible but quiet, so a
    // coordinated attack's other throws are there without competing for the eye.
    const looking = selectedRow?.proposal && !selectedRow.event ? selectedRow.proposal : null
    for (const { candidate: c, loud } of proposalsToDraw(candidates, candidateReviews, frame, looking)) {
      const [x1, y1, x2, y2] = c.box
      const box = rosterIndex.boxOfTrack(c.track_id, frame, now) ?? { x1, y1, x2, y2 }
      out.push({
        box,
        label: loud ? `proposed @${c.frame}` : `@${c.frame}`,
        color: 'var(--sig-model)',
        active: false,
        loud,
      })
    }

    if (!selected) return out
    for (const which of ['thrower', 'target'] as PlacementTarget[]) {
      const placed = selected[which]
      if (!placed) continue
      const own = placed.frame === frame
      const followed = own ? placed.box
        : rosterIndex.follow(placed.frame, placed.box, cache?.detections(placed.frame) ?? null, frame, now)
      out.push({
        box: followed ?? placed.box,
        label: `${which} @${placed.frame}`,
        following: !own && followed != null,
        color: SIGNAL_CSS[signalOf(selected)],
        active: which === focus && own,
      })
    }
    return out
  }, [selected, selectedRow, focus, frame, candidates, candidateReviews, rosterIndex, poseVersion])

  const saveLabel: Record<SaveState, string> = {
    clean: '', dirty: 'unsaved', saving: 'saving…', saved: 'saved', error: 'save failed',
  }
  const openCount = events.filter((e) => e.status === 'open').length

  return (
    <div className="h-screen flex flex-col px-[clamp(20px,3vw,52px)] py-3.5">
      <header className="flex-none flex items-center gap-4 flex-wrap pb-3 border-b border-rule">
        <a href="/" className="text-ink-mute hover:text-ink text-lg leading-none" title="All footage">‹</a>
        <span className="font-semibold tracking-[-.015em]">{info.name}</span>
        <div className="flex items-center gap-3.5 text-[12px] text-ink-mute">
          <span className="font-mono">{info.width}×{info.height}</span>
          <span className="w-px h-3 bg-rule-strong" />
          <span className="font-mono">{fps.toFixed(2)} fps</span>
          <span className="w-px h-3 bg-rule-strong" />
          <span>annotator <span className="font-mono text-ink">{annotator}</span></span>
        </div>

        <select
          className="text-[11px] font-mono bg-surface border border-rule-strong rounded px-1.5 py-1 text-ink-mute"
          value={runId ?? ''}
          onChange={(e) => setRunId(e.target.value || null)}
          title="Pose run"
        >
          <option value="">no pose run</option>
          {runs.map((r) => <option key={r.run_id} value={r.run_id}>{r.run_id}</option>)}
        </select>

        {!court && (
          <span className="text-[11px] text-open" title="data/court/<video>.json is missing or of an older shape">
            no court calibration — skeletons unfiltered, no player keys
          </span>
        )}
        {armed && (
          <span className="text-[10px] font-semibold uppercase tracking-[.07em] px-2 py-1 rounded bg-open-soft text-open">
            place {focus}
          </span>
        )}

        <div className="ml-auto flex items-center gap-3.5 text-[11px] text-ink-mute">
          {saveLabel[saveState] && (
            <span className="flex items-center gap-1.5">
              <span className={`w-1.5 h-1.5 rounded-full ${saveState === 'error' ? 'bg-hit' : 'bg-catch'}`} />
              {saveLabel[saveState]}
            </span>
          )}
          <span className="font-mono">{events.length} events</span>
        </div>
      </header>

      <div className="grid grid-cols-[minmax(0,1fr)_356px] gap-3.5 pt-3 flex-1 min-h-0 items-stretch">
        <main className="flex flex-col gap-2.5 min-w-0 min-h-0">
          <div className="relative flex-1 min-h-[220px] bg-surface-3 border border-rule-strong rounded-md overflow-hidden">
            <Stage
              ref={stageRef}
              src={`/footage/${encodeURIComponent(info.name)}`}
              fps={fps}
              width={info.width}
              height={info.height}
              players={players}
              ghosts={offCourt}
              boxes={overlayBoxes}
              court={court}
              layers={layers}
              onFrame={setFrame}
              onPlayState={setPlaying}
              onDuration={setDuration}
              onActiveBoxChange={editActiveBox}
              onDrawBox={onDrawBox}
            />
            <div className="absolute right-2.5 top-2.5 z-10 flex flex-wrap justify-end gap-1.5 max-w-[70%]">
              {LAYER_CHIPS.map(([id, label]) => (
                <button
                  key={id}
                  aria-pressed={layers[id]}
                  onClick={() => setLayers((l) => ({ ...l, [id]: !l[id] }))}
                  className={`px-2 py-1.5 rounded border text-[11.5px] font-medium leading-none shadow-panel ${
                    layers[id]
                      ? 'bg-ink border-ink text-surface'
                      : 'bg-surface border-rule-strong text-ink-mute hover:bg-surface-2'
                  }`}
                >{label}</button>
              ))}
            </div>

            {openCount > 0 && (
              <div className="absolute left-2.5 top-2.5 flex items-center gap-1.5 px-2 py-1 rounded shadow-panel
                bg-surface border border-rule text-[10.5px] uppercase tracking-[.07em] text-ink-mute">
                <span className="w-1.5 h-1.5 rounded-full bg-open" />
                {openCount} {openCount === 1 ? 'throw' : 'throws'} in flight
              </div>
            )}
            {liveBadge && (
              <div className="absolute left-2.5 bottom-2.5 flex items-center gap-1.5 px-2 py-1 rounded shadow-panel
                bg-surface border border-rule text-[10.5px] uppercase tracking-[.07em] text-ink-mute">
                {liveBadge.source === 'model' && (
                  <span className="w-1.5 h-1.5 rounded-full" style={{ background: 'var(--sig-model)' }} />
                )}
                {liveBadge.text}
              </div>
            )}
            {toast && (
              <div className="absolute top-2.5 left-1/2 -translate-x-1/2 px-2.5 py-1 rounded
                bg-ink text-surface text-[11px]">
                {toast}
              </div>
            )}
          </div>

          <Timeline
            events={displayOrder(events)}
            livePlay={livePlay}
            sets={sets}
            reviews={reviews}
            candidates={candidates}
            candidateReviews={candidateReviews}
            frame={frame}
            totalFrames={totalFrames}
            fps={fps}
            selectedId={selectedId}
            onSeek={seekFrame}
            onSelect={(id) => setSelectedId(id)}
          />

          <InstrumentBar
            playing={playing}
            frame={frame}
            totalFrames={totalFrames}
            fps={fps}
            speed={speed}
            muted={muted}
            onPlayPause={playPause}
            onSeekFrame={seekFrame}
            onStep={step}
            onSpeed={changeSpeed}
            onMute={() => setMuted((m) => !m)}
          />
        </main>

        <aside className="flex flex-col min-h-0 bg-surface border border-rule rounded-md shadow-panel overflow-hidden">
          <Stream
            rows={visible}
            total={rows.length}
            sources={sources}
            onSources={setSources}
            kind={kindFilter}
            onKind={setKindFilter}
            state={stateFilter}
            onState={setStateFilter}
            selectedRowId={selectedRowId}
            nearestRowId={nearest?.id ?? null}
            proximity={(row) => proximity(row, frame)}
            fps={fps}
            whoOf={whoOf}
            noteOf={(row) => (row.proposal ? proposalReviewFor(candidateReviews, row.proposal)?.note ?? '' : '')}
            editing={{
              frame, focus, armed, noteRef,
              onChange: patchSelected,
              onFocus: (f) => { setFocus(f); setArmed(true) },
            }}
            onSelect={selectRow}
            onJudge={(row, verdict) => {
              if (row.proposal) judgeProposal(row.proposal, verdict)
              else if (row.set) judge(row.set, verdict)
            }}
            onClassify={(row, what) => {
              if (!row.proposal) return
              if (what === 'fake') classifyProposal(row.proposal, markFake) && flash('fake')
              else if (what === 'pass') classifyProposal(row.proposal, (s) => markPass(s, frame)) && flash('pass')
              else {
                const done = classifyProposal(row.proposal, (s) => closeThrow(s, what, frame))
                if (!done) return
                const wantsTarget = TARGETED_OUTCOMES.includes(what)
                setFocus(wantsTarget ? 'target' : 'thrower')
                setArmed(wantsTarget)
                flash(what)
              }
            }}
            onNote={(row, note) => {
              if (!row.proposal) return
              const reviews = noteCandidate(candidateReviews, row.proposal, note, newId(), new Date().toISOString())
              setFile((f) => (f ? { ...f, candidate_reviews: reviews } : f))
              setSaveState('dirty')
            }}
            onDelete={(e) => { apply(deleteEvent(state, e.id)); setLastDeleted(e) }}
          />
          <div className="flex-none px-3 py-2 border-t border-rule text-[11px] text-ink-faint truncate"
            title={`data/labels/${key}.json`}>
            Saved to data/labels/{key}.json
          </div>
        </aside>
      </div>
    </div>
  )
}

