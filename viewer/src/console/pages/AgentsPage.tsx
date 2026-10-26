// Agents: every agent workspace in the store, which device (if any) is paired to it, and who it
// is on the integrity network. Pairing actions are offered only for a verified, writable workspace
// and only to an operator credential (the server enforces that and its refusal is shown as-is).

import { useState, type FormEvent } from 'react'
import { api, type Agent0Record, type AgentDevicePair, type AgentWorkspace } from '../../api'
import { useConsole } from '../state'
import { useAsync } from '../useAsync'
import { PAIR_ACTION_COPY, countText, describeIdentity, pairActions, type PairAction } from '../agents'
import { elideHash, parseServerTime, shortStamp } from '../model'
import { IconWarn } from '../icons'
import { Page } from './Page'
import { registerAgentWithMetaMask } from '../../agent0_wallet'

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
      title="Add your agents"
      note="Connect an agent once, then explore everything it records in the Graph and Timeline. Each agent keeps its own namespace of memories, sessions and entities."
      actions={canManage && <button type="button" className="xc-btn xc-btn--primary" onClick={() => setAssociating((v) => !v)} aria-expanded={associating}>Pair a device</button>}
    >
      <section className="xc-win xc-agent-onboarding" aria-labelledby="connect-agents-title">
        <div>
          <p className="xc-eyebrow">Start here</p>
          <h2 className="xc-title" id="connect-agents-title">Bring an agent into Cortex</h2>
          <p className="xc-copy">Run <code>cortex connect</code> from the agent’s harness. It creates or reuses the agent’s DID, prints the MCP configuration and SDK snippet, and keeps every write in this workspace.</p>
          <ol className="xc-agent-steps">
            <li><b>Connect</b><span>Generate the DID and add the MCP server or SDK adapter.</span></li>
            <li><b>Write</b><span>Let the agent record its first memory or session.</span></li>
            <li><b>Explore</b><span>Open Graph or Timeline to inspect the resulting workspace.</span></li>
          </ol>
          <div className="xc-actions-row">
            <button type="button" className="xc-btn xc-btn--primary" onClick={() => go('graph')}>Continue to Graph</button>
            <button type="button" className="xc-btn" onClick={() => go('timeline')}>Open Timeline</button>
          </div>
        </div>
        <div className="xc-agent-command" aria-label="Connect command">
          <p className="xc-eyebrow">Connect command</p>
          <code>cortex connect --agent &lt;name&gt; --harness &lt;harness&gt;</code>
          <p className="xc-note">The DID file and key stay with the harness. Cortex uses that identity to keep agent memory scoped and attributable.</p>
        </div>
      </section>
      {agents.data && !agents.data.oracle_reachable && (
        <div className="xc-callout xc-callout--review" role="status"><IconWarn /><span>The integrity oracle is not reachable, so no agent’s on-chain status could be checked. “Not checked” below is not “off-chain”.</span></div>
      )}
      {error && <div className="xc-callout xc-callout--conflict" role="alert"><IconWarn />{error}</div>}
      {associating && canManage && <PairDevice agents={entries} onDone={(m) => { setAssociating(false); setNotice(m); reload() }} />}
      {!canManage && <p className="xc-note">The selected workspace is read-only, so pairing is unavailable. Select a writable workspace to manage devices.</p>}
      {(agents.loading || devices.loading) && entries.length === 0 && <p className="xc-note" role="status">Loading…</p>}
      {!agents.loading && !error && entries.length === 0 && <div className="xc-empty"><h3 className="xc-title">No agents yet</h3><p>An agent appears here once it has written a memory or a device has been paired.</p></div>}
      {entries.length > 0 && <h2 className="xc-title xc-agents-list-title">Connected agents</h2>}
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
      <ERC8004Directory />
    </Page>
  )
}

function ERC8004Directory() {
  const [query, setQuery] = useState('')
  const [submitted, setSubmitted] = useState('')
  const [selected, setSelected] = useState<string | null>(null)
  const [localRecord, setLocalRecord] = useState<Agent0Record | null>(null)
  const [registrationName, setRegistrationName] = useState('Cortex Test Agent')
  const [registrationDescription, setRegistrationDescription] = useState('Test ERC-8004 identity registered from Cortex with MetaMask on Base Sepolia.')
  const [registering, setRegistering] = useState(false)
  const [registrationError, setRegistrationError] = useState<string | null>(null)
  const [registrationTx, setRegistrationTx] = useState<string | null>(null)
  const results = useAsync(() => api.agent0Search(submitted), [submitted], { keepData: true })
  const details = useAsync(() => selected ? api.agent0Agent(selected, true) : Promise.resolve(null), [selected], { keepData: true })
  const reputation = useAsync(() => selected ? api.agent0Reputation(selected) : Promise.resolve(null), [selected], { keepData: true })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    setSubmitted(query.trim())
    setSelected(null)
    setLocalRecord(null)
  }
  const register = async (event: FormEvent) => {
    event.preventDefault()
    setRegistering(true)
    setRegistrationError(null)
    setRegistrationTx(null)
    try {
      const result = await registerAgentWithMetaMask({ name: registrationName, description: registrationDescription })
      setLocalRecord(result.record as Agent0Record)
      setRegistrationTx(result.txHash)
      setSelected(result.agentId)
    } catch (error) {
      setRegistrationError(error instanceof Error ? error.message : String(error))
    } finally {
      setRegistering(false)
    }
  }

  return (
    <section className="xc-win xc-agent-onboarding" aria-labelledby="erc8004-directory-title">
      <div>
        <p className="xc-eyebrow">External directory · Agent0</p>
        <h2 className="xc-title" id="erc8004-directory-title">Search ERC-8004 agents</h2>
        <p className="xc-copy">Browse public ERC-8004 registration data and reputation. This is external chain evidence; it does not change Cortex identity or Integrity AIS.</p>
        <form className="xc-actions-row" onSubmit={submit}>
          <label className="xc-field" style={{ flex: 1 }}>Search by name
            <input className="xc-input" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="agent name (optional)" />
          </label>
          <button type="submit" className="xc-btn xc-btn--primary" disabled={results.loading}>Search</button>
        </form>
        <details className="xc-agent-register">
          <summary className="xc-btn">Register a test identity with MetaMask</summary>
          <form className="xc-agent-register-form" onSubmit={register}>
            <label className="xc-field">Name
              <input className="xc-input" value={registrationName} onChange={(event) => setRegistrationName(event.target.value)} required />
            </label>
            <label className="xc-field">Description
              <textarea className="xc-input" value={registrationDescription} onChange={(event) => setRegistrationDescription(event.target.value)} rows={3} required />
            </label>
            <p className="xc-note">MetaMask will switch to or add Base Sepolia, then ask you to approve the ERC-8004 registration transaction. Gas is paid by the connected wallet.</p>
            <button type="submit" className="xc-btn xc-btn--primary" disabled={registering}>{registering ? 'Waiting for MetaMask…' : 'Connect & register'}</button>
          </form>
        </details>
        {registrationError && <div className="xc-callout xc-callout--conflict" role="alert"><IconWarn />{registrationError}</div>}
        {registrationTx && <p className="xc-note">Confirmed transaction: <a className="xc-mono" href={`https://sepolia.basescan.org/tx/${registrationTx}`} target="_blank" rel="noreferrer">{registrationTx}</a></p>}
        {results.error && <div className="xc-callout xc-callout--review" role="status"><IconWarn /><span>{results.error}. Enable the Agent0 extra and configure the RPC/subgraph to use this directory.</span></div>}
        {results.loading && <p className="xc-note" role="status">Searching ERC-8004…</p>}
        {results.data && !results.error && (
          <div className="xc-agent-directory">
            <p className="xc-eyebrow xc-eyebrow--dim">{results.data.agents.length} result{results.data.agents.length === 1 ? '' : 's'} · Agent0 index</p>
            {results.data.agents.length === 0 && <p className="xc-note">No matching ERC-8004 agents.</p>}
            {results.data.agents.map((agent) => (
              <button type="button" className={`xc-agent-result ${selected === String(agent.agentId ?? '') ? 'xc-agent-result--selected' : ''}`} key={String(agent.agentId)} onClick={() => setSelected(String(agent.agentId))}>
                <span><b>{agent.name || 'Unnamed agent'}</b><small className="xc-mono">{String(agent.agentId ?? 'unknown')}</small></span>
                <span className="xc-tag"><i />{agent.active === false ? 'inactive' : 'active'}</span>
              </button>
            ))}
          </div>
        )}
      </div>
      {selected && <Agent0Details agentId={selected} details={details.data?.agent ?? localRecord} reputation={reputation.data?.reputation ?? null} loading={details.loading || reputation.loading} error={(details.data?.agent || localRecord) ? reputation.error : (details.error ?? reputation.error)} />}
    </section>
  )
}

function Agent0Details({ agentId, details, reputation, loading, error }: { agentId: string; details: Agent0Record | null; reputation: Record<string, unknown> | null; loading: boolean; error: string | null }) {
  return (
    <div className="xc-agent-directory-detail" aria-label="ERC-8004 agent details">
      <p className="xc-eyebrow">On-chain agent record</p>
      <h3 className="xc-title">{details?.name || agentId}</h3>
      <p className="xc-meta xc-mono">{agentId}</p>
      {loading && <p className="xc-note" role="status">Loading registration and reputation…</p>}
      {error && <div className="xc-callout xc-callout--conflict" role="alert"><IconWarn />{error}</div>}
      {details && <dl className="xc-kv">
        <div><dt>Description</dt><dd>{details.description || '—'}</dd></div>
        <div><dt>Owner</dt><dd className="xc-mono">{details.owners?.join(', ') || '—'}</dd></div>
        <div><dt>Wallet</dt><dd className="xc-mono">{details.walletAddress || '—'}</dd></div>
        <div><dt>Agent URI</dt><dd className="xc-mono">{details.agentURI || '—'}</dd></div>
        <div><dt>Trust models</dt><dd>{details.trustModels?.join(', ') || '—'}</dd></div>
      </dl>}
      {details?.endpoints && details.endpoints.length > 0 && <><p className="xc-eyebrow xc-eyebrow--dim">Endpoints</p><ul className="xc-pairs">{details.endpoints.map((endpoint, index) => <li className="xc-pair" key={index}><span className="xc-mono">{String(endpoint.type ?? 'endpoint')}</span> · {String(endpoint.value ?? '—')}</li>)}</ul></>}
      {reputation && <><p className="xc-eyebrow xc-eyebrow--dim">Reputation summary</p><pre className="xc-code-block">{JSON.stringify(reputation, null, 2)}</pre></>}
      <p className="xc-note">Source: Agent0 / ERC-8004. Cortex does not treat this record as authorization or Integrity truth.</p>
    </div>
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
