import { describe, expect, it } from 'vitest'
import { resolveKey, type KeyContext } from './keys'

const idle: KeyContext = { placing: null, boxFocused: false }
const placing: KeyContext = { placing: 'thrower', boxFocused: false }
const focused: KeyContext = { placing: null, boxFocused: true }

const press = (key: string, ctx: KeyContext = idle, mod: Partial<{
  shiftKey: boolean; ctrlKey: boolean; metaKey: boolean
}> = {}) =>
  resolveKey({ key, shiftKey: false, ctrlKey: false, metaKey: false, ...mod }, ctx)

describe('event keys', () => {
  it('opens releases and fakes', () => {
    expect(press('t')).toEqual({ type: 'openRelease' })
    expect(press('f')).toEqual({ type: 'openFake' })
  })

  it('resolves a pass, which is a destination rather than an outcome', () => {
    expect(press('p')).toEqual({ type: 'markPass' })
  })

  it('cycles the placement target off G, leaving P to the pass', () => {
    expect(press('g')).toEqual({ type: 'cyclePlacement' })
  })

  it('maps every outcome', () => {
    expect(press('h')).toEqual({ type: 'outcome', outcome: 'hit' })
    expect(press('c')).toEqual({ type: 'outcome', outcome: 'catch' })
    expect(press('b')).toEqual({ type: 'outcome', outcome: 'block' })
    expect(press('m')).toEqual({ type: 'outcome', outcome: 'miss' })
    expect(press('u')).toEqual({ type: 'outcome', outcome: 'unresolved' })
  })

  it('cycles open throws on tab', () => {
    expect(press('Tab')).toEqual({ type: 'cycleOpen', dir: 1 })
    expect(press('Tab', idle, { shiftKey: true })).toEqual({ type: 'cycleOpen', dir: -1 })
  })
})

describe('player keys take the keyboard while a box is pending', () => {
  it('reads T as far-court player five, not as a new throw', () => {
    expect(press('t', placing)).toEqual({ type: 'snapPlayer', playerKey: 't' })
    expect(press('e', placing)).toEqual({ type: 'snapPlayer', playerKey: 'e' })
    expect(press('3', placing)).toEqual({ type: 'snapPlayer', playerKey: '3' })
  })

  it('gives those keys back once the box is placed', () => {
    expect(press('t')).toEqual({ type: 'openRelease' })
    expect(press('e')).toEqual({ type: 'resolutionEnd' })
    expect(press('3')).toBeNull()
  })

  it('leaves outcome keys reachable, so a second throw can still be resolved', () => {
    expect(press('h', placing)).toEqual({ type: 'outcome', outcome: 'hit' })
  })

  it('does not swallow transport', () => {
    expect(press(' ', placing)).toEqual({ type: 'playPause' })
    expect(press('.', placing)).toEqual({ type: 'step', frames: 1 })
  })
})

describe('arrow keys', () => {
  it('seek when no box is selected', () => {
    expect(press('ArrowLeft')).toEqual({ type: 'seek', seconds: -1 })
    expect(press('ArrowRight', idle, { shiftKey: true })).toEqual({ type: 'seek', seconds: 5 })
    expect(press('ArrowUp')).toBeNull()
  })

  it('nudge the selected box a pixel at a time', () => {
    expect(press('ArrowLeft', focused)).toEqual({ type: 'nudge', dx: -1, dy: 0 })
    expect(press('ArrowDown', focused)).toEqual({ type: 'nudge', dx: 0, dy: 1 })
    expect(press('ArrowRight', focused, { shiftKey: true }))
      .toEqual({ type: 'nudge', dx: 10, dy: 0 })
  })
})

describe('modifiers', () => {
  it('reserves ctrl and meta for undo', () => {
    expect(press('z', idle, { ctrlKey: true })).toEqual({ type: 'restoreDeleted' })
    expect(press('t', idle, { ctrlKey: true })).toBeNull()
    expect(press('t', idle, { metaKey: true })).toBeNull()
  })

  it('keeps mute off the miss key', () => {
    expect(press('M')).toEqual({ type: 'mute' })
    expect(press('m')).toEqual({ type: 'outcome', outcome: 'miss' })
  })
})
