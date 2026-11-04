// Device pairing authorization screen.
// Displayed when an agent harness (e.g. Claude Desktop, Cursor) or CLI requests
// access to the Cortex Cloud workspace via the browser-mediated pairing flow.

import { useEffect, useState } from 'react'
import { approveDevicePairing, getDevicePairInfo, type DevicePairInfo } from '../api'
import { IconArrowRight, IconCheck, IconIntegrity, IconLock } from './icons'

export function DevicePair({
  code,
  onDone,
}: {
  code: string
  onDone: () => void
}) {
  const [pairInfo, setPairInfo] = useState<DevicePairInfo | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [approved, setApproved] = useState(false)

  useEffect(() => {
    if (!code) {
      setError('Missing device pairing code in URL.')
      setLoading(false)
      return
    }
    getDevicePairInfo(code)
      .then((info) => {
        setPairInfo(info)
        if (info.status === 'approved') setApproved(true)
        else if (info.status === 'expired') setError('This pairing request has expired. Please restart pairing from your agent.')
      })
      .catch((e) => {
        setError(e instanceof Error ? e.message : 'Pairing request not found')
      })
      .finally(() => setLoading(false))
  }, [code])

  const handleApprove = async () => {
    if (!code) return
    setBusy(true)
    setError('')
    try {
      const res = await approveDevicePairing(code)
      setApproved(true)
      // If a local loopback callback URL was provided, notify the local MCP listener immediately
      if (res.callback_url) {
        try {
          const callbackTarget = new URL(res.callback_url)
          callbackTarget.searchParams.set('token', res.token)
          callbackTarget.searchParams.set('api_url', window.location.origin)
          callbackTarget.searchParams.set('device_id', res.device_id)
          callbackTarget.searchParams.set('agent_did', res.agent_did)
          fetch(callbackTarget.toString(), { mode: 'no-cors' }).catch(() => {})
        } catch {
          // loopback callback is best-effort; polling fallback exists
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Authorization failed')
    } finally {
      setBusy(false)
    }
  };

  return (
    <main className="xc-auth">
      <section className="xc-auth-story">
        <a className="xc-brand" href="#" aria-label="Xibalba Cortex" onClick={(e) => e.preventDefault()}>
          <img className="xc-brand-lockup" src="/cortex-lockup-hero.png" width={300} height={279} alt="" />
        </a>
        <div className="xc-auth-story-body">
          <p className="xc-eyebrow">Zero-Trust Agent Pairing</p>
          <h1>Connect your agent<br />to Cortex Cloud</h1>
          <p>Authorize an agent running on your physical or virtual device to interact with your verifiable memory graph.</p>
        </div>
        <aside>
          <IconIntegrity />
          <span>
            <b>Local cryptographic identity</b>
            <small>Your agent signs exchanges locally with its Ed25519 key. Private keys never leave your device.</small>
          </span>
        </aside>
      </section>

      <section className="xc-auth-formwrap">
        <div className="xc-auth-form">
          <span className="xc-lock" aria-hidden="true">
            {approved ? <IconCheck /> : <IconLock />}
          </span>

          <h2 className="xc-auth-title">
            {approved ? 'Agent connected' : 'Authorize agent'}
          </h2>

          <p className="xc-auth-lede">
            {approved
              ? `Agent "${pairInfo?.agent_name || 'default'}" on ${pairInfo?.device_name || 'your device'} is now authorized.`
              : 'An agent harness on your device is requesting access to your Cortex memory workspace.'}
          </p>

          {loading && <p className="xc-note">Loading pairing request…</p>}
          {error && <div className="xc-callout xc-callout--conflict" role="alert">{error}</div>}

          {!loading && !error && !approved && pairInfo && (
            <>
              <div className="xc-pair-details">
                <div className="xc-pair-row">
                  <span className="xc-pair-label">Device</span>
                  <span className="xc-pair-val"><b>{pairInfo.device_name}</b> <small className="xc-dim">({pairInfo.device_id})</small></span>
                </div>
                <div className="xc-pair-row">
                  <span className="xc-pair-label">Agent name</span>
                  <span className="xc-pair-val">{pairInfo.agent_name}</span>
                </div>
                <div className="xc-pair-row">
                  <span className="xc-pair-label">Agent DID</span>
                  <span className="xc-pair-val xc-mono" title={pairInfo.agent_did}>
                    {pairInfo.agent_did.slice(0, 24)}…{pairInfo.agent_did.slice(-8)}
                  </span>
                </div>
                <div className="xc-pair-row">
                  <span className="xc-pair-label">Scopes</span>
                  <span className="xc-pair-val">memory:read, memory:write</span>
                </div>
              </div>

              <button
                className="xc-btn xc-btn--primary xc-auth-submit"
                type="button"
                onClick={handleApprove}
                disabled={busy}
              >
                {busy ? 'Authorizing…' : 'Authorize agent'} <IconArrowRight />
              </button>

              <button
                type="button"
                className="xc-link xc-auth-forgot"
                onClick={onDone}
                disabled={busy}
              >
                Cancel
              </button>
            </>
          )}

          {approved && (
            <>
              <div className="xc-callout xc-callout--anchored" role="status">
                Your agent is now securely connected to your cloud memory. You can close this tab and start interacting with your agent in Claude Desktop, Cursor, or your harness.
              </div>
              <button
                className="xc-btn xc-btn--primary xc-auth-submit"
                type="button"
                onClick={onDone}
              >
                Go to Workspace <IconArrowRight />
              </button>
            </>
          )}

          <small className="xc-auth-note"><IconLock /> Scoped tenant token with local Ed25519 DID</small>
        </div>
      </section>
    </main>
  )
}
