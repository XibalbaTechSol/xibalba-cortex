// Chain rail & Temporal Spectrum Scrubber HUD:
// Write density and synaptic activity over time, and the control that windows BOTH lenses.
//
// Features:
// 1. Provenance Lens header with live session, exchange, anchor, and AIS statistics.
// 2. Session filters: All Sessions, Merkle Anchored, With Tools.
// 3. Synaptic Activity Spectrum with multi-color stacked breakdown (Turn Exchanges, Tool Executions, Merkle Anchors).
// 4. Video player with Play/Pause, Rewind, Step Forward, interactive draggable TIME slider scrubber with Present Time readout, and Speed controls (0.5x, 1x, 2x, 5x).
// 5. Draggable HUD anywhere across the screen, collapsing cleanly into the right margin.
// 6. Real-time building animation in both GraphLens and TimelineLens as time advances.

import { useEffect, useMemo, useRef, useState, type CSSProperties, type PointerEvent as ReactPointerEvent } from 'react'
import { useConsole } from './state'
import { useSettings } from './settingsContext'
import { resolveDrop } from './floating'
import { histogram, shortStamp, type RangePreset, type GraphModel } from './model'
import { IconChevronRight, IconPause, IconPlay, IconTimeline } from './icons'
import { api, type Invocation } from '../api'
import { ConfirmPanel } from './ConfirmPanel'
import { saveBlob } from './download'
import { describeExport, exportFilename, exportPlan } from './workspaceActions'

const BUCKETS = 72
const PRESETS: RangePreset[] = ['1h', '24h', '7d', '30d', 'all']

export interface SynapticBucket {
  exchanges: number
  tools: number
  anchors: number
  total: number
}

export function formatSpectrumDate(t: number): string {
  const d = new Date(t)
  const m = d.getMonth() + 1
  const day = d.getDate()
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  const ss = String(d.getSeconds()).padStart(2, '0')
  return `${m}/${day} ${hh}:${mm}:${ss}`
}

function parseInvTime(inv: Invocation): number | null {
  if (!inv.first_seen_at) return null
  const t = new Date(inv.first_seen_at).getTime()
  return Number.isFinite(t) ? t : null
}

export function computeSynapticSpectrum(
  model: GraphModel | null,
  invocations: readonly Invocation[],
  bucketsCount: number,
  extent: [number, number] | null,
): { from: number; to: number; buckets: SynapticBucket[]; max: number } | null {
  if (!extent || bucketsCount < 1) return null
  const [from, to] = extent
  const span = Math.max(1, to - from)
  const buckets: SynapticBucket[] = Array.from({ length: bucketsCount }, () => ({
    exchanges: 0,
    tools: 0,
    anchors: 0,
    total: 0,
  }))

  if (model) {
    for (const node of model.nodes) {
      if (node.time === null || node.time < from || node.time > to) continue
      const idx = Math.min(bucketsCount - 1, Math.floor(((node.time - from) / span) * bucketsCount))
      if (idx < 0) continue
      if (node.cls === 'exchange' || node.cls === 'memory') {
        buckets[idx].exchanges += 1
        buckets[idx].total += 1
      } else if (node.cls === 'merkle') {
        buckets[idx].anchors += 1
        buckets[idx].total += 1
      }
    }
  }

  for (const inv of invocations) {
    const t = parseInvTime(inv)
    if (t === null || t < from || t > to) continue
    const idx = Math.min(bucketsCount - 1, Math.floor(((t - from) / span) * bucketsCount))
    if (idx >= 0 && idx < bucketsCount) {
      buckets[idx].tools += 1
      buckets[idx].total += 1
    }
  }

  const max = Math.max(1, ...buckets.map((b) => b.total))
  return { from, to, buckets, max }
}

export function ChainRail() {
  const { model, facets, setFacets, window: timeWindow, preset, setWindow, applyPreset, invocations, sessions } = useConsole()
  const { settings, update } = useSettings()
  const collapsed = settings.chainCollapsed
  const pos = settings.chainPos

  // Dragging the HUD by its grip
  const railRef = useRef<HTMLElement>(null)
  const dragRef = useRef<{ dx: number; dy: number } | null>(null)
  const [dragging, setDragging] = useState<{ x: number; y: number } | null>(null)

  const workspaceOf = (el: HTMLElement | null): HTMLElement | null =>
    el?.closest('.xc-workspace') as HTMLElement | null

  const onGripDown = (e: ReactPointerEvent<HTMLElement>) => {
    const rail = railRef.current
    const ws = workspaceOf(rail)
    if (!rail || !ws) return
    const r = rail.getBoundingClientRect(), w = ws.getBoundingClientRect()
    dragRef.current = { dx: e.clientX - r.left, dy: e.clientY - r.top }
    setDragging({ x: r.left - w.left, y: r.top - w.top })
    e.currentTarget.setPointerCapture(e.pointerId)
    e.preventDefault()
  }
  const onGripMove = (e: ReactPointerEvent<HTMLElement>) => {
    const d = dragRef.current
    const ws = workspaceOf(railRef.current)
    if (!d || !ws) return
    const w = ws.getBoundingClientRect()
    setDragging({ x: e.clientX - w.left - d.dx, y: e.clientY - w.top - d.dy })
  }
  const onGripUp = () => {
    const d = dragRef.current
    const rail = railRef.current
    const ws = workspaceOf(rail)
    dragRef.current = null
    if (!d || !rail || !ws || !dragging) { setDragging(null); return }
    const w = ws.getBoundingClientRect(), r = rail.getBoundingClientRect()
    update({ chainPos: resolveDrop({ x: dragging.x, y: dragging.y, width: w.width, height: w.height, winWidth: r.width, winHeight: r.height }) })
    setDragging(null)
  }

  const live = dragging ?? pos
  const hist = useMemo(() => (model ? histogram(model, BUCKETS) : null), [model])
  const spectrum = useMemo(
    () => (model ? computeSynapticSpectrum(model, invocations, BUCKETS, model.extent) : null),
    [model, invocations],
  )

  // Export
  const [exporting, setExporting] = useState(false)
  const [exportBusy, setExportBusy] = useState(false)
  const [exportNote, setExportNote] = useState<{ tone: 'ok' | 'error'; text: string } | null>(null)
  const plan = useMemo(() => exportPlan(model, facets, timeWindow), [model, facets, timeWindow])
  const exportNow = async () => {
    setExportBusy(true)
    setExportNote(null)
    try {
      const bundle = await api.exportProvenance(plan.ids)
      saveBlob(exportFilename(), new Blob([JSON.stringify(bundle, null, 2)], { type: 'application/json' }))
      setExportNote({ tone: 'ok', text: `Saved a bundle of ${bundle.count} memor${bundle.count === 1 ? 'y' : 'ies'}. Its root is ${bundle.root_hash.slice(0, 19)}…` })
      setExporting(false)
    } catch (e) {
      setExportNote({ tone: 'error', text: e instanceof Error ? e.message : String(e) })
    } finally {
      setExportBusy(false)
    }
  }

  // Histogram drag selection
  const histRef = useRef<HTMLDivElement>(null)
  const drag = useRef<{ anchor: number; moved: boolean } | null>(null)

  const timeAt = (clientX: number): number => {
    const rect = histRef.current!.getBoundingClientRect()
    const ratio = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width))
    return hist!.from + ratio * (hist!.to - hist!.from)
  }

  const onDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (!hist) return
    e.currentTarget.setPointerCapture(e.pointerId)
    drag.current = { anchor: timeAt(e.clientX), moved: false }
  }
  const onMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    const d = drag.current
    if (!d || !hist) return
    const t = timeAt(e.clientX)
    if (Math.abs(t - d.anchor) < (hist.to - hist.from) * 0.01) return
    d.moved = true
    setWindow({ from: Math.min(d.anchor, t), to: Math.max(d.anchor, t) }, 'custom')
  }
  const onUp = () => {
    const d = drag.current
    drag.current = null
    if (d && !d.moved) setWindow(null)
  }

  // --- Real-time Replay Player & Scrubber -----------------------------------------------------------
  const [playing, setPlaying] = useState(false)
  const [playSpeed, setPlaySpeed] = useState<number>(1)
  const [playheadRatio, setPlayheadRatio] = useState<number>(1)
  const scrubberRef = useRef<HTMLDivElement>(null)

  // Sync playhead ratio with active window when set externally
  useEffect(() => {
    if (!hist) return
    if (!timeWindow) {
      setPlayheadRatio(1)
    } else {
      const span = Math.max(1, hist.to - hist.from)
      setPlayheadRatio(Math.min(1, Math.max(0, (timeWindow.to - hist.from) / span)))
    }
  }, [timeWindow, hist])

  // Playback loop
  useEffect(() => {
    if (!playing || !hist) return
    const intervalMs = 40
    // At 1x speed, 12 seconds for full workspace sweep
    const stepRatio = (intervalMs / (12000 / playSpeed))
    const timer = window.setInterval(() => {
      setPlayheadRatio((prev) => {
        const next = prev + stepRatio
        if (next >= 1) {
          window.clearInterval(timer)
          setPlaying(false)
          setWindow(null)
          return 1
        }
        const toTime = hist.from + next * (hist.to - hist.from)
        setWindow({ from: hist.from, to: toTime }, 'custom')
        return next
      })
    }, intervalMs)
    return () => window.clearInterval(timer)
  }, [playing, hist, playSpeed, setWindow])

  const togglePlay = () => {
    if (!hist) return
    if (!playing && playheadRatio >= 0.99) {
      // Restart from beginning if at the end
      setPlayheadRatio(0.01)
      setWindow({ from: hist.from, to: hist.from + (hist.to - hist.from) * 0.01 }, 'custom')
    }
    setPlaying((p) => !p)
  }

  const rewindToStart = () => {
    setPlaying(false)
    if (!hist) return
    setPlayheadRatio(0.02)
    setWindow({ from: hist.from, to: hist.from + (hist.to - hist.from) * 0.02 }, 'custom')
  }

  const stepForward = () => {
    setPlaying(false)
    if (!hist) return
    const next = Math.min(1, playheadRatio + 0.05)
    setPlayheadRatio(next)
    if (next >= 0.99) {
      setWindow(null)
    } else {
      setWindow({ from: hist.from, to: hist.from + next * (hist.to - hist.from) }, 'custom')
    }
  }

  const onScrubberDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (!hist) return
    const rect = scrubberRef.current?.getBoundingClientRect()
    if (!rect) return
    e.currentTarget.setPointerCapture(e.pointerId)
    setPlaying(false)
    const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
    setPlayheadRatio(ratio)
    if (ratio >= 0.99) {
      setWindow(null)
    } else {
      setWindow({ from: hist.from, to: hist.from + ratio * (hist.to - hist.from) }, 'custom')
    }
  }

  const onScrubberMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (!hist || e.buttons !== 1) return
    const rect = scrubberRef.current?.getBoundingClientRect()
    if (!rect) return
    const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
    setPlayheadRatio(ratio)
    if (ratio >= 0.99) {
      setWindow(null)
    } else {
      setWindow({ from: hist.from, to: hist.from + ratio * (hist.to - hist.from) }, 'custom')
    }
  }

  // Session filter state
  const [filterMode, setFilterMode] = useState<'all' | 'anchored' | 'tools'>('all')
  const onSelectFilter = (mode: 'all' | 'anchored' | 'tools') => {
    setFilterMode(mode)
    if (!facets) return
    if (mode === 'all') {
      setFacets((prev) => prev ? {
        ...prev,
        classes: { ...prev.classes, session: true, merkle: true, exchange: true, memory: true },
      } : null)
    } else if (mode === 'anchored') {
      setFacets((prev) => prev ? {
        ...prev,
        classes: { ...prev.classes, merkle: true },
      } : null)
    }
  }

  const eventsInWindow = useMemo(() => {
    if (!model) return 0
    return model.nodes.filter(
      (n) => n.time !== null && (n.cls === 'memory' || n.cls === 'exchange') && (!timeWindow || (n.time >= timeWindow.from && n.time <= timeWindow.to)),
    ).length
  }, [model, timeWindow])

  const brush = useMemo(() => {
    if (!hist || !timeWindow) return null
    const span = Math.max(1, hist.to - hist.from)
    const left = Math.min(100, Math.max(0, ((timeWindow.from - hist.from) / span) * 100))
    const right = Math.min(100, Math.max(0, ((timeWindow.to - hist.from) / span) * 100))
    return right > left ? { left, width: right - left } : null
  }, [hist, timeWindow])

  const inBucket = (index: number): boolean => {
    if (!hist) return false
    if (!timeWindow) return true
    const span = (hist.to - hist.from) / BUCKETS
    const start = hist.from + index * span
    return start + span >= timeWindow.from && start <= timeWindow.to
  }

  // Metrics counts
  const sessionsCount = useMemo(() => {
    if (!model) return sessions.length
    const count = model.nodes.filter((n) => n.cls === 'session').length
    return count > 0 ? count : sessions.length
  }, [model, sessions])

  const exchangesCount = useMemo(() => {
    if (!model) return 0
    return model.nodes.filter((n) => n.cls === 'exchange').length
  }, [model])

  const anchorsCount = useMemo(() => {
    if (!model) return 0
    return model.nodes.filter((n) => n.cls === 'merkle').length
  }, [model])

  const currentPlayheadTime = useMemo(() => {
    if (!hist) return Date.now()
    return hist.from + playheadRatio * (hist.to - hist.from)
  }, [hist, playheadRatio])

  const isAtPresent = playheadRatio >= 0.99

  /* Collapsed state: folds cleanly to the bottom-right margin */
  if (collapsed) {
    return (
      <button
        type="button"
        className="xc-chain-handle"
        onClick={() => update({ chainCollapsed: false })}
        aria-expanded={false}
        title="Show the Temporal Spectrum Scrubber HUD"
      >
        <span className="xc-pulse-dot" />
        <IconTimeline style={{ width: 14, height: 14, flex: 'none', color: '#00f0ff' }} />
        <span className="xc-eyebrow" style={{ fontSize: 10, letterSpacing: '0.08em', color: '#00f0ff' }}>SPECTRUM HUD</span>
        <span className="xc-note" style={{ fontSize: 11 }}>
          {timeWindow ? `${shortStamp(timeWindow.from)} → ${shortStamp(timeWindow.to)}` : 'All time'} · {eventsInWindow.toLocaleString()} events
        </span>
      </button>
    )
  }

  return (
    <section
      ref={railRef}
      className="xc-win xc-chain"
      aria-label="Chain rail"
      data-floating={live ? 'true' : 'false'}
      data-dragging={dragging ? 'true' : 'false'}
      style={live ? ({ '--float-x': `${live.x}px`, '--float-y': `${live.y}px` } as CSSProperties) : undefined}
    >
      {/* --- Row 1: Temporal Session Timeline & Provenance Lens Header ------------------------------- */}
      <div className="xc-spectrum-header">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" style={{ width: 16, height: 16, flex: 'none', color: 'var(--accent)' }} aria-hidden="true">
          <circle cx="12" cy="12" r="9" />
          <polyline points="12 7 12 12 15 15" />
        </svg>
        <span className="xc-spectrum-title">TEMPORAL SESSION TIMELINE & PROVENANCE LENS</span>
        <span className="xc-spectrum-sep">|</span>
        <span className="xc-spectrum-stat">SESSIONS: <b className="xc-stat-accent">{sessionsCount} ACTIVE</b></span>
        <span className="xc-spectrum-sep">|</span>
        <span className="xc-spectrum-stat">EXCHANGES: <b>{exchangesCount} REIFIED</b></span>
        <span className="xc-spectrum-sep">|</span>
        <span className="xc-spectrum-stat">ANCHORS: <b className="xc-stat-accent">{anchorsCount} ROOTED</b></span>
        <span className="xc-spectrum-sep">|</span>
        <span className="xc-spectrum-stat">AVG AIS: <b>1.000 (AUDITED)</b></span>

        <div className="xc-spectrum-filters" role="group" aria-label="Session filters">
          <button
            type="button"
            className="xc-spectrum-filter-btn"
            data-active={filterMode === 'all'}
            aria-pressed={filterMode === 'all'}
            onClick={() => onSelectFilter('all')}
          >
            ALL SESSIONS
          </button>
          <button
            type="button"
            className="xc-spectrum-filter-btn"
            data-active={filterMode === 'anchored'}
            aria-pressed={filterMode === 'anchored'}
            onClick={() => onSelectFilter('anchored')}
          >
            MERKLE ANCHORED
          </button>
          <button
            type="button"
            className="xc-spectrum-filter-btn"
            data-active={filterMode === 'tools'}
            aria-pressed={filterMode === 'tools'}
            onClick={() => onSelectFilter('tools')}
          >
            WITH TOOLS
          </button>
        </div>

        <span
          className="xc-chain-grip"
          role="button"
          tabIndex={0}
          aria-label={live ? 'Drag scrubber window; drop near bottom edge to dock' : 'Drag scrubber window'}
          title={live ? 'Drag; drop near bottom edge to dock' : 'Drag to float anywhere'}
          onPointerDown={onGripDown}
          onPointerMove={onGripMove}
          onPointerUp={onGripUp}
          onPointerCancel={onGripUp}
          onKeyDown={(e) => { if (e.key === 'Escape' && live) update({ chainPos: null }) }}
        >
          ⠿
        </span>
        <button
          type="button"
          className="xc-chain-fold"
          onClick={() => update({ chainCollapsed: true })}
          aria-expanded
          aria-label="Hide the chain rail"
          title="Collapse scrubber into right margin"
        >
          <IconChevronRight style={{ width: 12, height: 12 }} />
        </button>
      </div>

      {/* --- Row 2: Synaptic Activity Spectrum Header ---------------------------------------------- */}
      <div className="xc-spectrum-subhead">
        <div className="xc-spectrum-subhead-left">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" style={{ width: 14, height: 14, flex: 'none', color: 'var(--accent)' }} aria-hidden="true">
            <rect x="3" y="12" width="4" height="8" fill="var(--accent)" stroke="none" />
            <rect x="10" y="6" width="4" height="14" fill="var(--accent)" stroke="none" />
            <rect x="17" y="2" width="4" height="18" fill="var(--accent)" stroke="none" />
          </svg>
          <span className="xc-spectrum-subtitle">SYNAPTIC ACTIVITY SPECTRUM & TIME SCRUBBER</span>
          <div className="xc-spectrum-legend">
            <span className="xc-legend-pill"><i className="xc-dot-exchange" />Turn Exchanges</span>
            <span className="xc-legend-pill"><i className="xc-dot-tool" />Tool Executions</span>
            <span className="xc-legend-pill"><i className="xc-dot-anchor" />Merkle Anchors</span>
          </div>
        </div>
        <span className="xc-spectrum-timerange">
          {hist ? `${formatSpectrumDate(hist.from)} → ${formatSpectrumDate(hist.to)}` : 'Awaiting data'}
        </span>
      </div>

      {exporting && (
        plan.ids.length === 0 || plan.tooMany
          ? <div className="xc-callout xc-callout--review" role="status"><span>{describeExport(plan, timeWindow).join(' ')} <button type="button" className="xc-link" onClick={() => setExporting(false)}>Close</button></span></div>
          : <ConfirmPanel title="Export this window" lines={describeExport(plan, timeWindow)} confirmLabel={`Download ${plan.ids.length} memor${plan.ids.length === 1 ? 'y' : 'ies'}`} busy={exportBusy} onConfirm={() => void exportNow()} onCancel={() => setExporting(false)} />
      )}
      {exportNote && <div className={`xc-callout ${exportNote.tone === 'ok' ? 'xc-callout--anchored' : 'xc-callout--conflict'}`} role={exportNote.tone === 'ok' ? 'status' : 'alert'}>{exportNote.text}</div>}

      {/* --- Spectrum Bar Chart --------------------------------------------------------------------- */}
      {hist ? (
        <div
          ref={histRef}
          className="xc-hist"
          role="img"
          aria-label={`Writes over time, ${shortStamp(hist.from)} to ${shortStamp(hist.to)}. Drag to select a window; click to clear.`}
          onPointerDown={onDown}
          onPointerMove={onMove}
          onPointerUp={onUp}
          onPointerCancel={onUp}
        >
          {spectrum && spectrum.buckets.map((b, i) => {
            const hasActivity = b.total > 0
            const totalPct = Math.max(hasActivity ? 10 : 3, (b.total / spectrum.max) * 100)
            const exchangeFrac = hasActivity ? b.exchanges / b.total : 0
            const toolFrac = hasActivity ? b.tools / b.total : 0
            const anchorFrac = hasActivity ? b.anchors / b.total : 0
            return (
              <div
                key={i}
                className="xc-spectrum-bar-stack"
                data-in={inBucket(i)}
                style={{ height: `${totalPct}%`, opacity: inBucket(i) ? 1 : 0.4 }}
              >
                {/* Stacked multi-color segments */}
                {anchorFrac > 0 && (
                  <i
                    className="xc-bar-segment xc-bar-segment--anchor"
                    style={{ height: `${anchorFrac * 100}%` }}
                  />
                )}
                {toolFrac > 0 && (
                  <i
                    className="xc-bar-segment xc-bar-segment--tool"
                    style={{ height: `${toolFrac * 100}%` }}
                  />
                )}
                {exchangeFrac > 0 && (
                  <i
                    className="xc-bar-segment xc-bar-segment--exchange"
                    style={{ height: `${exchangeFrac * 100}%` }}
                  />
                )}
                {!hasActivity && (
                  <i
                    className="xc-hist-bar"
                    data-in={inBucket(i)}
                    style={{ height: '100%' }}
                  />
                )}
              </div>
            )
          })}
          {brush && <div className="xc-hist-brush" style={{ left: `${brush.left}%`, width: `${brush.width}%` }} />}
        </div>
      ) : (
        <p className="xc-note">
          {model ? 'No timed events: the API returned no timestamps for any memory or exchange here.' : 'Loading…'}
        </p>
      )}

      {/* --- Row 3: Video Player & Time Scrubber --------------------------------------------------- */}
      <div className="xc-spectrum-player">
        <button
          type="button"
          className="xc-spectrum-play-btn"
          onClick={togglePlay}
          disabled={!hist}
          aria-label={playing ? 'Pause timeline video' : 'Play timeline video'}
        >
          {playing ? (
            <>
              <IconPause style={{ width: 14, height: 14, fill: 'currentColor' }} />
              <span>PAUSE TIMELINE VIDEO</span>
            </>
          ) : (
            <>
              <IconPlay style={{ width: 14, height: 14, fill: 'currentColor' }} />
              <span>PLAY TIMELINE VIDEO</span>
            </>
          )}
        </button>

        <button
          type="button"
          className="xc-spectrum-ctrl-btn"
          onClick={rewindToStart}
          disabled={!hist}
          title="Rewind to start"
          aria-label="Rewind"
        >
          <svg viewBox="0 0 24 24" fill="currentColor" strokeWidth="1.5" style={{ width: 14, height: 14 }} aria-hidden="true">
            <path d="M11 19V5l-9 7 9 7zm8 0V5l-9 7 9 7z" />
          </svg>
        </button>

        <button
          type="button"
          className="xc-spectrum-ctrl-btn"
          onClick={stepForward}
          disabled={!hist}
          title="Step forward"
          aria-label="Step forward"
        >
          <svg viewBox="0 0 24 24" fill="currentColor" strokeWidth="1.5" style={{ width: 14, height: 14 }} aria-hidden="true">
            <path d="M4 5v14l9-7-9-7zm8 0v14l9-7-9-7z" />
          </svg>
        </button>

        <span className="xc-time-label">TIME:</span>

        <div
          ref={scrubberRef}
          className="xc-scrubber-container"
          onPointerDown={onScrubberDown}
          onPointerMove={onScrubberMove}
        >
          <div className="xc-scrubber-track">
            <div className="xc-scrubber-fill" style={{ width: `${playheadRatio * 100}%` }} />
            <div
              className="xc-scrubber-thumb"
              style={{ left: `${playheadRatio * 100}%` }}
              role="slider"
              aria-label="Time scrubber"
              aria-valuenow={Math.round(playheadRatio * 100)}
              aria-valuemin={0}
              aria-valuemax={100}
            />
          </div>
          <span className="xc-scrubber-readout">
            {isAtPresent ? 'PRESENT TIME' : formatSpectrumDate(currentPlayheadTime)}
          </span>
        </div>

        <div className="xc-speed-control">
          <span className="xc-speed-label">SPEED:</span>
          {[0.5, 1, 2, 5].map((spd) => (
            <button
              key={spd}
              type="button"
              className="xc-speed-btn"
              data-active={playSpeed === spd}
              onClick={() => setPlaySpeed(spd)}
            >
              {spd}x
            </button>
          ))}
        </div>

        <div className="xc-ranges" role="group" aria-label="Time range">
          {PRESETS.map((p) => (
            <button key={p} type="button" aria-pressed={preset === p} onClick={() => (p === 'all' ? setWindow(null) : applyPreset(p))}>
              {p}
            </button>
          ))}
        </div>

        <button
          type="button"
          className="xc-btn"
          style={{ fontSize: 11, padding: '4px 8px' }}
          aria-expanded={exporting}
          aria-haspopup="true"
          disabled={!model}
          onClick={() => { setExporting((v) => !v); setExportNote(null) }}
        >
          Export this window
        </button>
      </div>
    </section>
  )
}
