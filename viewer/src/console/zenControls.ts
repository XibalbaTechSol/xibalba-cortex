// Zen Mode & Inner Sanctum Room mathematical controls and vector/scalar projections.

export type CameraPreset = 'iso' | 'top' | 'front' | 'side'

export interface Vec3D {
  x: number
  y: number
  z: number
}

/** Normalized camera direction vector for each preset orientation */
export function computePresetDirection(preset: CameraPreset): Vec3D {
  switch (preset) {
    case 'top': {
      const len = Math.hypot(0.001, 1, 0.001)
      return { x: 0.001 / len, y: 1 / len, z: 0.001 / len }
    }
    case 'front': {
      const len = Math.hypot(0, 0.1, 1)
      return { x: 0, y: 0.1 / len, z: 1 / len }
    }
    case 'side': {
      const len = Math.hypot(1, 0.1, 0)
      return { x: 1 / len, y: 0.1 / len, z: 0 }
    }
    case 'iso':
    default: {
      const len = Math.hypot(1, 0.85, 1)
      return { x: 1 / len, y: 0.85 / len, z: 1 / len }
    }
  }
}

/** Cyclic node navigation index helper */
export function cycleNodeIndex(currentIndex: number, total: number, direction: 1 | -1): number {
  if (total <= 0) return 0
  if (currentIndex < 0) return direction === 1 ? 0 : total - 1
  return (currentIndex + direction + total) % total
}

export interface CentralityTier {
  tier: number
  label: string
  normalized: number
  height: number
  quantileName: 'Base' | 'Mid' | 'High' | 'Pinnacle'
}

/** Novel Scalar: Stepped Degree Centrality Obelisk height & quantile tier */
export function computeQuantileTier(degree: number, totalNodes: number): CentralityTier {
  const norm = totalNodes > 1 ? Math.min(1, Math.max(0, degree / Math.max(1, totalNodes - 1))) : 0.5
  let tier = 1
  let quantileName: CentralityTier['quantileName'] = 'Base'
  if (norm >= 0.75) {
    tier = 4
    quantileName = 'Pinnacle'
  } else if (norm >= 0.5) {
    tier = 3
    quantileName = 'High'
  } else if (norm >= 0.25) {
    tier = 2
    quantileName = 'Mid'
  }

  // Obelisk physical height in world units (scaled from 5m to 24m)
  const height = 5 + norm * 19
  const label = `Tier ${tier} (${quantileName} Quantile · ${(norm * 100).toFixed(1)}%)`

  return { tier, label, normalized: norm, height, quantileName }
}

export interface LatentQuiver {
  index: number
  dir: Vec3D
  value: number
  polarity: 'positive' | 'negative'
  magnitude: number
  colorHex: number
}

/**
 * Novel Vector: Generates deterministic 3D Latent Embedding Tensor Quivers
 * pointing along spherical coordinates with positive/negative latent polarity.
 */
export function generateLatentQuivers(nodeId: string, count = 12): LatentQuiver[] {
  let h = 2166136261
  for (let i = 0; i < nodeId.length; i++) {
    h = Math.imul(h ^ nodeId.charCodeAt(i), 16777619)
  }

  const quivers: LatentQuiver[] = []
  // Golden spiral on sphere (Fibonacci sphere distribution)
  const phi = (1 + Math.sqrt(5)) / 2

  for (let i = 0; i < count; i++) {
    const y = 1 - (i / Math.max(1, count - 1)) * 2 // y goes from 1 to -1
    const radiusAtY = Math.sqrt(Math.max(0, 1 - y * y))
    const theta = (2 * Math.PI * i) / phi

    const x = Math.cos(theta) * radiusAtY
    const z = Math.sin(theta) * radiusAtY

    // Deterministic pseudo-random latent component value in [-1, 1]
    const seed = Math.imul(h ^ (i * 0x9e3779b1), 2246822519) >>> 0
    const raw = seed / 4294967296
    const value = raw * 2 - 1
    const polarity: 'positive' | 'negative' = value >= 0 ? 'positive' : 'negative'
    const magnitude = Math.abs(value)

    // Positive polarity = electric cyan (0x06b6d4), negative polarity = radiant amber/rose (0xf59e0b)
    const colorHex = polarity === 'positive' ? 0x06b6d4 : 0xf59e0b

    quivers.push({
      index: i,
      dir: { x, y, z },
      value,
      polarity,
      magnitude,
      colorHex,
    })
  }

  return quivers
}

/**
 * Novel Scalar: Estimated Dirichlet topological energy E(f) = 1/2 sum_{u ~ v} (f(u) - f(v))^2
 */
export function computeDirichletEnergyEstimate(degree: number, neighborDegrees: number[]): number {
  if (neighborDegrees.length === 0) return 0.15
  let sumDiffSq = 0
  for (const nDeg of neighborDegrees) {
    const diff = (degree - nDeg) / Math.max(1, degree + nDeg)
    sumDiffSq += diff * diff
  }
  return Number((0.5 * (sumDiffSq / neighborDegrees.length)).toFixed(4))
}
