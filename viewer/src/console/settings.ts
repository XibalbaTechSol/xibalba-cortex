// Console preferences that belong to this browser (not to a Cortex profile): how the shell is laid
// out. Pure parse/serialize so a corrupt or hand-edited value can never break startup -- every field
// falls back to its own default independently.

export type ShellLayout = 'rail' | 'top'

export interface ConsoleSettings {
  /** left rail (default) or the top bar with a tab row */
  shell: ShellLayout
  /** rail only: icons without labels */
  railCollapsed: boolean
}

export const DEFAULT_SETTINGS: ConsoleSettings = { shell: 'rail', railCollapsed: false }
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
  }
}

export const serializeSettings = (settings: ConsoleSettings): string => JSON.stringify(settings)
