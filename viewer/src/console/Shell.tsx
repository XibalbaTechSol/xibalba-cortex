// Top bar (brand, connection, scope, lens navigation) and the status bar.
//
// Navigation lists only what exists. Review and Integrity are drawer overlays that are not built
// yet, so they render disabled and say so -- a control that looks live but does nothing would be
// a silent stub.

import { useConsole } from './state'
import { IconGraph, IconRefresh, IconSearch, IconSignOut, IconTimeline } from './icons'

export function TopBar() {
  const { workspace, status, loading, error, lens, setLens, setOverlay, reload, signOut } = useConsole()
  const { options, selected, choose, loaded, error: workspaceError } = workspace

  const state = error || workspaceError ? 'error' : loading || !loaded ? 'pending' : 'ready'
  const connection =
    state === 'error' ? 'Unavailable' : state === 'pending' ? 'Connecting…' : `connected · ${status?.profile_id ?? 'default'}`

  return (
    <header className="xc-top">
      <div className="xc-top-row">
        <a className="xc-brand" href="#" onClick={(e) => { e.preventDefault(); setLens('graph') }}>
          <span className="xc-brand-mark"><img src="/cortex-icon-dark.png" alt="" /></span>
          <b>Xibalba <i>Cortex</i></b>
        </a>

        <div className="xc-conn" data-state={state} role="status" aria-live="polite">
          <i aria-hidden="true" />
          {connection}
        </div>

        <label className="xc-scope">
          Scope
          {options.length > 0 ? (
            <select
              className="xc-input"
              value={selected ? `${selected.storeId}\0${selected.agentId}` : ''}
              onChange={(e) => {
                const [storeId, agentId] = e.target.value.split('\0')
                choose(agentId, storeId)
              }}
            >
              {options.map((o) => (
                <option key={`${o.storeId}\0${o.agentId}`} value={`${o.storeId}\0${o.agentId}`}>
                  {o.label} · {o.storeId.slice(0, 6)} · {o.writable ? 'writable' : 'read only'}
                </option>
              ))}
            </select>
          ) : (
            <span className="xc-input" style={{ display: 'inline-flex', alignItems: 'center', color: 'var(--ink-muted)', textTransform: 'none', letterSpacing: 0 }}>
              Primary profile · read only
            </span>
          )}
        </label>

        <div style={{ display: 'flex', gap: 9 }}>
          <button type="button" className="xc-btn xc-btn--square" aria-label="Reload data" title="Reload data" onClick={reload}>
            <IconRefresh />
          </button>
          <button type="button" className="xc-btn xc-btn--square" aria-label="Sign out" title="Sign out" onClick={signOut}>
            <IconSignOut />
          </button>
        </div>
      </div>

      <nav className="xc-nav" aria-label="Lenses and workflows">
        <div className="xc-nav-group">
          <span className="xc-nav-kicker">Lens</span>
          <button type="button" className="xc-nav-btn" aria-current={lens === 'graph' ? 'page' : undefined} onClick={() => setLens('graph')}>
            <IconGraph /> Graph
          </button>
          <button type="button" className="xc-nav-btn" aria-current={lens === 'timeline' ? 'page' : undefined} onClick={() => setLens('timeline')}>
            <IconTimeline /> Timeline
          </button>
        </div>
        <div className="xc-nav-group xc-nav-group--end">
          <button type="button" className="xc-nav-btn" onClick={() => setOverlay('recall')} aria-haspopup="dialog">
            <IconSearch /> Recall <span className="xc-kbd">⌘K</span>
          </button>
          <button type="button" className="xc-nav-btn" disabled title="Planned: opens as a drawer over the current lens. Use the legacy viewer's Inference tab meanwhile.">
            Review <span className="xc-soon">soon</span>
          </button>
          <button type="button" className="xc-nav-btn" disabled title="Planned: opens as a drawer over the current lens. Use the legacy viewer's Integrity tab meanwhile.">
            Integrity <span className="xc-soon">soon</span>
          </button>
        </div>
      </nav>
    </header>
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
