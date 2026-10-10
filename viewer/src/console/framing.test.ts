import { describe, expect, it } from 'vitest'
import { frameCamera, principalAxes, type Vec3 } from './framing'

const FOV = 50
/** Project a point through the returned camera and report its normalised device coordinates. */
function ndc(p: Vec3, f: NonNullable<ReturnType<typeof frameCamera>>, aspect: number): [number, number] {
  const d = f.direction
  const worldUp: Vec3 = Math.abs(d[1]) > 0.98 ? [0, 0, 1] : [0, 1, 0]
  const r0: Vec3 = [worldUp[1] * d[2] - worldUp[2] * d[1], worldUp[2] * d[0] - worldUp[0] * d[2], worldUp[0] * d[1] - worldUp[1] * d[0]]
  const rl = Math.hypot(...r0)
  const right: Vec3 = [r0[0] / rl, r0[1] / rl, r0[2] / rl]
  const up: Vec3 = [d[1] * right[2] - d[2] * right[1], d[2] * right[0] - d[0] * right[2], d[0] * right[1] - d[1] * right[0]]
  const cam: Vec3 = [f.target[0] + d[0] * f.distance, f.target[1] + d[1] * f.distance, f.target[2] + d[2] * f.distance]
  const q: Vec3 = [p[0] - cam[0], p[1] - cam[1], p[2] - cam[2]]
  const x = q[0] * right[0] + q[1] * right[1] + q[2] * right[2]
  const y = q[0] * up[0] + q[1] * up[1] + q[2] * up[2]
  const depth = -(q[0] * d[0] + q[1] * d[1] + q[2] * d[2])
  const t = Math.tan((FOV * Math.PI) / 360)
  return [x / (depth * t * aspect), y / (depth * t)]
}

// a deterministic scatter so the tests do not depend on Math.random
const scatter = (n: number, sx: number, sy: number, sz: number): Vec3[] =>
  Array.from({ length: n }, (_, i) => [Math.sin(i * 12.9898) * sx, Math.sin(i * 78.233) * sy, Math.sin(i * 37.719) * sz] as Vec3)

describe('principalAxes', () => {
  it('finds the thin axis of a slab', () => {
    const { vectors, variances } = principalAxes(scatter(200, 100, 100, 3))
    expect(Math.abs(vectors[0][2])).toBeGreaterThan(0.99)
    expect(variances[0]).toBeLessThan(variances[1])
    expect(variances[1]).toBeLessThanOrEqual(variances[2])
  })
  it('returns unit, mutually perpendicular vectors', () => {
    const { vectors } = principalAxes(scatter(150, 80, 40, 10))
    for (const v of vectors) expect(Math.hypot(...v)).toBeCloseTo(1, 6)
    expect(Math.abs(vectors[0][0] * vectors[1][0] + vectors[0][1] * vectors[1][1] + vectors[0][2] * vectors[1][2])).toBeLessThan(1e-6)
  })
  it('handles an empty or single-point cloud without NaN', () => {
    expect(principalAxes([]).variances.every(Number.isFinite)).toBe(true)
    expect(principalAxes([[5, 5, 5]]).variances).toEqual([0, 0, 0])
  })
})

describe('frameCamera', () => {
  it('returns null for no points', () => {
    expect(frameCamera([], { fovDeg: FOV, aspect: 1.5 })).toBeNull()
  })
  it('puts every point inside the frame, for several shapes and aspects', () => {
    for (const aspect of [0.6, 1, 1.78]) {
      for (const pts of [scatter(120, 100, 100, 100), scatter(120, 200, 10, 10), scatter(120, 100, 100, 3), scatter(5, 50, 50, 50)]) {
        const f = frameCamera(pts, { fovDeg: FOV, aspect, margin: 1.05 })!
        for (const p of pts) {
          const [x, y] = ndc(p, f, aspect)
          expect(Math.abs(x)).toBeLessThanOrEqual(1.0001)
          expect(Math.abs(y)).toBeLessThanOrEqual(1.0001)
        }
      }
    }
  })
  it('is tight: some point nearly touches the frame edge', () => {
    const pts = scatter(120, 100, 60, 40)
    const f = frameCamera(pts, { fovDeg: FOV, aspect: 1.5, margin: 1 })!
    const worst = Math.max(...pts.map((p) => Math.max(...ndc(p, f, 1.5).map(Math.abs))))
    expect(worst).toBeGreaterThan(0.98)
  })
  it('looks at a flat cloud face-on, with a tilt so it still reads as 3D', () => {
    const f = frameCamera(scatter(200, 100, 100, 3), { fovDeg: FOV, aspect: 1.5 })!
    expect(Math.abs(f.direction[2])).toBeGreaterThan(0.85)
    expect(Math.abs(f.direction[0]) + Math.abs(f.direction[1])).toBeGreaterThan(0.1)
  })
  it('keeps the preferred direction for a round cloud', () => {
    const f = frameCamera(scatter(300, 100, 100, 100), { fovDeg: FOV, aspect: 1.5, prefer: [0, 0, 1] })!
    expect(f.direction[2]).toBeCloseTo(1, 1)
  })
  it('never flips to the far side of a flat cloud', () => {
    const pts = scatter(200, 100, 100, 3)
    const front = frameCamera(pts, { fovDeg: FOV, aspect: 1.5, prefer: [0, 0, 1] })!
    const back = frameCamera(pts, { fovDeg: FOV, aspect: 1.5, prefer: [0, 0, -1] })!
    expect(front.direction[2]).toBeGreaterThan(0)
    expect(back.direction[2]).toBeLessThan(0)
  })
  it('centres the cloud on the target, even when it is lopsided', () => {
    const pts: Vec3[] = [[0, 0, 0], [100, 0, 0], [100, 50, 0], [0, 50, 0], [90, 25, 0]]
    const f = frameCamera(pts, { fovDeg: FOV, aspect: 1.5, prefer: [0, 0, 1] })!
    expect(f.target[0]).toBeCloseTo(50, 0)
    expect(f.target[1]).toBeCloseTo(25, 0)
  })
  it('stays further away for a wider margin, a larger pad and a narrower window', () => {
    const pts = scatter(80, 100, 100, 100)
    const base = frameCamera(pts, { fovDeg: FOV, aspect: 1.5 })!.distance
    expect(frameCamera(pts, { fovDeg: FOV, aspect: 1.5, margin: 1.4 })!.distance).toBeGreaterThan(base)
    expect(frameCamera(pts, { fovDeg: FOV, aspect: 1.5, pad: 12 })!.distance).toBeGreaterThan(base)
    expect(frameCamera(pts, { fovDeg: FOV, aspect: 0.7 })!.distance).toBeGreaterThan(base)
  })
  it('honours a minimum distance for a lone node', () => {
    const f = frameCamera([[10, 10, 10]], { fovDeg: FOV, aspect: 1.5, minDistance: 60 })!
    expect(f.distance).toBe(60)
    f.target.forEach((v) => expect(v).toBeCloseTo(10, 6))
  })
})
