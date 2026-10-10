// The console's destinations, in one place, and the hash routes that reach them.
//
// Three layouts render this same list (left rail, top bar, phone tab bar + "More" sheet), so a
// destination added here appears in all three and cannot drift between them. A destination is only
// listed once its surface exists: BUILT is the gate, so there is no nav entry that does nothing.

export type Lens = 'graph' | 'timeline'
export type PageId = 'memories' | 'entities' | 'sessions' | 'operations' | 'agents' | 'settings'
export type OverlayId = 'recall' | 'review' | 'integrity'

export type DestinationId = Lens | PageId | OverlayId
export type DestinationKind = 'lens' | 'page' | 'overlay'
export type NavGroup = 'lens' | 'explore' | 'workflows' | 'system'

export interface Destination {
  id: DestinationId
  kind: DestinationKind
  label: string
  group: NavGroup
  /** short hint shown as the tooltip and the collapsed rail's accessible name */
  hint: string
}

export const GROUP_LABEL: Record<NavGroup, string> = {
  lens: 'Lens',
  explore: 'Explore',
  workflows: 'Workflows',
  system: 'System',
}

export const ALL_DESTINATIONS: readonly Destination[] = [
  { id: 'graph', kind: 'lens', label: 'Graph', group: 'lens', hint: 'Knowledge graph' },
  { id: 'timeline', kind: 'lens', label: 'Timeline', group: 'lens', hint: 'Sessions on a time axis' },
  { id: 'memories', kind: 'page', label: 'Memories', group: 'explore', hint: 'Browse, filter and add memories' },
  { id: 'entities', kind: 'page', label: 'Entities', group: 'explore', hint: 'Entity neighbours and paths' },
  { id: 'sessions', kind: 'page', label: 'Sessions', group: 'explore', hint: 'Sessions, exchanges, replay and traces' },
  { id: 'recall', kind: 'overlay', label: 'Recall', group: 'workflows', hint: 'Ask the memory a question' },
  { id: 'review', kind: 'overlay', label: 'Review', group: 'workflows', hint: 'Proposals, PARA and tasks' },
  { id: 'integrity', kind: 'overlay', label: 'Integrity', group: 'workflows', hint: 'Verify chains and checkpoints' },
  { id: 'operations', kind: 'page', label: 'Operations', group: 'system', hint: 'Health, workers and queues' },
  { id: 'agents', kind: 'page', label: 'Agents', group: 'system', hint: 'Agents, devices and pairing' },
  { id: 'settings', kind: 'page', label: 'Settings', group: 'system', hint: 'Layout, inference, account' },
]

/** Pages whose surface exists. A page is added here in the same change that builds it. */
export const BUILT: ReadonlySet<DestinationId> = new Set<DestinationId>([
  'graph', 'timeline', 'recall', 'review', 'integrity',
  'memories', 'entities', 'sessions', 'operations', 'agents', 'settings',
])

export const DESTINATIONS: readonly Destination[] = ALL_DESTINATIONS.filter((d) => BUILT.has(d.id))

export function destinationsIn(group: NavGroup, list: readonly Destination[] = DESTINATIONS): Destination[] {
  return list.filter((d) => d.group === group)
}

export const NAV_GROUPS: readonly NavGroup[] = ['lens', 'explore', 'workflows', 'system']

// --- hash routes --------------------------------------------------------------------------------------

export interface Route {
  lens: Lens
  /** null = the workspace (a lens); otherwise a full-page surface */
  page: PageId | null
}

const PAGE_IDS: readonly PageId[] = ['memories', 'entities', 'sessions', 'operations', 'agents', 'settings']

/** `#timeline` -> timeline lens; `#settings` -> settings page; anything else -> the graph lens. An
 *  unbuilt page falls back to the graph rather than rendering nothing. */
export function parseRoute(hash: string, built: ReadonlySet<DestinationId> = BUILT): Route {
  const token = hash.replace(/^#\/?/, '').split(/[?/]/)[0]
  if (token === 'timeline') return { lens: 'timeline', page: null }
  const page = PAGE_IDS.find((p) => p === token)
  if (page && built.has(page)) return { lens: 'graph', page }
  return { lens: 'graph', page: null }
}

/** The inverse of parseRoute. The default view (graph lens) has an empty hash. */
export function routeHash(route: Route): string {
  if (route.page) return `#${route.page}`
  return route.lens === 'timeline' ? '#timeline' : ''
}
