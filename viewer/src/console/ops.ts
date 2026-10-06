// Pure helpers for the Operations page: parse the Prometheus text the API exposes, and word the
// coverage and queue numbers without implying more than they measure.

export interface Metric {
  name: string
  labels: Record<string, string>
  value: number
}

/** Parse Prometheus text exposition (the subset the API emits: `name{a="b"} 12`, comments skipped). */
export function parsePrometheus(text: string): Metric[] {
  const out: Metric[] = []
  for (const raw of text.split('\n')) {
    const line = raw.trim()
    if (!line || line.startsWith('#')) continue
    const match = /^([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{([^}]*)\})?\s+(-?[0-9.eE+-]+|NaN|\+Inf|-Inf)$/.exec(line)
    if (!match) continue
    const value = Number(match[3])
    if (!Number.isFinite(value)) continue
    const labels: Record<string, string> = {}
    for (const part of (match[2] ?? '').matchAll(/([a-zA-Z_][a-zA-Z0-9_]*)="((?:[^"\\]|\\.)*)"/g)) labels[part[1]] = part[2].replace(/\\(.)/g, '$1')
    out.push({ name: match[1], labels, value })
  }
  return out
}

export const labelText = (labels: Record<string, string>): string =>
  Object.entries(labels).map(([k, v]) => `${k}=${v}`).join(' ')

export interface CoverageView {
  percent: string
  /** a sentence that says what the numbers mean, including the empty and the nothing-eligible cases */
  summary: string
  tone: 'ok' | 'review' | 'conflict' | 'neutral'
}

/** Embedding coverage is "how many eligible memories have a current vector", nothing more. */
export function describeCoverage(c: { eligible: number; current: number; missing: number; stale: number; failed: number; coverage_ratio: number }): CoverageView {
  if (c.eligible === 0) return { percent: '—', summary: 'No memories are eligible for embedding yet.', tone: 'neutral' }
  const percent = `${Math.round(c.coverage_ratio * 100)}%`
  if (c.failed > 0) return { percent, summary: `${c.failed} embedding${c.failed === 1 ? '' : 's'} failed; ${c.current} of ${c.eligible} eligible memories have a current vector.`, tone: 'conflict' }
  if (c.current === 0) return { percent, summary: `None of the ${c.eligible} eligible memories has a vector, so vector and hybrid retrieval have nothing to search. An embedding worker has not run.`, tone: 'review' }
  if (c.missing > 0 || c.stale > 0) return { percent, summary: `${c.current} of ${c.eligible} eligible memories have a current vector; ${c.missing} are missing and ${c.stale} are stale.`, tone: 'review' }
  return { percent, summary: `All ${c.eligible} eligible memories have a current vector.`, tone: 'ok' }
}

/** Total of a state map, for "N tasks in the queue". */
export const sum = (counts: Record<string, number> | undefined): number => Object.values(counts ?? {}).reduce((a, b) => a + b, 0)
