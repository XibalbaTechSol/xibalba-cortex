// Timeline lens: one lane per session, marks for the exchanges and memories we can place in time.
//
// Shares the selection, the facets and the window with the Graph lens. Memories with no timestamp
// signal in the API are not placed: the footer says how many were left out rather than guessing.

import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent, type KeyboardEvent as ReactKeyboardEvent } from 'react'
import { useConsole } from './state'
import { describeIntervention, interventions, interventionsForSession } from './runtime'
import { buildLanes, isNodeVisible, markRows, shortDay, shortStamp, thinTicks, type Lane } from './model'

/** `.xc-mark` is 10px wide; two closer than this on screen would overlap. */
const MARK_PX = 10

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
  const { model, facets, window: timeWindow, sessionEnds, memoryInfo, selectedId, select, setWindow, loading, error, reload, invocations } = useConsole()
  // policy denials and asks, drawn as marks on the lane of the session they happened in
  const policyStops = useMemo(() => interventions(invocations), [invocations])

  // the axis width decides how many date labels fit, so measure it
  const axisRef = useRef<HTMLDivElement>(null)
  const [axisPx, setAxisPx] = useState(0)
  useEffect(() => {
    const el = axisRef.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(() => setAxisPx(el.clientWidth))
    ro.observe(el)
    setAxisPx(el.clientWidth)
    return () => ro.disconnect()
  })

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

  const gesture = useRef<{ pointer: number; x: number; left: number; width: number; domain: Domain; anchor: number; lane?: string; moved: boolean } | null>(null)
  const [cursor, setCursor] = useState<number | null>(null)
  const [brush, setBrush] = useState<{ from: number; to: number } | null>(null)

  const nearest = (at: number, laneId?: string) => {
    const marks = lanes.filter((lane) => !laneId || lane.session.id === laneId).flatMap((lane) => lane.marks)
      .filter((mark) => {
        const node = model?.byId.get(mark.nodeId)
        return node && facets && isNodeVisible(node, facets, null) && inDomain(mark.time)
      })
    const mark = marks.reduce<(typeof marks)[number] | null>((best, next) =>
      !best || Math.abs(next.time - at) < Math.abs(best.time - at) ? next : best, null)
    if (mark) select(mark.nodeId)
  }
  const gestureTime = (x: number, g: NonNullable<typeof gesture.current>) =>
    Math.round(g.domain.from + Math.max(0, Math.min(1, (x - g.left) / g.width)) * (g.domain.to - g.domain.from))
  const cancelGesture = () => { gesture.current = null; setBrush(null) }
  const onDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    const rect = axisRef.current?.getBoundingClientRect()
    if (!domain || !rect?.width || e.button !== 0 || !e.isPrimary || e.clientX < rect.left ||
        (e.target as HTMLElement).closest('button')) return
    const g = { pointer: e.pointerId, x: e.clientX, left: rect.left, width: rect.width,
      domain: { ...domain }, anchor: 0, moved: false,
      lane: (e.target as HTMLElement).closest<HTMLElement>('.xc-lane-track')?.dataset.lane }
    g.anchor = gestureTime(e.clientX, g)
    gesture.current = g
    setCursor(g.anchor)
    axisRef.current?.focus({ preventScroll: true })
    e.currentTarget.setPointerCapture(e.pointerId)
    e.preventDefault()
  }
  const onMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    const g = gesture.current
    if (!g || e.pointerId !== g.pointer) return
    const at = gestureTime(e.clientX, g)
    setCursor(at)
    if (Math.abs(e.clientX - g.x) >= 4) g.moved = true
    if (g.moved) setBrush({ from: Math.min(g.anchor, at), to: Math.max(g.anchor, at) })
  }
  const onUp = (e: ReactPointerEvent<HTMLDivElement>) => {
    const g = gesture.current
    if (!g || e.pointerId !== g.pointer) return
    const at = gestureTime(e.clientX, g)
    cancelGesture()
    if (g.moved && at !== g.anchor) setWindow({ from: Math.min(g.anchor, at), to: Math.max(g.anchor, at) }, 'custom')
    else nearest(at, g.lane)
    if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId)
  }
  const onKey = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    if (!domain) return
    if (e.key === 'Escape') { const active = gesture.current; cancelGesture(); if (!active) setWindow(null); setCursor(null); e.preventDefault(); return }
    let at = cursor ?? domain.from
    if (e.key === 'ArrowRight') at += (domain.to - domain.from) / 100
    else if (e.key === 'ArrowLeft') at -= (domain.to - domain.from) / 100
    else if (e.key === 'Home') at = domain.from
    else if (e.key === 'End') at = domain.to
    else if (e.key !== 'Enter' && e.key !== ' ') return
    e.preventDefault()
    at = Math.round(Math.max(domain.from, Math.min(domain.to, at)))
    setCursor(at)
    nearest(at)
  }
  const cursorAt = domain && cursor !== null ? Math.max(domain.from, Math.min(domain.to, cursor)) : null

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
      <div className="xc-scroll">
        {!domain || lanes.length === 0 ? (
          <div className="xc-empty">
            <h3 className="xc-title">{loading ? 'Loading sessions…' : 'No sessions to place in time'}</h3>
            {!loading && <p>A lane needs a session with a start time. Sessions appear as agents open them.</p>}
          </div>
        ) : (
          <div className="xc-tl-grid" role="table" aria-label="Sessions on a time axis"
            onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp}
            onPointerCancel={cancelGesture} onLostPointerCapture={cancelGesture}
          >
            {/* The axis rules, drawn the full height of the plotting field rather than only
                through the 31px head, so the area below the last lane reads as unused time on a
                chart instead of as empty frame. Decoration only -- the head still carries the
                labels and the accessible axis. */}
            <div className="xc-tl-rules" aria-hidden="true">
              {thinTicks(ticksFor(domain).filter((t) => pct(t.at) < 94), axisPx).map((t) => (
                <span key={t.at} style={{ left: `${pct(t.at)}%` }} />
              ))}
            </div>
            <div className="xc-tl-feedback" aria-hidden="true">
              {brush && <div className="xc-tl-brush" style={{ left: `${pct(brush.from)}%`, width: `${pct(brush.to) - pct(brush.from)}%` }} />}
              {cursorAt !== null && <div className="xc-tl-cursor" style={{ left: `${pct(cursorAt)}%` }} />}
            </div>
            <div className="xc-tl-head">
              <div className="xc-tl-caption"><span>SESSION</span>{timeWindow && <button type="button" className="xc-btn" onClick={() => { cancelGesture(); setWindow(null); setCursor(null) }}>All time</button>}</div>
              <div className="xc-tl-ticks" ref={axisRef} role="slider" tabIndex={0}
                aria-label="Timeline time" aria-orientation="horizontal"
                aria-valuemin={Math.round(domain.from)} aria-valuemax={Math.round(domain.to)}
                aria-valuenow={Math.round(cursorAt ?? domain.from)} aria-valuetext={shortStamp(cursorAt ?? domain.from)}
                aria-describedby="timeline-help" onKeyDown={onKey}
              >
                {thinTicks(ticksFor(domain).filter((t) => pct(t.at) < 94), axisPx).map((t) => (
                  <span key={t.at} aria-hidden="true" style={{ left: `${pct(t.at)}%` }}>{t.label}</span>
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
              const stops = interventionsForSession(policyStops, lane.session.sessionId).filter((i) => inDomain(i.at))
              /* Marks are placed by time alone, so several written seconds apart land on the same
                 pixel and the topmost one swallows the others' clicks. `markRows` stacks them
                 across the lane instead of moving them along it, which would misreport when they
                 happened. It needs real pixels, which is what `axisPx` already measures for the
                 tick thinning. */
              const rows = markRows(marks.map((m) => (pct(m.time) / 100) * axisPx), MARK_PX)
              const rootAt = lane.root && lane.root.time !== null ? (lane.end ?? lane.marks.at(-1)?.time ?? lane.start) : null
              const selected = !lane.synthetic && selectedId === lane.session.id
              return (
                <div className="xc-lane" key={lane.session.id} data-selected={selected} role="row">
                  <button
                    type="button"
                    className="xc-lane-label"
                    onClick={lane.synthetic ? undefined : () => select(lane.session.id)}
                    aria-pressed={lane.synthetic ? undefined : selected}
                    disabled={lane.synthetic}
                    title={lane.synthetic ? 'Memories written outside any session, placed by when the store recorded them' : undefined}
                  >
                    <b title={lane.session.sessionId}>{lane.synthetic ? 'No session' : lane.session.sessionId}</b>
                    <span>
                      {lane.synthetic
                        ? `${lane.marks.length} memor${lane.marks.length === 1 ? 'y' : 'ies'}`
                        : `${lane.marks.filter((m) => m.cls === 'exchange').length} exchanges · ${lane.end === null ? 'open' : `${Math.max(1, Math.round((lane.end - lane.start) / 60_000))} min`}`}
                    </span>
                  </button>
                  <div className="xc-lane-track" data-lane={lane.session.id}>
                    {right > left && (
                      <i className="xc-lane-span" data-open={lane.end === null} style={{ left: `${left}%`, width: `${right - left}%` }} />
                    )}
                    {marks.map((m, i) => (
                      <button
                        key={m.nodeId}
                        type="button"
                        className="xc-mark"
                        data-cls={m.cls}
                        data-selected={selectedId === m.nodeId}
                        data-row={rows[i]}
                        style={{ left: `${pct(m.time)}%` }}
                        aria-label={`${m.cls} at ${shortStamp(m.time)}`}
                        title={`${m.cls} · ${shortStamp(m.time)}${m.status ? ` · ${m.status}` : ''}`}
                        onClick={() => select(m.nodeId)}
                      />
                    ))}
                    {stops.map((i) => (
                      <button
                        key={i.invocationId}
                        type="button"
                        className="xc-mark"
                        data-cls={i.verdict}
                        style={{ left: `${pct(i.at)}%` }}
                        aria-label={`${describeIntervention(i)} at ${shortStamp(i.at)}`}
                        title={`${describeIntervention(i)} · ${shortStamp(i.at)}`}
                        onClick={() => select(lane.session.id)}
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

      {/* The session count and the span it covers used to sit in a toolbar strip of their own
          under the workspace header. They are a caption, not a control, and the lens already
          has a caption strip at its foot -- so they join it, and the lens keeps that row. */}
      <div className="xc-bar" style={{ borderTop: '1px solid var(--hairline)', borderBottom: 0 }}>
        <span className="xc-note" aria-live="polite">
          {loading && !model ? 'Loading…' : `${lanes.length} session${lanes.length === 1 ? '' : 's'}`}
          {domain ? ` · ${shortStamp(domain.from)} → ${shortStamp(domain.to)}` : ''}
        </span>
        <span className="xc-note" id="timeline-help">Click to inspect · drag to select time · arrow keys to scrub</span>
        {cursorAt !== null && <span className="xc-note">{shortStamp(cursorAt)}</span>}
        <span className="xc-note" aria-hidden="true">·</span>
        <span className="xc-legend-inline xc-note">
          ■ memory · ■ exchange (gray) · ◻ Merkle root (server-reported) · ▮ denied by policy · ▯ asked for approval ·{' '}
          {untimedMemories > 0
            ? `${untimedMemories} memor${untimedMemories === 1 ? 'y has' : 'ies have'} no timestamp in the API and ${untimedMemories === 1 ? 'is' : 'are'} not placed`
            : 'every memory is placed'}
        </span>
      </div>
    </section>
  )
}
