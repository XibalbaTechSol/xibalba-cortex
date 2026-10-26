import { TAB_LABEL, tabsFor, type PageId } from '../nav'
import { useConsole } from '../state'
import { AgentsPage } from './AgentsPage'
import { EntitiesPage } from './EntitiesPage'
import { MemoriesPage } from './MemoriesPage'
import { OperationsPage } from './OperationsPage'
import { SessionsPage } from './SessionsPage'
import { SettingsPage } from './SettingsPage'

/** Moves between the sibling surfaces a single nav link now fronts.
 *
 *  The rail lists five destinations; these tabs are how the other six stay reachable in one
 *  click from the one that fronts them, rather than being buried. Rendered only when a page
 *  actually has peers. */
function PageTabs({ page }: { page: PageId }) {
  const { setPage } = useConsole()
  const tabs = tabsFor(page)
  if (tabs.length === 0) return null
  return (
    <nav className="xc-page-tabs" aria-label="Related pages">
      {tabs.map((id) => (
        <button
          key={id}
          type="button"
          className="xc-page-tab"
          aria-current={id === page ? 'page' : undefined}
          onClick={() => setPage(id)}
        >
          {TAB_LABEL[id]}
        </button>
      ))}
    </nav>
  )
}

/** Renders the page a PageId names, under the tab strip for its group. A page that is in the
 *  registry but has no surface here is a bug, so it says so instead of rendering a blank
 *  screen. */
export function PageHost({ page }: { page: PageId }) {
  return (
    <>
      <PageTabs page={page} />
      <PageBody page={page} />
    </>
  )
}

function PageBody({ page }: { page: PageId }) {
  switch (page) {
    case 'memories':
      return <MemoriesPage />
    case 'agents':
      return <AgentsPage />
    case 'entities':
      return <EntitiesPage />
    case 'operations':
      return <OperationsPage />
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
