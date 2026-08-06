import { useEffect, useState } from 'react'
import { api, type EntityRelation, type GraphPayload, type Memory, type SimilarHit, type Stats } from './api'
import { GraphView } from './GraphView'
import './index.css'

function SidePanel({
  memoryId,
  onSelectMemory,
  onClose,
}: {
  memoryId: string
  onSelectMemory: (id: string) => void
  onClose: () => void
}) {
  const [memory, setMemory] = useState<Memory | null>(null)
  const [similar, setSimilar] = useState<SimilarHit[] | null>(null)
  const [neighbors, setNeighbors] = useState<EntityRelation[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setMemory(null)
    setSimilar(null)
    setNeighbors(null)
    setError(null)
    api.memory(memoryId).then(setMemory).catch((e) => setError(String(e)))
    api.similar(memoryId).then(setSimilar).catch(() => setSimilar([]))
    api.neighbors(memoryId).then(setNeighbors).catch(() => setNeighbors([]))
  }, [memoryId])

  return (
    <aside className="side-panel">
      <button className="close-button" onClick={onClose}>
        &times;
      </button>
      {error && <p className="error">{error}</p>}
      {memory && (
        <>
          <h3>{(memory.source.metadata.title as string) ?? memory.source.kind}</h3>
          <p className="meta">
            {memory.status} · {memory.evidence_class} · {memory.source.kind}
          </p>
          <p className="content">{memory.content.slice(0, 2000)}</p>
        </>
      )}
      {neighbors && neighbors.length > 0 && (
        <>
          <h4>Entity relations</h4>
          <ul>
            {neighbors.map((r, i) => (
              <li key={i}>
                {r.subject} <span className="predicate">{r.predicate}</span> {r.object}
              </li>
            ))}
          </ul>
        </>
      )}
      {similar && similar.length > 0 && (
        <>
          <h4>Similar memories</h4>
          <ul>
            {similar.map((hit) => (
              <li key={hit.memory.id} className="clickable" onClick={() => onSelectMemory(hit.memory.id)}>
                <span className="score">{hit.cosine_similarity.toFixed(2)}</span>{' '}
                {hit.memory.content.slice(0, 80)}
              </li>
            ))}
          </ul>
        </>
      )}
    </aside>
  )
}

export default function App() {
  const [graph, setGraph] = useState<GraphPayload | null>(null)
  const [stats, setStats] = useState<Stats | null>(null)
  const [query, setQuery] = useState('')
  const [searchResults, setSearchResults] = useState<Memory[] | null>(null)
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.stats().then(setStats).catch((e) => setError(String(e)))
    api.graph().then(setGraph).catch((e) => setError(String(e)))
  }, [])

  useEffect(() => {
    if (!query.trim()) {
      setSearchResults(null)
      return
    }
    const timeout = setTimeout(() => {
      api.search(query).then(setSearchResults).catch(() => setSearchResults([]))
    }, 250)
    return () => clearTimeout(timeout)
  }, [query])

  const selectedMemoryId =
    selectedNodeId && selectedNodeId.startsWith('memory:') ? selectedNodeId.slice('memory:'.length) : null

  return (
    <div className="app">
      <header className="topbar">
        <h1>xibalba-graph-memory</h1>
        {stats && (
          <span className="stats">
            {stats.memories} memories · {stats.entities} entities · {stats.relations} relations ·{' '}
            {stats.embedded_memories} embedded
          </span>
        )}
        <input
          className="search-box"
          type="text"
          placeholder="Search memories..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </header>
      {error && <p className="error banner">{error} -- is local_api running on :8420?</p>}
      <div className="main">
        <div className="graph-area">
          {graph && (
            <GraphView
              data={graph}
              onNodeClick={(id) => setSelectedNodeId(id)}
              selectedNodeId={selectedNodeId}
            />
          )}
        </div>
        {searchResults && (
          <div className="search-results">
            <h4>Search results</h4>
            <ul>
              {searchResults.map((m) => (
                <li key={m.id} className="clickable" onClick={() => setSelectedNodeId(`memory:${m.id}`)}>
                  {m.content.slice(0, 100)}
                </li>
              ))}
            </ul>
          </div>
        )}
        {selectedMemoryId && (
          <SidePanel
            memoryId={selectedMemoryId}
            onSelectMemory={(id) => setSelectedNodeId(`memory:${id}`)}
            onClose={() => setSelectedNodeId(null)}
          />
        )}
      </div>
    </div>
  )
}
