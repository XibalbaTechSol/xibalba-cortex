import type { PageId } from '../nav'
import { EntitiesPage } from './EntitiesPage'
import { MemoriesPage } from './MemoriesPage'
import { SessionsPage } from './SessionsPage'
import { SettingsPage } from './SettingsPage'

/** Renders the page a PageId names. A page that is in the registry but has no surface here is a
 *  bug, so it says so instead of rendering a blank screen. */
export function PageHost({ page }: { page: PageId }) {
  switch (page) {
    case 'memories':
      return <MemoriesPage />
    case 'entities':
      return <EntitiesPage />
    case 'sessions':
      return <SessionsPage />
    case 'settings':
      return <SettingsPage />
    default:
      return (
        <main className="xc-page">
          <div className="xc-callout xc-callout--conflict" role="alert">The “{page}” page is registered but has no surface. This is a bug in the console.</div>
        </main>
      )
  }
}
