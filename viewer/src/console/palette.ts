// Canvas drawing can't use CSS variables directly, so read the design tokens once from the
// stylesheet. Fallbacks equal the token values, so the canvas still draws correctly if the
// stylesheet has not applied yet.

export interface Palette {
  ground: string
  ink: string
  inkMuted: string
  inkDim: string
  accent: string
  anchored: string
  review: string
  conflict: string
  hairline: string
  hairlineFaint: string
}

let cached: Palette | null = null

export function palette(): Palette {
  if (cached) return cached
  const style = getComputedStyle(document.documentElement)
  const read = (name: string, fallback: string) => style.getPropertyValue(name).trim() || fallback
  cached = {
    ground: read('--ground', '#14171a'),
    ink: read('--ink', '#eef0f1'),
    inkMuted: read('--ink-muted', '#b7bcc1'),
    inkDim: read('--ink-dim', '#9aa1a8'),
    accent: read('--cortex-accent', '#c3b6dd'),
    anchored: read('--status-anchored', '#9fc3df'),
    review: read('--status-review', '#d7aa6c'),
    conflict: read('--status-conflict', '#d88383'),
    hairline: read('--hairline', 'rgba(255,255,255,0.14)'),
    hairlineFaint: read('--hairline-faint', 'rgba(255,255,255,0.08)'),
  }
  return cached
}

/** `rgba(...)` from a #rrggbb colour, for edge strokes that need an alpha. */
export function withAlpha(hex: string, alpha: number): string {
  const m = /^#([0-9a-f]{6})$/i.exec(hex)
  if (!m) return hex
  const n = parseInt(m[1], 16)
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`
}
