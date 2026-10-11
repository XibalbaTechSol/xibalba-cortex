// Settings → Access: the credentials that can reach this profile.
//
//   * API tokens: issue one for a script, a worker or a teammate; see which are live; revoke one.
//     The secret is shown exactly once, in the callout that appears right after issuing. Cortex keeps
//     only a hash, so there is no "show again": close the callout and it is gone.
//   * Accounts waiting for approval: sign-ups that cannot sign in until an administrator approves
//     them. Approving lets that person sign in; it grants no agent workspace.
//
// Works for a bearer credential as well as an account session (unlike the Account tab), because
// managing credentials does not depend on being signed in as a person. Whether the caller may do each
// thing is the server's decision: a 403 is shown as "your credential may not", never as a failure.

import { useState, type FormEvent } from 'react'
import { ApiError, api, type IssuedApiToken } from '../../../api'
import { useAsync } from '../../useAsync'
import { IconWarn } from '../../icons'
import { DEFAULT_LIFETIME_HOURS, LIFETIMES, adminRefusal, describeRole, tokenRows, validateTokenLabel } from '../../access'

const statusOf = (e: unknown) => (e instanceof ApiError ? e.status : undefined)
const messageOf = (e: unknown) => (e instanceof Error ? e.message : String(e))

export function AccessSection() {
  const [rev, setRev] = useState(0)
  const tokens = useAsync(() => api.authTokens(), [rev])
  const pending = useAsync(() => api.pendingAccounts(), [rev])

  const [label, setLabel] = useState('')
  const [role, setRole] = useState('')
  const [hours, setHours] = useState(DEFAULT_LIFETIME_HOURS)
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const [issued, setIssued] = useState<IssuedApiToken | null>(null)
  const [copied, setCopied] = useState(false)
  const [confirmRevoke, setConfirmRevoke] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const grantable = tokens.data?.grantable_roles ?? []
  const chosenRole = role || grantable[0] || ''
  const rows = tokenRows(tokens.data?.tokens ?? [])

  const issue = async (event: FormEvent) => {
    event.preventDefault()
    const bad = validateTokenLabel(label)
    if (bad) { setProblem(bad); return }
    setBusy(true); setProblem(null); setNotice(null); setCopied(false)
    try {
      setIssued(await api.issueAuthToken({ label: label.trim(), role: chosenRole, ttl_hours: hours }))
      setLabel('')
      setRev((n) => n + 1)
    } catch (e) {
      setProblem(adminRefusal(statusOf(e), messageOf(e)))
    } finally {
      setBusy(false)
    }
  }

  const copy = async () => {
    if (!issued) return
    try { await navigator.clipboard.writeText(issued.token); setCopied(true) } catch { setCopied(false) }
  }

  const revoke = async (id: string) => {
    setBusy(true); setProblem(null); setNotice(null)
    try {
      await api.revokeAuthToken(id)
      setNotice('Token revoked. It stopped working immediately.')
      setConfirmRevoke(null)
      setRev((n) => n + 1)
    } catch (e) {
      setProblem(adminRefusal(statusOf(e), messageOf(e)))
      setConfirmRevoke(null)
    } finally {
      setBusy(false)
    }
  }

  const approve = async (email: string) => {
    setBusy(true); setProblem(null); setNotice(null)
    try {
      await api.approveAccount(email)
      setNotice(`${email} can now sign in.`)
      setRev((n) => n + 1)
    } catch (e) {
      setProblem(adminRefusal(statusOf(e), messageOf(e)))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="xc-form xc-settings-form">
      {problem && <div className="xc-callout xc-callout--conflict" role="alert"><IconWarn />{problem}</div>}
      {notice && <div className="xc-callout xc-callout--anchored" role="status">{notice}</div>}

      {issued && (
        <section className="xc-win xc-opscard" aria-label="New token">
          <p className="xc-eyebrow">New token · shown once</p>
          <p className="xc-note">Copy it now. Cortex stores only a hash of it, so it cannot be shown again. Anyone who has it can act as <b>{issued.record?.label ?? 'this token'}</b> until it is revoked or ends.</p>
          <code className="xc-mono xc-secret" aria-label="Token secret">{issued.token}</code>
          <div className="xc-actions-row">
            <button type="button" className="xc-btn xc-btn--primary" onClick={() => void copy()}>{copied ? 'Copied' : 'Copy token'}</button>
            <button type="button" className="xc-btn" onClick={() => { setIssued(null); setCopied(false) }}>I have stored it</button>
          </div>
        </section>
      )}

      <section className="xc-win xc-opscard" aria-label="API tokens">
        <p className="xc-eyebrow">API tokens</p>
        {tokens.error && <div className="xc-callout xc-callout--review" role="status"><IconWarn />{adminRefusal(undefined, tokens.error)}</div>}
        {tokens.loading ? <p className="xc-note" role="status">Loading…</p> : rows.length === 0 ? <p className="xc-note">No API tokens have been issued for this profile.</p> : (
          <ul className="xc-list">
            {rows.map((r) => (
              <li key={r.id} className="xc-listrow">
                <span>
                  <b>{r.label}</b> <span className="xc-tag"><i />{r.stateWord}</span>
                  <br /><span className="xc-meta">{r.role} · {r.scopes}</span>
                  <br /><span className="xc-meta">created {r.created} · {r.lastUsed} · {r.ends}</span>
                </span>
                {r.canRevoke && (confirmRevoke === r.id
                  ? <span className="xc-actions-row">
                      <button type="button" className="xc-btn xc-btn--danger-quiet" disabled={busy} onClick={() => void revoke(r.id)}>Confirm revoke</button>
                      <button type="button" className="xc-btn" onClick={() => setConfirmRevoke(null)}>Keep</button>
                    </span>
                  : <button type="button" className="xc-btn xc-btn--danger-quiet" disabled={busy} onClick={() => setConfirmRevoke(r.id)}>Revoke</button>)}
              </li>
            ))}
          </ul>
        )}
      </section>

      <form className="xc-win xc-opscard xc-form" aria-label="Issue a token" onSubmit={(e) => void issue(e)}>
        <p className="xc-eyebrow">Issue a token</p>
        {grantable.length === 0 && !tokens.loading
          ? <p className="xc-note">This credential may not issue tokens. An operator or administrator can.</p>
          : <>
              <label className="xc-field">Label<input className="xc-input" value={label} onChange={(e) => setLabel(e.target.value)} placeholder="ingest bot, laptop script…" maxLength={80} /></label>
              <label className="xc-field">Role
                <select className="xc-input" value={chosenRole} onChange={(e) => setRole(e.target.value)}>
                  {grantable.map((r) => <option key={r} value={r}>{r}</option>)}
                </select>
                <span className="xc-note">{describeRole(chosenRole)}</span>
              </label>
              <label className="xc-field">Lasts
                <select className="xc-input" value={hours} onChange={(e) => setHours(Number(e.target.value))}>
                  {LIFETIMES.map((l) => <option key={l.hours} value={l.hours}>{l.label}</option>)}
                </select>
                <span className="xc-note">Every token ends. Issue a new one before it does.</span>
              </label>
              <div className="xc-actions-row"><button type="submit" className="xc-btn xc-btn--primary" disabled={busy || !chosenRole}>{busy ? 'Working…' : 'Issue token'}</button></div>
            </>}
      </form>

      <section className="xc-win xc-opscard" aria-label="Accounts waiting for approval">
        <p className="xc-eyebrow">Accounts waiting for approval</p>
        {pending.error ? (
          <p className="xc-note" role="status">{statusText(pending.error)}</p>
        ) : pending.loading ? <p className="xc-note" role="status">Loading…</p> : (pending.data?.accounts ?? []).length === 0 ? (
          <p className="xc-note">No accounts are waiting.</p>
        ) : (
          <ul className="xc-list">
            {(pending.data?.accounts ?? []).map((a) => (
              <li key={a.id} className="xc-listrow">
                <span><b>{a.display_name}</b> <span className="xc-meta">{a.email} · requested {a.created_at.slice(0, 10)}{a.email_verified ? '' : ' · email not verified'}</span></span>
                <button type="button" className="xc-btn" disabled={busy} onClick={() => void approve(a.email)}>Approve</button>
              </li>
            ))}
          </ul>
        )}
        <p className="xc-note">Approving lets that person sign in. It does not give them an agent workspace.</p>
      </section>
    </div>
  )
}

/** The pending list is administrator-only; for anyone else say that, rather than showing a failure. */
function statusText(message: string): string {
  return /admin credential is required/i.test(message) ? 'Only an administrator can see and approve accounts waiting for approval.' : message
}
