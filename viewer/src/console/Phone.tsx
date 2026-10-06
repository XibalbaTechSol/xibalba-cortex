// Phone layout (<= 760px): one lens fills the screen, a tab bar switches between the two lenses and
// the three overlays, and everything that is a side column on a desktop becomes a bottom sheet.
//
//   Filters  -> the facet rail, in a sheet, opened from a button over the lens
//   Time     -> the chain rail, in a sheet
//   Inspector-> a sheet that rises when something is selected and closes with its own button
//
// The same components render in all three places; only where they sit changes, so a fix to the
// inspector or the facet rail is a fix on every screen size.

import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { useConsole } from './state'
import { TopBar, StatusBar } from './Shell'
import { FacetRail } from './FacetRail'
import { GraphLens } from './GraphLens'
import { TimelineLens } from './TimelineLens'
import { Inspector } from './Inspector'
import { ChainRail } from './ChainRail'
import { useDialog } from './useDialog'
import { changedFacetCount } from './model'
import { IconClose, IconGraph, IconIntegrity, IconReview, IconSearch, IconTimeline } from './icons'

type SheetName = 'filters' | 'time' | null

function Sheet({ title, onClose, children, modal = true }: { title: string; onClose: () => void; children: ReactNode; modal?: boolean }) {
  const ref = useRef<HTMLDivElement>(null)
  const closeRef = useRef<HTMLButtonElement>(null)
  const titleId = useId()
  // modal sheets trap focus and close on Escape; the inspector sheet leaves the lens usable above it
  useDialog(ref, modal ? onClose : () => {}, modal ? closeRef : undefined)
  useEffect(() => {
    if (modal) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [modal, onClose])
  return (
    <>
      {modal && <div className="xc-scrim xc-scrim--sheet" onClick={onClose} aria-hidden="true" />}
      <div ref={ref} className="xc-win xc-sheet" // non-modal: a plain group, because the Inspector inside is already the complementary landmark
      role={modal ? 'dialog' : 'group'} aria-modal={modal || undefined} aria-labelledby={titleId} data-modal={modal}>
        <div className="xc-sheet-head">
          <span className="xc-sheet-grip" aria-hidden="true" />
          <h2 className="xc-eyebrow" id={titleId}>{title}</h2>
          <button ref={closeRef} type="button" className="xc-btn xc-btn--square" onClick={onClose} aria-label={`Close ${title}`}><IconClose /></button>
        </div>
        <div className="xc-sheet-body">{children}</div>
      </div>
    </>
  )
}

function TabBar() {
  const { lens, setLens, overlay, setOverlay } = useConsole()
  const tabs = [
    { id: 'graph', label: 'Graph', icon: <IconGraph />, current: lens === 'graph' && !overlay, go: () => { setOverlay(null); setLens('graph') } },
    { id: 'timeline', label: 'Timeline', icon: <IconTimeline />, current: lens === 'timeline' && !overlay, go: () => { setOverlay(null); setLens('timeline') } },
    { id: 'recall', label: 'Recall', icon: <IconSearch />, current: overlay === 'recall', go: () => setOverlay('recall') },
    { id: 'review', label: 'Review', icon: <IconReview />, current: overlay === 'review', go: () => setOverlay('review') },
    { id: 'integrity', label: 'Integrity', icon: <IconIntegrity />, current: overlay === 'integrity', go: () => setOverlay('integrity') },
  ]
  return (
    <nav className="xc-tabbar" aria-label="Lenses and workflows">
      {tabs.map((t) => (
        <button key={t.id} type="button" className="xc-tabbar-btn" aria-current={t.current ? 'page' : undefined} onClick={t.go}>
          {t.icon}
          <span>{t.label}</span>
        </button>
      ))}
    </nav>
  )
}

export function PhoneWorkspace() {
  const { lens, selectedId, select, facets, model, window: timeWindow } = useConsole()
  const [sheet, setSheet] = useState<SheetName>(null)

  // anything that narrows the view is worth telling the user about while the controls are hidden
  const activeFilters = facets && model ? changedFacetCount(facets, model) : 0
  const windowed = timeWindow !== null

  return (
    <div className="xc-phone">
      <TopBar />
      <main className="xc-phone-main">
        <div className="xc-phone-actions">
          <button type="button" className="xc-btn" onClick={() => setSheet('filters')} aria-haspopup="dialog">
            Filters{activeFilters > 0 ? <b className="xc-count">{activeFilters}</b> : null}
          </button>
          <button type="button" className="xc-btn" onClick={() => setSheet('time')} aria-haspopup="dialog">
            Time{windowed ? <b className="xc-count">1</b> : null}
          </button>
        </div>
        {lens === 'graph' ? <GraphLens /> : <TimelineLens />}
      </main>
      <TabBar />

      {sheet === 'filters' && (
        <Sheet title="Filters" onClose={() => setSheet(null)}>
          <FacetRail />
          <StatusBar />
        </Sheet>
      )}
      {sheet === 'time' && (
        <Sheet title="Time window" onClose={() => setSheet(null)}>
          <ChainRail />
        </Sheet>
      )}
      {selectedId && sheet === null && (
        <Sheet title="Inspector" modal={false} onClose={() => select(null)}>
          <Inspector />
        </Sheet>
      )}
    </div>
  )
}
