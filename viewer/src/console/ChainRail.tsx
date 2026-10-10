// Chain rail: write density over time, and the control that windows BOTH lenses.
//
// Drag across the histogram to select a window; click it to clear. The range buttons are the
// keyboard path to the same thing, and "all" means no window. The play button replays the
// workspace growing by sweeping the window's end across the data.
//
// Honest counting: only memories and exchanges are events here, and nodes the API gave no
// timestamp for are reported as untimed instead of being given one.

import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import { useConsole } from './state'
import { histogram, shortStamp, type RangePreset } from './model'
import { IconPause, IconPlay } from './icons'

const BUCKETS = 72
const PRESETS: RangePreset[] = ['1h', '24h', '7d', '30d', 'all']
const REPLAY_STEPS = 110
const REPLAY_TICK_MS = 70

export function ChainRail() {
  const { model, window: timeWindow, preset, setWindow, applyPreset } = useConsole()
  const hist = useMemo(() => (model ? histogram(model, BUCKETS) : null), [model])

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
    if (d && !d.moved) setWindow(null) // a click, not a drag: back to all time
  }

  // --- replay ----------------------------------------------------------------------------------------
  const [playing, setPlaying] = useState(false)
  useEffect(() => {
    if (!playing || !hist) return
    let step = 0
    const timer = window.setInterval(() => {
      step += 1
      if (step > REPLAY_STEPS) {
        window.clearInterval(timer)
        setPlaying(false)
        setWindow(null)
        return
      }
      setWindow({ from: hist.from, to: hist.from + ((hist.to - hist.from) * step) / REPLAY_STEPS }, 'custom')
    }, REPLAY_TICK_MS)
    return () => window.clearInterval(timer)
  }, [playing, hist, setWindow])

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

  return (
    <section className="xc-win xc-chain" aria-label="Chain rail">
      <div className="xc-chain-top">
        <button
          type="button"
          className="xc-btn xc-btn--square"
          onClick={() => setPlaying((p) => !p)}
          disabled={!hist}
          aria-label={playing ? 'Pause replay' : 'Replay the workspace growing over time'}
          title={playing ? 'Pause replay' : 'Replay growth over time'}
          style={{ borderColor: 'var(--accent)', color: 'var(--accent)' }}
        >
          {playing ? <IconPause /> : <IconPlay />}
        </button>
        <p className="xc-eyebrow">Chain rail</p>
        <span className="xc-note" aria-live="polite">
          {timeWindow ? `${shortStamp(timeWindow.from)} → ${shortStamp(timeWindow.to)}` : 'All time'} · {eventsInWindow.toLocaleString()} timed event{eventsInWindow === 1 ? '' : 's'}
          {model && model.untimed > 0 ? ` · ${model.untimed} node${model.untimed === 1 ? '' : 's'} untimed (no timestamp in the API)` : ''}
        </span>
        <span className="xc-spacer" />
        <div className="xc-ranges" role="group" aria-label="Time range">
          {PRESETS.map((p) => (
            <button key={p} type="button" aria-pressed={preset === p} onClick={() => (p === 'all' ? setWindow(null) : applyPreset(p))}>
              {p}
            </button>
          ))}
        </div>
      </div>

      {hist ? (
        <>
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
            {hist.buckets.map((count, i) => (
              <i
                key={i}
                className="xc-hist-bar"
                data-in={inBucket(i)}
                style={{ height: `${Math.max(count > 0 ? 8 : 2, (count / hist.max) * 100)}%`, opacity: count > 0 ? 1 : 0.4 }}
              />
            ))}
            {brush && <div className="xc-hist-brush" style={{ left: `${brush.left}%`, width: `${brush.width}%` }} />}
          </div>
          <div className="xc-hist-axis" aria-hidden="true">
            <span>{shortStamp(hist.from)}</span>
            <span>drag to window both lenses</span>
            <span>{shortStamp(hist.to)}</span>
          </div>
        </>
      ) : (
        <p className="xc-note">
          {model ? 'No timed events: the API returned no timestamps for any memory or exchange here.' : 'Loading…'}
        </p>
      )}
    </section>
  )
}
