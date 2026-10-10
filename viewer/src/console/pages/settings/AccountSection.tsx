// Settings → Account: who this browser is signed in as, the account's sessions, its recent
// security events, and password change.
//
// These routes exist only for account (cookie) sessions. A bearer credential — the dev proxy, a
// machine token — has no account behind it and /api/auth/me answers "account session not found".
// That is shown as what it is, not as an error, and the actions are not offered.

import { useState } from 'react'
import { accountChangePassword, accountEvents, accountMe, accountRevokeSession, accountSessions } from '../../../api'
import { useAsync } from '../../useAsync'
import { IconWarn } from '../../icons'
import { asText, sessionRows } from '../../account'

export function AccountSection() {
  const [rev, setRev] = useState(0)
  const me = useAsync(() => accountMe(), [rev])
  const signedInAsAccount = Boolean(me.data)
  const sessions = useAsync(() => (signedInAsAccount ? accountSessions() : Promise.resolve({ sessions: [] })), [rev, signedInAsAccount])
  const events = useAsync(() => (signedInAsAccount ? accountEvents() : Promise.resolve({ events: [] })), [rev, signedInAsAccount])

  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<{ tone: 'anchored' | 'conflict'; text: string } | null>(null)

  if (me.loading) return <p className="xc-note" role="status">Loading…</p>

  if (!me.data) {
    const notAccount = me.error === 'account session not found'
    return notAccount ? (
      <div className="xc-callout xc-callout--review" role="status">
        <IconWarn />
        <span>This browser is connected with a token, not an account session (for example the local dev proxy), so there is no account to show. Sign in with an account to manage sessions and your password.</span>
      </div>
    ) : (
      <div className="xc-callout xc-callout--conflict" role="alert"><IconWarn />{me.error}</div>
    )
  }

  const account = me.data.account
  const mismatch = next !== confirm
  const canChange = !busy && current !== '' && next.length > 0 && !mismatch

  const change = async () => {
    setBusy(true)
    setResult(null)
    try {
      await accountChangePassword(current, next)
      setCurrent(''); setNext(''); setConfirm('')
      setResult({ tone: 'anchored', text: 'Password changed.' })
      setRev((n) => n + 1)
    } catch (e) {
      setResult({ tone: 'conflict', text: e instanceof Error ? e.message : String(e) })
    } finally {
      setBusy(false)
    }
  }

  const revoke = async (id: string) => {
    setBusy(true)
    setResult(null)
    try {
      await accountRevokeSession(id)
      setResult({ tone: 'anchored', text: 'Session revoked.' })
      setRev((n) => n + 1)
    } catch (e) {
      setResult({ tone: 'conflict', text: e instanceof Error ? e.message : String(e) })
    } finally {
      setBusy(false)
    }
  }

  const rows = sessionRows(sessions.data?.sessions ?? [])

  return (
    <div className="xc-form xc-settings-form">
      <section className="xc-win xc-opscard" aria-label="Signed in as">
        <p className="xc-eyebrow">Signed in as</p>
        <dl className="xc-kv">
          {Object.entries(account).map(([k, v]) => <div key={k}><dt>{k.replace(/_/g, ' ')}</dt><dd>{asText(v)}</dd></div>)}
          {me.data.session_expires_at && <div><dt>this session expires</dt><dd>{me.data.session_expires_at}</dd></div>}
        </dl>
      </section>

      {result && <div className={`xc-callout xc-callout--${result.tone}`} role={result.tone === 'conflict' ? 'alert' : 'status'}>{result.tone === 'conflict' && <IconWarn />}{result.text}</div>}

      <section className="xc-win xc-opscard" aria-label="Sessions">
        <p className="xc-eyebrow">Sessions</p>
        {sessions.error && <p className="xc-note" role="alert">{sessions.error}</p>}
        {rows.length === 0 ? <p className="xc-note">No sessions are recorded for this account.</p> : (
          <ul className="xc-list">
            {rows.map((r) => (
              <li key={r.id} className="xc-listrow">
                <span><b>{r.label}</b> <span className="xc-meta">created {r.created} · last used {r.lastUsed}</span></span>
                {r.revoked ? <span className="xc-tag"><i />revoked</span> : <button type="button" className="xc-btn xc-btn--danger-quiet" disabled={busy} onClick={() => void revoke(r.id)}>Revoke</button>}
              </li>
            ))}
          </ul>
        )}
      </section>

      <form className="xc-win xc-opscard xc-form" aria-label="Change password" onSubmit={(e) => { e.preventDefault(); void change() }}>
        <p className="xc-eyebrow">Change password</p>
        <label className="xc-field">Current password<input className="xc-input" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} /></label>
        <label className="xc-field">New password<input className="xc-input" type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} /></label>
        <label className="xc-field">Confirm new password<input className="xc-input" type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} aria-invalid={mismatch && confirm !== ''} />
          {mismatch && confirm !== '' && <span className="xc-field-error" role="alert">The two passwords differ.</span>}
        </label>
        <div className="xc-actions-row"><button type="submit" className="xc-btn xc-btn--primary" disabled={!canChange}>{busy ? 'Working…' : 'Change password'}</button></div>
      </form>

      <section className="xc-win xc-opscard" aria-label="Security events">
        <p className="xc-eyebrow">Recent security events</p>
        {events.error && <p className="xc-note" role="alert">{events.error}</p>}
        {(events.data?.events ?? []).length === 0 ? <p className="xc-note">No events recorded.</p> : (
          <ul className="xc-list">
            {(events.data?.events ?? []).map((e, i) => (
              <li key={i} className="xc-listrow"><span><b>{asText(e.event_type)}</b> {e.detail ? <span className="xc-meta">{asText(e.detail)}</span> : null}</span><span className="xc-meta">{asText(e.created_at)}</span></li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
