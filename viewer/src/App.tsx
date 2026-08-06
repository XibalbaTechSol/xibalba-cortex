import { useEffect, useMemo, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import {
  api,
  type Attachment,
  type EntityRelation,
  type Exchange,
  type GraphNode,
  type GraphPayload,
  type IntegrityLinksStatus,
  type InferenceManifest,
  type InferenceTask,
  type Memory,
  type MemoryEvent,
  type MerkleRoot,
  type OtelEvent,
  type Session,
  type SimilarHit,
  type Stats,
  type StoreStatus,
  type TraversalResult,
} from './api'
import { Graph3DView, type DemoEdge, type DemoGraph, type DemoNode, type DemoNodeType, type GraphBackground, type GraphViewOptions } from './Graph3DView'
import './index.css'

type Tab = 'timeline' | 'graph' | 'recall' | 'inference' | 'integrity'
type GraphFilterIntent = { nonce: number; status?: string; evidence?: string }

const tabs: Array<{ id: Tab; label: string }> = [
  { id: 'timeline', label: 'Timeline' },
  { id: 'graph', label: 'Graph' },
  { id: 'recall', label: 'Recall' },
  { id: 'inference', label: 'Inference' },
  { id: 'integrity', label: 'Integrity' },
]

function Badge({ children }: { children: string | number | null | undefined }) {
  if (children === null || children === undefined || children === '') return null
  return <span className="badge">{children}</span>
}

function Hash({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="muted">none</span>
  return <code title={value}>{value.slice(0, 18)}...</code>
}

function memoryNodeId(memoryId: string) {
  return `memory:${memoryId}`
}

function nodeMemoryId(nodeId: string) {
  return nodeId.startsWith('memory:') ? nodeId.slice('memory:'.length) : null
}

function buildDemoGraph(
  graph: GraphPayload | null,
  sessions: Session[],
  selectedSessionId: string,
  exchanges: Exchange[],
  root: MerkleRoot | null,
): DemoGraph {
  const nodes = new Map<string, DemoNode>()
  const edges: DemoGraph['edges'] = []
  const addNode = (node: DemoNode) => {
    const existing = nodes.get(node.id)
    if (existing) {
      nodes.set(node.id, {
        ...existing,
        tags: [...new Set([...existing.tags, ...node.tags])],
        relatedIds: [...new Set([...existing.relatedIds, ...node.relatedIds])],
        payload: node.type === 'memory' && node.payload ? node.payload : existing.payload ?? node.payload,
      })
      return
    }
    nodes.set(node.id, node)
  }
  const addEdge = (source: string, target: string, type: string, label?: string, edge?: Partial<DemoEdge>) => {
    edges.push({ source, target, type, label, ...edge })
    const a = nodes.get(source)
    const b = nodes.get(target)
    if (a && !a.relatedIds.includes(target)) a.relatedIds.push(target)
    if (b && !b.relatedIds.includes(source)) b.relatedIds.push(source)
  }

  graph?.nodes.forEach((node) => {
    addNode({
      id: node.id,
      type: node.type,
      label: node.label,
      tags: [node.type, node.status, node.evidence_class, node.source_kind, node.entity_type].filter(Boolean) as string[],
      relatedIds: [],
      payload: node,
    })
  })
  graph?.edges.forEach((edge) =>
    addEdge(edge.source, edge.target, edge.type, edge.predicate, {
      evidenceMemoryId: edge.evidence_memory_id,
      cosineSimilarity: edge.cosine_similarity,
      reason: edge.reason,
    }),
  )

  sessions.forEach((session) => {
    const id = `session:${session.external_session_id}`
    addNode({
      id,
      type: 'session',
      label: session.external_session_id,
      tags: ['session', session.retention_tier, session.ended_at ? 'closed' : 'open'],
      relatedIds: [],
      payload: session,
    })
  })

  if (selectedSessionId) {
    const sessionNodeId = `session:${selectedSessionId}`
    if (root?.root_node_id) {
      addNode({
        id: `merkle:${root.root_node_id}`,
        type: 'merkle',
        label: 'Merkle root',
        tags: ['merkle-root', root.valid ? 'valid' : 'invalid', `${root.exchange_count} exchanges`],
        relatedIds: [],
        payload: root,
      })
      addEdge(sessionNodeId, `merkle:${root.root_node_id}`, 'merkle_root', 'root')
    }
    exchanges.forEach((exchange) => {
      const exchangeNodeId = `exchange:${exchange.id}`
      addNode({
        id: exchangeNodeId,
        type: 'exchange',
        label: `Exchange ${exchange.sequence_number}`,
        tags: ['exchange', exchange.prompt_id ?? 'no-prompt-id', exchange.node_id.slice(0, 18)],
        relatedIds: [],
        payload: exchange,
      })
      addEdge(sessionNodeId, exchangeNodeId, 'contains', 'exchange')
      if (root?.root_node_id) addEdge(exchangeNodeId, `merkle:${root.root_node_id}`, 'merkle_root', 'commits')
      exchange.prompt_memories.forEach((memory) => {
        addNode({
          id: memoryNodeId(memory.id),
          type: 'memory',
          label: memory.content.slice(0, 60),
          tags: ['prompt', memory.status, memory.evidence_class, memory.source.kind],
          relatedIds: [],
          payload: memory,
        })
        addEdge(exchangeNodeId, memoryNodeId(memory.id), 'prompt', 'prompt')
      })
      exchange.response_memories.forEach((memory) => {
        addNode({
          id: memoryNodeId(memory.id),
          type: 'memory',
          label: memory.content.slice(0, 60),
          tags: ['llm-output', memory.status, memory.evidence_class, memory.source.kind],
          relatedIds: [],
          payload: memory,
        })
        addEdge(exchangeNodeId, memoryNodeId(memory.id), 'response', 'response')
      })
      exchange.context_contributions.forEach((item) => {
        addNode({
          id: memoryNodeId(item.memory.id),
          type: 'memory',
          label: item.memory.content.slice(0, 60),
          tags: ['context', item.context_kind, item.memory.status, item.memory.evidence_class],
          relatedIds: [],
          payload: item.memory,
        })
        addEdge(exchangeNodeId, memoryNodeId(item.memory.id), 'context', item.contribution_id)
      })
    })
  }

  return { nodes: [...nodes.values()], edges }
}

function MemorySnippet({
  memory,
  contradictionCount = 0,
  onSelect,
  onUseAsContext,
}: {
  memory: Memory
  contradictionCount?: number
  onSelect: (id: string) => void
  onUseAsContext?: (memory: Memory) => void
}) {
  return (
    <article className="item">
      <div className="item-head">
        <button className="link-button" onClick={() => onSelect(memory.id)}>
          {memory.content.slice(0, 120) || memory.id}
        </button>
        {onUseAsContext && (
          <button className="small-button" onClick={() => onUseAsContext(memory)}>
            Use as context
          </button>
        )}
      </div>
      <div className="badges">
        <Badge>{memory.status}</Badge>
        <Badge>{memory.evidence_class}</Badge>
        <Badge>{memory.source.kind}</Badge>
        {contradictionCount > 0 && <Badge>{`${contradictionCount} contradiction${contradictionCount === 1 ? '' : 's'}`}</Badge>}
        {memory.cosine_similarity !== undefined && <Badge>{memory.cosine_similarity.toFixed(2)}</Badge>}
      </div>
      <p className="hash-line">
        hash <Hash value={memory.content_hash} />
      </p>
    </article>
  )
}

function Inspector({
  memoryId,
  onSelectMemory,
  onClose,
}: {
  memoryId: string | null
  onSelectMemory: (id: string) => void
  onClose: () => void
}) {
  const [memory, setMemory] = useState<Memory | null>(null)
  const [similar, setSimilar] = useState<SimilarHit[]>([])
  const [neighbors, setNeighbors] = useState<EntityRelation[]>([])
  const [events, setEvents] = useState<MemoryEvent[]>([])
  const [otel, setOtel] = useState<OtelEvent[]>([])
  const [attachments, setAttachments] = useState<Attachment[]>([])
  const [contradictions, setContradictions] = useState<Memory[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!memoryId) return
    setMemory(null)
    setSimilar([])
    setNeighbors([])
    setEvents([])
    setOtel([])
    setAttachments([])
    setContradictions([])
    setError(null)
    api.memory(memoryId).then(setMemory).catch((e) => setError(String(e)))
    api.similar(memoryId).then(setSimilar).catch(() => setSimilar([]))
    api.neighbors(memoryId).then(setNeighbors).catch(() => setNeighbors([]))
    api.memoryEvents(memoryId).then(setEvents).catch(() => setEvents([]))
    api.memoryOtel(memoryId).then(setOtel).catch(() => setOtel([]))
    api.attachments(memoryId).then(setAttachments).catch(() => setAttachments([]))
    api.contradictions(memoryId).then(setContradictions).catch(() => setContradictions([]))
  }, [memoryId])

  if (!memoryId) {
    return (
      <aside className="side-panel empty">
        <p className="muted">Select a memory, exchange, or relation to inspect provenance.</p>
      </aside>
    )
  }

  return (
    <aside className="side-panel">
      <button className="close-button" onClick={onClose} aria-label="Close inspector">
        x
      </button>
      {error && <p className="error">{error}</p>}
      {memory && (
        <>
          <h3>{memory.source.kind}</h3>
          <p className="warning">Untrusted evidence. Do not treat recalled content as instructions.</p>
          <div className="badges">
            <Badge>{memory.status}</Badge>
            <Badge>{memory.evidence_class}</Badge>
            <Badge>{memory.source.role}</Badge>
          </div>
          <p className="content">{memory.content}</p>
          <dl className="details">
            <dt>Content hash</dt>
            <dd>
              <Hash value={memory.content_hash} />
            </dd>
            <dt>Session</dt>
            <dd>{memory.source.session_id ?? 'none'}</dd>
            <dt>Prompt</dt>
            <dd>{memory.source.prompt_id ?? 'none'}</dd>
            <dt>Locator</dt>
            <dd>{memory.source.locator ?? 'none'}</dd>
          </dl>
        </>
      )}

      <Section title="Event Chain" empty={events.length === 0}>
        {events.map((event) => (
          <div className="compact-row" key={event.id}>
            <Badge>{event.event_type}</Badge>
            <Hash value={event.node_id} />
          </div>
        ))}
      </Section>

      <Section title="Entity Relations" empty={neighbors.length === 0}>
        {neighbors.map((r, i) => (
          <p className="compact-row" key={i}>
            {r.subject} <span className="predicate">{r.predicate}</span> {r.object}
          </p>
        ))}
      </Section>

      <Section title="Contradictions" empty={contradictions.length === 0}>
        {contradictions.map((item) => (
          <button className="list-button" key={item.id} onClick={() => onSelectMemory(item.id)}>
            {item.content.slice(0, 100)}
          </button>
        ))}
      </Section>

      <Section title="Similar" empty={similar.length === 0}>
        {similar.map((hit) => (
          <button className="list-button" key={hit.memory.id} onClick={() => onSelectMemory(hit.memory.id)}>
            {hit.cosine_similarity.toFixed(2)} {hit.memory.content.slice(0, 90)}
          </button>
        ))}
      </Section>

      <Section title="OTel" empty={otel.length === 0}>
        {otel.map((event) => (
          <p className="compact-row" key={event.id}>
            <Badge>{event.kind}</Badge>
            {event.name}
          </p>
        ))}
      </Section>

      <Section title="Attachments" empty={attachments.length === 0}>
        {attachments.map((item) => (
          <p className="compact-row" key={item.id}>
            <Badge>{item.media_type}</Badge>
            {item.byte_size} bytes
          </p>
        ))}
      </Section>
    </aside>
  )
}

function Section({
  title,
  empty,
  children,
}: {
  title: string
  empty: boolean
  children: ReactNode
}) {
  return (
    <section className="inspector-section">
      <h4>{title}</h4>
      {empty ? <p className="muted small">No records.</p> : children}
    </section>
  )
}

export default function App() {
  const [stats, setStats] = useState<Stats | null>(null)
  const [storeStatus, setStoreStatus] = useState<StoreStatus | null>(null)
  const [integrityLinks, setIntegrityLinks] = useState<IntegrityLinksStatus | null>(null)
  const [sessions, setSessions] = useState<Session[]>([])
  const [selectedSessionId, setSelectedSessionId] = useState('')
  const [root, setRoot] = useState<MerkleRoot | null>(null)
  const [exchanges, setExchanges] = useState<Exchange[]>([])
  const [graph, setGraph] = useState<GraphPayload | null>(null)
  const [similarityThreshold, setSimilarityThreshold] = useState(0.75)
  const [graphFilterIntent, setGraphFilterIntent] = useState<GraphFilterIntent>({ nonce: 0 })
  const [query, setQuery] = useState('')
  const [searchResults, setSearchResults] = useState<Memory[]>([])
  const [selectedMemoryId, setSelectedMemoryId] = useState<string | null>(null)
  const [selectedGraphNode, setSelectedGraphNode] = useState<DemoNode | null>(null)
  const [activeTab, setActiveTab] = useState<Tab>('timeline')
  const [contextBundle, setContextBundle] = useState<Memory[]>([])
  const [manifest, setManifest] = useState<InferenceManifest | null>(null)
  const [tasks, setTasks] = useState<InferenceTask[]>([])
  const [taskStatus, setTaskStatus] = useState('pending')
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const refreshOverview = () => {
    api.stats().then(setStats).catch((e) => setError(String(e)))
    api.status().then(setStoreStatus).catch((e) => setError(String(e)))
    api.integrityLinks().then(setIntegrityLinks).catch(() => setIntegrityLinks(null))
    api.sessions().then((items) => {
      setSessions(items)
      setSelectedSessionId((current) => current || items[0]?.external_session_id || '')
    }).catch((e) => setError(String(e)))
    api.graph(500, similarityThreshold).then(setGraph).catch((e) => setError(String(e)))
  }

  useEffect(() => {
    refreshOverview()
    api.inferenceManifest().then(setManifest).catch(() => setManifest(null))
  }, [])

  useEffect(() => {
    api.graph(500, similarityThreshold).then(setGraph).catch((e) => setError(String(e)))
  }, [similarityThreshold])

  useEffect(() => {
    if (!selectedSessionId) {
      setExchanges([])
      setRoot(null)
      return
    }
    api.sessionExchanges(selectedSessionId).then(setExchanges).catch(() => setExchanges([]))
    api.sessionMerkleRoot(selectedSessionId).then(setRoot).catch(() => setRoot(null))
  }, [selectedSessionId])

  useEffect(() => {
    if (!query.trim()) {
      setSearchResults([])
      return
    }
    const timeout = setTimeout(() => {
      api.search(query).then(setSearchResults).catch(() => setSearchResults([]))
    }, 200)
    return () => clearTimeout(timeout)
  }, [query])

  useEffect(() => {
    api.inferenceTasks(taskStatus).then(setTasks).catch(() => setTasks([]))
  }, [taskStatus])

  const selectedSession = useMemo(
    () => sessions.find((item) => item.external_session_id === selectedSessionId) ?? null,
    [sessions, selectedSessionId],
  )
  const demoGraph = useMemo(
    () => buildDemoGraph(graph, sessions, selectedSessionId, exchanges, root),
    [graph, sessions, selectedSessionId, exchanges, root],
  )
  const railStatusCounts = useMemo(() => {
    const counts = new Map<string, number>()
    demoGraph.nodes.forEach((node) => {
      const status = graphNodeStatus(node)
      if (status) counts.set(status, (counts.get(status) ?? 0) + 1)
    })
    return [...counts.entries()].sort(([a], [b]) => a.localeCompare(b))
  }, [demoGraph])
  const railEvidenceCounts = useMemo(() => {
    const counts = new Map<string, number>()
    demoGraph.nodes.forEach((node) => {
      const evidence = graphNodeEvidenceClass(node)
      if (evidence) counts.set(evidence, (counts.get(evidence) ?? 0) + 1)
    })
    return [...counts.entries()].sort(([a], [b]) => a.localeCompare(b))
  }, [demoGraph])
  const contradictionCounts = useMemo(() => {
    const counts = new Map<string, number>()
    demoGraph.edges.filter((edge) => edge.type === 'contradiction').forEach((edge) => {
      const sourceMemory = nodeMemoryId(edge.source)
      const targetMemory = nodeMemoryId(edge.target)
      if (sourceMemory) counts.set(sourceMemory, (counts.get(sourceMemory) ?? 0) + 1)
      if (targetMemory) counts.set(targetMemory, (counts.get(targetMemory) ?? 0) + 1)
    })
    return counts
  }, [demoGraph])
  const applyRailGraphFilter = (filter: Omit<GraphFilterIntent, 'nonce'>) => {
    setGraphFilterIntent((current) => ({ ...filter, nonce: current.nonce + 1 }))
    setActiveTab('graph')
  }

  const selectMemory = (id: string) => {
    setSelectedMemoryId(id)
    const node = demoGraph.nodes.find((item) => item.id === memoryNodeId(id))
    if (node) setSelectedGraphNode(node)
  }

  const selectGraphNode = (node: DemoNode) => {
    setSelectedGraphNode(node)
    const memoryId = nodeMemoryId(node.id)
    if (memoryId) setSelectedMemoryId(memoryId)
    if (node.type === 'session') {
      const session = node.payload as Session | undefined
      if (session?.external_session_id) setSelectedSessionId(session.external_session_id)
    }
  }

  const addContext = (memory: Memory) => {
    setContextBundle((items) => (items.some((item) => item.id === memory.id) ? items : [...items, memory]))
    setNotice('Added memory to context bundle.')
  }

  const handleRecordExchange = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const sessionId = String(form.get('session') || selectedSessionId || 'mvp-demo-session')
    const prompt = String(form.get('prompt') || '')
    const response = String(form.get('response') || '')
    const extraContext = String(form.get('context') || '')
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean)
      .map((content, index) => ({
        content,
        contribution_id: `manual-${index + 1}`,
        context_kind: 'manual_context',
        relevance: 0.7,
      }))
    const selectedContext = contextBundle.map((memory, index) => ({
      memory_id: memory.id,
      contribution_id: `selected-${index + 1}`,
      context_kind: 'selected_memory',
      relevance: 0.9,
    }))
    const promptId = `viewer-${Date.now()}`
    const now = new Date().toISOString()
    try {
      const result = await api.recordModelExchange({
        external_session_id: sessionId,
        user_prompt: prompt,
        model_response: response,
        context: [...selectedContext, ...extraContext],
        runtime: 'viewer',
        prompt_id: promptId,
        prompt_time: now,
        response_time: now,
        idempotency_key: `${sessionId}:${promptId}`,
      })
      setSelectedSessionId(result.session.external_session_id)
      setSelectedMemoryId(result.response_memory.id)
      setContextBundle([])
      setNotice('Recorded model exchange and updated Merkle root.')
      refreshOverview()
      event.currentTarget.reset()
    } catch (e) {
      setError(String(e))
    }
  }

  const queueInference = async (subjectType: string, subjectId: string, taskType: string) => {
    try {
      const task = await api.requestInferenceTask({
        task_type: taskType,
        subject_type: subjectType,
        subject_id: subjectId,
        input_payload: { subject_type: subjectType, subject_id: subjectId },
        requested_by: 'viewer',
        idempotency_key: `viewer:${taskType}:${subjectType}:${subjectId}:${Date.now()}`,
      })
      setTaskStatus(task.status)
      setNotice(`Queued inference task ${task.id}.`)
      api.inferenceTasks(task.status).then(setTasks)
    } catch (e) {
      setError(String(e))
    }
  }

  const completeTask = async (task: InferenceTask) => {
    try {
      const completed = await api.completeInferenceTask(task.id, {
        demo_output: true,
        subject_id: task.subject_id,
        note: 'Operator-supplied MVP demo output.',
      })
      setNotice(`Completed task ${completed.id}.`)
      api.inferenceTasks(taskStatus).then(setTasks)
    } catch (e) {
      setError(String(e))
    }
  }

  const applyWriteBack = async (action: string, payload: Record<string, unknown>) => {
    try {
      if (action === 'proposition') {
        const memory = await api.createProposition(payload)
        setSelectedMemoryId(memory.id)
        setNotice(`Created proposition memory ${memory.id}.`)
      } else if (action === 'link_entities') {
        await api.linkEntities(payload)
        setNotice('Linked entities with selected evidence memory.')
      } else if (action === 'contradiction') {
        await api.markContradiction(payload)
        setNotice('Recorded contradiction between memories.')
      } else if (action === 'supersede') {
        const target = String(payload.old_id || '')
        const memory = await api.supersedeMemory(target, payload)
        setSelectedMemoryId(memory.id)
        setNotice(`Superseded memory ${target}.`)
      } else {
        throw new Error(`unknown write-back action: ${action}`)
      }
      refreshOverview()
      api.inferenceTasks(taskStatus).then(setTasks)
    } catch (e) {
      setError(String(e))
    }
  }

  return (
    <div className="app">
      <header className="topbar">
        <div>
          <h1>xibalba-graph-memory</h1>
          <p className="subhead">Local provenance graph memory for agent harnesses</p>
        </div>
        {stats && (
          <span className="stats">
            {stats.memories} memories · {stats.entities} entities · {stats.relations} relations ·{' '}
            {stats.sessions} sessions · {stats.embedded_memories} embedded
          </span>
        )}
        <div className="health-strip" title={storeStatus?.db_path ?? 'No store path loaded'}>
          <Badge>{storeStatus?.integrity_check ?? 'unknown'}</Badge>
          <Badge>{storeStatus ? `schema ${storeStatus.schema_version}` : 'schema unknown'}</Badge>
          <Badge>{storeStatus?.journal_mode ?? 'journal unknown'}</Badge>
          <Badge>{storeStatus?.backup_ready ? 'backup ready' : 'backup pending'}</Badge>
          <Badge>{root?.valid ? 'root valid' : 'root unverified'}</Badge>
        </div>
        <select
          className="session-select"
          value={selectedSessionId}
          onChange={(event) => setSelectedSessionId(event.target.value)}
        >
          <option value="">No session</option>
          {sessions.map((session) => (
            <option key={session.id} value={session.external_session_id}>
              {session.external_session_id}
            </option>
          ))}
        </select>
      </header>

      {error && (
        <p className="error banner" onClick={() => setError(null)}>
          {error} -- is local_api running on :8420?
        </p>
      )}
      {notice && (
        <p className="notice banner" onClick={() => setNotice(null)}>
          {notice}
        </p>
      )}

      <div className="shell">
        <nav className="left-rail">
          <h2>Views</h2>
          {tabs.map((tab) => (
            <button
              key={tab.id}
              className={activeTab === tab.id ? 'nav-button active' : 'nav-button'}
              onClick={() => setActiveTab(tab.id)}
            >
              {tab.label}
            </button>
          ))}
          <section className="rail-section">
            <h3>Session</h3>
            <div className="rail-list">
              {sessions.slice(0, 8).map((session) => (
                <button
                  className={session.external_session_id === selectedSessionId ? 'rail-filter active' : 'rail-filter'}
                  key={session.id}
                  onClick={() => setSelectedSessionId(session.external_session_id)}
                  type="button"
                >
                  {session.external_session_id}
                </button>
              ))}
            </div>
            <p>{selectedSession?.retention_tier ?? 'none'}</p>
            <p className="small muted">{selectedSession?.started_at ?? 'No active session selected.'}</p>
          </section>
          <section className="rail-section">
            <h3>Saved Filters</h3>
            <button className="rail-filter" onClick={() => applyRailGraphFilter({ status: 'confirmed' })} type="button">
              Confirmed memories
            </button>
            <button className="rail-filter" onClick={() => applyRailGraphFilter({ status: 'quarantined' })} type="button">
              Quarantined memories
            </button>
            <button className="rail-filter" onClick={() => applyRailGraphFilter({ evidence: 'extracted_proposition' })} type="button">
              Extracted propositions
            </button>
            <button className="rail-filter" onClick={() => applyRailGraphFilter({})} type="button">
              Clear graph filters
            </button>
          </section>
          <section className="rail-section">
            <h3>Lifecycle</h3>
            <div className="rail-list">
              {railStatusCounts.map(([status, count]) => (
                <button className="rail-filter" key={status} onClick={() => applyRailGraphFilter({ status })} type="button">
                  {status} <span>{count}</span>
                </button>
              ))}
            </div>
          </section>
          <section className="rail-section">
            <h3>Evidence</h3>
            <div className="rail-list">
              {railEvidenceCounts.map(([evidence, count]) => (
                <button className="rail-filter" key={evidence} onClick={() => applyRailGraphFilter({ evidence })} type="button">
                  {evidence} <span>{count}</span>
                </button>
              ))}
            </div>
          </section>
          <section className="rail-section">
            <h3>Root</h3>
            <p>
              <Badge>{root?.valid ? 'valid' : 'unverified'}</Badge>
            </p>
            <Hash value={root?.root_node_id} />
          </section>
        </nav>

        <main className="workspace">
          {activeTab === 'timeline' && (
            <TimelineTab
              exchanges={exchanges}
              contextBundle={contextBundle}
              selectedSessionId={selectedSessionId}
              onRecord={handleRecordExchange}
              onSelectMemory={selectMemory}
            />
          )}
          {activeTab === 'graph' && (
            <GraphTab
              graph={demoGraph}
              selectedNodeId={selectedGraphNode?.id ?? null}
              similarityThreshold={similarityThreshold}
              filterIntent={graphFilterIntent}
              onSimilarityThresholdChange={setSimilarityThreshold}
              onSelectNode={selectGraphNode}
              onSelectMemory={selectMemory}
            />
          )}
          {activeTab === 'recall' && (
            <RecallTab
              query={query}
              results={searchResults}
              contradictionCounts={contradictionCounts}
              onQuery={setQuery}
              onSelectMemory={selectMemory}
              onUseAsContext={addContext}
            />
          )}
          {activeTab === 'inference' && (
            <InferenceTab
              manifest={manifest}
              tasks={tasks}
              taskStatus={taskStatus}
              selectedMemoryId={selectedMemoryId}
              selectedSessionId={selectedSessionId}
              onStatus={setTaskStatus}
              onQueue={queueInference}
              onClaim={async (task) => {
                await api.claimInferenceTask(task.id, 'viewer')
                api.inferenceTasks(taskStatus).then(setTasks)
              }}
              onComplete={completeTask}
              onWriteBack={applyWriteBack}
            />
          )}
          {activeTab === 'integrity' && <IntegrityTab root={root} exchanges={exchanges} storeStatus={storeStatus} integrityLinks={integrityLinks} />}
        </main>

        <Inspector
          memoryId={selectedMemoryId}
          onSelectMemory={selectMemory}
          onClose={() => setSelectedMemoryId(null)}
        />
      </div>
      {selectedGraphNode && (
        <NodePopup
          node={selectedGraphNode}
          exchanges={exchanges}
          root={root}
          onClose={() => setSelectedGraphNode(null)}
          onSelectMemory={selectMemory}
        />
      )}
    </div>
  )
}

function TimelineTab({
  exchanges,
  contextBundle,
  selectedSessionId,
  onRecord,
  onSelectMemory,
}: {
  exchanges: Exchange[]
  contextBundle: Memory[]
  selectedSessionId: string
  onRecord: (event: FormEvent<HTMLFormElement>) => void
  onSelectMemory: (id: string) => void
}) {
  return (
    <section className="tab-panel">
      <div className="panel-header">
        <h2>Timeline</h2>
        <p>{exchanges.length} exchanges</p>
      </div>
      <form className="exchange-form" onSubmit={onRecord}>
        <input name="session" defaultValue={selectedSessionId || 'mvp-demo-session'} placeholder="session id" />
        <textarea name="prompt" required placeholder="User prompt" />
        <textarea name="response" required placeholder="Full model response" />
        <textarea name="context" placeholder="Additional context, one contribution per line" />
        <div className="form-footer">
          <span className="small muted">{contextBundle.length} selected memories will be linked as context</span>
          <button type="submit">Record exchange</button>
        </div>
      </form>

      <div className="timeline">
        {exchanges.map((exchange) => (
          <article className="exchange" key={exchange.id}>
            <div className="exchange-meta">
              <Badge>{`#${exchange.sequence_number}`}</Badge>
              <span>prompt {exchange.prompt_id ?? 'none'}</span>
              <span>latency {exchange.latency_ms?.toFixed(0) ?? 'n/a'} ms</span>
              <Hash value={exchange.node_id} />
            </div>
            {exchange.prompt_memories.map((memory) => (
              <MemorySnippet key={memory.id} memory={memory} onSelect={onSelectMemory} />
            ))}
            {exchange.response_memories.map((memory) => (
              <MemorySnippet key={memory.id} memory={memory} onSelect={onSelectMemory} />
            ))}
            <Section title="Context Contributions" empty={exchange.context_contributions.length === 0}>
              {exchange.context_contributions.map((item) => (
                <button className="list-button" key={item.contribution_id} onClick={() => onSelectMemory(item.memory.id)}>
                  {item.contribution_id} · {item.context_kind} · {item.relevance ?? 'n/a'} ·{' '}
                  {item.memory.content.slice(0, 90)}
                </button>
              ))}
            </Section>
            <Section title="Tool and OTel Events" empty={exchange.tool_calls.length === 0}>
              {exchange.tool_calls.map((tool) => (
                <p className="compact-row" key={tool.id}>
                  <Badge>{tool.kind}</Badge>
                  {tool.name}
                </p>
              ))}
            </Section>
          </article>
        ))}
      </div>
    </section>
  )
}

const nodeReference: Array<{ type: DemoNodeType; label: string; detail: string }> = [
  { type: 'memory', label: 'Memory', detail: 'Stored source record, retrieval fact, note, or evidence payload.' },
  { type: 'entity', label: 'Entity', detail: 'Named person, project, system, account, document, or topic extracted from memory.' },
  { type: 'session', label: 'Session', detail: 'Local agent run boundary that groups exchanges and records a provenance trail.' },
  { type: 'exchange', label: 'Exchange', detail: 'Prompt, response, context, and tool-use bundle from an agent turn.' },
  { type: 'merkle', label: 'Merkle Root', detail: 'Integrity head for the session graph; proves structure and byte lineage.' },
]

const connectionReference: Record<string, { label: string; detail: string }> = {
  relation: { label: 'Relation', detail: 'Semantic entity or memory relationship emitted by the graph API.' },
  similarity: { label: 'Similarity', detail: 'Embedding-distance neighbor above the configured similarity threshold.' },
  contains: { label: 'Contains', detail: 'Session or exchange containment link for grouped records.' },
  merkle_root: { label: 'Merkle Root', detail: 'Commitment edge from session/exchange data into the local root node.' },
  context: { label: 'Context', detail: 'Memory item used as retrieved context for an exchange.' },
  prompt: { label: 'Prompt', detail: 'Exchange link to prompt-side provenance.' },
  response: { label: 'Response', detail: 'Exchange link to response-side provenance.' },
  contradiction: { label: 'Contradiction', detail: 'Memory-to-memory conflict recorded through the contradiction lifecycle.' },
}

const backgroundOptions: Array<{ value: GraphBackground; label: string; detail: string }> = [
  { value: 'midnight', label: 'Midnight', detail: 'Dark review mode' },
  { value: 'paper', label: 'Paper', detail: 'Light documentation mode' },
  { value: 'matrix', label: 'Matrix', detail: 'Green terminal mode' },
  { value: 'contrast', label: 'Contrast', detail: 'Maximum separation' },
]

function graphNodeStatus(node: DemoNode): string | undefined {
  const payload = node.payload as Partial<GraphNode> | Partial<Memory> | undefined
  return typeof payload?.status === 'string' ? payload.status : undefined
}

function graphNodeEvidenceClass(node: DemoNode): string | undefined {
  const payload = node.payload as Partial<GraphNode> | Partial<Memory> | undefined
  return typeof payload?.evidence_class === 'string' ? payload.evidence_class : undefined
}

function graphNodeSourceKind(node: DemoNode): string | undefined {
  const payload = node.payload as (Partial<GraphNode> & Partial<Memory>) | undefined
  return typeof payload?.source_kind === 'string' ? payload.source_kind : payload?.source?.kind
}

function graphEdgeKey(edge: DemoEdge): string {
  return `${edge.source}->${edge.target}:${edge.type}:${edge.label ?? ''}`
}

function graphNodeLabel(graph: DemoGraph, id: string): string {
  return graph.nodes.find((node) => node.id === id)?.label ?? id
}

function GraphTab({
  graph,
  selectedNodeId,
  similarityThreshold,
  filterIntent,
  onSimilarityThresholdChange,
  onSelectNode,
  onSelectMemory,
}: {
  graph: DemoGraph
  selectedNodeId: string | null
  similarityThreshold: number
  filterIntent: GraphFilterIntent
  onSimilarityThresholdChange: (threshold: number) => void
  onSelectNode: (node: DemoNode) => void
  onSelectMemory: (id: string) => void
}) {
  const [background, setBackground] = useState<GraphBackground>('midnight')
  const [nodeType, setNodeType] = useState<DemoNodeType | 'all'>('all')
  const [statusFilter, setStatusFilter] = useState('all')
  const [evidenceFilter, setEvidenceFilter] = useState('all')
  const [sourceKindFilter, setSourceKindFilter] = useState('all')
  const [edgeType, setEdgeType] = useState('all')
  const [predicateFilter, setPredicateFilter] = useState('all')
  const [zoom, setZoom] = useState(1)
  const [panX, setPanX] = useState(0)
  const [panY, setPanY] = useState(0)
  const [fitMode, setFitMode] = useState<'all' | 'selected'>('all')
  const [fitNonce, setFitNonce] = useState(0)
  const [selectedEdge, setSelectedEdge] = useState<DemoEdge | null>(null)
  const [traversalDepth, setTraversalDepth] = useState(1)
  const [traversalResult, setTraversalResult] = useState<TraversalResult | null>(null)
  const [pathFrom, setPathFrom] = useState('')
  const [pathTo, setPathTo] = useState('')
  const [pathDepth, setPathDepth] = useState(3)
  const [traversalError, setTraversalError] = useState<string | null>(null)

  useEffect(() => {
    setStatusFilter(filterIntent.status ?? 'all')
    setEvidenceFilter(filterIntent.evidence ?? 'all')
  }, [filterIntent])
  const nodeTypes = useMemo(
    () => ['all', ...Array.from(new Set([...nodeReference.map((item) => item.type), ...graph.nodes.map((node) => node.type)])).sort()] as Array<
      DemoNodeType | 'all'
    >,
    [graph],
  )
  const edgeTypes = useMemo(() => ['all', ...Array.from(new Set([...Object.keys(connectionReference), ...graph.edges.map((edge) => edge.type)])).sort()], [graph])
  const statusOptions = useMemo(() => ['all', ...Array.from(new Set(graph.nodes.map(graphNodeStatus).filter(Boolean) as string[])).sort()], [graph])
  const evidenceOptions = useMemo(
    () => ['all', ...Array.from(new Set(graph.nodes.map(graphNodeEvidenceClass).filter(Boolean) as string[])).sort()],
    [graph],
  )
  const sourceKindOptions = useMemo(
    () => ['all', ...Array.from(new Set(graph.nodes.map(graphNodeSourceKind).filter(Boolean) as string[])).sort()],
    [graph],
  )
  const predicateOptions = useMemo(() => ['all', ...Array.from(new Set(graph.edges.map((edge) => edge.label).filter(Boolean) as string[])).sort()], [graph])
  const edgeCounts = useMemo(() => {
    const counts = new Map<string, number>()
    graph.edges.forEach((edge) => counts.set(edge.type, (counts.get(edge.type) ?? 0) + 1))
    return counts
  }, [graph])
  const filteredGraph = useMemo(() => {
    const visibleNodes = graph.nodes.filter((node) => {
      const nodeTypeMatches = nodeType === 'all' || node.type === nodeType
      const statusMatches = statusFilter === 'all' || graphNodeStatus(node) === statusFilter
      const evidenceMatches = evidenceFilter === 'all' || graphNodeEvidenceClass(node) === evidenceFilter
      const sourceMatches = sourceKindFilter === 'all' || graphNodeSourceKind(node) === sourceKindFilter
      return nodeTypeMatches && statusMatches && evidenceMatches && sourceMatches
    })
    const visibleNodeIds = new Set(visibleNodes.map((node) => node.id))
    const visibleEdges = graph.edges.filter((edge) => {
      const typeMatches = edgeType === 'all' || edge.type === edgeType
      const predicateMatches = predicateFilter === 'all' || edge.label === predicateFilter
      return typeMatches && predicateMatches && visibleNodeIds.has(edge.source) && visibleNodeIds.has(edge.target)
    })
    return { nodes: visibleNodes, edges: visibleEdges }
  }, [edgeType, evidenceFilter, graph, nodeType, predicateFilter, sourceKindFilter, statusFilter])
  const selectedNodeHidden = Boolean(selectedNodeId && !filteredGraph.nodes.some((node) => node.id === selectedNodeId))
  const selectedEdgeHidden = Boolean(selectedEdge && !filteredGraph.edges.some((edge) => graphEdgeKey(edge) === graphEdgeKey(selectedEdge)))
  const selectedEntityLabel = selectedNodeId ? graph.nodes.find((node) => node.id === selectedNodeId && node.type === 'entity')?.label : undefined
  const options: GraphViewOptions = { background, zoom, panX, panY, fitMode, fitNonce }
  const refit = (mode: 'all' | 'selected') => {
    setFitMode(mode)
    setFitNonce((value) => value + 1)
  }
  const loadSelectedNeighbors = async () => {
    if (!selectedEntityLabel) return
    setTraversalError(null)
    try {
      setTraversalResult(await api.entityNeighbors(selectedEntityLabel, traversalDepth))
    } catch (error) {
      setTraversalError(String(error))
    }
  }
  const findEntityPath = async () => {
    if (!pathFrom.trim() || !pathTo.trim()) return
    setTraversalError(null)
    try {
      setTraversalResult(await api.entityPath(pathFrom.trim(), pathTo.trim(), pathDepth))
    } catch (error) {
      setTraversalError(String(error))
    }
  }
  return (
    <section className="tab-panel full-bleed">
      <div className="panel-header">
        <h2>3D Memory Graph</h2>
        <p>
          {filteredGraph.nodes.length} of {graph.nodes.length} nodes · {filteredGraph.edges.length} of {graph.edges.length} links · click a node to zoom and inspect
        </p>
      </div>
      <div className="graph-controls" aria-label="3D graph controls">
        <fieldset className="background-picker">
          <legend>Background</legend>
          {backgroundOptions.map((item) => (
            <button
              className={`background-choice ${item.value}${background === item.value ? ' active' : ''}`}
              key={item.value}
              onClick={() => setBackground(item.value)}
              title={item.detail}
              type="button"
            >
              <span className="swatch" />
              <span>{item.label}</span>
            </button>
          ))}
        </fieldset>
        <label>
          Node type
          <select value={nodeType} onChange={(event) => setNodeType(event.target.value as DemoNodeType | 'all')}>
            {nodeTypes.map((type) => (
              <option key={type} value={type}>
                {type === 'all' ? 'All nodes' : type}
              </option>
            ))}
          </select>
        </label>
        <label>
          Lifecycle status
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
            {statusOptions.map((status) => (
              <option key={status} value={status}>
                {status === 'all' ? 'All statuses' : status}
              </option>
            ))}
          </select>
        </label>
        <label>
          Evidence class
          <select value={evidenceFilter} onChange={(event) => setEvidenceFilter(event.target.value)}>
            {evidenceOptions.map((item) => (
              <option key={item} value={item}>
                {item === 'all' ? 'All evidence' : item}
              </option>
            ))}
          </select>
        </label>
        <label>
          Source kind
          <select value={sourceKindFilter} onChange={(event) => setSourceKindFilter(event.target.value)}>
            {sourceKindOptions.map((item) => (
              <option key={item} value={item}>
                {item === 'all' ? 'All sources' : item}
              </option>
            ))}
          </select>
        </label>
        <label>
          Connection type
          <select value={edgeType} onChange={(event) => setEdgeType(event.target.value)}>
            {edgeTypes.map((type) => (
              <option key={type} value={type}>
                {type === 'all' ? 'All connections' : `${connectionReference[type]?.label ?? type} (${edgeCounts.get(type) ?? 0})`}
              </option>
            ))}
          </select>
        </label>
        <label>
          Relation predicate
          <select value={predicateFilter} onChange={(event) => setPredicateFilter(event.target.value)}>
            {predicateOptions.map((predicate) => (
              <option key={predicate} value={predicate}>
                {predicate === 'all' ? 'All predicates' : predicate}
              </option>
            ))}
          </select>
        </label>
        <label>
          Similarity threshold
          <span className="range-control">
            <input
              max="0.99"
              min="0.2"
              onChange={(event) => onSimilarityThresholdChange(Number(event.target.value))}
              step="0.01"
              type="range"
              value={similarityThreshold}
            />
            <output>{similarityThreshold.toFixed(2)}</output>
          </span>
        </label>
        <div className="button-group camera-buttons" aria-label="Camera controls">
          <button onClick={() => refit('all')} type="button">Fit all</button>
          <button disabled={!selectedNodeId || selectedNodeHidden} onClick={() => refit('selected')} type="button">Fit selected</button>
          <button onClick={() => setZoom((value) => Math.min(2.4, value + 0.18))} type="button">Zoom in</button>
          <button onClick={() => setZoom((value) => Math.max(0.55, value - 0.18))} type="button">Zoom out</button>
          <button onClick={() => setPanX((value) => value - 18)} type="button">Left</button>
          <button onClick={() => setPanX((value) => value + 18)} type="button">Right</button>
          <button onClick={() => setPanY((value) => value + 12)} type="button">Up</button>
          <button onClick={() => setPanY((value) => value - 12)} type="button">Down</button>
          <button
            onClick={() => {
              setZoom(1)
              setPanX(0)
              setPanY(0)
              refit('all')
            }}
            type="button"
          >
            Reset
          </button>
        </div>
      </div>
      {selectedNodeHidden && <p className="graph-note">The selected node is hidden by the current node filter. Switch to all nodes or fit the full graph.</p>}
      {selectedEdgeHidden && <p className="graph-note">The selected edge is hidden by the current filters. Clear the edge selection or reset filters.</p>}
      <div className="graph3d-area">
        <Graph3DView
          graph={filteredGraph}
          selectedNodeId={selectedNodeHidden ? null : selectedNodeId}
          selectedEdgeKey={selectedEdgeHidden ? null : selectedEdge ? graphEdgeKey(selectedEdge) : null}
          options={options}
          onSelectNode={onSelectNode}
          onSelectEdge={setSelectedEdge}
        />
      </div>
      {selectedEdge && !selectedEdgeHidden && (
        <section className="edge-inspector" aria-label="Selected edge details">
          <div>
            <h3>Selected Edge</h3>
            <p>
              <span className={`edge-key ${selectedEdge.type}`}>{connectionReference[selectedEdge.type]?.label ?? selectedEdge.type}</span>{' '}
              {selectedEdge.label ?? 'unlabeled'}
            </p>
          </div>
          <dl className="graph-reference edge-details">
            <dt>Source</dt>
            <dd>{graphNodeLabel(graph, selectedEdge.source)}</dd>
            <dt>Target</dt>
            <dd>{graphNodeLabel(graph, selectedEdge.target)}</dd>
            <dt>Evidence</dt>
            <dd>{selectedEdge.evidenceMemoryId ? <Hash value={selectedEdge.evidenceMemoryId} /> : 'none'}</dd>
            <dt>Score</dt>
            <dd>{selectedEdge.cosineSimilarity === undefined ? 'n/a' : selectedEdge.cosineSimilarity.toFixed(3)}</dd>
            <dt>Reason</dt>
            <dd>{selectedEdge.reason ?? 'none'}</dd>
          </dl>
          <div className="button-group edge-actions">
            {selectedEdge.evidenceMemoryId && (
              <button onClick={() => onSelectMemory(selectedEdge.evidenceMemoryId!)} type="button">
                Open evidence memory
              </button>
            )}
            {selectedEdge.type === 'contradiction' && [selectedEdge.source, selectedEdge.target].map(nodeMemoryId).filter(Boolean).map((id) => (
              <button key={id} onClick={() => onSelectMemory(id!)} type="button">
                Open contradiction memory
              </button>
            ))}
            <button onClick={() => setSelectedEdge(null)} type="button">Clear edge</button>
          </div>
        </section>
      )}
      <section className="traversal-panel" aria-label="Bounded graph traversal">
        <div>
          <h3>Bounded Traversal</h3>
          <p className="muted small">Traversal is capped by depth and reports truncation instead of silently hiding overflow.</p>
        </div>
        <div className="traversal-controls">
          <label>
            Neighbor depth
            <select value={traversalDepth} onChange={(event) => setTraversalDepth(Number(event.target.value))}>
              {[1, 2, 3].map((depth) => (
                <option key={depth} value={depth}>{depth}</option>
              ))}
            </select>
          </label>
          <button disabled={!selectedEntityLabel} onClick={loadSelectedNeighbors} type="button">
            Selected neighbors
          </button>
          <label>
            From
            <input value={pathFrom} onChange={(event) => setPathFrom(event.target.value)} placeholder={selectedEntityLabel ?? 'Entity name'} />
          </label>
          <label>
            To
            <input value={pathTo} onChange={(event) => setPathTo(event.target.value)} placeholder="Entity name" />
          </label>
          <label>
            Path depth
            <select value={pathDepth} onChange={(event) => setPathDepth(Number(event.target.value))}>
              {[1, 2, 3, 4, 5].map((depth) => (
                <option key={depth} value={depth}>{depth}</option>
              ))}
            </select>
          </label>
          <button disabled={!pathFrom.trim() || !pathTo.trim()} onClick={findEntityPath} type="button">
            Find path
          </button>
        </div>
        {traversalError && <p className="error small">{traversalError}</p>}
        {traversalResult && (
          <div className="traversal-results">
            <p className="small muted">
              {traversalResult.edges.length} edges · truncated {traversalResult.truncated ? 'true' : 'false'}
            </p>
            {traversalResult.edges.map((edge, index) => (
              <div className="traversal-row" key={`${edge.predicate}:${edge.object}:${index}`}>
                <span className="predicate">{edge.predicate}</span>
                <span>{edge.object}</span>
                {edge.evidence_memory_id && (
                  <button onClick={() => onSelectMemory(edge.evidence_memory_id!)} type="button">
                    Evidence
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </section>
      <div className="graph-key detailed">
        <section>
          <h3>Node Key</h3>
          <div className="key-list">
            {nodeReference.map((item) => (
              <div className="key-row" key={item.type}>
                <span className={`legend-item ${item.type}`}>{item.label}</span>
                <p>{item.detail}</p>
              </div>
            ))}
          </div>
        </section>
        <section>
          <h3>Connection Key</h3>
          <div className="key-list">
            {edgeTypes.filter((type) => type !== 'all').map((type) => (
              <div className="key-row" key={type}>
                <span className={`edge-key ${type}`}>{connectionReference[type]?.label ?? type}</span>
                <p>{connectionReference[type]?.detail ?? 'Custom graph relationship returned by the local API.'}</p>
              </div>
            ))}
          </div>
        </section>
        <section>
          <h3>Camera And Filters</h3>
          <dl className="graph-reference">
            <dt>Fit all</dt>
            <dd>Frames every visible node after node and connection filters are applied.</dd>
            <dt>Fit selected</dt>
            <dd>Frames the clicked node and its local neighborhood when the node is visible.</dd>
            <dt>Zoom</dt>
            <dd>Changes camera distance without changing filters or selected node state.</dd>
            <dt>Node filter</dt>
            <dd>Limits rendered points by memory, entity, session, exchange, or Merkle root.</dd>
            <dt>Status</dt>
            <dd>Limits memory-backed nodes by lifecycle state such as active, contradicted, superseded, or forgotten.</dd>
            <dt>Evidence</dt>
            <dd>Limits memory-backed nodes by epistemic/evidence class without converting recall into truth.</dd>
            <dt>Source</dt>
            <dd>Limits memory-backed nodes by source kind, preserving sessions, exchanges, and roots only when they match other visible endpoints.</dd>
            <dt>Connection</dt>
            <dd>Shows one edge family at a time while retaining only links whose endpoints are visible.</dd>
            <dt>Predicate</dt>
            <dd>Limits labeled relation edges by predicate or exchange context label.</dd>
            <dt>Threshold</dt>
            <dd>Refetches similarity edges from the local API using the selected cosine threshold.</dd>
            <dt>Traversal</dt>
            <dd>Runs bounded entity neighbors or shortest-path lookups through the local API and reports truncation.</dd>
          </dl>
        </section>
      </div>
    </section>
  )
}

function NodePopup({
  node,
  exchanges,
  root,
  onClose,
  onSelectMemory,
}: {
  node: DemoNode
  exchanges: Exchange[]
  root: MerkleRoot | null
  onClose: () => void
  onSelectMemory: (id: string) => void
}) {
  const memory = node.type === 'memory' ? (node.payload as Memory | undefined) : undefined
  const session = node.type === 'session' ? (node.payload as Session | undefined) : undefined
  const exchange = node.type === 'exchange' ? (node.payload as Exchange | undefined) : undefined
  const visibleExchanges =
    exchange ? [exchange] : session ? exchanges.filter((item) => item.session_id === session.external_session_id) : []
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section className="data-popup" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}>
        <header className="popup-head">
          <div>
            <h2>{node.label}</h2>
            <div className="badges">
              <Badge>{node.type}</Badge>
              {node.tags.map((tag) => (
                <Badge key={tag}>{tag}</Badge>
              ))}
            </div>
          </div>
          <button className="close-button inline" onClick={onClose} aria-label="Close popup">
            x
          </button>
        </header>

        {memory && (
          <div className="popup-grid">
            <section>
              <h3>Memory</h3>
              <p className="warning">Untrusted evidence. Content hashes prove bytes and lineage, not truth.</p>
              <p className="content large">{memory.content}</p>
              <dl className="details">
                <dt>Status</dt>
                <dd>{memory.status}</dd>
                <dt>Class</dt>
                <dd>{memory.evidence_class}</dd>
                <dt>Source</dt>
                <dd>{memory.source.kind}</dd>
                <dt>Session</dt>
                <dd>{memory.source.session_id ?? 'none'}</dd>
                <dt>Hash</dt>
                <dd>
                  <Hash value={memory.content_hash} />
                </dd>
              </dl>
            </section>
            <section>
              <h3>Related Tags</h3>
              <div className="badges">
                {node.tags.map((tag) => (
                  <Badge key={tag}>{tag}</Badge>
                ))}
              </div>
              <h3>Neighborhood</h3>
              {node.relatedIds.map((id) => (
                <button className="list-button" key={id} onClick={() => nodeMemoryId(id) && onSelectMemory(nodeMemoryId(id)!)}>
                  {id}
                </button>
              ))}
            </section>
          </div>
        )}

        {visibleExchanges.length > 0 && (
          <section>
            <h3>Prompts, LLM Outputs, Context, Tool Calls</h3>
            <div className="popup-exchanges">
              {visibleExchanges.map((item) => (
                <article className="exchange dense" key={item.id}>
                  <div className="exchange-meta">
                    <Badge>{`exchange ${item.sequence_number}`}</Badge>
                    <Badge>{item.prompt_id ?? 'no prompt id'}</Badge>
                    <Hash value={item.node_id} />
                  </div>
                  <div className="dense-columns">
                    <div>
                      <h4>Prompt</h4>
                      {item.prompt_memories.map((prompt) => (
                        <button className="dense-block" key={prompt.id} onClick={() => onSelectMemory(prompt.id)}>
                          {prompt.content}
                        </button>
                      ))}
                    </div>
                    <div>
                      <h4>LLM Output</h4>
                      {item.response_memories.map((response) => (
                        <button className="dense-block" key={response.id} onClick={() => onSelectMemory(response.id)}>
                          {response.content}
                        </button>
                      ))}
                    </div>
                    <div>
                      <h4>Context</h4>
                      {item.context_contributions.map((context) => (
                        <button className="dense-block" key={context.contribution_id} onClick={() => onSelectMemory(context.memory.id)}>
                          <strong>{context.contribution_id}</strong> · {context.context_kind} ·{' '}
                          {context.relevance ?? 'n/a'}
                          <br />
                          {context.memory.content}
                        </button>
                      ))}
                    </div>
                    <div>
                      <h4>Tool Calls</h4>
                      {item.tool_calls.length === 0 ? (
                        <p className="muted small">No tool calls recorded for this exchange.</p>
                      ) : (
                        item.tool_calls.map((tool) => (
                          <div className="dense-block static" key={tool.id}>
                            <Badge>{tool.kind}</Badge> {tool.name}
                            <br />
                            prompt {tool.prompt_id ?? 'none'} · memory {tool.memory_id ?? 'none'}
                          </div>
                        ))
                      )}
                    </div>
                  </div>
                </article>
              ))}
            </div>
          </section>
        )}

        {node.type === 'merkle' && (
          <section className="popup-grid">
            <div>
              <h3>Merkle Root</h3>
              <dl className="details">
                <dt>Root</dt>
                <dd>
                  <Hash value={root?.root_node_id} />
                </dd>
                <dt>Valid</dt>
                <dd>{root?.valid ? 'true' : 'false'}</dd>
                <dt>Exchanges</dt>
                <dd>{root?.exchange_count ?? 0}</dd>
                <dt>Kind</dt>
                <dd>{root?.root_kind ?? 'none'}</dd>
              </dl>
            </div>
            <div>
              <h3>Committed Exchanges</h3>
              {exchanges.map((item) => (
                <p className="compact-row" key={item.id}>
                  <Badge>{`#${item.sequence_number}`}</Badge>
                  <Hash value={item.node_id} />
                </p>
              ))}
            </div>
          </section>
        )}
      </section>
    </div>
  )
}

function RecallTab({
  query,
  results,
  contradictionCounts,
  onQuery,
  onSelectMemory,
  onUseAsContext,
}: {
  query: string
  results: Memory[]
  contradictionCounts: Map<string, number>
  onQuery: (query: string) => void
  onSelectMemory: (id: string) => void
  onUseAsContext: (memory: Memory) => void
}) {
  return (
    <section className="tab-panel">
      <div className="panel-header">
        <h2>Recall</h2>
        <p>Lexical browser recall. Vector query stays tool-side unless a caller supplies embeddings.</p>
      </div>
      <input
        className="wide-input"
        value={query}
        onChange={(event) => onQuery(event.target.value)}
        placeholder="Search active and confirmed memories"
      />
      <div className="item-list">
        {results.map((memory) => (
          <MemorySnippet
            key={memory.id}
            memory={memory}
            contradictionCount={contradictionCounts.get(memory.id) ?? 0}
            onSelect={onSelectMemory}
            onUseAsContext={onUseAsContext}
          />
        ))}
      </div>
    </section>
  )
}

function InferenceTab({
  manifest,
  tasks,
  taskStatus,
  selectedMemoryId,
  selectedSessionId,
  onStatus,
  onQueue,
  onClaim,
  onComplete,
  onWriteBack,
}: {
  manifest: InferenceManifest | null
  tasks: InferenceTask[]
  taskStatus: string
  selectedMemoryId: string | null
  selectedSessionId: string
  onStatus: (status: string) => void
  onQueue: (subjectType: string, subjectId: string, taskType: string) => void
  onClaim: (task: InferenceTask) => void
  onComplete: (task: InferenceTask) => void
  onWriteBack: (action: string, payload: Record<string, unknown>) => void
}) {
  const taskType = manifest?.task_types[0] ?? 'extract_memory_metadata'
  return (
    <section className="tab-panel two-column">
      <div>
        <div className="panel-header">
          <h2>Inference</h2>
          <p>{manifest?.name ?? 'xibalba-memory-inference'}</p>
        </div>
        {manifest && (
          <div className="manifest">
            <p>{manifest.role}</p>
            <p className="small muted">{manifest.input_rule}</p>
            <p className="small muted">{manifest.output_rule}</p>
            <div className="badges">
              {manifest.task_types.map((type) => (
                <Badge key={type}>{type}</Badge>
              ))}
            </div>
          </div>
        )}
        <div className="action-row">
          <button disabled={!selectedMemoryId} onClick={() => selectedMemoryId && onQueue('memory', selectedMemoryId, taskType)}>
            Queue selected memory
          </button>
          <button disabled={!selectedSessionId} onClick={() => onQueue('session', selectedSessionId, 'summarize_session')}>
            Queue session summary
          </button>
        </div>
      </div>
      <div>
        <div className="panel-header">
          <h2>Tasks</h2>
          <select value={taskStatus} onChange={(event) => onStatus(event.target.value)}>
            {['pending', 'claimed', 'completed', 'failed', 'cancelled'].map((status) => (
              <option key={status} value={status}>
                {status}
              </option>
            ))}
          </select>
        </div>
        <div className="item-list">
          {tasks.map((task) => (
            <article className="item" key={task.id}>
              <div className="item-head">
                <strong>{task.task_type}</strong>
                <Badge>{task.status}</Badge>
              </div>
              <p className="small muted">
                {task.subject_type} · {task.subject_id}
              </p>
              <div className="action-row">
                <button disabled={task.status !== 'pending'} onClick={() => onClaim(task)}>
                  Claim
                </button>
                <button disabled={task.status === 'completed'} onClick={() => onComplete(task)}>
                  Complete demo output
                </button>
              </div>
              <WriteBackActions task={task} selectedMemoryId={selectedMemoryId} onWriteBack={onWriteBack} />
            </article>
          ))}
        </div>
      </div>
    </section>
  )
}

function WriteBackActions({
  task,
  selectedMemoryId,
  onWriteBack,
}: {
  task: InferenceTask
  selectedMemoryId: string | null
  onWriteBack: (action: string, payload: Record<string, unknown>) => void
}) {
  const [action, setAction] = useState('proposition')
  const [content, setContent] = useState('')
  const [subject, setSubject] = useState('')
  const [predicate, setPredicate] = useState('relates_to')
  const [object, setObject] = useState('')
  const [otherMemoryId, setOtherMemoryId] = useState('')
  const [reason, setReason] = useState('')
  const targetMemoryId = task.subject_type === 'memory' ? task.subject_id : selectedMemoryId
  const evidenceMemoryId = targetMemoryId ?? ''
  const canApply =
    action === 'proposition'
      ? Boolean(content.trim())
      : action === 'link_entities'
        ? Boolean(subject.trim() && predicate.trim() && object.trim() && evidenceMemoryId)
        : action === 'contradiction'
          ? Boolean(evidenceMemoryId && otherMemoryId.trim() && reason.trim())
          : Boolean(evidenceMemoryId && content.trim())

  const apply = () => {
    const source = {
      kind: 'inference_output',
      locator: `xibalba://inference-task/${task.id}`,
      role: 'operator_writeback',
      session_id: task.subject_type === 'session' ? task.subject_id : undefined,
    }
    if (action === 'proposition') {
      onWriteBack('proposition', {
        content,
        source,
        status: 'confirmed',
        evidence_class: 'extracted_proposition',
        idempotency_key: `writeback:proposition:${task.id}:${content}`,
      })
    } else if (action === 'link_entities') {
      onWriteBack('link_entities', {
        subject,
        predicate,
        object,
        evidence_memory_id: evidenceMemoryId,
        confidence: 1,
      })
    } else if (action === 'contradiction') {
      onWriteBack('contradiction', {
        memory_id_a: evidenceMemoryId,
        memory_id_b: otherMemoryId,
        reason,
      })
    } else {
      onWriteBack('supersede', {
        old_id: evidenceMemoryId,
        new_content: content,
        source,
        status: 'confirmed',
        evidence_class: 'extracted_proposition',
        idempotency_key: `writeback:supersede:${task.id}:${evidenceMemoryId}:${content}`,
      })
    }
  }

  return (
    <section className="writeback-panel">
      <div className="writeback-head">
        <strong>Explicit Write Back</strong>
        <select value={action} onChange={(event) => setAction(event.target.value)}>
          <option value="proposition">Create proposition</option>
          <option value="link_entities">Link entities</option>
          <option value="contradiction">Mark contradiction</option>
          <option value="supersede">Supersede memory</option>
        </select>
      </div>
      {(action === 'proposition' || action === 'supersede') && (
        <textarea value={content} onChange={(event) => setContent(event.target.value)} placeholder="Operator-reviewed proposition or replacement memory" />
      )}
      {action === 'link_entities' && (
        <div className="writeback-grid">
          <input value={subject} onChange={(event) => setSubject(event.target.value)} placeholder="Subject entity" />
          <input value={predicate} onChange={(event) => setPredicate(event.target.value)} placeholder="Predicate" />
          <input value={object} onChange={(event) => setObject(event.target.value)} placeholder="Object entity" />
        </div>
      )}
      {action === 'contradiction' && (
        <div className="writeback-grid two">
          <input value={otherMemoryId} onChange={(event) => setOtherMemoryId(event.target.value)} placeholder="Other memory id" />
          <input value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Reason" />
        </div>
      )}
      <div className="writeback-foot">
        <span className="small muted">Target/evidence {evidenceMemoryId || 'select a memory-backed task first'}</span>
        <button disabled={!canApply} onClick={apply} type="button">Apply write back</button>
      </div>
    </section>
  )
}

function IntegrityTab({
  root,
  exchanges,
  storeStatus,
  integrityLinks,
}: {
  root: MerkleRoot | null
  exchanges: Exchange[]
  storeStatus: StoreStatus | null
  integrityLinks: IntegrityLinksStatus | null
}) {
  const linkStates = integrityLinks?.states ? Object.entries(integrityLinks.states) : []
  return (
    <section className="tab-panel">
      <div className="panel-header">
        <h2>Integrity</h2>
        <p>Local tamper evidence only. Not truth, authorization, completeness, or DAG anchoring.</p>
      </div>
      <div className="integrity-grid">
        <article className="item">
          <div className="item-head">
            <strong>Store Health</strong>
            <Badge>{storeStatus?.integrity_check ?? 'unknown'}</Badge>
          </div>
          <dl className="details wide">
            <dt>Schema</dt>
            <dd>{storeStatus?.schema_version ?? 'unknown'}</dd>
            <dt>Journal</dt>
            <dd>{storeStatus?.journal_mode ?? 'unknown'}</dd>
            <dt>Foreign keys</dt>
            <dd>{storeStatus ? String(storeStatus.foreign_keys) : 'unknown'}</dd>
            <dt>FTS5</dt>
            <dd>{storeStatus ? String(storeStatus.fts5) : 'unknown'}</dd>
            <dt>Identity</dt>
            <dd>{storeStatus?.identity_mode ?? 'unknown'}</dd>
            <dt>Database</dt>
            <dd>{storeStatus?.db_path ?? 'unknown'}</dd>
          </dl>
        </article>
        <article className="item">
          <div className="item-head">
            <strong>Backup Readiness</strong>
            <Badge>{storeStatus?.backup_ready ? 'ready' : 'not ready'}</Badge>
          </div>
          <dl className="details wide">
            <dt>Method</dt>
            <dd>{storeStatus?.backup_method ?? 'unknown'}</dd>
            <dt>Memories</dt>
            <dd>{storeStatus?.memory_count ?? 'unknown'}</dd>
            <dt>Readiness</dt>
            <dd>{storeStatus?.backup_ready ? 'SQLite online backup can run against this profile.' : 'Profile path is not ready for backup.'}</dd>
          </dl>
        </article>
      </div>
      <article className="item">
        <div className="item-head">
          <strong>Session Merkle Root</strong>
          <Badge>{root?.valid ? 'valid' : 'unverified'}</Badge>
        </div>
        <dl className="details">
          <dt>Root</dt>
          <dd>
            <Hash value={root?.root_node_id} />
          </dd>
          <dt>Exchange count</dt>
          <dd>{root?.exchange_count ?? 0}</dd>
          <dt>Kind</dt>
          <dd>{root?.root_kind ?? 'none'}</dd>
        </dl>
      </article>
      <article className="item">
        <div className="item-head">
          <strong>Integrity Links</strong>
          <Badge>{integrityLinks ? `${integrityLinks.linked_records}/${integrityLinks.total_memories} linked` : 'unknown'}</Badge>
        </div>
        <div className="integrity-state-grid">
          {linkStates.map(([state, count]) => (
            <div className="state-chip" key={state}>
              <span>{state}</span>
              <strong>{count}</strong>
            </div>
          ))}
        </div>
        <p className="small muted">
          `unlinked` means no Integrity DAG record has been associated locally. `content_unavailable` means a link exists but bytes were not available for verification.
        </p>
        {integrityLinks && integrityLinks.sample.length > 0 && (
          <div className="item-list compact">
            {integrityLinks.sample.map((link) => (
              <article className="item dense-row" key={link.memory_id}>
                <div>
                  <Badge>{link.verification_state}</Badge>
                  <p className="small muted">memory {link.memory_id}</p>
                </div>
                <dl className="details wide">
                  <dt>Node</dt>
                  <dd>{link.node_id ?? 'none'}</dd>
                  <dt>Hash</dt>
                  <dd><Hash value={link.expected_content_hash} /></dd>
                  <dt>Failure</dt>
                  <dd>{link.failure_reason ?? 'none'}</dd>
                  <dt>Verified</dt>
                  <dd>{link.verified_at ?? 'never'}</dd>
                </dl>
              </article>
            ))}
          </div>
        )}
      </article>
      <div className="item-list">
        {exchanges.map((exchange) => (
          <article className="item" key={exchange.id}>
            <div className="item-head">
              <strong>Exchange #{exchange.sequence_number}</strong>
              <Hash value={exchange.node_id} />
            </div>
            <p className="small muted">parent {exchange.parent_node_id ?? 'none'}</p>
          </article>
        ))}
      </div>
    </section>
  )
}
