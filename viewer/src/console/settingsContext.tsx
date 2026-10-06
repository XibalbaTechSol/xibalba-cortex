import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import { DEFAULT_SETTINGS, SETTINGS_KEY, parseSettings, serializeSettings, type ConsoleSettings } from './settings'

interface SettingsValue {
  settings: ConsoleSettings
  update: (patch: Partial<ConsoleSettings>) => void
  reset: () => void
}

const SettingsContext = createContext<SettingsValue | null>(null)

function read(): ConsoleSettings {
  try {
    return parseSettings(window.localStorage.getItem(SETTINGS_KEY))
  } catch {
    return { ...DEFAULT_SETTINGS } // storage blocked (private window): the defaults work without it
  }
}

function write(settings: ConsoleSettings): void {
  try {
    window.localStorage.setItem(SETTINGS_KEY, serializeSettings(settings))
  } catch { /* a preference is a convenience; losing it is not an error */ }
}

export function SettingsProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<ConsoleSettings>(read)
  const update = useCallback((patch: Partial<ConsoleSettings>) => {
    setSettings((prev) => {
      const next = { ...prev, ...patch }
      write(next)
      return next
    })
  }, [])
  const reset = useCallback(() => {
    write(DEFAULT_SETTINGS)
    setSettings({ ...DEFAULT_SETTINGS })
  }, [])
  const value = useMemo(() => ({ settings, update, reset }), [settings, update, reset])
  return <SettingsContext.Provider value={value}>{children}</SettingsContext.Provider>
}

export function useSettings(): SettingsValue {
  const value = useContext(SettingsContext)
  if (!value) throw new Error('useSettings must be used inside <SettingsProvider>')
  return value
}
