import { describe, expect, it } from 'vitest'
import { DEFAULT_SETTINGS, parseSettings, serializeSettings } from './settings'

describe('parseSettings', () => {
  it('defaults to the left rail, expanded', () => {
    expect(parseSettings(null)).toEqual({ shell: 'rail', railCollapsed: false, facetsCollapsed: false, inspectorCollapsed: false, graphMode: '3d', graphSnap: true })
    expect(DEFAULT_SETTINGS.shell).toBe('rail')
    expect(DEFAULT_SETTINGS.graphMode).toBe('3d')
  })
  it('round-trips a valid value', () => {
    const s = { shell: 'top', railCollapsed: true, facetsCollapsed: true, inspectorCollapsed: true, graphMode: '2d', graphSnap: false } as const
    expect(parseSettings(serializeSettings(s))).toEqual(s)
  })
  it('survives garbage, wrong types and unknown values, field by field', () => {
    expect(parseSettings('{not json')).toEqual(DEFAULT_SETTINGS)
    expect(parseSettings('42')).toEqual(DEFAULT_SETTINGS)
    expect(parseSettings('null')).toEqual(DEFAULT_SETTINGS)
    expect(parseSettings(JSON.stringify({ shell: 'sidebar', railCollapsed: 'yes' }))).toEqual(DEFAULT_SETTINGS)
    expect(parseSettings(JSON.stringify({ graphMode: '4d' }))).toEqual(DEFAULT_SETTINGS)
    expect(parseSettings(JSON.stringify({ shell: 'top', railCollapsed: 'yes' }))).toEqual({ shell: 'top', railCollapsed: false, facetsCollapsed: false, inspectorCollapsed: false, graphMode: '3d', graphSnap: true })
  })

  it('snaps to the grid by default, and ignores a snap value that is not a boolean', () => {
    expect(DEFAULT_SETTINGS.graphSnap).toBe(true)
    expect(parseSettings(JSON.stringify({ graphSnap: 'no' })).graphSnap).toBe(true)
    expect(parseSettings(JSON.stringify({ graphSnap: false })).graphSnap).toBe(false)
  })
  it('keeps each pane collapse independently, and shows every pane by default', () => {
    expect(DEFAULT_SETTINGS.facetsCollapsed).toBe(false)
    expect(DEFAULT_SETTINGS.inspectorCollapsed).toBe(false)
    const v = parseSettings(JSON.stringify({ facetsCollapsed: true, inspectorCollapsed: 'no' }))
    expect(v.facetsCollapsed).toBe(true)
    expect(v.inspectorCollapsed).toBe(false)
  })
})
