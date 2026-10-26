import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { Landing } from './Landing'
import { ManagedGraphLens, ManagedTimelineLens } from './ManagedLenses'
import { registerAgentWithMetaMask } from '../agent0_wallet'
import './managed.css'

type Plan = { id: string; name: string; monthly_cents: number; max_memories: number; writes_per_month: number; retrievals_per_month: number }
type Catalog = { plans: Plan[]; billing_configured: boolean; signup_enabled: boolean; hosted_inference_enabled: boolean }
type Account = { account: { display_name: string; email: string }; entitlement: { plan: Plan; status: string; writable: boolean; period_end: number | null; cancel_at_period_end: boolean }; usage: { month: string; used: Record<string, number> }; counts: Record<string, number>; csrf_token: string }
type Memory = { id: string; content: string; status: string }
type Agent0Record = { agentId?: string; agentURI?: string; name?: string; description?: string; owners?: string[]; walletAddress?: string; trustModels?: unknown[]; endpoints?: Array<Record<string, unknown>>; active?: boolean }
type Agent0Search = { agents: Agent0Record[]; source: 'agent0'; query: string }

class ManagedError extends Error {
  status: number
  constructor(status: number, message: string) { super(message); this.status = status }
}

async function request<T>(path: string, options: RequestInit = {}, csrf?: string): Promise<T> {
  const response = await fetch('/api/managed/' + path, { ...options, credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', ...(csrf ? { 'X-Cortex-CSRF-Token': csrf } : {}), ...options.headers } })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new ManagedError(response.status, data.error || `Request failed (${response.status})`)
  return data as T
}

export function ManagedApp() {
  const [catalog, setCatalog] = useState<Catalog | null>(null)
  const [account, setAccount] = useState<Account | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState(() => new URLSearchParams(location.search).has('verified') ? 'Email verified. Sign in to open your workspace.' : '')
  const [authMode, setAuthMode] = useState<'login' | 'signup' | 'forgot-password' | 'resend-verification' | 'reset' | null>(() => new URLSearchParams(location.search).has('reset_token') ? 'reset' : null)
  const resetToken = useRef(new URLSearchParams(location.search).get('reset_token') || '')
  const [keys, setKeys] = useState<Array<{id: string; label: string; expires_at: string; agent_ids?: string[]}>>([])
  const [agentDids, setAgentDids] = useState('')
  const [busy, setBusy] = useState(false)
  const [memories, setMemories] = useState<Memory[]>([])
  const [query, setQuery] = useState('')
  const [newKey, setNewKey] = useState('')
  const [lens, setLens] = useState<'workspace' | 'graph' | 'timeline'>('workspace')
  const retryWrite = useRef<{ content: string; key: string } | null>(null)

  const refresh = useCallback(async () => {
    const state = await request<Account>('me')
    setAccount(state)
    return state
  }, [])

  useEffect(() => {
    let alive = true
    if (resetToken.current) history.replaceState(null, '', '/managed')
    Promise.all([
      request<Catalog>('plans'),
      request<Account>('me').catch((e: unknown) => { if (e instanceof ManagedError && e.status === 401) return null; throw e }),
    ]).then(([plans, state]) => { if (alive) { setCatalog(plans); setAccount(state) } })
      .catch((e: Error) => { if (alive) setError(e.message) })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [])

  useEffect(() => {
    if (authMode) document.querySelector('.xc-managed-auth')?.scrollIntoView({ block: 'center' })
  }, [authMode])

  const act = async (work: () => Promise<void>) => {
    setError(''); setNotice(''); setBusy(true)
    try { await work() } catch (e) {
      if (e instanceof ManagedError && e.status === 401) { setAccount(null); setNewKey(''); setKeys([]); setMemories([]); setAuthMode('login') }
      const message = e instanceof Error ? e.message : 'Request failed'
      setError(message === 'account requires email verification or administrator approval'
        ? 'Your email is not verified yet. Open the newest “Verify your Cortex account” email, click its link, then sign in again.'
        : message)
    }
    finally { setBusy(false) }
  }

  const signIn = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const fields = new FormData(event.currentTarget)
    void act(async () => {
      const recovery = authMode && !['signup', 'login'].includes(authMode)
      const input = { ...Object.fromEntries(fields), ...(authMode === 'reset' ? { token: resetToken.current } : {}) }
      await request(recovery ? 'recovery/' + authMode : authMode === 'signup' ? 'signup' : 'login', { method: 'POST', body: JSON.stringify(input) })
      if (recovery) {
        setNotice(authMode === 'reset' ? 'Password reset. Sign in with your new password.' : 'If this account needs this action, an email has been sent.')
        if (authMode === 'reset') { resetToken.current = ''; history.replaceState(null, '', '/managed'); setAuthMode('login') }
        return
      }
      if (authMode === 'signup') setNotice('Check your email for a verification link. Verify your address before signing in.')
      else { await refresh(); setAuthMode(null) }
    })
  }

  const billing = (plan?: string) => void act(async () => {
    const result = await request<{ url: string }>(plan ? 'checkout' : 'portal', { method: 'POST', body: JSON.stringify(plan ? { plan } : {}) }, account?.csrf_token)
    const destination = new URL(result.url)
    if (destination.protocol !== 'https:' || !['checkout.stripe.com', 'billing.stripe.com'].includes(destination.hostname)) throw new Error('The payment service returned an invalid destination')
    location.assign(destination.href)
  })

  const search = () => void act(async () => {
    const result = await request<{ memories: Memory[] }>('memories' + (query.trim() ? '?q=' + encodeURIComponent(query.trim()) : ''))
    setMemories(result.memories)
    await refresh()
  })

  const exportMemories = () => void act(async () => {
    await refresh()
    const link = document.createElement('a')
    link.href = '/api/managed/export-download'; link.download = 'cortex-memories.json'; link.click()
    setNotice('Your memory export download has started.')
  })

  const cards = catalog && <div className="xc-managed-plans">
    {catalog.plans.map((plan) => <article className="xc-win xc-managed-plan" key={plan.id} aria-label={plan.name + ' plan'}>
      <p className="xc-eyebrow">{plan.name}</p>
      <h3 className="xc-managed-price">${plan.monthly_cents / 100}<span> / month</span></h3>
      <p className="xc-note">USD · monthly subscription</p>
      <dl className="xc-managed-limits">
        <div><dt>Stored memories</dt><dd>{plan.max_memories.toLocaleString()}</dd></div>
        <div><dt>Write requests / month</dt><dd>{plan.writes_per_month.toLocaleString()}</dd></div>
        <div><dt>Retrieval requests / month</dt><dd>{plan.retrievals_per_month.toLocaleString()}</dd></div>
      </dl>
      <p className="xc-copy">Isolated memory storage, a verifiable event history, lexical search, API keys, and data export.</p>
      {account ? <button className="xc-btn xc-btn--primary" disabled={busy || plan.id === 'free' || plan.id === account.entitlement.plan.id || !catalog.billing_configured} onClick={() => account.entitlement.plan.id === 'free' ? billing(plan.id) : billing()}>
        {plan.id === account.entitlement.plan.id ? 'Current plan' : plan.id === 'free' ? 'Manage through billing' : account.entitlement.plan.id === 'free' ? 'Choose ' + plan.name : 'Change through billing'}
      </button> : <button className="xc-btn xc-btn--primary" disabled={busy || !catalog.signup_enabled || (plan.id !== 'free' && !catalog.billing_configured)} onClick={() => setAuthMode('signup')}>
        {plan.id === 'free' ? 'Start free' : 'Choose ' + plan.name}
      </button>}
    </article>)}
  </div>

  const messages = <div aria-live="polite">
    {error && <p className="xc-callout xc-callout--conflict" role="alert">{error}</p>}
    {notice && <p className="xc-callout">{notice}</p>}
  </div>

  if (loading) return <div className="xc"><main className="xc-managed"><p className="xc-note">Loading managed memory services…</p></main></div>

  if (!account) return <div className="xc"><Landing managed onSignIn={() => setAuthMode('login')}>
    <section className="xc-landing-section" id="pricing" aria-labelledby="managed-plans-title">
      <p className="xc-eyebrow">Managed memory</p>
      <h2 className="xc-landing-h2" id="managed-plans-title">Choose the capacity you need</h2>
      {!authMode && messages}
      {cards}
      {catalog && !catalog.billing_configured && <p className="xc-note xc-managed-note">Paid subscriptions are not available yet.</p>}
      {catalog && !catalog.signup_enabled && <p className="xc-note">New workspace registration is not available yet.</p>}
      <p className="xc-note xc-managed-note">Limits reset monthly in UTC. Each memory supports up to 16 KiB of text. These plans cover memory storage and lexical retrieval; hosted inference is not included yet. Team provides higher workspace capacity; shared user seats are not offered in this release.</p>
    </section>
    {authMode && <section className="xc-landing-section xc-managed-auth" aria-labelledby="managed-auth-title">
      <h2 className="xc-landing-h2" id="managed-auth-title">{authMode === 'signup' ? 'Create your workspace' : authMode === 'forgot-password' ? 'Reset your password' : authMode === 'resend-verification' ? 'Resend verification email' : authMode === 'reset' ? 'Set a new password' : 'Sign in to managed Cortex'}</h2>
      {messages}
      <form className="xc-managed-form" onSubmit={signIn}>
        {authMode === 'signup' && <label className="xc-field">Name<input className="xc-input" name="display_name" autoComplete="name" required maxLength={120} /></label>}
        {authMode !== 'reset' && <label className="xc-field">Email<input className="xc-input" name="email" type="email" autoComplete="username" required /></label>}
        {!['forgot-password', 'resend-verification'].includes(authMode) && <label className="xc-field">Password<input className="xc-input" name="password" type="password" autoComplete={authMode === 'login' ? 'current-password' : 'new-password'} minLength={10} required /></label>}
        <button className="xc-btn xc-btn--primary" disabled={busy || (authMode === 'signup' && !catalog?.signup_enabled)}>{busy ? 'Working…' : authMode === 'signup' ? 'Create workspace' : authMode === 'login' ? 'Sign in' : authMode === 'reset' ? 'Set password' : 'Send email'}</button>
        <button className="xc-btn" type="button" disabled={busy || (authMode === 'login' && !catalog?.signup_enabled)} onClick={() => setAuthMode(authMode === 'login' ? 'signup' : 'login')}>{authMode === 'login' ? 'Create an account' : 'I already have an account'}</button>
        <button className="xc-btn" type="button" disabled={busy} onClick={() => setAuthMode('forgot-password')}>Forgot password</button>
        <button className="xc-btn" type="button" disabled={busy} onClick={() => setAuthMode('resend-verification')}>Resend verification</button>
      </form>
    </section>}
  </Landing></div>

  if (lens === 'graph') return <div className="xc"><main className="xc-managed"><div className="xc-managed-inner"><ManagedGraphLens onBack={() => setLens('workspace')} /></div></main></div>
  if (lens === 'timeline') return <div className="xc"><main className="xc-managed"><div className="xc-managed-inner"><ManagedTimelineLens onBack={() => setLens('workspace')} /></div></main></div>

  return <div className="xc"><main className="xc-managed"><div className="xc-managed-inner">
    <header className="xc-managed-head">
      <a className="xc-brand" href="/managed" aria-label="Xibalba Cortex"><img className="xc-managed-logo" src="/cortex-rail-mark.png" alt="" /><b>Xibalba Cortex</b></a>
      <span className="xc-tag">{account.entitlement.plan.name}</span>
      <div className="xc-managed-nav" aria-label="Explore workspace"><button className="xc-btn" onClick={() => setLens('graph')}>Graph</button><button className="xc-btn" onClick={() => setLens('timeline')}>Timeline</button></div>
      <button className="xc-btn" disabled={busy} onClick={() => void act(async () => { await request('logout', { method: 'POST' }, account.csrf_token); setAccount(null); setMemories([]); setNewKey(''); setKeys([]); setQuery('') })}>Sign out</button>
    </header>
    <p className="xc-eyebrow">Managed workspace</p>
    <h1 className="xc-managed-title">{account.account.display_name}’s memory</h1>
    {messages}
    {!account.entitlement.writable && <p className="xc-callout">This workspace is read-only. Your existing memories remain available to read and export. Update billing to resume writes.</p>}
    <section className="xc-win xc-managed-panel" aria-label="Usage and subscription">
      <h2 className="xc-title">Usage · {account.usage.month} UTC</h2>
      <div className="xc-managed-usage">
        <p><b>{(account.counts.memories ?? 0).toLocaleString()}</b> / {account.entitlement.plan.max_memories.toLocaleString()} stored memories</p>
        <p><b>{(account.usage.used.writes ?? 0).toLocaleString()}</b> / {account.entitlement.plan.writes_per_month.toLocaleString()} write requests</p>
        <p><b>{(account.usage.used.retrievals ?? 0).toLocaleString()}</b> / {account.entitlement.plan.retrievals_per_month.toLocaleString()} retrieval requests</p>
      </div>
      <p className="xc-note">Subscription status: {account.entitlement.status}{account.entitlement.cancel_at_period_end ? ' · cancels at the end of the paid period' : ''}</p>
      <div className="xc-managed-actions"><button className="xc-btn" disabled={busy || !catalog?.billing_configured} onClick={() => billing()}>Manage billing</button><button className="xc-btn" disabled={busy} onClick={exportMemories}>Export memories</button></div>
    </section>
    <section className="xc-win xc-managed-panel" aria-label="Memory workspace">
      <h2 className="xc-title">Store and retrieve</h2>
      <form className="xc-managed-form" onSubmit={(event) => {
        event.preventDefault(); const form = event.currentTarget; const content = String(new FormData(form).get('content') || '')
        if (retryWrite.current?.content !== content) retryWrite.current = { content, key: crypto.randomUUID() }
        const write = retryWrite.current
        void act(async () => { await request('memories', { method: 'POST', body: JSON.stringify({ content }), headers: { 'Idempotency-Key': write!.key } }, account.csrf_token); retryWrite.current = null; form.reset(); await refresh(); setNotice('Memory saved with a verifiable event history.') })
      }}>
        <label className="xc-field">Memory<textarea className="xc-input" name="content" required maxLength={16384} rows={4} disabled={!account.entitlement.writable} /></label>
        <button className="xc-btn xc-btn--primary" disabled={busy || !account.entitlement.writable}>Save memory</button>
      </form>
      <form className="xc-managed-search" onSubmit={(event) => { event.preventDefault(); search() }}>
        <label className="xc-field">Search memories<input className="xc-input" value={query} onChange={(event) => setQuery(event.target.value)} maxLength={500} /></label>
        <button className="xc-btn" disabled={busy}>Search / list</button>
      </form>
      <div className="xc-managed-results">{memories.map((memory) => <article key={memory.id}><p className="xc-copy">{memory.content}</p><p className="xc-meta">{memory.id}</p></article>)}</div>
    </section>
    <section className="xc-win xc-managed-panel" aria-label="Agent API keys">
      <h2 className="xc-title">Connect an agent</h2>
      <p className="xc-copy">Bind a key to the agent’s stable <code>did:integrity:…</code> identity. The same DID can use MCP or the SDK; keys expire after 30 days and are shown once.</p>
      <label className="xc-field">Agent DIDs<textarea className="xc-input xc-input--mono" value={agentDids} onChange={(event) => setAgentDids(event.target.value)} placeholder="did:integrity:…" rows={3} required /></label>
      <p className="xc-note">Enter one DID per line or separate them with commas. One key can serve multiple agents on the same device.</p>
      <button className="xc-btn" disabled={busy || !agentDids.trim()} onClick={() => void act(async () => { const ids = [...new Set(agentDids.split(/[\n,]+/).map((value) => value.trim()).filter(Boolean))]; if (ids.length === 0) throw new Error('Enter at least one agent DID'); const result = await request<{ token: string }>('keys', { method: 'POST', body: JSON.stringify({ label: 'agent', agent_ids: ids }) }, account.csrf_token); setNewKey(result.token) })}>Create API key</button>
      <button className="xc-btn" disabled={busy} onClick={() => void act(async () => { setKeys((await request<{keys: typeof keys}>('keys')).keys) })}>Show API keys</button>
      {keys.map((key) => <div className="xc-managed-actions" key={key.id}><span className="xc-note">{key.label.replace(/^managed-api:/, '')} · {key.agent_ids?.length ? `${key.agent_ids.length} agent${key.agent_ids.length === 1 ? '' : 's'}` : 'unbound'} · expires {new Date(key.expires_at).toLocaleDateString()}</span><button className="xc-btn" disabled={busy} onClick={() => void act(async () => { await request('keys/revoke', { method: 'POST', body: JSON.stringify({ id: key.id }) }, account.csrf_token); setKeys(keys.filter((item) => item.id !== key.id)); setNewKey('') })}>Revoke key</button></div>)}
      {newKey && <div><p className="xc-note">Copy this key now; it will disappear when you leave this page.</p><code className="xc-managed-key">{newKey}</code><button className="xc-btn" onClick={() => setNewKey('')}>Hide key</button></div>}
    </section>
    <ManagedAgent0Directory />
    <section aria-labelledby="workspace-plans-title"><h2 className="xc-landing-h2" id="workspace-plans-title">Workspace plans</h2>{cards}{!catalog?.billing_configured && <p className="xc-note xc-managed-note">Paid subscriptions are not available yet.</p>}</section>
  </div></main></div>
}

function ManagedAgent0Directory() {
  const [query, setQuery] = useState('')
  const [agents, setAgents] = useState<Agent0Record[]>([])
  const [selected, setSelected] = useState<Agent0Record | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [name, setName] = useState('Cortex Managed Test Agent')
  const [description, setDescription] = useState('Test ERC-8004 identity registered from managed Cortex with MetaMask on Base Sepolia.')
  const [txHash, setTxHash] = useState('')
  const search = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setMessage('')
    try { const result = await request<Agent0Search>('agent0/search?q=' + encodeURIComponent(query.trim())); setAgents(result.agents); setSelected(null) }
    catch (error) { setMessage(error instanceof Error ? error.message : String(error)) }
    finally { setBusy(false) }
  }
  const register = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setMessage(''); setTxHash('')
    try { const result = await registerAgentWithMetaMask({ name, description }); setSelected(result.record as Agent0Record); setTxHash(result.txHash); setMessage(`Registered ${result.agentId} on Base Sepolia.`) }
    catch (error) { setMessage(error instanceof Error ? error.message : String(error)) }
    finally { setBusy(false) }
  }
  return <section className="xc-win xc-managed-panel xc-managed-agent0" aria-labelledby="managed-agent0-title">
    <p className="xc-eyebrow">External directory · Agent0</p>
    <h2 className="xc-title" id="managed-agent0-title">Search ERC-8004 agents</h2>
    <p className="xc-copy">Managed and local Cortex use the same Agent0/ERC-8004 directory and MetaMask registration flow. Agent0 remains external chain evidence, not workspace authorization.</p>
    <form className="xc-managed-search" onSubmit={search}>
      <label className="xc-field">Search by name<input className="xc-input" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="agent name (optional)" /></label>
      <button className="xc-btn xc-btn--primary" disabled={busy}>Search</button>
    </form>
    <details className="xc-managed-agent0-register">
      <summary className="xc-btn">Register a test identity with MetaMask</summary>
      <form className="xc-managed-form" onSubmit={register}>
        <label className="xc-field">Name<input className="xc-input" value={name} onChange={(event) => setName(event.target.value)} required /></label>
        <label className="xc-field">Description<textarea className="xc-input" value={description} onChange={(event) => setDescription(event.target.value)} rows={3} required /></label>
        <p className="xc-note">MetaMask will switch to Base Sepolia and ask for approval. Gas is paid by the connected wallet.</p>
        <button className="xc-btn xc-btn--primary" disabled={busy}>{busy ? 'Waiting…' : 'Connect & register'}</button>
      </form>
    </details>
    {message && <p className="xc-callout xc-callout--review" role="status">{message}</p>}
    {txHash && <p className="xc-note">Confirmed transaction: <a className="xc-mono" href={`https://sepolia.basescan.org/tx/${txHash}`} target="_blank" rel="noreferrer">{txHash}</a></p>}
    {agents.map((agent) => <button className="xc-managed-agent0-result" type="button" key={String(agent.agentId)} onClick={() => setSelected(agent)}><b>{agent.name || 'Unnamed agent'}</b><span className="xc-mono">{agent.agentId}</span></button>)}
    {selected && <div className="xc-managed-agent0-detail"><p className="xc-eyebrow">On-chain agent record</p><h3 className="xc-title">{selected.name || selected.agentId}</h3><p className="xc-mono">{selected.agentId}</p><dl className="xc-kv"><div><dt>Description</dt><dd>{selected.description || '—'}</dd></div><div><dt>Owner</dt><dd className="xc-mono">{selected.owners?.join(', ') || '—'}</dd></div><div><dt>Wallet</dt><dd className="xc-mono">{selected.walletAddress || '—'}</dd></div><div><dt>Agent URI</dt><dd className="xc-mono">{selected.agentURI || '—'}</dd></div><div><dt>Trust models</dt><dd>{selected.trustModels?.join(', ') || '—'}</dd></div></dl><p className="xc-note">Source: Agent0 / ERC-8004. This record does not grant workspace access.</p></div>}
  </section>
}
