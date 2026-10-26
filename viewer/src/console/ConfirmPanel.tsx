// "Say what it does before it does it." A small panel for the actions that write, reach outside, or
// cannot be undone: it lists what will happen, then offers the named action and a way out. It does not
// block the screen (the person may want to read the lens behind it) and it never confirms by default:
// Escape and "Cancel" both close it, and nothing is sent until the named button is pressed.

import type { ReactNode } from 'react'
import { IconWarn } from './icons'

export function ConfirmPanel({
  title, lines, confirmLabel, busy = false, danger = false, onConfirm, onCancel, children,
}: {
  title: string
  lines: readonly string[]
  confirmLabel: string
  busy?: boolean
  /** an action that cannot be undone: the confirm button is the quiet-danger style */
  danger?: boolean
  onConfirm: () => void
  onCancel: () => void
  children?: ReactNode
}) {
  return (
    <div
      className="xc-callout xc-callout--review xc-confirm"
      role="group"
      aria-label={title}
      onKeyDown={(e) => { if (e.key === 'Escape') { e.stopPropagation(); onCancel() } }}
    >
      <IconWarn />
      <div style={{ minWidth: 0 }}>
        <b>{title}</b>
        <ul className="xc-list">{lines.map((line) => <li key={line} className="xc-note">{line}</li>)}</ul>
        {children}
        <div className="xc-actions-row">
          <button type="button" className={`xc-btn ${danger ? 'xc-btn--danger-quiet' : 'xc-btn--primary'}`} disabled={busy} onClick={onConfirm} autoFocus>{busy ? 'Working…' : confirmLabel}</button>
          <button type="button" className="xc-btn" disabled={busy} onClick={onCancel}>Cancel</button>
        </div>
      </div>
    </div>
  )
}
