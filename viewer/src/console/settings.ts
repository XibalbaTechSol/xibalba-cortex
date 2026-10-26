import { parseFloat2, type FloatPos } from './floating'

// Console preferences that belong to this browser (not to a Cortex profile): how the shell is laid
// out. Pure parse/serialize so a corrupt or hand-edited value can never break startup -- every field
// falls back to its own default independently.

export type ShellLayout = 'rail' | 'top'
export type GraphMode = '2d' | '3d'
/* One form per setting, rendered in each lens's own idiom: the 3D lens builds the solid, the 2D
   lens traces the same silhouette flat. Every one of them has to read when it is unlit and only
   a few pixels across, which is why there is no sphere -- under an unlit material a sphere is a
   flat disc, and its edge geometry is a mess of triangles rather than a readable outline. */
export type NodeShape = 'box' | 'diamond' | 'facet'
/** The backdrop the graph is drawn on: a spatial grid, the bounding frame alone, or neither. */
export type GraphCanvas = 'lattice' | 'frame' | 'plain'

export const NODE_SHAPES: readonly NodeShape[] = ['box', 'diamond', 'facet']
export const GRAPH_CANVASES: readonly GraphCanvas[] = ['lattice', 'frame', 'plain']

export interface ConsoleSettings {
  /** left rail (default) or the top bar with a tab row */
  shell: ShellLayout
  /** rail only: icons without labels */
  railCollapsed: boolean
  /** the Projection dock in the workspace, collapsed to its edge strip */
  facetsCollapsed: boolean
  /** the selected-memory dock, same */
  detailCollapsed: boolean
  /** the Graph lens as a 3D layout you can orbit (default), or a flat 2D force layout */
  graphMode: GraphMode
  /** graph nodes sit on the lattice (default) instead of wherever the force layout leaves them */
  graphSnap: boolean
  /** the solid a node is drawn as, in both lenses */
  nodeShape: NodeShape
  /** what the graph is drawn on behind the nodes */
  graphCanvas: GraphCanvas
  /** the chain rail, folded down to its handle on the workspace's bottom-right margin */
  chainCollapsed: boolean
  /** where the chain rail was dragged to, or null for its dock on the bottom edge */
  chainPos: FloatPos
}

export const DEFAULT_SETTINGS: ConsoleSettings = { shell: 'rail', railCollapsed: false, facetsCollapsed: false, detailCollapsed: false, graphMode: '3d', graphSnap: true, nodeShape: 'box', graphCanvas: 'lattice', chainCollapsed: false, chainPos: null }
export const SETTINGS_KEY = 'xibalba-cortex.console-settings'

export function parseSettings(raw: string | null | undefined): ConsoleSettings {
  if (!raw) return { ...DEFAULT_SETTINGS }
  let value: unknown
  try {
    value = JSON.parse(raw)
  } catch {
    return { ...DEFAULT_SETTINGS }
  }
  if (typeof value !== 'object' || value === null) return { ...DEFAULT_SETTINGS }
  const v = value as Record<string, unknown>
  return {
    shell: v.shell === 'rail' || v.shell === 'top' ? v.shell : DEFAULT_SETTINGS.shell,
    railCollapsed: typeof v.railCollapsed === 'boolean' ? v.railCollapsed : DEFAULT_SETTINGS.railCollapsed,
    facetsCollapsed: typeof v.facetsCollapsed === 'boolean' ? v.facetsCollapsed : DEFAULT_SETTINGS.facetsCollapsed,
    detailCollapsed: typeof v.detailCollapsed === 'boolean' ? v.detailCollapsed : DEFAULT_SETTINGS.detailCollapsed,
    graphMode: v.graphMode === '2d' || v.graphMode === '3d' ? v.graphMode : DEFAULT_SETTINGS.graphMode,
    graphSnap: typeof v.graphSnap === 'boolean' ? v.graphSnap : DEFAULT_SETTINGS.graphSnap,
    nodeShape: NODE_SHAPES.includes(v.nodeShape as NodeShape) ? (v.nodeShape as NodeShape) : DEFAULT_SETTINGS.nodeShape,
    graphCanvas: GRAPH_CANVASES.includes(v.graphCanvas as GraphCanvas) ? (v.graphCanvas as GraphCanvas) : DEFAULT_SETTINGS.graphCanvas,
    chainCollapsed: typeof v.chainCollapsed === 'boolean' ? v.chainCollapsed : DEFAULT_SETTINGS.chainCollapsed,
    chainPos: parseFloat2(v.chainPos),
  }
}

export const serializeSettings = (settings: ConsoleSettings): string => JSON.stringify(settings)
