// Where a dragged window ends up, kept out of the component so the rule is testable rather than
// something you can only discover by dragging.
//
// A floating window has two states, not a free position plus a separate "docked" flag: it is
// either at its dock or at a point. Dropping it near the dock returns it there, which is what
// makes the dock reachable again without a separate control -- otherwise a window dragged away
// could only be restored by clearing storage.

/** A dropped window's resting place: `null` means "at its dock". */
export type FloatPos = { x: number; y: number } | null

/** How close to the dock edge a drop has to land to snap back, in px. */
export const SNAP_PX = 56

export interface DropInput {
  /** pointer offset applied to the window's top-left, in workspace coordinates */
  x: number
  y: number
  /** the workspace the window is confined to */
  width: number
  height: number
  /** the dragged window's own size */
  winWidth: number
  winHeight: number
}

/**
 * Clamp a drop into the workspace and decide whether it returns to the dock.
 *
 * Clamping matters as much as snapping: a window dropped past an edge would otherwise be
 * unreachable, and since the position persists, unreachable forever.
 */
export function resolveDrop(d: DropInput): FloatPos {
  const maxX = Math.max(0, d.width - d.winWidth)
  const maxY = Math.max(0, d.height - d.winHeight)
  const x = Math.min(Math.max(0, d.x), maxX)
  const y = Math.min(Math.max(0, d.y), maxY)
  // the dock is the bottom edge; a drop that lands within SNAP_PX of it goes back there
  if (maxY - y <= SNAP_PX) return null
  return { x, y }
}

/** Parse a stored position, rejecting anything that is not a finite pair. */
export function parseFloat2(value: unknown): FloatPos {
  if (typeof value !== 'object' || value === null) return null
  const v = value as { x?: unknown; y?: unknown }
  if (typeof v.x !== 'number' || typeof v.y !== 'number') return null
  if (!Number.isFinite(v.x) || !Number.isFinite(v.y)) return null
  return { x: v.x, y: v.y }
}
