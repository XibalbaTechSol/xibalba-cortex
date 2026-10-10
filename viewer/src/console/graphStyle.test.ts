import { describe, expect, it } from 'vitest'
import { MIN_LINK_PX, MIN_NODE_PX, blendOver, boundingSphere, fitDistance, linkWidth, nodeHalf } from './graphStyle'

describe('nodeHalf', () => {
  it('never draws a node smaller than the screen floor, however far out the zoom is', () => {
    for (const scale of [0.05, 0.2, 0.5, 1, 4]) {
      expect(nodeHalf(3, 0, scale) * scale).toBeGreaterThanOrEqual(MIN_NODE_PX - 1e-9)
    }
  })
  it('lets a hub be larger than a leaf, with a ceiling', () => {
    expect(nodeHalf(4.5, 12, 4)).toBeGreaterThan(nodeHalf(4.5, 0, 4))
    expect(nodeHalf(4.5, 500, 4)).toBe(nodeHalf(4.5, 12, 4))
  })
  it('survives a zero or negative scale', () => {
    expect(Number.isFinite(nodeHalf(3, 1, 0))).toBe(true)
  })
})

describe('linkWidth', () => {
  it('renders at least one pixel at any zoom', () => {
    for (const scale of [0.1, 0.5, 1, 3]) expect(linkWidth(0.7, scale) * scale).toBeGreaterThanOrEqual(MIN_LINK_PX - 1e-9)
  })
  it('keeps a thicker requested width', () => {
    expect(linkWidth(2, 1)).toBe(2)
  })
})

describe('blendOver', () => {
  it('is the ground at alpha 0 and the colour at alpha 1', () => {
    expect(blendOver(0xc3b6dd, 0x14171a, 0)).toBe(0x14171a)
    expect(blendOver(0xc3b6dd, 0x14171a, 1)).toBe(0xc3b6dd)
  })
  it('lands between them in each channel, and clamps alpha', () => {
    const mid = blendOver(0xffffff, 0x000000, 0.5)
    expect((mid >> 16) & 255).toBe(128)
    expect(blendOver(0xffffff, 0x000000, 9)).toBe(0xffffff)
    expect(blendOver(0xffffff, 0x000000, -1)).toBe(0x000000)
  })
})

describe('fitDistance', () => {
  it('moves back further for a bigger cloud and a narrower view', () => {
    expect(fitDistance(200, 50, 1.5)).toBeGreaterThan(fitDistance(100, 50, 1.5))
    expect(fitDistance(100, 50, 0.5)).toBeGreaterThan(fitDistance(100, 50, 2))
  })
  it('puts the whole sphere inside the narrower half-angle', () => {
    const d = fitDistance(100, 50, 0.5, 1)
    const half = Math.atan(Math.tan((50 * Math.PI) / 360) * 0.5)
    expect(Math.asin(100 / d)).toBeCloseTo(half, 5)
  })
})

describe('boundingSphere', () => {
  it('is empty for no points', () => {
    expect(boundingSphere([])).toEqual({ cx: 0, cy: 0, cz: 0, radius: 0 })
  })
  it('centres on the extents and reaches the farthest point', () => {
    const s = boundingSphere([{ x: -10, y: 0, z: 0 }, { x: 30, y: 0, z: 0 }, { x: 10, y: 5, z: 0 }])
    // the box is x -10..30, y 0..5, so its centre is (10, 2.5, 0) and the farthest point is (30, 0, 0)
    expect(s.cx).toBe(10)
    expect(s.cy).toBe(2.5)
    expect(s.radius).toBeCloseTo(Math.hypot(20, 2.5), 5)
  })
})
