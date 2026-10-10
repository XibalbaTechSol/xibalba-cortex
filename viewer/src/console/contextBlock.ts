// Presentation helpers for POST /api/context/assemble. The server decides which section each
// memory lands in (GraphStore.assemble_context); this only orders and words them, so the console
// never re-classifies evidence on its own.

import type { ContextBlock, ContextItem } from '../api'

export interface ContextSection {
  key: 'current_facts' | 'historical_facts' | 'summaries' | 'observations'
  title: string
  /** what membership in this section means, in the server's own terms */
  note: string
  items: ContextItem[]
}

const SECTIONS: Array<Omit<ContextSection, 'items'>> = [
  { key: 'current_facts', title: 'Current facts', note: 'Extracted propositions, policies and declared intents that are still valid.' },
  { key: 'historical_facts', title: 'Historical facts', note: 'Superseded, or no longer valid at the query time.' },
  { key: 'summaries', title: 'Summaries', note: 'Memories recorded as summaries.' },
  { key: 'observations', title: 'Observations', note: 'Everything else the retrieval returned within budget.' },
]

/** Sections in a fixed order, with empty ones dropped so the page shows only what exists. */
export function contextSections(block: ContextBlock): ContextSection[] {
  return SECTIONS.map((s) => ({ ...s, items: block[s.key] ?? [] })).filter((s) => s.items.length > 0)
}

export function contextItemCount(block: ContextBlock): number {
  return SECTIONS.reduce((n, s) => n + (block[s.key]?.length ?? 0), 0)
}

/** "1,204 of 12,000 characters used" — the budget is a cap, not a target. */
export function budgetText(block: ContextBlock): string {
  const { used_chars, max_total_chars } = block.budget
  return `${used_chars.toLocaleString('en-US')} of ${max_total_chars.toLocaleString('en-US')} characters used`
}
