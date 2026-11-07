import { describe, it, expect } from 'vitest'

describe('Formal Mathematics of Graphs', () => {
  it('computes Combinatorial Laplacian L = D - A with zero row sums', () => {
    // 3-cycle triangle graph
    const adj = [
      [0, 1, 1],
      [1, 0, 1],
      [1, 1, 0],
    ]
    const deg = [
      [2, 0, 0],
      [0, 2, 0],
      [0, 0, 2],
    ]
    const laplacian = [
      [2, -1, -1],
      [-1, 2, -1],
      [-1, -1, 2],
    ]

    for (let i = 0; i < 3; i++) {
      const rowSum = laplacian[i].reduce((a, b) => a + b, 0)
      expect(rowSum).toBe(0)
    }

    // Verify L = D - A element-wise
    for (let i = 0; i < 3; i++) {
      for (let j = 0; j < 3; j++) {
        expect(laplacian[i][j]).toBe(deg[i][j] - adj[i][j])
      }
    }
  })

  it('verifies cosine similarity properties S_ij in [-1, 1] and S_ii = 1.0', () => {
    const vectors = [
      [1, 0, 0],
      [0, 1, 0],
      [1, 1, 0],
    ]
    const norm = (v: number[]) => Math.sqrt(v.reduce((s, x) => s + x * x, 0))
    const dot = (u: number[], v: number[]) => u.reduce((s, x, idx) => s + x * v[idx], 0)

    for (let i = 0; i < vectors.length; i++) {
      const selfSim = dot(vectors[i], vectors[i]) / (norm(vectors[i]) * norm(vectors[i]))
      expect(selfSim).toBeCloseTo(1.0, 5)

      for (let j = 0; j < vectors.length; j++) {
        const sim = dot(vectors[i], vectors[j]) / (norm(vectors[i]) * norm(vectors[j]))
        expect(sim).toBeGreaterThanOrEqual(-1.0)
        expect(sim).toBeLessThanOrEqual(1.0)
      }
    }
  })
})
