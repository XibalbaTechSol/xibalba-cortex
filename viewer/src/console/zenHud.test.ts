import { describe, expect, it } from 'vitest'
import {
  computeDirichletEnergyEstimate,
  computePresetDirection,
  computeQuantileTier,
  cycleNodeIndex,
  generateLatentQuivers,
} from './zenControls'

describe('Zen Mode & Inner Sanctum Room Contract', () => {
  it('maps all 4 cardinal presets to unit length camera vectors', () => {
    const presets = ['iso', 'top', 'front', 'side'] as const
    for (const p of presets) {
      const v = computePresetDirection(p)
      const len = Math.hypot(v.x, v.y, v.z)
      expect(len).toBeCloseTo(1, 5)
    }
  })

  it('cycles nodes forwards, backwards, and handles boundary wraparound', () => {
    expect(cycleNodeIndex(0, 10, 1)).toBe(1)
    expect(cycleNodeIndex(9, 10, 1)).toBe(0)
    expect(cycleNodeIndex(0, 10, -1)).toBe(9)
    expect(cycleNodeIndex(-1, 10, 1)).toBe(0)
  })

  it('generates high-dimensional embedding tensor quivers with deterministic polarity', () => {
    const quivers = generateLatentQuivers('node-bdnf-001', 16)
    expect(quivers).toHaveLength(16)

    const positiveCount = quivers.filter((q) => q.polarity === 'positive').length
    const negativeCount = quivers.filter((q) => q.polarity === 'negative').length
    expect(positiveCount + negativeCount).toBe(16)

    for (const q of quivers) {
      expect(q.colorHex).toBe(q.polarity === 'positive' ? 0x06b6d4 : 0xf59e0b)
      expect(q.magnitude).toBeGreaterThanOrEqual(0)
      expect(q.magnitude).toBeLessThanOrEqual(1)
    }
  })

  it('computes stepped centrality obelisk tiers and quantile ratings', () => {
    const low = computeQuantileTier(2, 50)
    expect(low.tier).toBe(1)
    expect(low.quantileName).toBe('Base')

    const high = computeQuantileTier(45, 50)
    expect(high.tier).toBe(4)
    expect(high.quantileName).toBe('Pinnacle')
    expect(high.height).toBeGreaterThan(20)
  })

  it('computes Dirichlet topological Laplacian energy for the ripple pool', () => {
    const energy = computeDirichletEnergyEstimate(10, [10, 10, 10])
    expect(energy).toBe(0) // identical neighbor degrees -> zero gradient energy

    const highGradient = computeDirichletEnergyEstimate(20, [1, 2, 1])
    expect(highGradient).toBeGreaterThan(0.3)
  })
})
