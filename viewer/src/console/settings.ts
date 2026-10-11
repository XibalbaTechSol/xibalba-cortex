// Console preferences that belong to this browser (not to a Cortex profile): how the shell is laid
// out. Pure parse/serialize so a corrupt or hand-edited value can never break startup -- every field
// falls back to its own default independently.

export type ShellLayout = 'rail' | 'top'
export type GraphMode = '2d' | '3d'

export interface ConsoleSettings {
  /** left rail (default) or the top bar with a tab row */
  shell: ShellLayout
  /** navigation (the rail, or the top bar's second row) shows icons without labels */
  railCollapsed: boolean
  /** the Filters pane is hidden, so the lens takes its width */
  facetsCollapsed: boolean
  /** the Inspector pane is hidden, so the lens takes its width */
  inspectorCollapsed: boolean
  /** the Graph lens as a 3D layout you can orbit (default), or a flat 2D force layout */
  graphMode: GraphMode
  /** graph nodes sit on the lattice (default) instead of wherever the force layout leaves them */
  graphSnap: boolean
}

export const DEFAULT_SETTINGS: ConsoleSettings = { shell: 'rail', railCollapsed: false, facetsCollapsed: false, inspectorCollapsed: false, graphMode: '3d', graphSnap: true }
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
    inspectorCollapsed: typeof v.inspectorCollapsed === 'boolean' ? v.inspectorCollapsed : DEFAULT_SETTINGS.inspectorCollapsed,
    graphMode: v.graphMode === '2d' || v.graphMode === '3d' ? v.graphMode : DEFAULT_SETTINGS.graphMode,
    graphSnap: typeof v.graphSnap === 'boolean' ? v.graphSnap : DEFAULT_SETTINGS.graphSnap,
  }
}

export const serializeSettings = (settings: ConsoleSettings): string => JSON.stringify(settings)
