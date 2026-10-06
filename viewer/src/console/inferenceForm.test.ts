import { describe, expect, it } from 'vitest'
import type { InferenceSettings } from '../api'
import { isDirty, toDraft, validateDraft } from './inferenceForm'

// The exact payload the live API returned during development.
const saved: InferenceSettings = {
  enabled: true,
  provider: 'native_harness',
  harness: 'hermes',
  profile_name: 'xibalba-cortex-worker',
  allow_fallback: false,
  task_types: ['extract_entities', 'extract_relations', 'classify_para', 'detect_contradictions'],
  batch_size: 5,
  interval_seconds: 5,
  max_attempts: 3,
  timeout_seconds: 120,
  max_parallel_families: 2,
  combined_batching: true,
  max_evidence_chars_per_memory: 12000,
  max_items_per_type: 20,
  human_review_confidence_threshold: 0.75,
  task_confidence_thresholds: {},
  promotion_policy: 'confidence_gated',
  contradictions_require_review: true,
}

describe('inference form', () => {
  it('round-trips the saved settings unchanged', () => {
    const r = validateDraft(toDraft(saved), saved.provider)
    expect(r.errors).toEqual({})
    expect(r.payload).toEqual(saved)
  })

  it('is not dirty until something changes', () => {
    const d = toDraft(saved)
    expect(isDirty(d, saved)).toBe(false)
    expect(isDirty({ ...d, batch_size: '6' }, saved)).toBe(true)
  })

  it('rejects empty and non-numeric numbers rather than treating them as zero', () => {
    const d = { ...toDraft(saved), batch_size: '', timeout_seconds: '12abc' }
    const r = validateDraft(d, saved.provider)
    expect(r.payload).toBeNull()
    expect(r.errors.batch_size).toMatch(/number/)
    expect(r.errors.timeout_seconds).toMatch(/number/)
  })

  it('enforces the server bounds', () => {
    const d = {
      ...toDraft(saved),
      interval_seconds: '0.1', // server minimum is 0.25
      max_parallel_families: '4', // 1..3
      max_items_per_type: '101', // 1..100
      max_evidence_chars_per_memory: '255', // >= 256
      human_review_confidence_threshold: '1.5', // 0..1
      max_attempts: '2.5', // whole number
    }
    const r = validateDraft(d, saved.provider)
    expect(Object.keys(r.errors).sort()).toEqual(
      ['human_review_confidence_threshold', 'interval_seconds', 'max_attempts', 'max_evidence_chars_per_memory', 'max_items_per_type', 'max_parallel_families'].sort(),
    )
  })

  it('accepts the bounds themselves', () => {
    const d = { ...toDraft(saved), interval_seconds: '0.25', max_parallel_families: '3', max_items_per_type: '100', max_evidence_chars_per_memory: '256', human_review_confidence_threshold: '0' }
    expect(validateDraft(d, saved.provider).errors).toEqual({})
  })

  it('requires a task type, harness and profile name', () => {
    const d = { ...toDraft(saved), task_types: [], harness: '  ', profile_name: '' }
    const r = validateDraft(d, saved.provider)
    expect(r.errors.task_types).toBeDefined()
    expect(r.errors.harness).toBeDefined()
    expect(r.errors.profile_name).toBeDefined()
  })

  it('sends only the per-task overrides that were filled in', () => {
    const d = toDraft(saved)
    d.task_confidence_thresholds.classify_para = '0.9'
    const r = validateDraft(d, saved.provider)
    expect(r.payload?.task_confidence_thresholds).toEqual({ classify_para: 0.9 })
  })

  it('rejects an out-of-range override and names the task', () => {
    const d = toDraft(saved)
    d.task_confidence_thresholds.extract_entities = '2'
    const r = validateDraft(d, saved.provider)
    expect(r.errors['threshold:extract_entities']).toMatch(/extract entities/)
  })

  it('shows a stored override in the draft', () => {
    const d = toDraft({ ...saved, task_confidence_thresholds: { classify_para: 0.6 } })
    expect(d.task_confidence_thresholds.classify_para).toBe('0.6')
    expect(d.task_confidence_thresholds.extract_entities).toBe('')
  })
})
