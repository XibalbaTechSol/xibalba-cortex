import { describe, expect, it } from 'vitest'
import {
  computeDirichletEnergyEstimate,
  computePresetDirection,
  computeQuantileTier,
  cycleNodeIndex,
  generateLatentQuivers,
} from './zenControls'

describe('zenControls', () => {
  describe('computePresetDirection', () => {
    it('computes unit vectors for all 4 camera presets', () => {
      const presets = ['iso', 'top', 'front', 'side'] as const
      for (const p of presets) {
        const v = computePresetDirection(p)
        const len = Math.hypot(v.x, v.y, v.z)
        expect(len).toBeCloseTo(1, 5)
      }
    })

    it('top preset looks predominantly along +Y', () => {
      const v = computePresetDirection('top')
      expect(v.y).toBeGreaterThan(0.99)
    })

    it('front preset looks predominantly along +Z', () => {
      const v = computePresetDirection('front')
      expect(v.z).toBeGreaterThan(0.95)
    })

    it('side preset looks predominantly along +X', () => {
      const v = computePresetDirection('side')
      expect(v.x).toBeGreaterThan(0.95)
    })
  })

  describe('cycleNodeIndex', () => {
    it('cycles forwards and wraps around', () => {
      expect(cycleNodeIndex(0, 5, 1)).toBe(1)
      expect(cycleNodeIndex(4, 5, 1)).toBe(0)
    })

    it('cycles backwards and wraps around', () => {
      expect(cycleNodeIndex(2, 5, -1)).toBe(1)
      expect(cycleNodeIndex(0, 5, -1)).toBe(4)
    })

    it('handles negative or unselected start index', () => {
      expect(cycleNodeIndex(-1, 5, 1)).toBe(0)
      expect(cycleNodeIndex(-1, 5, -1)).toBe(4)
    })

    it('handles empty collection safely', () => {
      expect(cycleNodeIndex(0, 0, 1)).toBe(0)
    })
  })

  describe('computeQuantileTier (Degree Centrality Obelisk)', () => {
    it('calculates tiered obelisk heights and quantile tiers', () => {
      const base = computeQuantileTier(1, 100)
      expect(base.tier).toBe(1)
      expect(base.quantileName).toBe('Base')
      expect(base.height).toBeLessThan(10)

      const mid = computeQuantileTier(35, 100)
      expect(mid.tier).toBe(2)
      expect(mid.quantileName).toBe('Mid')

      const high = computeQuantileTier(60, 100)
      expect(high.tier).toBe(3)
      expect(high.quantileName).toBe('High')

      const pinnacle = computeQuantileTier(90, 100)
      expect(pinnacle.tier).toBe(4)
      expect(pinnacle.quantileName).toBe('Pinnacle')
      expect(pinnacle.height).toBeGreaterThan(20)
    })
  })

  describe('generateLatentQuivers (High-D Tensor Starburst)', () => {
    it('generates the specified count of quivers in spherical distribution', () => {
      const quivers = generateLatentQuivers('node-bdnf-001', 12)
      expect(quivers).toHaveLength(12)
      for (const q of quivers) {
        expect(q.value).toBeGreaterThanOrEqual(-1)
        expect(q.value).toBeLessThanOrEqual(1)
        expect(q.magnitude).toBeCloseTo(Math.abs(q.value), 4)
        if (q.polarity === 'positive') {
          expect(q.colorHex).toBe(0x06b6d4) // cyan
        } else {
          expect(q.colorHex).toBe(0xf59e0b) // amber
        }
        // Direction vector must be normalized on the unit sphere
        const dirLen = Math.hypot(q.dir.x, q.dir.y, q.dir.z)
        expect(dirLen).toBeCloseTo(1, 4)
      }
    })

    it('is deterministic for the same node id', () => {
      const q1 = generateLatentQuivers('node-alpha', 8)
      const q2 = generateLatentQuivers('node-alpha', 8)
      expect(q1).toEqual(q2)
    })
  })

  describe('computeDirichletEnergyEstimate', () => {
    it('computes Dirichlet energy bounded in [0, 0.5]', () => {
      const e = computeDirichletEnergyEstimate(10, [8, 12, 10, 9])
      expect(e).toBeGreaterThanOrEqual(0)
      expect(e).toBeLessThanOrEqual(0.5)
    })

    it('returns default energy when no neighbors are present', () => {
      expect(computeDirichletEnergyEstimate(5, [])).toBe(0.15)
    })
  })
})
