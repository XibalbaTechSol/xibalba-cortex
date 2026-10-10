import { describe, expect, it } from 'vitest'
import { DEFAULT_SETTINGS, parseSettings, serializeSettings } from './settings'

describe('parseSettings', () => {
  it('defaults to the left rail, expanded', () => {
    expect(parseSettings(null)).toEqual({ shell: 'rail', railCollapsed: false, graphMode: '3d' })
    expect(DEFAULT_SETTINGS.shell).toBe('rail')
    expect(DEFAULT_SETTINGS.graphMode).toBe('3d')
  })
  it('round-trips a valid value', () => {
    const s = { shell: 'top', railCollapsed: true, graphMode: '2d' } as const
    expect(parseSettings(serializeSettings(s))).toEqual(s)
  })
  it('survives garbage, wrong types and unknown values, field by field', () => {
    expect(parseSettings('{not json')).toEqual(DEFAULT_SETTINGS)
    expect(parseSettings('42')).toEqual(DEFAULT_SETTINGS)
    expect(parseSettings('null')).toEqual(DEFAULT_SETTINGS)
    expect(parseSettings(JSON.stringify({ shell: 'sidebar', railCollapsed: 'yes' }))).toEqual(DEFAULT_SETTINGS)
    expect(parseSettings(JSON.stringify({ graphMode: '4d' }))).toEqual(DEFAULT_SETTINGS)
    expect(parseSettings(JSON.stringify({ shell: 'top', railCollapsed: 'yes' }))).toEqual({ shell: 'top', railCollapsed: false, graphMode: '3d' })
  })
})
