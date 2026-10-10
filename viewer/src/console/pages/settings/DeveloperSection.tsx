// Settings → Developer: connection facts and the kernel-bridge Guided System Test.
//
// The self-test submits two real UserOperations through the kernel-bridge testbed: one the
// adapter should allow, one that exceeds the kernel's budget and must be denied. If the testbed is
// not deployed on this machine the route answers `ok: false` with the reason; that reason is shown
// exactly, because "not deployed" and "the kernel allowed what it should have denied" are very
// different findings.

import { useState } from 'react'
import { api, getApiBaseUrl, type KernelBridgeDecision, type KernelBridgeSelfTest } from '../../../api'
import { useAsync } from '../../useAsync'
import { IconWarn } from '../../icons'

function Decision({ title, expected, d }: { title: string; expected: 'allow' | 'deny'; d: KernelBridgeDecision }) {
  // success === true is an on-chain allow, false a deny; null means the adapter reported neither
  const got = d.success === true ? 'allow' : d.success === false ? 'deny' : 'unknown'
  const ok = got === expected
  return (
    <section className="xc-win xc-opscard" aria-label={title}>
      <p><b>{title}</b> <span className={`xc-tag ${ok ? 'xc-tag--anchored' : 'xc-tag--conflict'}`}><i />{ok ? `${got} as expected` : `${got}, expected ${expected}`}</span></p>
      <dl className="xc-kv">
        <div><dt>UserOp hash</dt><dd>{d.user_op_hash}</dd></div>
        <div><dt>Gas cost</dt><dd>{d.actual_gas_cost ?? 'not reported'}</dd></div>
        <div><dt>Revert reason</dt><dd>{d.revert_reason_hex ?? 'none'}</dd></div>
      </dl>
      {d.adapter_note && <p className="xc-note">{d.adapter_note}</p>}
    </section>
  )
}

export function DeveloperSection() {
  const health = useAsync(() => fetch(`${getApiBaseUrl()}/healthz`, { credentials: 'include' }).then((r) => (r.ok ? r.json() : Promise.reject(new Error(`healthz ${r.status}`)))), [])
  const [sessionId, setSessionId] = useState('')
  const [record, setRecord] = useState(false)
  const [running, setRunning] = useState(false)
  const [outcome, setOutcome] = useState<KernelBridgeSelfTest | null>(null)
  const [failure, setFailure] = useState<string | null>(null)

  const run = async () => {
    setRunning(true)
    setOutcome(null)
    setFailure(null)
    try {
      setOutcome(await api.kernelBridgeSelfTest(record && sessionId.trim() ? sessionId.trim() : undefined))
    } catch (e) {
      setFailure(e instanceof Error ? e.message : String(e))
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="xc-form xc-settings-form">
      <section className="xc-win xc-opscard" aria-label="Connection">
        <p className="xc-eyebrow">Connection</p>
        <dl className="xc-kv">
          <div><dt>API base</dt><dd>{getApiBaseUrl() || 'this origin'}</dd></div>
          <div><dt>Liveness</dt><dd>{health.loading ? 'checking…' : health.error ? `unreachable — ${health.error}` : String((health.data as { status?: string } | null)?.status ?? 'unknown')}</dd></div>
          <div><dt>Profile</dt><dd>{String((health.data as { profile_id?: string } | null)?.profile_id ?? 'unknown')}</dd></div>
        </dl>
      </section>

      <section className="xc-win xc-opscard xc-form" aria-label="Kernel bridge self-test">
        <p className="xc-eyebrow">Kernel bridge self-test</p>
        <p className="xc-note">Submits two real UserOperations to the kernel-bridge testbed: one within the kernel’s budget (should be allowed) and one beyond it (should be denied). It needs the testbed deployed locally.</p>
        <label className="xc-check xc-settings-row"><input type="checkbox" checked={record} onChange={(e) => setRecord(e.target.checked)} /><span>Also record both verdicts as tool-call events in a session</span></label>
        {record && <label className="xc-field">Session id<input className="xc-input xc-input--mono" value={sessionId} onChange={(e) => setSessionId(e.target.value)} placeholder="an existing session’s id" /></label>}
        <div className="xc-actions-row"><button type="button" className="xc-btn xc-btn--primary" disabled={running || (record && sessionId.trim() === '')} onClick={() => void run()}>{running ? 'Running…' : 'Run self-test'}</button></div>

        {failure && <div className="xc-callout xc-callout--conflict" role="alert"><IconWarn />{failure}</div>}
        {outcome && !outcome.ok && (
          <div className="xc-callout xc-callout--review" role="status"><IconWarn /><span><b>The test could not run.</b> The server reported: <code>{outcome.error}</code></span></div>
        )}
        {outcome && outcome.ok && (
          <>
            <p><span className={`xc-tag ${outcome.passed ? 'xc-tag--anchored' : 'xc-tag--conflict'}`}><i />{outcome.passed ? 'passed' : 'failed'}</span></p>
            <Decision title="Within budget" expected="allow" d={outcome.matched} />
            <Decision title="Beyond the kernel’s budget" expected="deny" d={outcome.kernel_exceeding} />
          </>
        )}
      </section>
    </div>
  )
}
