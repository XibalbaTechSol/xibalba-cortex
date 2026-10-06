// Agents: every agent workspace in the store, which device (if any) is paired to it, and who it
// is on the integrity network. Pairing actions are offered only for a verified, writable workspace
// and only to an operator credential (the server enforces that and its refusal is shown as-is).

import { useState, type FormEvent } from 'react'
import { api, type AgentDevicePair, type AgentWorkspace } from '../../api'
import { useConsole } from '../state'
import { useAsync } from '../useAsync'
import { PAIR_ACTION_COPY, countText, describeIdentity, pairActions, type PairAction } from '../agents'
import { elideHash, parseServerTime, shortStamp } from '../model'
import { IconWarn } from '../icons'
import { Page } from './Page'

const stamp = (value: string | null | undefined): string => {
  const ms = parseServerTime(value)
  return ms === null ? '—' : shortStamp(ms)
}

/** One card per agent: its workspace row (absent for an agent that is paired but has not written yet)
 *  and every device paired to it. */
interface AgentEntry {
  agentId: string
  workspace: AgentWorkspace | null
  pairs: AgentDevicePair[]
}

function mergeAgents(workspaces: readonly AgentWorkspace[], pairs: readonly AgentDevicePair[]): AgentEntry[] {
  const byAgent = new Map<string, AgentEntry>()
  for (const w of workspaces) {
    const existing = byAgent.get(w.agent_id)
    // an agent can have several workspace rows (one per device); keep the one with a verified scope
    if (!existing) byAgent.set(w.agent_id, { agentId: w.agent_id, workspace: w, pairs: [] })
    else if (!existing.workspace?.store_id && w.store_id) existing.workspace = w
  }
  for (const p of pairs) {
    const entry = byAgent.get(p.agent_id) ?? { agentId: p.agent_id, workspace: null, pairs: [] }
    entry.pairs.push(p)
    byAgent.set(p.agent_id, entry)
  }
  return [...byAgent.values()]
}

export function AgentsPage() {
  const { workspace, go, revision, reload, setNotice } = useConsole()
  const agents = useAsync(() => api.agents(200), [revision], { keepData: true })
  const devices = useAsync(() => api.agentDevices(), [revision], { keepData: true })
  const [associating, setAssociating] = useState(false)
  const entries = mergeAgents(agents.data?.agents ?? [], devices.data?.pairs ?? [])
  const canManage = workspace.canWrite
  const error = agents.error ?? devices.error

  return (
    <Page
      eyebrow="System"
      title="Agents"
      note="Each agent keeps its own namespace of memories, sessions and entities. A device is paired to an agent so its writes land in that namespace."
      actions={canManage && <button type="button" className="xc-btn xc-btn--primary" onClick={() => setAssociating((v) => !v)} aria-expanded={associating}>Pair a device</button>}
    >
      {agents.data && !agents.data.oracle_reachable && (
        <div className="xc-callout xc-callout--review" role="status"><IconWarn /><span>The integrity oracle is not reachable, so no agent’s on-chain status could be checked. “Not checked” below is not “off-chain”.</span></div>
      )}
      {error && <div className="xc-callout xc-callout--conflict" role="alert"><IconWarn />{error}</div>}
      {associating && canManage && <PairDevice agents={entries} onDone={(m) => { setAssociating(false); setNotice(m); reload() }} />}
      {!canManage && <p className="xc-note">The selected workspace is read-only, so pairing is unavailable. Select a writable workspace to manage devices.</p>}
      {(agents.loading || devices.loading) && entries.length === 0 && <p className="xc-note" role="status">Loading…</p>}
      {!agents.loading && !error && entries.length === 0 && <div className="xc-empty"><h3 className="xc-title">No agents yet</h3><p>An agent appears here once it has written a memory or a device has been paired.</p></div>}
      <div className="xc-opsgrid">
        {entries.map((entry) => (
          <AgentCard
            key={entry.agentId}
            entry={entry}
            canManage={canManage}
            onOpen={() => { if (entry.workspace?.store_id) { workspace.choose(entry.agentId, entry.workspace.store_id); go('graph') } }}
            onChanged={(m) => { setNotice(m); reload() }}
          />
        ))}
      </div>
    </Page>
  )
}

function AgentCard({ entry, canManage, onOpen, onChanged }: { entry: AgentEntry; canManage: boolean; onOpen: () => void; onChanged: (message: string) => void }) {
  const a = entry.workspace
  const identity = describeIdentity({ on_chain: a?.on_chain, identity_verified: a?.identity_verified, wallet_address: a?.wallet_address })
  const [summary, setSummary] = useState(false)
  const scoped = Boolean(a?.store_id && a?.profile_id && a?.store_access)
  const title = a?.display_name ?? a?.agent_name ?? elideHash(entry.agentId)

  return (
    <section className="xc-win xc-opscard" aria-label={title}>
      <p className="xc-eyebrow">Agent</p>
      <h3 className="xc-title" title={entry.agentId}>{title}</h3>
      <div className="xc-card-facts">
        <span className={`xc-tag ${a?.writable ? 'xc-tag--anchored' : ''}`}><i />{!a ? 'no workspace yet' : scoped ? (a.writable ? 'writable' : 'read only') : 'scope unverified'}</span>
        <span className={`xc-tag ${identity.tone === 'ok' ? 'xc-tag--anchored' : identity.tone === 'review' ? 'xc-tag--review' : ''}`} title={identity.detail}><i />{identity.label}</span>
      </div>
      {a && (
        <dl className="xc-kv">
          <div><dt>Memories</dt><dd>{countText(a.memories, a.memories_counted)}</dd></div>
          <div><dt>Sessions</dt><dd>{countText(a.sessions, a.sessions_counted)}</dd></div>
          <div><dt>Last seen</dt><dd>{stamp(a.last_seen_at)}</dd></div>
          <div><dt>Store</dt><dd className="xc-mono">{a.store_id ?? '—'}</dd></div>
        </dl>
      )}
      <p className="xc-note">{identity.detail}</p>
      {scoped && (
        <div className="xc-actions-row">
          <button type="button" className="xc-btn" onClick={onOpen}>Open workspace</button>
          <button type="button" className="xc-btn" onClick={() => setSummary((v) => !v)} aria-expanded={summary}>{summary ? 'Hide summary' : 'Exact summary'}</button>
        </div>
      )}
      {summary && scoped && a && <Summary agentId={entry.agentId} storeId={a.store_id ?? ''} />}

      <p className="xc-eyebrow xc-eyebrow--dim">Paired devices · {entry.pairs.length}</p>
      {entry.pairs.length === 0 && <p className="xc-note">No device is paired to this agent.</p>}
      <ul className="xc-pairs">
        {entry.pairs.map((p) => <PairRow key={p.device_id} pair={p} canManage={canManage} onChanged={onChanged} />)}
      </ul>
    </section>
  )
}

function PairRow({ pair, canManage, onChanged }: { pair: AgentDevicePair; canManage: boolean; onChanged: (message: string) => void }) {
  const [action, setAction] = useState<PairAction | null>(null)
  const [name, setName] = useState(pair.display_name)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const run = async (kind: PairAction) => {
    setBusy(true)
    setError(null)
    try {
      if (kind === 'rename') await api.renameAgentDevice(pair.device_id, name.trim())
      if (kind === 'detach') await api.detachAgentDevice(pair.device_id)
      if (kind === 'revoke') await api.revokeAgentDevice(pair.device_id)
      setAction(null)
      onChanged(`Device ${pair.display_name} ${kind === 'rename' ? 'renamed' : kind === 'detach' ? 'detached' : 'revoked'}.`)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <li className="xc-pair">
      <div className="xc-card-top">
        <b>{pair.display_name}</b>
        <span className={`xc-tag ${pair.status === 'active' ? 'xc-tag--anchored' : pair.status === 'revoked' ? 'xc-tag--conflict' : 'xc-tag--review'}`}><i />{pair.status}</span>
      </div>
      <p className="xc-meta xc-mono" title={pair.device_id}>{pair.device_id} · paired {stamp(pair.created_at)} · last seen {stamp(pair.last_seen_at)}</p>
      {error && <div className="xc-callout xc-callout--conflict" role="alert"><IconWarn />{error}</div>}
      {action ? (
        <div className="xc-form">
          {action === 'rename' ? (
            <label className="xc-field">New device name<input className="xc-input" value={name} onChange={(e) => setName(e.target.value)} autoFocus /></label>
          ) : (
            <div className="xc-callout xc-callout--conflict"><IconWarn /><span>{PAIR_ACTION_COPY[action].confirm}</span></div>
          )}
          <div className="xc-actions-row">
            <button type="button" className="xc-btn" disabled={busy} onClick={() => setAction(null)}>Cancel</button>
            <button type="button" className={action === 'revoke' ? 'xc-btn xc-btn--danger' : 'xc-btn xc-btn--primary'} disabled={busy || (action === 'rename' && !name.trim())} onClick={() => run(action)}>{busy ? 'Working…' : PAIR_ACTION_COPY[action].label}</button>
          </div>
        </div>
      ) : (
        canManage && (
          <div className="xc-actions-row">
            {pairActions(pair.status).map((p) => (
              <button key={p} type="button" className={p === 'revoke' ? 'xc-btn xc-btn--danger-quiet' : 'xc-btn'} onClick={() => setAction(p)}>{PAIR_ACTION_COPY[p].label}</button>
            ))}
          </div>
        )
      )}
    </li>
  )
}

function Summary({ agentId, storeId }: { agentId: string; storeId: string }) {
  const s = useAsync(() => api.agentSummary(agentId, storeId), [agentId, storeId])
  if (s.loading) return <p className="xc-note" role="status">Counting…</p>
  if (s.error) return <div className="xc-callout xc-callout--conflict" role="alert"><IconWarn />{s.error}</div>
  if (!s.data) return null
  return (
    <dl className="xc-kv">
      <div><dt>Memories</dt><dd>{s.data.memories.toLocaleString()}</dd></div>
      <div><dt>Sessions</dt><dd>{s.data.sessions.toLocaleString()}</dd></div>
      <div><dt>Sources</dt><dd>{s.data.sources.toLocaleString()}</dd></div>
      <div><dt>Embedded memories</dt><dd>{s.data.embedded_memories === null ? 'not counted' : s.data.embedded_memories.toLocaleString()}</dd></div>
    </dl>
  )
}

function PairDevice({ agents, onDone }: { agents: AgentEntry[]; onDone: (message: string) => void }) {
  const choices = agents
  const [agentId, setAgentId] = useState(choices[0]?.agentId ?? '')
  const [deviceId, setDeviceId] = useState('')
  const [display, setDisplay] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!agentId || !deviceId.trim()) { setError('Choose an agent and give the device an id.'); return }
    setBusy(true)
    setError(null)
    try {
      await api.associateAgentDevice(agentId, deviceId.trim(), display.trim() || undefined)
      onDone(`Device ${display.trim() || deviceId.trim()} paired.`)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setBusy(false)
    }
  }
  return (
    <form className="xc-win xc-newmemory" onSubmit={submit} aria-label="Pair a device">
      <p className="xc-eyebrow">Pair a device</p>
      <label className="xc-field">Agent
        <select className="xc-input" value={agentId} onChange={(e) => setAgentId(e.target.value)}>
          {choices.map((a) => <option key={a.agentId} value={a.agentId}>{a.workspace?.display_name ?? elideHash(a.agentId)}</option>)}
        </select>
      </label>
      <div className="xc-newmemory-row">
        <label className="xc-field">Device id<input className="xc-input xc-input--mono" value={deviceId} onChange={(e) => setDeviceId(e.target.value)} placeholder="the device’s stable id" /></label>
        <label className="xc-field">Display name <span className="xc-note">optional</span><input className="xc-input" value={display} onChange={(e) => setDisplay(e.target.value)} /></label>
      </div>
      {error && <div className="xc-callout xc-callout--conflict" role="alert"><IconWarn />{error}</div>}
      <div className="xc-actions-row"><button type="submit" className="xc-btn xc-btn--primary" disabled={busy}>{busy ? 'Pairing…' : 'Pair device'}</button></div>
    </form>
  )
}
