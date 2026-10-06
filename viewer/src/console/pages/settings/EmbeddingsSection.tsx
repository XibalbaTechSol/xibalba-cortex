// Settings → Embeddings: which vector models are registered and how much of the store each
// covers. Read-only: models are registered by the embedding worker (`xibalba-cortex-embedding-worker`),
// not from the browser, and nothing here implies otherwise.

import { api } from '../../../api'
import { useAsync } from '../../useAsync'
import { describeCoverage } from '../../ops'
import { IconWarn } from '../../icons'

const stateTone = (s: string) => (s === 'active' ? 'xc-tag--anchored' : s === 'failed' ? 'xc-tag--conflict' : 'xc-tag--review')

export function EmbeddingsSection() {
  const models = useAsync(() => api.embeddingModels(), [])
  const ops = useAsync(() => api.operations(), [])
  const coverage = ops.data ? describeCoverage(ops.data.embedding_coverage) : null

  if (models.error) return <div className="xc-callout xc-callout--conflict" role="alert"><IconWarn />{models.error}</div>
  if (models.loading) return <p className="xc-note" role="status">Loading…</p>

  return (
    <div className="xc-form xc-settings-form">
      <p className="xc-note">Vector models the store has registered. Hybrid retrieval uses the active one. Registering or switching a model is done by the embedding worker, not from here.</p>

      {coverage && ops.data && (
        <section className="xc-win xc-opscard" aria-label="Coverage of the active model">
          <p className="xc-eyebrow">Coverage of the active model</p>
          <p><span className={`xc-tag xc-tag--${coverage.tone === 'ok' ? 'anchored' : coverage.tone === 'conflict' ? 'conflict' : coverage.tone === 'review' ? 'review' : ''}`}><i />{coverage.percent}</span> <span className="xc-meta">{coverage.summary}</span></p>
        </section>
      )}

      {(models.data ?? []).length === 0 ? (
        <p className="xc-note">No embedding model is registered yet.</p>
      ) : (
        <div className="xc-modellist">
          {(models.data ?? []).map((m) => (
            <section key={m.model_key} className="xc-win xc-opscard" aria-label={m.model_id}>
              <p><b>{m.model_id}</b> <span className="xc-meta">revision {m.revision}</span> <span className={`xc-tag ${stateTone(m.state)}`}><i />{m.state}</span></p>
              <dl className="xc-kv">
                <div><dt>Dimension</dt><dd>{m.dimension}</dd></div>
                <div><dt>Distance</dt><dd>{m.distance_metric}{m.normalize ? ', normalised' : ''}</dd></div>
                <div><dt>Availability</dt><dd>{m.availability}{m.availability_detail ? ` — ${m.availability_detail}` : ''}</dd></div>
                <div><dt>Vector table</dt><dd>{m.vector_table}</dd></div>
                <div><dt>Registered</dt><dd>{m.registered_at}</dd></div>
                <div><dt>Last checked</dt><dd>{m.checked_at ?? 'never'}</dd></div>
              </dl>
            </section>
          ))}
        </div>
      )}
    </div>
  )
}
