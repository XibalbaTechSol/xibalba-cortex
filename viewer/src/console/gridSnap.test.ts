import { describe, expect, it } from 'vitest'
import { cellBounds, cellCentre, gridLines, latticeFrame, latticeLines, latticeStride, MAX_LATTICE_SEGMENTS, snapToGrid, type Point } from './gridSnap'

const pt = (id: string, x: number, y: number, z: number, priority = 0): Point => ({ id, x, y, z, priority })
const keyOf = (c: { i: number; j: number; k: number }) => `${c.i},${c.j},${c.k}`

describe('snapToGrid', () => {
  it('puts a lone point in the nearest cell', () => {
    const cells = snapToGrid([pt('a', 49, -23, 1)], 24)
    expect(cells.get('a')).toEqual({ i: 2, j: -1, k: 0 })
  })

  it('never puts two points in one cell, however many land on the same spot', () => {
    const points = Array.from({ length: 40 }, (_, n) => pt(`n${n}`, 0.1 * n, 0, 0))
    const cells = snapToGrid(points, 24)
    expect(new Set([...cells.values()].map(keyOf)).size).toBe(40)
  })

  it('keeps displaced points near where they wanted to be', () => {
    const points = Array.from({ length: 27 }, (_, n) => pt(`n${n}`, 0, 0, 0))
    const cells = snapToGrid(points, 24)
    // 27 points around the origin fill the 3x3x3 block, so none is more than one cell away
    for (const c of cells.values()) expect(Math.max(Math.abs(c.i), Math.abs(c.j), Math.abs(c.k))).toBeLessThanOrEqual(1)
  })

  it('gives the hub its own ideal cell and displaces the leaf', () => {
    const cells = snapToGrid([pt('leaf', 1, 0, 0, 0), pt('hub', 0, 0, 0, 10)], 24)
    expect(cells.get('hub')).toEqual({ i: 0, j: 0, k: 0 })
    expect(keyOf(cells.get('leaf')!)).not.toBe('0,0,0')
  })

  it('is deterministic: the same points in any order land in the same cells', () => {
    const a = [pt('x', 3, 3, 3), pt('y', 3, 4, 3), pt('z', 2, 3, 4)]
    const one = snapToGrid(a, 24)
    const two = snapToGrid([...a].reverse(), 24)
    for (const p of a) expect(two.get(p.id)).toEqual(one.get(p.id))
  })

  it('does not flicker: a point just past a cell boundary stays in its previous cell', () => {
    const first = snapToGrid([pt('a', 11, 0, 0)], 24)
    expect(first.get('a')!.i).toBe(0)
    // 13 is past the 12 boundary (0.54 of a cell from 0), but inside the 0.62 hysteresis
    expect(snapToGrid([pt('a', 13, 0, 0)], 24, first).get('a')!.i).toBe(0)
    // 16 is 0.67 of a cell away, so it moves
    expect(snapToGrid([pt('a', 16, 0, 0)], 24, first).get('a')!.i).toBe(1)
  })

  it('does not let hysteresis put two points in one cell', () => {
    const prev = new Map([['a', { i: 0, j: 0, k: 0 }], ['b', { i: 0, j: 0, k: 0 }]])
    const cells = snapToGrid([pt('a', 0, 0, 0), pt('b', 0, 0, 0)], 24, prev)
    expect(keyOf(cells.get('a')!)).not.toBe(keyOf(cells.get('b')!))
  })

  it('returns nothing for nothing', () => {
    expect(snapToGrid([], 24).size).toBe(0)
  })
})

describe('cellCentre and cellBounds', () => {
  it('maps a cell back to its centre', () => {
    expect(cellCentre({ i: 2, j: -1, k: 0 }, 24)).toEqual({ x: 48, y: -24, z: 0 })
  })
  it('bounds a set of cells, and is null for none', () => {
    expect(cellBounds([{ i: 1, j: 5, k: -2 }, { i: -3, j: 2, k: 4 }])).toEqual({ min: { i: -3, j: 2, k: -2 }, max: { i: 1, j: 5, k: 4 } })
    expect(cellBounds([])).toBeNull()
  })
})

describe('gridLines', () => {
  const b = { min: { i: 0, j: 0, k: 0 }, max: { i: 1, j: 1, k: 1 } }
  it('draws two lines per boundary on each of the three faces', () => {
    // with pad 1 the lattice is 4 cells across, so 5 boundaries each way: 2 directions x 5 lines x 3 faces
    expect(gridLines(b, 24, 1).length / 6).toBe(2 * 5 * 3)
  })
  it('puts every line on a cell boundary, half a cell from the cell centres', () => {
    const v = gridLines(b, 24, 1)
    for (const n of v) expect(Math.abs((n / 24 + 0.5) % 1)).toBeCloseTo(0, 5)
  })
  it('grows with the padding', () => {
    expect(gridLines(b, 24, 2).length).toBeGreaterThan(gridLines(b, 24, 1).length)
  })
})

describe('latticeLines', () => {
  const b = { min: { i: 0, j: 0, k: 0 }, max: { i: 1, j: 1, k: 1 } }
  it('fills the volume: lines along all three axes at every boundary pair', () => {
    // pad 1 makes a 4x4x4 block, so 5 boundaries per axis: 3 axes x 5 x 5 lines
    expect(latticeLines(b, 24, 1).length / 6).toBe(3 * 5 * 5)
  })
  it('has lines that run through the middle, not only on the outside faces', () => {
    const v = latticeLines(b, 24, 1)
    const inner = (n: number) => Math.abs(n) < 24 * 1.4 // well inside the block, away from every face
    let through = 0
    for (let n = 0; n < v.length; n += 6) if (inner(v[n + 1]) && inner(v[n + 2]) && v[n] !== v[n + 3]) through++
    expect(through).toBeGreaterThan(0)
  })
  it('puts every line on a cell boundary', () => {
    for (const n of latticeLines(b, 24, 1)) expect(Math.abs((n / 24 + 0.5) % 1)).toBeCloseTo(0, 5)
  })
  it('falls back to the three faces when the lattice would be too dense', () => {
    const big = { min: { i: 0, j: 0, k: 0 }, max: { i: 80, j: 80, k: 80 } }
    expect(latticeLines(big, 24, 1).length / 6).toBeLessThanOrEqual(MAX_LATTICE_SEGMENTS)
    expect(latticeLines(big, 24, 1)).toEqual(gridLines(big, 24, 1))
  })
})

describe('latticeFrame', () => {
  it('is the twelve edges of the box', () => {
    expect(latticeFrame({ min: { i: 0, j: 0, k: 0 }, max: { i: 1, j: 1, k: 1 } }, 24, 1).length / 6).toBe(12)
  })
})

describe('latticeLines stride', () => {
  const b = { min: { i: 0, j: 0, k: 0 }, max: { i: 5, j: 5, k: 5 } }
  it('draws fewer lines at a larger stride, and a subset of the finer lattice', () => {
    const fine = latticeLines(b, 24, 1, 1), coarse = latticeLines(b, 24, 1, 2)
    expect(coarse.length).toBeLessThan(fine.length)
    const key = (a: Float32Array, n: number) => Array.from(a.slice(n, n + 6)).join(',')
    const fineKeys = new Set<string>()
    for (let n = 0; n < fine.length; n += 6) fineKeys.add(key(fine, n))
    for (let n = 0; n < coarse.length; n += 6) expect(fineKeys.has(key(coarse, n))).toBe(true)
  })
  it('treats a stride below 1 as 1', () => {
    expect(latticeLines(b, 24, 1, 0).length).toBe(latticeLines(b, 24, 1, 1).length)
  })
})

describe('latticeStride', () => {
  it('is 1 while cells are comfortably large on screen', () => {
    expect(latticeStride(30)).toBe(1)
    expect(latticeStride(14)).toBe(1)
  })
  it('doubles until the lines are far enough apart', () => {
    expect(latticeStride(7)).toBe(2)
    expect(latticeStride(3)).toBe(8)
  })
  it('stays finite for a degenerate size', () => {
    expect(latticeStride(0)).toBe(1)
    expect(latticeStride(NaN)).toBe(1)
    expect(latticeStride(1e-9)).toBeLessThanOrEqual(1024)
  })
})
