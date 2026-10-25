import { EVIDENCE_FACES, type NodeEvidence } from './model'

// Pure sizing and colour rules shared by the 2D and 3D graph lenses, so the two read as one design
// and so the rules that make a graph legible are tested rather than eyeballed.
//
// The reason these exist: react-force-graph takes node sizes and line widths in GRAPH units, which a
// fit-to-screen zoom (often 0.3 to 0.6 for a few hundred nodes) shrinks to a few pixels and sub-pixel
// hairlines. Sizes here are therefore expressed as a floor in SCREEN pixels.

/** Grid stays subordinate to node faces and relationship edges in both renderers. */
export const GRID_INK = { lattice: 0.018, frame: 0.075, flat: 0.02 } as const

export const MIN_NODE_PX = 3.5
export const MIN_LINK_PX = 1

/** How much of its colour a faded (not in the selection's neighbourhood) element keeps. */
export const FADE = { node: 0.34, link: 0.16 } as const

/** Stroke alpha by edge group. Structure edges are the most numerous, so the faintest, but visible. */
export const LINK_ALPHA = { structure: 0.28, relation: 0.85, similarity: 0.8, contradiction: 1 } as const
export type LinkGroup = keyof typeof LINK_ALPHA

const safeScale = (scale: number): number => Math.max(scale, 0.05)

/** Half-extent of a node in graph units: grows a little with degree, never below MIN_NODE_PX on screen. */
export function nodeHalf(base: number, degree: number, scale: number): number {
  const grown = base * (1 + Math.min(Math.max(degree, 0), 12) * 0.05)
  return Math.max(grown, MIN_NODE_PX / safeScale(scale))
}

/** Line width in graph units that renders at least MIN_LINK_PX wide at this zoom. */
export function linkWidth(basePx: number, scale: number): number {
  return Math.max(basePx, MIN_LINK_PX) / safeScale(scale)
}

/**
 * Blend `colour` (0xRRGGBB) over `ground` at `alpha`. WebGL line materials have no per-vertex alpha,
 * and the ground is a flat colour, so blending ahead of time gives the same pixels.
 */
export function blendOver(colour: number, ground: number, alpha: number): number {
  const a = Math.min(1, Math.max(0, alpha))
  const channel = (shift: number) => {
    const c = (colour >> shift) & 255
    const g = (ground >> shift) & 255
    return Math.round(g + (c - g) * a)
  }
  return (channel(16) << 16) | (channel(8) << 8) | channel(0)
}

/** Distance at which a sphere of `radius` fits the view, for a perspective camera. */
export function fitDistance(radius: number, fovDeg: number, aspect: number, margin = 1.2): number {
  const vertical = (fovDeg * Math.PI) / 180
  // the narrower of the two half-angles is the one that limits the fit
  const horizontal = 2 * Math.atan(Math.tan(vertical / 2) * Math.max(aspect, 0.1))
  const half = Math.min(vertical, horizontal) / 2
  return (Math.max(radius, 1) * margin) / Math.sin(half)
}

/** Centre and radius of the smallest axis-aligned-centred sphere around a point cloud. */
export function boundingSphere(points: ReadonlyArray<{ x: number; y: number; z: number }>): { cx: number; cy: number; cz: number; radius: number } {
  if (points.length === 0) return { cx: 0, cy: 0, cz: 0, radius: 0 }
  let minX = Infinity, minY = Infinity, minZ = Infinity, maxX = -Infinity, maxY = -Infinity, maxZ = -Infinity
  for (const p of points) {
    minX = Math.min(minX, p.x); maxX = Math.max(maxX, p.x)
    minY = Math.min(minY, p.y); maxY = Math.max(maxY, p.y)
    minZ = Math.min(minZ, p.z); maxZ = Math.max(maxZ, p.z)
  }
  const cx = (minX + maxX) / 2, cy = (minY + maxY) / 2, cz = (minZ + maxZ) / 2
  let radius = 0
  for (const p of points) radius = Math.max(radius, Math.hypot(p.x - cx, p.y - cy, p.z - cz))
  return { cx, cy, cz, radius }
}

/**
 * The silhouette of a node shape as unit offsets from its centre, each in [-1, 1], to be scaled by
 * the node's half-extent. The 2D lens traces these directly; the 3D lens builds the matching solid.
 *
 * Shared so the two lenses cannot drift into drawing different things for the same setting, and so
 * the half-extent contract is testable: every point stays inside the box the layout reserves for a
 * node, which is what keeps nodes off each other when they are snapped to the lattice.
 */
export const NODE_OUTLINE: Record<'box' | 'diamond' | 'facet', ReadonlyArray<readonly [number, number]>> = {
  box: [[-1, -1], [1, -1], [1, 1], [-1, 1]],
  diamond: [[0, -1], [1, 0], [0, 1], [-1, 0]],
  // a hexagon, flat-topped, as the plan view of the 3D lens's icosahedron
  facet: [[-0.5, -1], [0.5, -1], [1, 0], [0.5, 1], [-0.5, 1], [-1, 0]],
}

/** Trace a node's outline on a 2D context, centred on (x, y) with half-extent `h`. */
export function traceNode(
  ctx: { moveTo: (x: number, y: number) => void; lineTo: (x: number, y: number) => void; closePath: () => void },
  shape: keyof typeof NODE_OUTLINE,
  x: number,
  y: number,
  h: number,
): void {
  const pts = NODE_OUTLINE[shape] ?? NODE_OUTLINE.box
  pts.forEach(([dx, dy], i) => {
    const px = x + dx * h, py = y + dy * h
    if (i === 0) ctx.moveTo(px, py)
    else ctx.lineTo(px, py)
  })
  ctx.closePath()
}


/** Cube materials follow BoxGeometry's +X, -X, +Y, -Y, +Z, -Z groups. */
export function faceColours(base: number, ground: number, evidence: NodeEvidence, conflict: number): number[] {
  const dim = blendOver(base, ground, 0.30)
  return EVIDENCE_FACES.map((face) => evidence[face] ? face === 'contradiction' ? conflict : base : dim)
}
