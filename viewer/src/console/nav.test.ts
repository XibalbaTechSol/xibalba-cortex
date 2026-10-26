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
  it('round-trips every page and lens', () => {
    for (const hash of ['', '#timeline', '#memories', '#entities', '#sessions', '#operations', '#agents', '#settings']) {
      expect(routeHash(parseRoute(hash, all))).toBe(hash)
    }
  })

  /* A page opened from the timeline has to say so in the hash. state.tsx's setPage keeps
   * `{ lens: route.lens, page: next }` precisely so Escape can return to the lens the page was
   * opened from -- but that intent is only real if the pair survives a trip through the URL. */
  it('keeps the lens a page was opened from', () => {
    expect(parseRoute('#timeline/memories', all)).toEqual({ lens: 'timeline', page: 'memories' })
    expect(parseRoute('#timeline/sessions', all)).toEqual({ lens: 'timeline', page: 'sessions' })
    expect(routeHash({ lens: 'timeline', page: 'memories' })).toBe('#timeline/memories')
  })

  it('leaves a graph-opened page unprefixed, so existing links keep working', () => {
    expect(routeHash({ lens: 'graph', page: 'memories' })).toBe('#memories')
    expect(parseRoute('#graph/memories', all)).toEqual({ lens: 'graph', page: 'memories' })
  })

  it('round-trips a page under each lens', () => {
    for (const hash of ['#timeline/memories', '#timeline/entities', '#timeline/sessions',
      '#timeline/operations', '#timeline/agents', '#timeline/settings']) {
      expect(routeHash(parseRoute(hash, all))).toBe(hash)
    }
  })

  it('still falls back when the page under a lens is unknown or unbuilt', () => {
    expect(parseRoute('#timeline/nonsense', all)).toEqual({ lens: 'timeline', page: null })
    expect(parseRoute('#timeline/memories', new Set<DestinationId>(['graph', 'timeline'])))
      .toEqual({ lens: 'timeline', page: null })
    expect(parseRoute('#timeline/settings?tab=account', all)).toEqual({ lens: 'timeline', page: 'settings' })
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
