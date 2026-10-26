// Entities: look an entity up by name and see what it connects to, or find a path between two.
//
// The entity list is the entities in the current graph sample (so it can be browsed), but the
// lookup itself runs against the whole store: a name that is not in the sample still resolves.
// Both lookups are scoped to the selected agent workspace. Relations are only ever created
// elsewhere (the inspector's "Link entities", or accepting a proposal in Review); this page reads.

import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { api, type TraversalResult } from '../../api'
import { useConsole } from '../state'
import { useAsync } from '../useAsync'
import { canBuildTree, countNodes, describePath, edgesToTree, type TreeNode } from '../entities'
import { IconWarn } from '../icons'
import { Page } from './Page'

export function EntitiesPage() {
  const { model, workspace, pageArg } = useConsole()
  const scope = workspace.scope
  const [filter, setFilter] = useState('')
  const [name, setName] = useState('')
  const [query, setQuery] = useState<{ name: string; depth: number } | null>(null)
  const [depth, setDepth] = useState(1)
  const [pathFrom, setPathFrom] = useState('')
  const [pathTo, setPathTo] = useState('')
  const [pathDepth, setPathDepth] = useState(3)
  const [pathQuery, setPathQuery] = useState<{ from: string; to: string; depth: number } | null>(null)

  const entities = useMemo(() => (model ? model.nodes.filter((n) => n.cls === 'entity').sort((a, b) => a.label.localeCompare(b.label)) : []), [model])
  const shown = entities.filter((n) => n.label.toLowerCase().includes(filter.trim().toLowerCase()))

  const neighbours = useAsync<TraversalResult | null>(() => (query ? api.entityNeighbors(query.name, query.depth, scope) : Promise.resolve(null)), [query, scope])
  const path = useAsync<TraversalResult | null>(() => (pathQuery ? api.entityPath(pathQuery.from, pathQuery.to, pathQuery.depth, scope) : Promise.resolve(null)), [pathQuery, scope])

  const lookup = (label: string) => {
    setName(label)
    setQuery({ name: label, depth })
  }
  // opened from an entity in the lens: look that one up straight away
  useEffect(() => {
    if (pageArg?.page === 'entities') { setName(pageArg.arg); setQuery({ name: pageArg.arg, depth: 1 }) }
  }, [pageArg])
  const submitLookup = (e: FormEvent) => {
    e.preventDefault()
    if (name.trim()) setQuery({ name: name.trim(), depth })
  }
  const submitPath = (e: FormEvent) => {
    e.preventDefault()
    if (pathFrom.trim() && pathTo.trim()) setPathQuery({ from: pathFrom.trim(), to: pathTo.trim(), depth: pathDepth })
  }

  return (
    <Page eyebrow="Explore" title="Entities" note="Entities and the relations between them, each backed by the memory that evidences it. Lookups search the whole workspace, not just the graph sample.">
      <div className="xc-entities">
        <section className="xc-win xc-pane xc-entities-list" aria-label="Entities in the graph sample">
          <div className="xc-memories-filters">
            <input className="xc-input" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter entities in the sample…" aria-label="Filter entities" />
            <p className="xc-note">{entities.length} in the graph sample{entities.length === 500 ? ' (the sample limit)' : ''}</p>
          </div>
          <div className="xc-scroll">
            <ul className="xc-rows" style={{ listStyle: 'none', margin: 0, padding: 0 }}>
              {shown.map((n) => (
                <li key={n.id}>
                  <button type="button" className="xc-session-row" aria-pressed={query?.name === n.label} onClick={() => lookup(n.label)}>
                    <b>{n.label}</b>
                    <span className="xc-meta">{n.degree} connection{n.degree === 1 ? '' : 's'} in the sample</span>
                  </button>
                </li>
              ))}
            </ul>
            {shown.length === 0 && <div className="xc-empty"><h3 className="xc-title">{entities.length === 0 ? 'No entities in the sample' : 'No match'}</h3><p>{entities.length === 0 ? 'Entities appear when a relation is linked from a memory, or a proposal is accepted in Review.' : 'Try a shorter filter, or look the name up directly.'}</p></div>}
          </div>
        </section>

        <div className="xc-entities-main">
          <section className="xc-win xc-newmemory" aria-label="Neighbours">
            <p className="xc-eyebrow">What connects to…</p>
            <form className="xc-memories-search" onSubmit={submitLookup}>
              <input className="xc-input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Entity name" aria-label="Entity name" />
              <label className="xc-inline">Depth
                <select className="xc-input" value={depth} onChange={(e) => setDepth(Number(e.target.value))}>{[1, 2, 3].map((d) => <option key={d} value={d}>{d}</option>)}</select>
              </label>
              <button type="submit" className="xc-btn xc-btn--primary" disabled={!name.trim()}>Look up</button>
            </form>
            <Result state={neighbours} idle={!query}>
              {(r) => {
                if (r.edges.length === 0) return <p className="xc-note">“{query?.name}” has no relations in this workspace, or does not exist here.</p>
                if (!canBuildTree(r.edges)) {
                  return <FlatEdges edges={r.edges} note="This backend does not say which entity each relation leaves, so deeper hops are shown as a flat list." />
                }
                const tree = edgesToTree(query!.name, r.edges)
                return (
                  <>
                    {r.truncated && <div className="xc-callout xc-callout--review"><IconWarn /><span>The result was cut off at the server’s node or edge limit. Narrow the depth to see all of it.</span></div>}
                    <p className="xc-note">{countNodes(tree)} entities within {query!.depth} hop{query!.depth === 1 ? '' : 's'}.</p>
                    <Tree node={tree} onPick={lookup} />
                  </>
                )
              }}
            </Result>
          </section>

          <section className="xc-win xc-newmemory" aria-label="Path between entities">
            <p className="xc-eyebrow">Path between two entities</p>
            <form className="xc-memories-search" onSubmit={submitPath}>
              <input className="xc-input" value={pathFrom} onChange={(e) => setPathFrom(e.target.value)} placeholder="From" aria-label="From entity" />
              <input className="xc-input" value={pathTo} onChange={(e) => setPathTo(e.target.value)} placeholder="To" aria-label="To entity" />
              <label className="xc-inline">Max hops
                <select className="xc-input" value={pathDepth} onChange={(e) => setPathDepth(Number(e.target.value))}>{[1, 2, 3, 4, 5].map((d) => <option key={d} value={d}>{d}</option>)}</select>
              </label>
              <button type="submit" className="xc-btn xc-btn--primary" disabled={!pathFrom.trim() || !pathTo.trim()}>Find path</button>
            </form>
            <Result state={path} idle={!pathQuery}>
              {(r) => r.edges.length === 0
                ? <p className="xc-note">No path from “{pathQuery?.from}” to “{pathQuery?.to}” within {pathQuery?.depth} hop{pathQuery?.depth === 1 ? '' : 's'}. Either they are not connected, or one of them does not exist in this workspace.</p>
                : <p className="xc-path">{describePath(pathQuery!.from, r.edges)}</p>}
            </Result>
          </section>
        </div>
      </div>
    </Page>
  )
}

function Result({ state, idle, children }: { state: ReturnType<typeof useAsync<TraversalResult | null>>; idle: boolean; children: (r: TraversalResult) => React.ReactNode }) {
  if (idle) return null
  if (state.loading && !state.data) return <p className="xc-note" role="status">Looking…</p>
  if (state.error) return <div className="xc-callout xc-callout--conflict" role="alert"><IconWarn />{state.error}</div>
  if (!state.data) return null
  return <>{children(state.data)}</>
}

function FlatEdges({ edges, note }: { edges: TraversalResult['edges']; note: string }) {
  return (
    <>
      <p className="xc-note">{note}</p>
      <ul className="xc-rows" style={{ listStyle: 'none', padding: 0 }}>
        {edges.map((e, i) => <li className="xc-row" key={i}><i className="xc-row-dot" /><div className="xc-row-main"><span>— {e.predicate} → {e.object}</span></div></li>)}
      </ul>
    </>
  )
}

function Tree({ node, onPick }: { node: TreeNode; onPick: (name: string) => void }) {
  const { reveal, go } = useConsole()
  return (
    <ul className="xc-tree" role={node.depth === 0 ? 'tree' : 'group'}>
      <li role="treeitem" aria-expanded={node.children.length > 0 ? true : undefined}>
        <div className="xc-tree-row">
          {node.via && <span className="xc-meta">— {node.via} →</span>}
          {node.depth === 0 ? <b>{node.name}</b> : <button type="button" className="xc-link" onClick={() => onPick(node.name)}>{node.name}</button>}
          {node.evidenceMemoryId && <button type="button" className="xc-link xc-meta" title="Open the memory that evidences this relation" onClick={() => { go('graph'); reveal(`memory:${node.evidenceMemoryId}`) }}>evidence</button>}
        </div>
        {node.children.map((child, i) => <Tree key={`${child.name}-${i}`} node={child} onPick={onPick} />)}
      </li>
    </ul>
  )
}
