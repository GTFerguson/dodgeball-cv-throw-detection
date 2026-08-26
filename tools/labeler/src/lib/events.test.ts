import { describe, expect, it } from 'vitest'
import {
  closeThrow, cycleOpen, emptyState, isLive, kindAfterOutcome, markLiveEnd, markLiveStart,
  markFake, markPass, moveRelease, openEvents, openFake, openRelease, selectedEvent, setIndexAt,
} from './events'

const open3 = () => {
  let s = openRelease(emptyState, 'a', 100)
  s = openRelease(s, 'b', 104)
  s = openRelease(s, 'c', 109)
  return s
}

describe('opening', () => {
  it('opens a release at its frame and selects it', () => {
    const s = openRelease(emptyState, 'a', 100)
    expect(selectedEvent(s)).toMatchObject({ id: 'a', status: 'open', release_frame: 100 })
  })

  it('claims no destination for a release, because none has been seen yet', () => {
    expect(selectedEvent(openRelease(emptyState, 'a', 100))?.kind).toBeNull()
  })

  it('selects the most recently opened throw', () => {
    expect(selectedEvent(open3())?.id).toBe('c')
  })

  it('moves the selected release to a frame without opening a second event', () => {
    const s = moveRelease(open3(), 112)
    expect(s?.events).toHaveLength(3)
    expect(selectedEvent(s!)).toMatchObject({ id: 'c', release_frame: 112 })
  })

  it('moves a fake too: its release frame is the anchor the tolerance is measured from', () => {
    const s = moveRelease(openFake(emptyState, 'f', 50), 47)
    expect(selectedEvent(s!)).toMatchObject({ id: 'f', kind: 'fake', release_frame: 47 })
  })

  it('has nothing to move with no selection, so the caller opens a release instead', () => {
    expect(moveRelease(emptyState, 112)).toBeNull()
  })

  it('opens a fake closed, because it has no resolution to wait for', () => {
    const s = openFake(emptyState, 'f', 50)
    expect(selectedEvent(s)).toMatchObject({ kind: 'fake', status: 'closed', outcome: null })
    expect(openEvents(s)).toEqual([])
  })
})

describe('destination', () => {
  it('settles an outcome as a throw: the ball reached the far side', () => {
    const s = closeThrow(openRelease(emptyState, 'a', 10), 'hit')!
    expect(s.events[0]).toMatchObject({ kind: 'throw', outcome: 'hit' })
  })

  it('leaves an unobserved event undecided rather than counting it a throw', () => {
    const s = closeThrow(openRelease(emptyState, 'a', 10), 'unresolved')!
    expect(s.events[0]).toMatchObject({ kind: null, status: 'closed', outcome: 'unresolved' })
  })

  it('keeps a destination that was seen when the outcome was not', () => {
    expect(kindAfterOutcome('throw', 'unresolved')).toBe('throw')
  })

  it('retracts a pass when the annotator says nothing was observed', () => {
    expect(kindAfterOutcome('pass', 'unresolved')).toBeNull()
  })

  it('closes a pass, which has no ball outcome to wait for', () => {
    const s = markPass(openRelease(emptyState, 'a', 10), 40)!
    expect(s.events[0]).toMatchObject({
      kind: 'pass', status: 'closed', outcome: null, end_frame: 40,
    })
    expect(openEvents(s)).toEqual([])
  })

  it('reclassifies a pass as a throw, because destination is read a beat late', () => {
    const passed = markPass(openRelease(emptyState, 'a', 10))!
    const s = closeThrow(passed, 'hit', 40)!
    expect(s.events[0]).toMatchObject({ kind: 'throw', outcome: 'hit' })
  })

  it('drops the outcome when a throw is reclassified as a pass', () => {
    const thrown = closeThrow(openRelease(emptyState, 'a', 10), 'miss')!
    expect(markPass(thrown)!.events[0]).toMatchObject({ kind: 'pass', outcome: null })
  })

  it('refuses a pass on a fake, which released no ball to send anywhere', () => {
    expect(markPass(openFake(emptyState, 'f', 10))).toBeNull()
  })

  it('refuses a pass with nothing selected', () => {
    expect(markPass(emptyState)).toBeNull()
  })

  it('turns the selected release into a fake, closed with nothing thrown', () => {
    const s = markFake(openRelease(emptyState, 'a', 10))!
    expect(s.events[0]).toMatchObject({ kind: 'fake', status: 'closed', outcome: null, target: null })
    expect(openEvents(s)).toEqual([])
  })

  it('drops the outcome and target when a throw turns out to have been a fake', () => {
    const thrown = closeThrow(openRelease(emptyState, 'a', 10), 'hit')!
    expect(markFake(thrown)!.events[0]).toMatchObject({ kind: 'fake', outcome: null, target: null })
  })

  it('refuses a fake with nothing selected', () => {
    expect(markFake(emptyState)).toBeNull()
  })
})

describe('closing', () => {
  it('closes the selected open throw', () => {
    const s = closeThrow(open3(), 'hit')
    expect(s?.events.find((e) => e.id === 'c')).toMatchObject({ status: 'closed', outcome: 'hit' })
  })

  it('leaves the other open throws open', () => {
    const s = closeThrow(open3(), 'hit')!
    expect(openEvents(s).map((e) => e.id)).toEqual(['a', 'b'])
  })

  it('selects the next most recently opened throw once one closes', () => {
    const s = closeThrow(open3(), 'hit')!
    expect(s.selectedId).toBe('b')
  })

  it('keeps the closed throw selected when nothing is left in the air', () => {
    const s = closeThrow(openRelease(emptyState, 'a', 10), 'miss')!
    expect(s.selectedId).toBe('a')
  })

  it('records the resolution frame when one is given', () => {
    const s = closeThrow(openRelease(emptyState, 'a', 10), 'catch', 31)!
    expect(s.events[0].end_frame).toBe(31)
  })

  it('refuses to close a fake', () => {
    expect(closeThrow(openFake(emptyState, 'f', 10), 'hit')).toBeNull()
  })

  it('refuses to close an already closed throw', () => {
    const once = closeThrow(openRelease(emptyState, 'a', 10), 'hit')!
    expect(closeThrow(once, 'catch')).toBeNull()
  })

  it('refuses to close with nothing selected', () => {
    expect(closeThrow(emptyState, 'hit')).toBeNull()
  })
})

describe('cycling open throws', () => {
  it('walks the open throws in the order they were opened', () => {
    let s = open3()
    expect(s.selectedId).toBe('c')
    s = cycleOpen(s, 1)
    expect(s.selectedId).toBe('a')
    s = cycleOpen(s, 1)
    expect(s.selectedId).toBe('b')
  })

  it('wraps backwards', () => {
    expect(cycleOpen(cycleOpen(open3(), 1), -1).selectedId).toBe('c')
  })

  it('skips closed throws', () => {
    const s = closeThrow(open3(), 'block')!
    expect(cycleOpen(s, 1).selectedId).toBe('a')
    expect(cycleOpen(cycleOpen(s, 1), 1).selectedId).toBe('b')
  })

  it('does nothing when nothing is open', () => {
    const s = closeThrow(openRelease(emptyState, 'a', 10), 'miss')!
    expect(cycleOpen(s, 1)).toBe(s)
  })

  it('enters the ring from a closed selection', () => {
    let s = open3()
    s = closeThrow(s, 'miss')!
    s = { ...s, selectedId: 'c' }
    expect(cycleOpen(s, 1).selectedId).toBe('a')
  })

  it('closes the throw the annotator cycled to, not the newest', () => {
    const s = closeThrow(cycleOpen(open3(), 1), 'catch')!
    expect(s.events.find((e) => e.id === 'a')?.outcome).toBe('catch')
    expect(s.events.find((e) => e.id === 'c')?.status).toBe('open')
  })
})

describe('live play', () => {
  it('marks a set and closes it', () => {
    let iv = markLiveStart([], 's1', 450)
    expect(isLive(iv, 500)).toBe(true)
    expect(isLive(iv, 400)).toBe(false)
    iv = markLiveEnd(iv, 5000)!
    expect(isLive(iv, 5001)).toBe(false)
  })

  it('refuses to end a set that never started', () => {
    expect(markLiveEnd([], 100)).toBeNull()
  })

  it('numbers sets in time order', () => {
    let iv = markLiveStart([], 's1', 100)
    iv = markLiveEnd(iv, 200)!
    iv = markLiveStart(iv, 's2', 300)
    iv = markLiveEnd(iv, 400)!
    expect(setIndexAt(iv, 150)).toBe(1)
    expect(setIndexAt(iv, 350)).toBe(2)
    expect(setIndexAt(iv, 250)).toBeNull()
  })
})
