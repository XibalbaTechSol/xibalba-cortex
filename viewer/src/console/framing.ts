// Where to put the 3D camera so a cloud of nodes is framed well, as pure maths (no three.js) so it can
// be tested without a GPU.
//
// "Framed well" means three things:
//   1. The camera looks along the cloud's THINNEST direction, so the most spread-out face of the cloud
//      is the one you see, instead of a face-on edge. The thinnest direction is the eigenvector of the
//      smallest eigenvalue of the points' covariance matrix (principal component analysis;
//      https://en.wikipedia.org/wiki/Principal_component_analysis). The covariance is a symmetric 3x3
//      matrix, so the cyclic Jacobi eigenvalue method converges in a few sweeps
//      (https://en.wikipedia.org/wiki/Jacobi_eigenvalue_algorithm).
//   2. A little of the preferred (oblique) direction is blended back in, so a flat cloud still reads as
//      3D rather than as a flat slide.
//   3. The distance is solved for the real perspective frustum, not a bounding sphere: for each point,
//      the camera must be far enough that its horizontal and vertical offsets from the view axis fit
//      inside the half-angles of the field of view at that point's depth.

export type Vec3 = readonly [number, number, number]

const dot = (a: Vec3, b: Vec3): number => a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
const cross = (a: Vec3, b: Vec3): Vec3 => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
const len = (a: Vec3): number => Math.hypot(a[0], a[1], a[2])
const scale = (a: Vec3, k: number): Vec3 => [a[0] * k, a[1] * k, a[2] * k]
const add = (a: Vec3, b: Vec3): Vec3 => [a[0] + b[0], a[1] + b[1], a[2] + b[2]]
const unit = (a: Vec3, fallback: Vec3): Vec3 => {
  const l = len(a)
  return l < 1e-9 ? fallback : scale(a, 1 / l)
}

export interface Axes {
  /** unit eigenvectors, smallest variance first */
  vectors: [Vec3, Vec3, Vec3]
  /** the variance along each, smallest first */
  variances: [number, number, number]
}

/** Principal axes of a point cloud, by cyclic Jacobi rotations on the 3x3 covariance matrix. */
export function principalAxes(points: readonly Vec3[]): Axes {
  const n = points.length
  const mean: Vec3 = n === 0 ? [0, 0, 0] : [
    points.reduce((s, p) => s + p[0], 0) / n,
    points.reduce((s, p) => s + p[1], 0) / n,
    points.reduce((s, p) => s + p[2], 0) / n,
  ]
  // covariance, symmetric
  const a = [[0, 0, 0], [0, 0, 0], [0, 0, 0]]
  for (const p of points) {
    const d = [p[0] - mean[0], p[1] - mean[1], p[2] - mean[2]]
    for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) a[i][j] += (d[i] * d[j]) / Math.max(1, n)
  }
  // v accumulates the rotations: its columns converge to the eigenvectors
  const v = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
  for (let sweep = 0; sweep < 24; sweep++) {
    const off = Math.abs(a[0][1]) + Math.abs(a[0][2]) + Math.abs(a[1][2])
    if (off < 1e-12) break
    for (const [p, q] of [[0, 1], [0, 2], [1, 2]] as const) {
      if (Math.abs(a[p][q]) < 1e-18) continue
      const theta = (a[q][q] - a[p][p]) / (2 * a[p][q])
      const t = Math.sign(theta || 1) / (Math.abs(theta) + Math.sqrt(theta * theta + 1))
      const c = 1 / Math.sqrt(t * t + 1)
      const s = t * c
      // rotate rows/columns p and q of a, and the eigenvector matrix
      for (let k = 0; k < 3; k++) {
        const akp = a[k][p], akq = a[k][q]
        a[k][p] = c * akp - s * akq
        a[k][q] = s * akp + c * akq
      }
      for (let k = 0; k < 3; k++) {
        const apk = a[p][k], aqk = a[q][k]
        a[p][k] = c * apk - s * aqk
        a[q][k] = s * apk + c * aqk
      }
      for (let k = 0; k < 3; k++) {
        const vkp = v[k][p], vkq = v[k][q]
        v[k][p] = c * vkp - s * vkq
        v[k][q] = s * vkp + c * vkq
      }
    }
  }
  const order = [0, 1, 2].sort((i, j) => a[i][i] - a[j][j])
  const col = (j: number): Vec3 => [v[0][j], v[1][j], v[2][j]]
  return {
    vectors: [col(order[0]), col(order[1]), col(order[2])],
    variances: [Math.max(0, a[order[0]][order[0]]), Math.max(0, a[order[1]][order[1]]), Math.max(0, a[order[2]][order[2]])],
  }
}

export interface FrameOptions {
  fovDeg: number
  aspect: number
  /** > 1 leaves breathing room; 1.08 is 8% */
  margin?: number
  /** world units added around every point, so a cube's own size is inside the frame */
  pad?: number
  /** the oblique direction to fall back to and to blend in (camera minus target) */
  prefer?: Vec3
  /** never come closer than this */
  minDistance?: number
}

export interface Frame {
  target: Vec3
  /** unit vector from the target toward the camera */
  direction: Vec3
  distance: number
}

const DEFAULT_PREFER: Vec3 = [0.45, 0.35, 1]
/** how much of the preferred oblique direction is blended into the thin-axis view */
const OBLIQUE = 0.4
/** below this thin/mid variance ratio the cloud is flat enough to look along its thin axis */
const FLAT = 0.55

/** Camera placement that frames every point. */
export function frameCamera(points: readonly Vec3[], opts: FrameOptions): Frame | null {
  if (points.length === 0) return null
  const margin = opts.margin ?? 1.08
  const pad = opts.pad ?? 0
  const prefer = unit(opts.prefer ?? DEFAULT_PREFER, unit(DEFAULT_PREFER, [0, 0, 1]))

  // 1. view direction
  let direction = prefer
  if (points.length >= 3) {
    const { vectors, variances } = principalAxes(points)
    const flat = variances[1] > 1e-9 && variances[0] / variances[1] < FLAT
    if (flat) {
      // the sign that agrees with the preferred side, so the view never flips under the person
      const thin = dot(vectors[0], prefer) < 0 ? scale(vectors[0], -1) : vectors[0]
      direction = unit(add(thin, scale(prefer, OBLIQUE)), prefer)
    }
  }

  // 2. camera basis: y is up unless the view is straight down it
  const worldUp: Vec3 = Math.abs(direction[1]) > 0.98 ? [0, 0, 1] : [0, 1, 0]
  const right = unit(cross(worldUp, direction), [1, 0, 0])
  const up = unit(cross(direction, right), [0, 1, 0])

  // 3. centre of the projected extents, not the centroid, so lopsided clouds sit in the middle
  const extent = (axis: Vec3): [number, number] => {
    let lo = Infinity, hi = -Infinity
    for (const p of points) { const d = dot(p, axis); if (d < lo) lo = d; if (d > hi) hi = d }
    return [lo, hi]
  }
  const [x0, x1] = extent(right), [y0, y1] = extent(up), [z0, z1] = extent(direction)
  const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2, cz = (z0 + z1) / 2
  const target = add(add(scale(right, cx), scale(up, cy)), scale(direction, cz))

  // 4. the nearest the camera can be and still hold every point inside the frustum
  const tanV = Math.tan((opts.fovDeg * Math.PI) / 360)
  const tanH = tanV * opts.aspect
  let distance = opts.minDistance ?? 0
  for (const p of points) {
    const x = dot(p, right) - cx, y = dot(p, up) - cy, z = dot(p, direction) - cz // z > 0 is toward the camera
    const need = Math.max(((Math.abs(x) + pad) * margin) / tanH, ((Math.abs(y) + pad) * margin) / tanV) + z
    if (need > distance) distance = need
  }
  return { target, direction, distance }
}
