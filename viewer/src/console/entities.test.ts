import { describe, expect, it } from 'vitest'
import type { TraversalEdge } from '../api'
import { canBuildTree, countNodes, describePath, edgesToTree } from './entities'

const e = (subject: string | undefined, predicate: string, object: string, evidence?: string): TraversalEdge => ({ subject, predicate, object, evidence_memory_id: evidence })

describe('canBuildTree', () => {
  it('needs a subject on every edge', () => {
    expect(canBuildTree([e('a', 'x', 'b')])).toBe(true)
    expect(canBuildTree([e('a', 'x', 'b'), e(undefined, 'x', 'c')])).toBe(false)
    expect(canBuildTree([])).toBe(false)
  })
})

describe('edgesToTree', () => {
  it('rebuilds a two-hop tree with the relation that led to each node', () => {
    const tree = edgesToTree('alpha', [e('alpha', 'feeds', 'beta', 'm1'), e('alpha', 'owns', 'delta'), e('beta', 'feeds', 'gamma')])
    expect(tree.name).toBe('alpha')
    expect(tree.children.map((c) => [c.via, c.name, c.depth])).toEqual([['feeds', 'beta', 1], ['owns', 'delta', 1]])
    expect(tree.children[0].evidenceMemoryId).toBe('m1')
    expect(tree.children[0].children.map((c) => c.name)).toEqual(['gamma'])
    expect(countNodes(tree)).toBe(4)
  })
  it('matches names the way the store does: case and spacing folded', () => {
    const tree = edgesToTree('Alpha  One', [e('alpha one', 'feeds', 'beta')])
    expect(tree.children.map((c) => c.name)).toEqual(['beta'])
  })
  it('terminates on a cycle by showing the repeat as a leaf', () => {
    const tree = edgesToTree('a', [e('a', 'x', 'b'), e('b', 'x', 'a')])
    const back = tree.children[0].children[0]
    expect(back.name).toBe('a')
    expect(back.children).toEqual([])
  })
  it('drops an edge whose subject is unreachable instead of attaching it elsewhere', () => {
    const tree = edgesToTree('a', [e('a', 'x', 'b'), e('stranger', 'x', 'c')])
    expect(countNodes(tree)).toBe(2)
  })
  it('is just the root when there are no edges', () => {
    expect(edgesToTree('solo', []).children).toEqual([])
  })
})

describe('describePath', () => {
  it('chains the hops and is empty for no path', () => {
    expect(describePath('a', [e('a', 'feeds', 'b'), e('b', 'feeds', 'c')])).toBe('a — feeds → b — feeds → c')
    expect(describePath('a', [])).toBe('')
  })
})
