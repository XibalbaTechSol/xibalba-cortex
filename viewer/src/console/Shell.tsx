// Navigation chrome: the left rail (default), the top bar (an alternative, chosen in Settings), and
// the status bar. Both layouts render the same destination registry (nav.ts), so a surface added
// there shows up in each, and the phone tab bar, without a second list to keep in step.

import type { ReactNode } from 'react'
import { useConsole } from './state'
import { useSettings } from './settingsContext'
import { GROUP_LABEL, NAV_GROUPS, destinationsIn, type Destination, type DestinationId } from './nav'
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

export function NavButton({ dest, compact = false }: { dest: Destination; compact?: boolean }) {
  const { go } = useConsole()
  const isCurrent = useIsCurrent()
  return (
    <button
      type="button"
      className="xc-nav-btn"
      aria-current={isCurrent(dest) ? 'page' : undefined}
      aria-haspopup={dest.kind === 'overlay' ? 'dialog' : undefined}
      aria-label={compact ? dest.label : undefined}
      title={dest.hint}
      onClick={() => go(dest.id)}
    >
      {DESTINATION_ICON[dest.id]}
      <span className="xc-nav-label">{dest.label}</span>
      {dest.id === 'recall' && <span className="xc-kbd xc-nav-label">⌘K</span>}
    </button>
  )
}

export function Brand() {
  const { setLens } = useConsole()
  return (
    <a className="xc-brand" href="#" onClick={(e) => { e.preventDefault(); setLens('graph') }}>
      <span className="xc-brand-mark"><img src="/cortex-mark.png" alt="" /></span>
      <b className="xc-nav-label">Xibalba <i>Cortex</i></b>
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
        {NAV_GROUPS.map((group) => {
          const items = destinationsIn(group)
          if (items.length === 0) return null
          return (
            <div className="xc-nav-group" key={group}>
              <span className="xc-nav-kicker">{GROUP_LABEL[group]}</span>
              {items.map((d) => <NavButton key={d.id} dest={d} />)}
            </div>
          )
        })}
      </nav>
    </header>
  )
}

/** The left-rail layout (the default). Collapsing keeps the icons and moves the scope to a badge. */
export function Rail() {
  const { workspace } = useConsole()
  const { settings, update } = useSettings()
  const { state, text } = useConnection()
  const collapsed = settings.railCollapsed
  const scopeLabel = workspace.selected ? workspace.selected.label : 'Primary profile'
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

      <div className="xc-rail-scope">
        <ScopePicker />
        {/* shown only when collapsed: which workspace am I in, and can I write to it */}
        <span className="xc-rail-badge" title={`${scopeLabel} · ${workspace.canWrite ? 'writable' : 'read only'}`}>
          {workspace.canWrite ? 'RW' : 'RO'}
        </span>
      </div>

      <nav className="xc-rail-nav" aria-label="Lenses and workflows">
        {NAV_GROUPS.map((group) => {
          const items = destinationsIn(group)
          if (items.length === 0) return null
          return (
            <div className="xc-rail-group" key={group}>
              <p className="xc-rail-kicker">{GROUP_LABEL[group]}</p>
              {items.map((d) => <NavButton key={d.id} dest={d} compact={collapsed} />)}
            </div>
          )
        })}
      </nav>

      <div className="xc-rail-foot">
        <div className="xc-conn" data-state={state} role="status" aria-live="polite" title={text}>
          <i aria-hidden="true" />
          <span className="xc-nav-label">{text}</span>
        </div>
        <Actions />
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
      <a href="?ui=legacy">Legacy viewer</a>
    </footer>
  )
}

