import { describe, expect, it } from 'vitest'
import { SNAP_PX, parseFloat2, resolveDrop } from './floating'

const base = { width: 1000, height: 800, winWidth: 400, winHeight: 100 }

describe('resolveDrop', () => {
  it('keeps a drop in open space as a floating position', () => {
    expect(resolveDrop({ ...base, x: 120, y: 200 })).toEqual({ x: 120, y: 200 })
  })

  it('returns to the dock when dropped near the bottom edge', () => {
    // maxY is 700; anything within SNAP_PX of it is a dock
    expect(resolveDrop({ ...base, x: 120, y: 700 })).toBeNull()
    expect(resolveDrop({ ...base, x: 120, y: 700 - SNAP_PX })).toBeNull()
    expect(resolveDrop({ ...base, x: 120, y: 700 - SNAP_PX - 1 })).toEqual({ x: 120, y: 700 - SNAP_PX - 1 })
  })

  it('clamps a drop that would leave the window unreachable', () => {
    // a position is persisted, so off-screen would be off-screen forever
    expect(resolveDrop({ ...base, x: -500, y: -500 })).toEqual({ x: 0, y: 0 })
    expect(resolveDrop({ ...base, x: 9999, y: 100 })).toEqual({ x: 600, y: 100 })
  })

  it('does not go negative when the window is larger than the workspace', () => {
    const r = resolveDrop({ x: 50, y: 10, width: 300, height: 80, winWidth: 400, winHeight: 100 })
    // maxY is 0, so the drop is at the dock
    expect(r).toBeNull()
  })
})

describe('parseFloat2', () => {
  it('accepts a finite pair', () => {
    expect(parseFloat2({ x: 1, y: 2 })).toEqual({ x: 1, y: 2 })
  })
  it('rejects anything else rather than placing a window at NaN', () => {
    for (const bad of [null, undefined, 42, 'x', {}, { x: 1 }, { x: 1, y: 'a' }, { x: NaN, y: 0 }, { x: 0, y: Infinity }]) {
      expect(parseFloat2(bad), JSON.stringify(bad) ?? 'undefined').toBeNull()
    }
  })
})
