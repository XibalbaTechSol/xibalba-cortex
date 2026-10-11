// The console's destinations, in one place, and the hash routes that reach them.
//
// Three layouts render this same list (left rail, top bar, phone tab bar + "More" sheet), so a
// destination added here appears in all three and cannot drift between them. A destination is only
// listed once its surface exists: BUILT is the gate, so there is no nav entry that does nothing.

export type Lens = 'graph' | 'timeline'
export type PageId = 'memories' | 'entities' | 'sessions' | 'operations' | 'agents' | 'settings'
export type OverlayId = 'recall' | 'review' | 'integrity'

export type DestinationId = Lens | PageId | OverlayId
/** lens = a primary view; page = a drawer over the lens (it keeps its route); overlay = a modal dialog */
export type DestinationKind = 'lens' | 'page' | 'overlay'
// Two groups, and the split is the product's information architecture: the Graph and Timeline lenses are
// where people work; every other destination is a "tool" that opens over the lens it was opened from --
// a dialog (Recall, Review, Integrity) or a drawer (everything that used to be a full page).
export type NavGroup = 'lens' | 'tools'

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
  tools: 'Tools',
}

export const ALL_DESTINATIONS: readonly Destination[] = [
  { id: 'graph', kind: 'lens', label: 'Graph', group: 'lens', hint: 'Knowledge graph' },
  { id: 'timeline', kind: 'lens', label: 'Timeline', group: 'lens', hint: 'Sessions on a time axis' },
  { id: 'memories', kind: 'page', label: 'Memories', group: 'tools', hint: 'Browse, filter and add memories' },
  { id: 'entities', kind: 'page', label: 'Entities', group: 'tools', hint: 'Entity neighbours and paths' },
  { id: 'sessions', kind: 'page', label: 'Sessions', group: 'tools', hint: 'Sessions, exchanges, replay and traces' },
  { id: 'recall', kind: 'overlay', label: 'Recall', group: 'tools', hint: 'Ask the memory a question' },
  { id: 'review', kind: 'overlay', label: 'Review', group: 'tools', hint: 'Proposals, PARA and tasks' },
  { id: 'integrity', kind: 'overlay', label: 'Integrity', group: 'tools', hint: 'Verify chains and checkpoints' },
  { id: 'operations', kind: 'page', label: 'Operations', group: 'tools', hint: 'Health, workers and queues' },
  { id: 'agents', kind: 'page', label: 'Agents', group: 'tools', hint: 'Agents, devices and pairing' },
  { id: 'settings', kind: 'page', label: 'Settings', group: 'tools', hint: 'Layout, inference, account' },
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

export const NAV_GROUPS: readonly NavGroup[] = ['lens', 'tools']

// --- hash routes --------------------------------------------------------------------------------------

export interface Route {
  lens: Lens
  /** null = just the lens; otherwise the drawer open over it */
  page: PageId | null
}

const PAGE_IDS: readonly PageId[] = ['memories', 'entities', 'sessions', 'operations', 'agents', 'settings']

/** The route is a lens, and optionally a drawer open over it:
 *    ``            graph lens            `#timeline`           timeline lens
 *    `#settings`   settings over graph   `#timeline/sessions`  sessions over the timeline
 *  An unknown token falls back to the graph; an unbuilt page is ignored rather than rendering nothing. */
export function parseRoute(hash: string, built: ReadonlySet<DestinationId> = BUILT): Route {
  const [first, second] = hash.replace(/^#\/?/, '').split('?')[0].split('/')
  const pageOf = (token: string | undefined): PageId | null => {
    const page = PAGE_IDS.find((p) => p === token)
    return page && built.has(page) ? page : null
  }
  if (first === 'timeline') return { lens: 'timeline', page: pageOf(second) }
  return { lens: 'graph', page: pageOf(first) }
}

/** The inverse of parseRoute. The default view (graph lens, no drawer) has an empty hash. */
export function routeHash(route: Route): string {
  if (route.lens === 'timeline') return route.page ? `#timeline/${route.page}` : '#timeline'
  return route.page ? `#${route.page}` : ''
}
