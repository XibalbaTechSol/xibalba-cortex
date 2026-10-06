// Wording for the server-side verification and export routes. Pure, so what each result is allowed
// to claim is tested rather than eyeballed. Every result here is the SERVER's own recomputation,
// shown as such; none is a browser recomputation, and none proves anchoring, truth or authorization.

import type { ChainVerification, ExchangeChainVerification, OtelSummary } from '../api'

export type Tone = 'ok' | 'bad' | 'neutral'

export interface Verdict {
  tone: Tone
  headline: string
  detail: string
}

/** The server recomputed a memory's event chain (GraphStore.verify_chain). */
export function describeMemoryChain(v: ChainVerification): Verdict {
  if (!v.valid) {
    return {
      tone: 'bad',
      headline: 'Server found a break in this history',
      detail: `The chain stops being consistent at event ${v.broken_at_event_id ?? 'unknown'} of ${v.length}. Either an event was altered or its parent link was changed.`,
    }
  }
  if (v.length === 0) {
    return { tone: 'neutral', headline: 'Nothing to verify', detail: 'This memory has no recorded events.' }
  }
  return {
    tone: 'ok',
    headline: 'Server recomputed this history and it is consistent',
    detail: `${v.length} event${v.length === 1 ? '' : 's'}: every node hash and parent link matched. This is local consistency, not on-chain anchoring.`,
  }
}

/** The server recomputed a session's exchange chain (GraphStore.verify_exchange_chain). */
export function describeExchangeChain(v: ExchangeChainVerification): Verdict {
  if (!v.valid) {
    return {
      tone: 'bad',
      headline: 'Server found a break in this session’s exchanges',
      detail: `The chain stops being consistent at exchange ${v.broken_at_sequence_number ?? 'unknown'} of ${v.length}. An exchange may have been reordered, altered or dropped.`,
    }
  }
  if (v.length === 0) {
    return { tone: 'neutral', headline: 'Nothing to verify', detail: 'This session has no exchanges yet.' }
  }
  const legacy = v.legacy_commitment ? ' Some exchanges use an older commitment format that predates tool-call hashes; they verify under that format.' : ''
  return {
    tone: 'ok',
    headline: 'Server recomputed this session and it is consistent',
    detail: `${v.length} exchange${v.length === 1 ? '' : 's'}: every node hash and parent link matched.${legacy}`,
  }
}

/** A filesystem-safe name for a downloaded bundle. Ids are opaque, so keep only safe characters. */
export function provenanceFilename(memoryId: string): string {
  const safe = memoryId.replace(/[^A-Za-z0-9._-]+/g, '_').slice(0, 64) || 'memory'
  return `provenance-${safe}.json`
}

/** Metric totals as printable rows; a null sum (a metric with no numeric values) is "no value", not 0. */
export function metricRows(summary: OtelSummary): Array<{ name: string; total: string; count: number }> {
  return Object.entries(summary.metric_totals)
    .map(([name, m]) => ({ name, total: m.total === null ? 'no value' : String(m.total), count: m.count }))
    .sort((a, b) => a.name.localeCompare(b.name))
}

/** One line for the counts by kind, always in the same order and always naming all three kinds. */
export function kindCounts(summary: OtelSummary): string {
  return (['span', 'metric', 'log'] as const).map((k) => `${summary.counts_by_kind[k] ?? 0} ${k}${(summary.counts_by_kind[k] ?? 0) === 1 ? '' : 's'}`).join(' · ')
}
