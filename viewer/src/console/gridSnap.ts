// Snapping graph nodes to a 3D lattice. The force simulation works in continuous space; what is
// drawn is each node's lattice cell, so every node sits on a grid point and no two share one.
//
// Pure and deterministic, so it is testable and the same graph always lands the same way.

export interface Cell { i: number; j: number; k: number }
export interface Point { id: string; x: number; y: number; z: number; /** higher gets its ideal cell first */ priority?: number }

const key = (i: number, j: number, k: number): string => `${i},${j},${k}`
export const cellCentre = (c: Cell, size: number): { x: number; y: number; z: number } => ({ x: c.i * size, y: c.j * size, z: c.k * size })

/**
 * Assign each point a distinct cell. Hubs (higher priority) get their nearest cell first; a point that
 * finds its cell taken takes the nearest free one, searched outward in shells. `prev` adds hysteresis:
 * a point stays in its previous cell until it has moved clearly out of it (0.62 of a cell rather than
 * 0.5), so a node on a boundary does not flicker between cells as the simulation settles.
 */
export function snapToGrid(points: ReadonlyArray<Point>, size: number, prev?: ReadonlyMap<string, Cell>): Map<string, Cell> {
  const out = new Map<string, Cell>()
  const taken = new Set<string>()
  const order = [...points].sort((a, b) => (b.priority ?? 0) - (a.priority ?? 0) || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0))
  for (const p of order) {
    const fx = p.x / size, fy = p.y / size, fz = p.z / size
    const before = prev?.get(p.id)
    if (before && Math.max(Math.abs(fx - before.i), Math.abs(fy - before.j), Math.abs(fz - before.k)) <= 0.62 && !taken.has(key(before.i, before.j, before.k))) {
      out.set(p.id, before)
      taken.add(key(before.i, before.j, before.k))
      continue
    }
    const ci = Math.round(fx), cj = Math.round(fy), ck = Math.round(fz)
    let chosen: Cell | null = null
    for (let r = 0; chosen === null; r++) {
      let best = Infinity
      for (let di = -r; di <= r; di++) for (let dj = -r; dj <= r; dj++) for (let dk = -r; dk <= r; dk++) {
        // only the shell at Chebyshev distance r; the inside was already searched
        if (Math.max(Math.abs(di), Math.abs(dj), Math.abs(dk)) !== r) continue
        const i = ci + di, j = cj + dj, k = ck + dk
        if (taken.has(key(i, j, k))) continue
        const d = (fx - i) ** 2 + (fy - j) ** 2 + (fz - k) ** 2
        if (d < best) { best = d; chosen = { i, j, k } }
      }
    }
    out.set(p.id, chosen)
    taken.add(key(chosen.i, chosen.j, chosen.k))
  }
  return out
}

/** Smallest box of cells holding every cell, or null for none. */
export function cellBounds(cells: Iterable<Cell>): { min: Cell; max: Cell } | null {
  let min: Cell | null = null
  let max: Cell | null = null
  for (const c of cells) {
    min = min ? { i: Math.min(min.i, c.i), j: Math.min(min.j, c.j), k: Math.min(min.k, c.k) } : { ...c }
    max = max ? { i: Math.max(max.i, c.i), j: Math.max(max.j, c.j), k: Math.max(max.k, c.k) } : { ...c }
  }
  return min && max ? { min, max } : null
}

/**
 * Line segments (x1 y1 z1 x2 y2 z2 ...) for the three back faces of the lattice around `bounds`, at
 * cell boundaries (half a cell out from the cell centres), padded by `pad` cells. The faces are the
 * floor (low y), the back wall (low z) and the side wall (low x), so the grid frames the cloud without
 * hiding it.
 */
export function gridLines(bounds: { min: Cell; max: Cell }, size: number, pad = 1): Float32Array {
  const lo = { i: bounds.min.i - pad, j: bounds.min.j - pad, k: bounds.min.k - pad }
  const hi = { i: bounds.max.i + pad, j: bounds.max.j + pad, k: bounds.max.k + pad }
  const edge = (n: number) => (n - 0.5) * size
  const out: number[] = []
  const seg = (a: number[], b: number[]) => out.push(a[0], a[1], a[2], b[0], b[1], b[2])
  const x0 = edge(lo.i), x1 = edge(hi.i + 1), y0 = edge(lo.j), y1 = edge(hi.j + 1), z0 = edge(lo.k), z1 = edge(hi.k + 1)
  // floor: y = y0
  for (let k = lo.k; k <= hi.k + 1; k++) seg([x0, y0, edge(k)], [x1, y0, edge(k)])
  for (let i = lo.i; i <= hi.i + 1; i++) seg([edge(i), y0, z0], [edge(i), y0, z1])
  // back wall: z = z0
  for (let j = lo.j; j <= hi.j + 1; j++) seg([x0, edge(j), z0], [x1, edge(j), z0])
  for (let i = lo.i; i <= hi.i + 1; i++) seg([edge(i), y0, z0], [edge(i), y1, z0])
  // side wall: x = x0
  for (let j = lo.j; j <= hi.j + 1; j++) seg([x0, edge(j), z0], [x0, edge(j), z1])
  for (let k = lo.k; k <= hi.k + 1; k++) seg([x0, y0, edge(k)], [x0, y1, edge(k)])
  return new Float32Array(out)
}

/** Largest number of lattice segments drawn through the volume before it falls back to the three faces. */
export const MAX_LATTICE_SEGMENTS = 9000

/**
 * The full 3D lattice: one line along x for every (y, z) cell boundary, one along y for every (x, z)
 * boundary and one along z for every (x, y) boundary, so the cell walls fill the whole volume around
 * `bounds` (padded by `pad` cells) and every cube sits inside a visible cell. It is a cubic lattice of
 * 3 (n+1)^2 segments for an n-cell cube, which stays small for the sample sizes the lens draws; a
 * lattice past MAX_LATTICE_SEGMENTS returns the three-face frame from `gridLines` instead.
 */
export function latticeLines(bounds: { min: Cell; max: Cell }, size: number, pad = 1): Float32Array {
  const lo = { i: bounds.min.i - pad, j: bounds.min.j - pad, k: bounds.min.k - pad }
  const hi = { i: bounds.max.i + pad, j: bounds.max.j + pad, k: bounds.max.k + pad }
  const ni = hi.i - lo.i + 2, nj = hi.j - lo.j + 2, nk = hi.k - lo.k + 2 // boundaries per axis
  if (nj * nk + ni * nk + ni * nj > MAX_LATTICE_SEGMENTS) return gridLines(bounds, size, pad)
  const edge = (n: number) => (n - 0.5) * size
  const x0 = edge(lo.i), x1 = edge(hi.i + 1), y0 = edge(lo.j), y1 = edge(hi.j + 1), z0 = edge(lo.k), z1 = edge(hi.k + 1)
  const out: number[] = []
  const seg = (ax: number, ay: number, az: number, bx: number, by: number, bz: number) => out.push(ax, ay, az, bx, by, bz)
  for (let j = lo.j; j <= hi.j + 1; j++) for (let k = lo.k; k <= hi.k + 1; k++) seg(x0, edge(j), edge(k), x1, edge(j), edge(k))
  for (let i = lo.i; i <= hi.i + 1; i++) for (let k = lo.k; k <= hi.k + 1; k++) seg(edge(i), y0, edge(k), edge(i), y1, edge(k))
  for (let i = lo.i; i <= hi.i + 1; i++) for (let j = lo.j; j <= hi.j + 1; j++) seg(edge(i), edge(j), z0, edge(i), edge(j), z1)
  return new Float32Array(out)
}

/** The twelve edges of the box that holds the lattice, drawn brighter so the volume reads as a volume. */
export function latticeFrame(bounds: { min: Cell; max: Cell }, size: number, pad = 1): Float32Array {
  const edge = (n: number) => (n - 0.5) * size
  const x0 = edge(bounds.min.i - pad), x1 = edge(bounds.max.i + pad + 1)
  const y0 = edge(bounds.min.j - pad), y1 = edge(bounds.max.j + pad + 1)
  const z0 = edge(bounds.min.k - pad), z1 = edge(bounds.max.k + pad + 1)
  const out: number[] = []
  for (const y of [y0, y1]) for (const z of [z0, z1]) out.push(x0, y, z, x1, y, z)
  for (const x of [x0, x1]) for (const z of [z0, z1]) out.push(x, y0, z, x, y1, z)
  for (const x of [x0, x1]) for (const y of [y0, y1]) out.push(x, y, z0, x, y, z1)
  return new Float32Array(out)
}

