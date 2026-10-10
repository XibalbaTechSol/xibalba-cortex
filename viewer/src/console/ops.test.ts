import { describe, expect, it } from 'vitest'
import { describeCoverage, labelText, parsePrometheus, sum } from './ops'

describe('parsePrometheus', () => {
  const text = `# HELP xibalba_cortex_requests_total Total local API responses.
# TYPE xibalba_cortex_requests_total counter
xibalba_cortex_requests_total 50
xibalba_cortex_responses_total{status="200"} 48
xibalba_cortex_responses_total{status="404",route="/api/x"} 2

not a metric line
bad_value NaN
`
  it('reads plain and labelled samples and skips comments, blanks and junk', () => {
    expect(parsePrometheus(text)).toEqual([
      { name: 'xibalba_cortex_requests_total', labels: {}, value: 50 },
      { name: 'xibalba_cortex_responses_total', labels: { status: '200' }, value: 48 },
      { name: 'xibalba_cortex_responses_total', labels: { status: '404', route: '/api/x' }, value: 2 },
    ])
  })
  it('unescapes quoted label values', () => {
    expect(parsePrometheus('m{a="x\\"y"} 1')[0].labels.a).toBe('x"y')
  })
  it('renders labels for a table cell', () => {
    expect(labelText({ status: '200', route: '/a' })).toBe('status=200 route=/a')
    expect(labelText({})).toBe('')
  })
})

describe('describeCoverage', () => {
  const base = { eligible: 69, current: 0, missing: 69, stale: 0, failed: 0, coverage_ratio: 0 }
  it('says plainly that zero coverage means vector retrieval has nothing to search', () => {
    const v = describeCoverage(base)
    expect(v.tone).toBe('review')
    expect(v.summary).toContain('nothing to search')
    expect(v.percent).toBe('0%')
  })
  it('does not call an empty store "complete"', () => {
    expect(describeCoverage({ ...base, eligible: 0, missing: 0 })).toMatchObject({ percent: '—', tone: 'neutral' })
  })
  it('is ok only when every eligible memory has a current vector', () => {
    expect(describeCoverage({ eligible: 4, current: 4, missing: 0, stale: 0, failed: 0, coverage_ratio: 1 }).tone).toBe('ok')
    expect(describeCoverage({ eligible: 4, current: 3, missing: 1, stale: 0, failed: 0, coverage_ratio: 0.75 }).tone).toBe('review')
  })
  it('a failure outranks partial coverage', () => {
    expect(describeCoverage({ eligible: 4, current: 3, missing: 0, stale: 0, failed: 1, coverage_ratio: 0.75 }).tone).toBe('conflict')
  })
})

describe('sum', () => {
  it('totals a state map and tolerates none', () => {
    expect(sum({ completed: 5, pending: 105 })).toBe(110)
    expect(sum(undefined)).toBe(0)
  })
})
