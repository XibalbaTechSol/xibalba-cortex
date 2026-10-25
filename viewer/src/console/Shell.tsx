// Navigation chrome: the left rail (default), the top bar (an alternative, chosen in Settings), and
// the status bar. Both layouts render the same destination registry (nav.ts), so a surface added
// there shows up in each, and the phone tab bar, without a second list to keep in step.

import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { useConsole } from './state'
import { useSettings } from './settingsContext'
import { primaryDestinations, type Destination, type DestinationId } from './nav'
import {
  IconAgents, IconChevronLeft, IconChevronRight, IconEntities, IconGraph, IconIntegrity, IconMemories, IconOperations,
  IconRefresh, IconReview, IconSearch, IconSessions, IconSettings, IconSignOut, IconTimeline,
} from './icons'

export const DESTINATION_ICON: Record<DestinationId, ReactNode> = {
  graph: <IconGraph />,
  timeline: <IconTimeline />,
  memories: <IconMemories />,
  entities: <IconEntities />,
  sessions: <IconSessions />,
  recall: <IconSearch />,
  review: <IconReview />,
  integrity: <IconIntegrity />,
  operations: <IconOperations />,
  agents: <IconAgents />,
  settings: <IconSettings />,
}

/** Which destination is showing now: a lens/page by route, an overlay by being open. */
export function useIsCurrent(): (dest: Destination) => boolean {
  const { lens, page, overlay } = useConsole()
  return (dest) => {
    if (dest.kind === 'overlay') return overlay === dest.id
    if (overlay) return false
    if (dest.kind === 'page') return page === dest.id
    return page === null && lens === dest.id
  }
}

export function NavButton({ dest }: { dest: Destination }) {
  const { go } = useConsole()
  const isCurrent = useIsCurrent()
  return (
    <button
      type="button"
      className="xc-nav-btn"
      aria-current={isCurrent(dest) ? 'page' : undefined}
      aria-haspopup={dest.kind === 'overlay' ? 'dialog' : undefined}
      /* The name is unconditional. It used to be set only when the rail's JS
         collapse toggle was on, but the rail is also forced icon-only by CSS
         between 761 and 1280px -- that media query hides `.xc-nav-label` and the
         toggle both. So at those widths every button in the primary navigation
         went nameless. Naming it always costs nothing when the label is visible:
         the accessible name is the same string either way. */
      aria-label={dest.label}
      title={dest.hint}
      onClick={() => go(dest.id)}
    >
      {DESTINATION_ICON[dest.id]}
      <span className="xc-nav-label">{dest.label}</span>
      {/* a keyboard hint, decorative for assistive tech: it would otherwise land
          inside the accessible name as "Recall ⌘K". */}
      {dest.id === 'recall' && <span className="xc-kbd xc-nav-label" aria-hidden="true">⌘K</span>}
    </button>
  )
}

export function Brand() {
  const { setLens } = useConsole()
  return (
    <a
      className="xc-brand"
      href="#"
      aria-label="Xibalba Cortex"
      onClick={(e) => { e.preventDefault(); setLens('graph') }}
    >
      {/* Two marks, one shown at a time by CSS. The lockup already contains the wordmark,
          so it stands alone; the square mark is for the collapsed rail, where the lockup's
          wordmark would be too small to read. Both are decorative -- the link is named by
          aria-label above, which the old `<b>` could not do: it carries `xc-nav-label`,
          which the <=1280px rail rules display:none, leaving the link with no name. */}
      <img className="xc-brand-lockup" src="/cortex-brain-compact-dark.png" alt="" />
      <span className="xc-brand-mark"><img src="/cortex-mark.png" alt="" /></span>
    </a>
  )
}

function useConnection() {
  const { workspace, status, loading, error } = useConsole()
  const { loaded, error: workspaceError } = workspace
  const state = error || workspaceError ? 'error' : loading || !loaded ? 'pending' : 'ready'
  const text = state === 'error' ? 'Unavailable' : state === 'pending' ? 'Connecting…' : `connected · ${status?.profile_id ?? 'default'}`
  return { state, text }
}

/** Not a store/agent pair, so it cannot collide with one (those join their ids with a NUL). */
const PRIMARY_VALUE = '__primary__'

export function ScopePicker() {
  const { workspace } = useConsole()
  const { options, selected, primary, choose, choosePrimary } = workspace
  return (
    <label className="xc-scope">
      <span className="xc-scope-label">Scope</span>
      {options.length > 0 ? (
        <select
          className="xc-input"
          value={primary ? PRIMARY_VALUE : selected ? `${selected.storeId}\0${selected.agentId}` : ''}
          onChange={(e) => {
            if (e.target.value === PRIMARY_VALUE) { choosePrimary(); return }
            const [storeId, agentId] = e.target.value.split('\0')
            choose(agentId, storeId)
          }}
        >
          {options.map((o) => (
            <option key={`${o.storeId}\0${o.agentId}`} value={`${o.storeId}\0${o.agentId}`}>
              {o.label} · {o.storeId.slice(0, 6)} · {o.writable ? 'writable' : 'read only'}
            </option>
          ))}
          <option value={PRIMARY_VALUE}>Primary profile · all memories · read only</option>
        </select>
      ) : (
        <span className="xc-input xc-scope-static">Primary profile · read only</span>
      )}
    </label>
  )
}

export function Actions() {
  const { reload, signOut } = useConsole()
  return (
    <div className="xc-top-actions">
      <button type="button" className="xc-btn xc-btn--square" aria-label="Reload data" title="Reload data" onClick={reload}>
        <IconRefresh />
      </button>
      <button type="button" className="xc-btn xc-btn--square" aria-label="Sign out" title="Sign out" onClick={signOut}>
        <IconSignOut />
      </button>
    </div>
  )
}

/** The rail layout's own header, spanning the content column.
 *
 *  Scope and Reload are workspace controls -- they say which memories are on screen and refetch
 *  them -- so they belong over the workspace, not inside the navigation. In the rail they were
 *  split across the rail's top and its foot, and both vanished into icons whenever the rail
 *  collapsed; here they stay stated at full width at either rail width. The top-bar layout
 *  already had both in its header (see TopBar), so this gives the two shells the same place
 *  for them. Connection and profile stay in the rail foot: those are about the session, not
 *  about what the workspace is showing.
 */
export function WorkspaceHeader() {
  const { reload } = useConsole()
  return (
    <header className="xc-workspace-header">
      <ScopePicker />
      <span className="xc-spacer" />
      <button type="button" className="xc-btn xc-btn--square" aria-label="Reload data" title="Reload data" onClick={reload}>
        <IconRefresh />
      </button>
    </header>
  )
}

/** Graph / Timeline, in the lens's own toolbar.
 *
 *  The two lenses are two views of one workspace, not two destinations, so they share a single
 *  nav link and switch here instead. Rendered by both lenses in place of the static title they
 *  used to carry, so the control sits in the same spot whichever one is showing. */
export function LensSwitch() {
  const { lens, setLens } = useConsole()
  return (
    <div className="xc-ranges" role="group" aria-label="Lens">
      <button type="button" className="xc-btn" aria-pressed={lens === 'graph'} onClick={() => setLens('graph')}>Graph</button>
      <button type="button" className="xc-btn" aria-pressed={lens === 'timeline'} onClick={() => setLens('timeline')}>Timeline</button>
    </div>
  )
}

/** The account control at the foot of the rail: avatar, name, and a menu with Settings and
 *  Log out. Deliberately the same control as Shield's (`ui/src/components/Dashboard.jsx`'s
 *  `.profile-btn` / `.profile-menu`) down to the 28px avatar, the menu's placement above the
 *  button and its two items, so an operator moving between the two consoles finds the same
 *  thing in the same corner. The only addition is dismissal -- Escape and a click outside --
 *  which Shield's does not do and which costs nothing visually. */
export function ProfileButton() {
  const { status, signOut, go } = useConsole()
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  const name = status?.profile_id || 'Operator profile'

  const close = useCallback(() => setOpen(false), [])
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') close() }
    const onDown = (e: MouseEvent) => {
      if (!root.current?.contains(e.target as Node)) close()
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onDown)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onDown)
    }
  }, [open, close])

  return (
    <div className="xc-profile" ref={root}>
      {open && (
        <div className="xc-profile-menu" role="menu">
          <button type="button" role="menuitem" onClick={() => { close(); go('settings') }}>Settings</button>
          <button type="button" role="menuitem" onClick={() => { close(); signOut() }}>Log out</button>
        </div>
      )}
      <button
        type="button"
        className="xc-profile-btn"
        aria-label="Open operator profile settings"
        aria-expanded={open}
        aria-haspopup="menu"
        title={name}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="xc-profile-avatar" aria-hidden="true">{name.trim().slice(0, 1).toUpperCase()}</span>
        <span className="xc-profile-name xc-nav-label">{name}</span>
      </button>
    </div>
  )
}

/** The top-bar layout: brand, connection, scope and actions on a row; every destination on a second. */
export function TopBar() {
  const { state, text } = useConnection()
  return (
    <header className="xc-top">
      <div className="xc-top-row">
        <Brand />
        <div className="xc-conn" data-state={state} role="status" aria-live="polite">
          <i aria-hidden="true" />
          {text}
        </div>
        <ScopePicker />
        <Actions />
      </div>
      <nav className="xc-nav" aria-label="Lenses and workflows">
        {primaryDestinations().map((d) => <NavButton key={d.id} dest={d} />)}
      </nav>
    </header>
  )
}

/** The left-rail layout (the default). Collapsing keeps the icons; scope and reload live in
 *  WorkspaceHeader, over the content, so collapsing no longer hides them. */
export function Rail() {
  const { settings, update } = useSettings()
  const { state, text } = useConnection()
  const collapsed = settings.railCollapsed
  return (
    <aside className="xc-rail-shell" data-collapsed={collapsed} aria-label="Navigation">
      <div className="xc-rail-head">
        <Brand />
        <button
          type="button"
          className="xc-btn xc-btn--square xc-rail-toggle"
          aria-label={collapsed ? 'Expand navigation' : 'Collapse navigation'}
          aria-pressed={collapsed}
          title={collapsed ? 'Expand navigation' : 'Collapse navigation'}
          onClick={() => update({ railCollapsed: !collapsed })}
        >
          {collapsed ? <IconChevronRight /> : <IconChevronLeft />}
        </button>
      </div>

      <nav className="xc-rail-nav" aria-label="Lenses and workflows">
        {primaryDestinations().map((d) => <NavButton key={d.id} dest={d} />)}
      </nav>

      <div className="xc-rail-foot">
        <div className="xc-conn" data-state={state} role="status" aria-live="polite" title={text}>
          <i aria-hidden="true" />
          <span className="xc-nav-label">{text}</span>
        </div>
        <ProfileButton />
      </div>
    </aside>
  )
}

export function StatusBar() {
  const { workspace, status, stats, timingNote } = useConsole()
  return (
    <footer className="xc-status">
      <span>profile {status?.profile_id ?? '—'}</span>
      <span>schema v{status?.schema_version ?? '—'}</span>
      <span>identity {status?.identity_mode ?? '—'}</span>
      <span>integrity check: {status?.integrity_check ?? '—'}</span>
      <span>{workspace.canWrite ? 'writable' : 'read only'}</span>
      <span>{stats?.memories == null ? 'memory total not counted' : `${stats.memories.toLocaleString()} memories`}</span>
      {timingNote && <span title={timingNote} style={{ color: 'var(--status-review)' }}>timing partial</span>}
      <span className="xc-spacer" />
    </footer>
  )
}

