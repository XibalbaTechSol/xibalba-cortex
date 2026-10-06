// Pure helpers for the Entities page: turn the traversal API's flat edge list into the tree the
// reader wants to see. The API returns edges in breadth-first order; with the subject on every edge
// (added 2026-10-06) the tree can be rebuilt exactly, and without it (an older backend) the page
// falls back to a flat list and says so rather than guessing a shape.

import type { TraversalEdge } from '../api'

export interface TreeNode {
  name: string
  /** the relation that led here from the parent; null for the root */
  via: string | null
  evidenceMemoryId: string | null
  depth: number
  children: TreeNode[]
}

/** True when every edge names its subject, so a tree can be built without guessing. */
export function canBuildTree(edges: readonly TraversalEdge[]): boolean {
  return edges.length > 0 && edges.every((e) => typeof e.subject === 'string' && e.subject.length > 0)
}

const key = (name: string) => name.trim().toLowerCase().split(/\s+/).join(' ')

/**
 * Group edges by subject and walk out from `root`. An entity that has already appeared on the
 * path is shown as a leaf instead of being expanded again, so a cycle (a -> b -> a) terminates.
 * Edges whose subject is not reachable from the root are dropped rather than attached somewhere
 * they do not belong.
 */
export function edgesToTree(root: string, edges: readonly TraversalEdge[]): TreeNode {
  const bySubject = new Map<string, TraversalEdge[]>()
  for (const edge of edges) {
    if (!edge.subject) continue
    const list = bySubject.get(key(edge.subject)) ?? []
    list.push(edge)
    bySubject.set(key(edge.subject), list)
  }
  const build = (name: string, via: string | null, evidence: string | null, depth: number, ancestors: readonly string[]): TreeNode => {
    const node: TreeNode = { name, via, evidenceMemoryId: evidence, depth, children: [] }
    const k = key(name)
    if (ancestors.includes(k)) return node // already on this path: a leaf, not a loop
    for (const edge of bySubject.get(k) ?? []) {
      node.children.push(build(edge.object, edge.predicate, edge.evidence_memory_id ?? null, depth + 1, [...ancestors, k]))
    }
    return node
  }
  return build(root, null, null, 0, [])
}

export function countNodes(tree: TreeNode): number {
  return 1 + tree.children.reduce((n, c) => n + countNodes(c), 0)
}

/** "a — feeds → b — feeds → c" for a path result; empty edges mean no path, not an error. */
export function describePath(from: string, edges: readonly TraversalEdge[]): string {
  if (edges.length === 0) return ''
  return [from, ...edges.map((e) => `— ${e.predicate} → ${e.object}`)].join(' ')
}
