// Pure helpers behind Settings → Inference: turn the server's InferenceSettings into an editable
// draft (every field a string, so a half-typed number is representable), validate the draft with
// the same limits `config.load_config` enforces, and build the POST body.
//
// The server remains the authority: it re-validates the merged config before writing it, and the
// page shows its message verbatim. Validating here only saves a round trip and lets the form say
// which field is wrong. Limits mirror src/xibalba_cortex/config.py (inference block); if they
// drift, the server's refusal still wins and is displayed.

import type { InferenceSettings } from '../api'

/** Tasks the server accepts in `task_types` (config.py `supported_inference_tasks`). */
export const TASK_TYPES = [
  'extract_memory_metadata',
  'extract_entities',
  'extract_relations',
  'classify_para',
  'detect_contradictions',
  'summarize_session',
] as const

/** Tasks that may carry their own confidence threshold (config.py `supported_threshold_tasks`). */
export const THRESHOLD_TASKS = ['classify_para', 'extract_entities', 'extract_relations', 'detect_contradictions'] as const

export const PROMOTION_POLICIES = ['confidence_gated', 'review_required'] as const

/** Editable form state. Numbers stay strings until validated so "0." or "" can be typed. */
export interface InferenceDraft {
  enabled: boolean
  harness: string
  profile_name: string
  allow_fallback: boolean
  task_types: string[]
  batch_size: string
  interval_seconds: string
  max_attempts: string
  timeout_seconds: string
  max_parallel_families: string
  combined_batching: boolean
  max_evidence_chars_per_memory: string
  max_items_per_type: string
  human_review_confidence_threshold: string
  /** per-task override; an empty string means "use the default threshold" */
  task_confidence_thresholds: Record<string, string>
  promotion_policy: InferenceSettings['promotion_policy']
  contradictions_require_review: boolean
}

export function toDraft(s: InferenceSettings): InferenceDraft {
  const overrides: Record<string, string> = {}
  for (const task of THRESHOLD_TASKS) {
    const v = s.task_confidence_thresholds?.[task]
    overrides[task] = v === undefined ? '' : String(v)
  }
  return {
    enabled: s.enabled,
    harness: s.harness,
    profile_name: s.profile_name,
    allow_fallback: s.allow_fallback,
    task_types: [...s.task_types],
    batch_size: String(s.batch_size),
    interval_seconds: String(s.interval_seconds),
    max_attempts: String(s.max_attempts),
    timeout_seconds: String(s.timeout_seconds),
    max_parallel_families: String(s.max_parallel_families),
    combined_batching: s.combined_batching,
    max_evidence_chars_per_memory: String(s.max_evidence_chars_per_memory),
    max_items_per_type: String(s.max_items_per_type),
    human_review_confidence_threshold: String(s.human_review_confidence_threshold),
    task_confidence_thresholds: overrides,
    promotion_policy: s.promotion_policy,
    contradictions_require_review: s.contradictions_require_review,
  }
}

type NumericField = {
  key: keyof InferenceDraft
  label: string
  integer: boolean
  min: number
  max?: number
}

/** One row per numeric setting: label, integer-ness and the server's bounds. */
const NUMERIC: NumericField[] = [
  { key: 'batch_size', label: 'Batch size', integer: true, min: 1 },
  { key: 'interval_seconds', label: 'Interval (seconds)', integer: false, min: 0.25 },
  { key: 'max_attempts', label: 'Max attempts', integer: true, min: 1 },
  { key: 'timeout_seconds', label: 'Timeout (seconds)', integer: true, min: 1 },
  { key: 'max_parallel_families', label: 'Parallel families', integer: true, min: 1, max: 3 },
  { key: 'max_evidence_chars_per_memory', label: 'Evidence characters per memory', integer: true, min: 256 },
  { key: 'max_items_per_type', label: 'Items per type', integer: true, min: 1, max: 100 },
  { key: 'human_review_confidence_threshold', label: 'Review confidence threshold', integer: false, min: 0, max: 1 },
]

export type DraftErrors = Partial<Record<string, string>>

/** Strict numeric parse: "" and "12abc" are not numbers (Number('') would silently be 0). */
function parseNumber(text: string): number | null {
  const trimmed = text.trim()
  if (trimmed === '') return null
  const n = Number(trimmed)
  return Number.isFinite(n) ? n : null
}

export interface DraftResult {
  errors: DraftErrors
  /** present only when there are no errors */
  payload: InferenceSettings | null
}

/**
 * Validate a draft against the server's limits and build the full settings body. The route merges
 * the body over the stored block, so sending every field keeps the saved file explicit.
 * `provider` is carried through unchanged: the server accepts only `native_harness` today and the
 * form does not offer a choice it would refuse.
 */
export function validateDraft(draft: InferenceDraft, provider: string): DraftResult {
  const errors: DraftErrors = {}
  const numbers: Record<string, number> = {}

  for (const f of NUMERIC) {
    const n = parseNumber(draft[f.key] as string)
    if (n === null) {
      errors[f.key] = `${f.label} must be a number.`
    } else if (f.integer && !Number.isInteger(n)) {
      errors[f.key] = `${f.label} must be a whole number.`
    } else if (n < f.min || (f.max !== undefined && n > f.max)) {
      errors[f.key] = f.max !== undefined ? `${f.label} must be between ${f.min} and ${f.max}.` : `${f.label} must be at least ${f.min}.`
    } else {
      numbers[f.key as string] = n
    }
  }

  if (!draft.harness.trim()) errors.harness = 'Harness must not be empty.'
  if (!draft.profile_name.trim()) errors.profile_name = 'Profile name must not be empty.'
  if (draft.task_types.length === 0) errors.task_types = 'Choose at least one task type, or turn inference off.'

  const thresholds: Record<string, number> = {}
  for (const task of THRESHOLD_TASKS) {
    const text = draft.task_confidence_thresholds[task] ?? ''
    if (text.trim() === '') continue // no override
    const n = parseNumber(text)
    if (n === null || n < 0 || n > 1) errors[`threshold:${task}`] = `${task.replace(/_/g, ' ')} threshold must be between 0 and 1, or empty.`
    else thresholds[task] = n
  }

  if (Object.keys(errors).length > 0) return { errors, payload: null }

  return {
    errors,
    payload: {
      enabled: draft.enabled,
      provider,
      harness: draft.harness.trim(),
      profile_name: draft.profile_name.trim(),
      allow_fallback: draft.allow_fallback,
      task_types: [...draft.task_types],
      batch_size: numbers.batch_size,
      interval_seconds: numbers.interval_seconds,
      max_attempts: numbers.max_attempts,
      timeout_seconds: numbers.timeout_seconds,
      max_parallel_families: numbers.max_parallel_families,
      combined_batching: draft.combined_batching,
      max_evidence_chars_per_memory: numbers.max_evidence_chars_per_memory,
      max_items_per_type: numbers.max_items_per_type,
      human_review_confidence_threshold: numbers.human_review_confidence_threshold,
      task_confidence_thresholds: thresholds,
      promotion_policy: draft.promotion_policy,
      contradictions_require_review: draft.contradictions_require_review,
    },
  }
}

/** True when the draft would save something different from what the server holds. */
export function isDirty(draft: InferenceDraft, saved: InferenceSettings): boolean {
  return JSON.stringify(draft) !== JSON.stringify(toDraft(saved))
}
