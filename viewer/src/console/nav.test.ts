import { describe, expect, it } from 'vitest'
import { ALL_DESTINATIONS, BUILT, DESTINATIONS, NAV_GROUPS, destinationsIn, parseRoute, routeHash, type DestinationId } from './nav'

const all = new Set<DestinationId>(ALL_DESTINATIONS.map((d) => d.id))

describe('parseRoute / routeHash', () => {
  it('maps the lens hashes and the default', () => {
    expect(parseRoute('')).toEqual({ lens: 'graph', page: null })
    expect(parseRoute('#timeline')).toEqual({ lens: 'timeline', page: null })
  })
  it('maps a built page and accepts a leading slash or a query', () => {
    expect(parseRoute('#settings')).toEqual({ lens: 'graph', page: 'settings' })
    expect(parseRoute('#/settings')).toEqual({ lens: 'graph', page: 'settings' })
    expect(parseRoute('#settings?tab=account')).toEqual({ lens: 'graph', page: 'settings' })
  })
  it('falls back to the graph for an unknown token or a page that is not built', () => {
    expect(parseRoute('#nonsense')).toEqual({ lens: 'graph', page: null })
    expect(parseRoute('#memories', new Set<DestinationId>(['graph']))).toEqual({ lens: 'graph', page: null })
    expect(parseRoute('#memories', all)).toEqual({ lens: 'graph', page: 'memories' })
  })
  it('keeps the lens a drawer is open over, so closing it returns there', () => {
    expect(parseRoute('#timeline/sessions', all)).toEqual({ lens: 'timeline', page: 'sessions' })
    expect(routeHash({ lens: 'timeline', page: 'settings' })).toBe('#timeline/settings')
    expect(parseRoute('#timeline/nonsense', all)).toEqual({ lens: 'timeline', page: null })
    expect(parseRoute('#timeline/memories', new Set<DestinationId>(['graph', 'timeline']))).toEqual({ lens: 'timeline', page: null })
  })
  it('round-trips every page and lens', () => {
    for (const hash of ['', '#timeline', '#memories', '#entities', '#sessions', '#operations', '#agents', '#settings', '#timeline/memories', '#timeline/agents']) {
      expect(routeHash(parseRoute(hash, all))).toBe(hash)
    }
  })
})

describe('the destination registry', () => {
  it('lists only built destinations, so no entry is a dead control', () => {
    expect(DESTINATIONS.every((d) => BUILT.has(d.id))).toBe(true)
  })
  it('has unique ids and every group non-empty when everything is built', () => {
    expect(new Set(ALL_DESTINATIONS.map((d) => d.id)).size).toBe(ALL_DESTINATIONS.length)
    for (const g of NAV_GROUPS) expect(destinationsIn(g, ALL_DESTINATIONS).length).toBeGreaterThan(0)
  })
})

describe('information architecture', () => {
  it('has exactly two lenses, and every other destination is a tool that opens over one', () => {
    expect(destinationsIn('lens', ALL_DESTINATIONS).map((d) => d.id)).toEqual(['graph', 'timeline'])
    for (const d of ALL_DESTINATIONS) if (d.group === 'tools') expect(d.kind === 'page' || d.kind === 'overlay').toBe(true)
  })
})
