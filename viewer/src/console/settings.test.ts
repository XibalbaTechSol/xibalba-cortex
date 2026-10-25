import { describe, expect, it } from 'vitest'
import { DEFAULT_SETTINGS, parseSettings, serializeSettings } from './settings'

describe('parseSettings', () => {
  it('defaults to the left rail, expanded', () => {
    expect(parseSettings(null)).toEqual({ shell: 'rail', railCollapsed: false, facetsCollapsed: false, detailCollapsed: false, graphMode: '3d', graphSnap: true, nodeShape: 'box', graphCanvas: 'lattice', chainCollapsed: false })
    expect(DEFAULT_SETTINGS.shell).toBe('rail')
    expect(DEFAULT_SETTINGS.graphMode).toBe('3d')
  })
  it('round-trips a valid value', () => {
    const s = { shell: 'top', railCollapsed: true, facetsCollapsed: true, detailCollapsed: true, graphMode: '2d', graphSnap: false, nodeShape: 'facet', graphCanvas: 'plain', chainCollapsed: true } as const
    expect(parseSettings(serializeSettings(s))).toEqual(s)
  })
  it('survives garbage, wrong types and unknown values, field by field', () => {
    expect(parseSettings('{not json')).toEqual(DEFAULT_SETTINGS)
    expect(parseSettings('42')).toEqual(DEFAULT_SETTINGS)
    expect(parseSettings('null')).toEqual(DEFAULT_SETTINGS)
    expect(parseSettings(JSON.stringify({ shell: 'sidebar', railCollapsed: 'yes' }))).toEqual(DEFAULT_SETTINGS)
    expect(parseSettings(JSON.stringify({ graphMode: '4d' }))).toEqual(DEFAULT_SETTINGS)
    expect(parseSettings(JSON.stringify({ shell: 'top', railCollapsed: 'yes' }))).toEqual({ shell: 'top', railCollapsed: false, facetsCollapsed: false, detailCollapsed: false, graphMode: '3d', graphSnap: true, nodeShape: 'box', graphCanvas: 'lattice', chainCollapsed: false })
  })

  it('snaps to the grid by default, and ignores a snap value that is not a boolean', () => {
    expect(DEFAULT_SETTINGS.graphSnap).toBe(true)
    expect(parseSettings(JSON.stringify({ graphSnap: 'no' })).graphSnap).toBe(true)
    expect(parseSettings(JSON.stringify({ graphSnap: false })).graphSnap).toBe(false)
  })

  it('falls back on an unknown node shape or canvas rather than rendering nothing', () => {
    expect(DEFAULT_SETTINGS.nodeShape).toBe('box')
    expect(DEFAULT_SETTINGS.graphCanvas).toBe('lattice')
    expect(parseSettings(JSON.stringify({ nodeShape: 'sphere' })).nodeShape).toBe('box')
    expect(parseSettings(JSON.stringify({ graphCanvas: 'hex' })).graphCanvas).toBe('lattice')
    expect(parseSettings(JSON.stringify({ nodeShape: 'diamond' })).nodeShape).toBe('diamond')
    expect(parseSettings(JSON.stringify({ graphCanvas: 'frame' })).graphCanvas).toBe('frame')
  })
})
