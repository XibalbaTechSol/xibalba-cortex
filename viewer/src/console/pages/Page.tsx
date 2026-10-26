// The frame every drawer surface (Memories, Sessions, Settings, ...) renders in, so a page only
// supplies its title and content and the console's rhythm (eyebrow, title, note, spacing) is not
// re-decided per page. Inside a drawer the drawer's own header carries the title, so the page keeps
// only its note and actions.

import type { ReactNode } from 'react'
import { useInDrawer } from '../PageDrawer'

export function Page({ eyebrow, title, note, actions, children }: { eyebrow: string; title: string; note?: ReactNode; actions?: ReactNode; children: ReactNode }) {
  const inDrawer = useInDrawer()
  return (
    <section className="xc-page" data-in-drawer={inDrawer} aria-label={inDrawer ? undefined : title}>
      {inDrawer ? (
        (note || actions) && (
          <header className="xc-page-head">
            {note && <p className="xc-note xc-page-note">{note}</p>}
            {actions && <div className="xc-page-actions">{actions}</div>}
          </header>
        )
      ) : (
        <header className="xc-page-head">
          <div>
            <p className="xc-eyebrow">{eyebrow}</p>
            <h1 className="xc-page-title">{title}</h1>
            {note && <p className="xc-note xc-page-note">{note}</p>}
          </div>
          {actions && <div className="xc-page-actions">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  )
}
