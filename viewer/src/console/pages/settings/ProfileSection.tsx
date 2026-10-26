// Settings → Profile: how this Cortex profile is configured, read-only.
//
// Read-only on purpose. Mode, identity and retention come from config.yaml or environment variables
// and need a restart to change; a web form that pretended to change them would be a silent mock.
// The view carries no filesystem path and no secret: the places the server uses (backup, vault, DAG,
// anchor service) are reported only as configured or not, because the actions that depend on them
// send an id or a hash, never a path.

import { api } from '../../../api'
import { useAsync } from '../../useAsync'
import { IconWarn } from '../../icons'
import { destinationRows, featureRows } from '../../access'
import { asText } from '../../account'

export function ProfileSection() {
  const config = useAsync(() => api.profileConfig(), [])
  if (config.loading) return <p className="xc-note" role="status">Loading…</p>
  if (config.error || !config.data) return <div className="xc-callout xc-callout--conflict" role="alert"><IconWarn />{config.error ?? 'The profile configuration could not be read.'}</div>
  const c = config.data
  return (
    <div className="xc-form xc-settings-form">
      <div className="xc-callout xc-callout--review" role="note">
        <IconWarn />
        <span>Read only. {c.changed_by.charAt(0).toUpperCase() + c.changed_by.slice(1)}.</span>
      </div>

      <section className="xc-win xc-opscard" aria-label="Profile">
        <p className="xc-eyebrow">Profile</p>
        <dl className="xc-kv">
          <div><dt>profile</dt><dd>{c.profile_id}</dd></div>
          <div><dt>mode</dt><dd>{c.mode}</dd></div>
          <div><dt>identity</dt><dd>{c.identity_mode}</dd></div>
          <div><dt>retention tier</dt><dd>{c.retention_tier}</dd></div>
          <div><dt>storage</dt><dd>{c.storage.backend}</dd></div>
          <div><dt>remote inference</dt><dd>{c.remote.configured ? 'configured' : 'not configured'}</dd></div>
        </dl>
      </section>

      <section className="xc-win xc-opscard" aria-label="Where the server writes and reads">
        <p className="xc-eyebrow">Places the server uses</p>
        <ul className="xc-list">
          {destinationRows(c.destinations).map((d) => (
            <li key={d.id} className="xc-listrow">
              <span><b>{d.label}</b> <span className="xc-meta">{d.what}</span></span>
              <span className="xc-tag"><i />{d.word}</span>
            </li>
          ))}
        </ul>
        <p className="xc-note">Paths and addresses are never sent to the browser. Actions that use these places send an id or a hash.</p>
      </section>

      <section className="xc-win xc-opscard" aria-label="Features">
        <p className="xc-eyebrow">Features</p>
        <ul className="xc-list">
          {featureRows(c.features).map((f) => (
            <li key={f.name} className="xc-listrow"><span>{f.name}</span><span className="xc-tag"><i />{f.on ? 'on' : 'off'}</span></li>
          ))}
        </ul>
      </section>

      <section className="xc-win xc-opscard" aria-label="Retrieval, quotas and telemetry">
        <p className="xc-eyebrow">Retrieval, quotas and telemetry</p>
        <dl className="xc-kv">
          {Object.entries(c.retrieval).map(([k, v]) => <div key={`r-${k}`}><dt>retrieval · {k}</dt><dd>{v ? 'on' : 'off'}</dd></div>)}
          {Object.entries(c.quotas).map(([k, v]) => <div key={`q-${k}`}><dt>quota · {k.replace(/_/g, ' ')}</dt><dd>{v === null ? 'unlimited' : asText(v)}</dd></div>)}
          {Object.entries(c.telemetry).map(([k, v]) => <div key={`t-${k}`}><dt>telemetry · {k.replace(/_/g, ' ')}</dt><dd>{asText(v)}</dd></div>)}
        </dl>
      </section>
    </div>
  )
}
