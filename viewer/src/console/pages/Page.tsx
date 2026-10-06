// The frame every full-page surface (Memories, Sessions, Settings, ...) renders in, so a page only
// supplies its title and content and the console's rhythm (eyebrow, title, note, spacing) is not
// re-decided per page.

import type { ReactNode } from 'react'

export function Page({ eyebrow, title, note, actions, children }: { eyebrow: string; title: string; note?: ReactNode; actions?: ReactNode; children: ReactNode }) {
  return (
    <main className="xc-page">
      <header className="xc-page-head">
        <div>
          <p className="xc-eyebrow">{eyebrow}</p>
          <h1 className="xc-page-title">{title}</h1>
          {note && <p className="xc-note xc-page-note">{note}</p>}
        </div>
        {actions && <div className="xc-page-actions">{actions}</div>}
      </header>
      {children}
    </main>
  )
}
