// Timeline lens: one lane per session, marks for the exchanges and memories we can place in time.
//
// Shares the selection, the facets and the window with the Graph lens. Memories with no timestamp
// signal in the API are not placed: the footer says how many were left out rather than guessing.

import { useMemo } from 'react'
import { useConsole } from './state'
import { buildLanes, isNodeVisible, shortDay, shortStamp, type Lane } from './model'

interface Domain {
  from: number
  to: number
}

const HOUR = 3_600_000
const DAY = 24 * HOUR

function tickStep(span: number): number {
  if (span <= 6 * HOUR) return HOUR
  if (span <= 2 * DAY) return 6 * HOUR
  if (span <= 21 * DAY) return DAY
  return 7 * DAY
}

function ticksFor(domain: Domain): { at: number; label: string }[] {
  const step = tickStep(domain.to - domain.from)
  const out: { at: number; label: string }[] = []
  // day-or-longer ticks align to local midnight; shorter ones to the clock hour
  const align = new Date(domain.from)
  if (step >= DAY) align.setHours(0, 0, 0, 0)
  else align.setMinutes(0, 0, 0)
  for (let t = align.getTime(); t <= domain.to && out.length < 24; t += step) {
    if (t < domain.from) continue
    out.push({ at: t, label: step >= DAY ? shortDay(t) : shortStamp(t).slice(6) })
  }
  return out
}

export function TimelineLens() {
  const { model, facets, window: timeWindow, sessionEnds, memoryInfo, selectedId, select, loading, error, reload } = useConsole()

  const lanes = useMemo<Lane[]>(() => (model ? buildLanes(model, sessionEnds, memoryInfo) : []), [model, sessionEnds, memoryInfo])
  // re-read the clock when the data reloads so an open session's span grows with it
  const now = useMemo(() => (lanes ? Date.now() : 0), [lanes])

  const domain = useMemo<Domain | null>(() => {
    if (timeWindow) return { from: timeWindow.from, to: timeWindow.to }
    if (lanes.length === 0) return null
    let from = Infinity
    let to = -Infinity
    for (const lane of lanes) {
      from = Math.min(from, lane.start)
      to = Math.max(to, lane.end ?? now, ...lane.marks.map((m) => m.time))
    }
    const pad = Math.max(HOUR, (to - from) * 0.03)
    return { from: from - pad, to: to + pad }
  }, [timeWindow, lanes, now])

  const pct = (t: number): number => (domain ? ((t - domain.from) / Math.max(1, domain.to - domain.from)) * 100 : 0)
  const inDomain = (t: number): boolean => (domain ? t >= domain.from && t <= domain.to : false)

  const untimedMemories = useMemo(
    () => (model ? model.nodes.filter((n) => n.cls === 'memory' && n.time === null).length : 0),
    [model],
  )

  if (error && !model) {
    return (
      <section className="xc-win xc-pane xc-canvas-win" role="alert">
        <div className="xc-empty">
          <h3 className="xc-title">Timeline unavailable</h3>
          <p>{error}</p>
          <div><button className="xc-btn" onClick={reload}>Retry</button></div>
        </div>
      </section>
    )
  }

  return (
    <section className="xc-win xc-pane xc-canvas-win" aria-label="Timeline lens">
      <div className="xc-bar">
        <p className="xc-eyebrow">Timeline lens</p>
        <span className="xc-note" aria-live="polite">
          {loading && !model ? 'Loading…' : `${lanes.length} session${lanes.length === 1 ? '' : 's'}`}
          {domain ? ` · ${shortStamp(domain.from)} → ${shortStamp(domain.to)}` : ''}
        </span>
      </div>

      <div className="xc-scroll">
        {!domain || lanes.length === 0 ? (
          <div className="xc-empty">
            <h3 className="xc-title">{loading ? 'Loading sessions…' : 'No sessions to place in time'}</h3>
            {!loading && <p>A lane needs a session with a start time. Sessions appear as agents open them.</p>}
          </div>
        ) : (
          <div className="xc-tl-grid" role="table" aria-label="Sessions on a time axis">
            <div className="xc-tl-head">
              <div>SESSION</div>
              <div className="xc-tl-ticks" aria-hidden="true">
                {ticksFor(domain).filter((t) => pct(t.at) < 94).map((t) => (
                  <span key={t.at} style={{ left: `${pct(t.at)}%` }}>{t.label}</span>
                ))}
              </div>
            </div>

            {lanes.map((lane) => {
              const end = lane.end ?? now
              const left = Math.max(0, pct(lane.start))
              const right = Math.min(100, pct(end))
              const marks = lane.marks.filter((m) => {
                const node = model?.byId.get(m.nodeId)
                return node && facets && isNodeVisible(node, facets, null) && inDomain(m.time)
              })
              const rootAt = lane.root && lane.root.time !== null ? (lane.end ?? lane.marks.at(-1)?.time ?? lane.start) : null
              const selected = selectedId === lane.session.id
              return (
                <div className="xc-lane" key={lane.session.id} data-selected={selected} role="row">
                  <button type="button" className="xc-lane-label" onClick={() => select(lane.session.id)} aria-pressed={selected}>
                    <b title={lane.session.sessionId}>{lane.session.sessionId}</b>
                    <span>
                      {lane.marks.filter((m) => m.cls === 'exchange').length} exchanges ·{' '}
                      {lane.end === null ? 'open' : `${Math.max(1, Math.round((lane.end - lane.start) / 60_000))} min`}
                    </span>
                  </button>
                  <div className="xc-lane-track">
                    {right > left && (
                      <i className="xc-lane-span" data-open={lane.end === null} style={{ left: `${left}%`, width: `${right - left}%` }} />
                    )}
                    {marks.map((m) => (
                      <button
                        key={m.nodeId}
                        type="button"
                        className="xc-mark"
                        data-cls={m.cls}
                        data-selected={selectedId === m.nodeId}
                        style={{ left: `${pct(m.time)}%` }}
                        aria-label={`${m.cls} at ${shortStamp(m.time)}`}
                        title={`${m.cls} · ${shortStamp(m.time)}${m.status ? ` · ${m.status}` : ''}`}
                        onClick={() => select(m.nodeId)}
                      />
                    ))}
                    {lane.root && rootAt !== null && inDomain(rootAt) && (
                      <button
                        type="button"
                        className="xc-mark"
                        data-cls="root"
                        data-valid={lane.root.valid !== false}
                        data-selected={selectedId === lane.root.id}
                        style={{ left: `${pct(rootAt)}%` }}
                        aria-label={`Merkle root, ${lane.root.valid === false ? 'reported invalid' : 'reported valid'} by the server`}
                        title={`Merkle root · server reports ${lane.root.valid === false ? 'INVALID' : 'valid'}`}
                        onClick={() => select(lane.root!.id)}
                      />
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      <div className="xc-bar" style={{ borderTop: '1px solid var(--hairline)', borderBottom: 0 }}>
        <span className="xc-legend-inline xc-note">
          ■ memory · ■ exchange (gray) · ◻ Merkle root (server-reported) ·{' '}
          {untimedMemories > 0
            ? `${untimedMemories} memor${untimedMemories === 1 ? 'y has' : 'ies have'} no timestamp in the API and ${untimedMemories === 1 ? 'is' : 'are'} not placed`
            : 'every memory is placed'}
        </span>
      </div>
    </section>
  )
}
