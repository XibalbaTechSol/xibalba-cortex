// A page that used to replace the workspace (Memories, Entities, Sessions, Operations, Agents,
// Settings) now opens as a drawer over it. The lens underneath stays mounted -- the graph keeps its
// camera, the timeline its window, the selection survives -- so opening a tool never costs the place
// you were working. Escape and the scrim close it; focus returns to whatever opened it.
//
// Review and Integrity are drawers too, in their own files, with the same frame: this one is for the
// pages the route (#memories, #settings, ...) names, so a link still opens the right drawer.

import { createContext, useContext, useId, useRef, type ReactNode } from 'react'
import { useConsole } from './state'
import { useDialog } from './useDialog'
import { ALL_DESTINATIONS, type PageId } from './nav'
import { IconClose } from './icons'

/** How wide a drawer needs to be. Lists with a detail pane need room; a form does not. */
const WIDTH: Record<PageId, 'wide' | 'medium' | 'narrow'> = {
  memories: 'wide',
  sessions: 'wide',
  entities: 'wide',
  operations: 'medium',
  agents: 'medium',
  settings: 'medium',
}

const InDrawer = createContext(false)
/** True inside a page drawer, so a page can leave out the heading the drawer already shows. */
export const useInDrawer = (): boolean => useContext(InDrawer)

export function PageDrawer({ page, children }: { page: PageId; children: ReactNode }) {
  const { setPage } = useConsole()
  const ref = useRef<HTMLDivElement>(null)
  const closeRef = useRef<HTMLButtonElement>(null)
  const titleId = useId()
  const close = () => setPage(null)
  useDialog(ref, close, closeRef)
  const dest = ALL_DESTINATIONS.find((d) => d.id === page)
  return (
    <InDrawer.Provider value>
      <div className="xc-scrim" onClick={close} aria-hidden="true" />
      <aside ref={ref} className="xc-win xc-drawer xc-drawer--page" data-width={WIDTH[page]} role="dialog" aria-modal="true" aria-labelledby={titleId}>
        <div className="xc-drawer-head">
          <div>
            <p className="xc-eyebrow">Tool</p>
            <h2 className="xc-drawer-title" id={titleId}>{dest?.label ?? page}</h2>
            {dest && <p className="xc-note">{dest.hint}</p>}
          </div>
          <button ref={closeRef} type="button" className="xc-btn xc-btn--square" onClick={close} aria-label={`Close ${dest?.label ?? page}`}><IconClose /></button>
        </div>
        <div className="xc-drawer-scroll">{children}</div>
      </aside>
    </InDrawer.Provider>
  )
}
