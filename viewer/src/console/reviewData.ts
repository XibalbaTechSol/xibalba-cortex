// Loads the review queue for the selected workspace.
//
// /api/extraction-proposals and /api/para/classifications list the whole store and take no agent
// scope, and GET /api/memory/{id} does not enforce the agent parameter for operator credentials.
// So scope is decided here: an item is shown only if its source memory is in the workspace's own
// scoped memory listing (the same listing the timeline uses). Anything else is hidden and counted.
// The inference-task list is already scoped by the server. Reads only; decisions are made in
// Review.tsx.

import { api, type ExtractionProposal, type InferenceTask, type ParaClassification, type WorkspaceScope } from '../api'
import { loadMemoryIndex } from './data'
import { partitionByScope } from './review'

export interface ReviewQueue {
  proposals: ExtractionProposal[]
  para: ParaClassification[]
  /** items listed by the store but not matched to this workspace, never shown */
  hiddenProposals: number
  hiddenPara: number
  /** False when the workspace has more memories than the index reads, so "hidden" may include
   *  items that do belong here. Said out loud rather than assumed. */
  indexComplete: boolean
}

export async function loadReviewQueue(scope: WorkspaceScope): Promise<ReviewQueue> {
  const [proposals, para, index] = await Promise.all([
    api.extractionProposals('proposed', 100),
    api.paraClassifications('proposed', 100),
    loadMemoryIndex(scope),
  ])
  const inScope = new Set(index.info.keys())
  const p = partitionByScope(proposals, inScope, (item) => item.source_memory_id)
  const c = partitionByScope(para, inScope, (item) => item.memory_id)
  return { proposals: p.visible, para: c.visible, hiddenProposals: p.hidden, hiddenPara: c.hidden, indexComplete: index.complete }
}

export const TASK_STATUSES = ['pending', 'claimed', 'failed', 'completed'] as const
export type TaskStatus = (typeof TASK_STATUSES)[number]

export const loadTasks = (status: TaskStatus, scope: WorkspaceScope): Promise<InferenceTask[]> => api.inferenceTasks(status, 50, scope)
