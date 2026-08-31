import { useEffect, useMemo, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import {
  api,
  type Attachment,
  type EntityRelation,
  type Exchange,
  type ExtractionProposal,
  type GraphNode,
  type GraphPayload,
  type IntegrityLinksStatus,
  type InferenceManifest,
  type InferenceTask,
  type Memory,
  type MemoryEvent,
  type MerkleRoot,
  type OperationsSnapshot,
  type OtelEvent,
  type ParaClassification,
  type Session,
  type SessionReplay,
  type SimilarHit,
  type Stats,
  type StoreStatus,
  type TraversalResult,
} from './api'
import { Graph3DView, type DemoEdge, type DemoGraph, type DemoNode, type DemoNodeType, type GraphBackground, type GraphViewOptions } from './Graph3DView'
import { ExtractionProposalsPanel, ProjectionHealthPanel, RetrievalTraceInspector } from './ProvenancePanels'
import './index.css'

type Tab = 'timeline' | 'graph' | 'recall' | 'inference' | 'provenance' | 'integrity' | 'operations'
type GraphFilterIntent = { nonce: number; status?: string; evidence?: string }

const tabs: Array<{ id: Tab; label: string }> = [
  { id: 'timeline', label: 'Timeline' },
  { id: 'graph', label: 'Graph' },
  { id: 'recall', label: 'Recall' },
  { id: 'inference', label: 'Inference' },
  { id: 'provenance', label: 'Provenance' },
  { id: 'integrity', label: 'Integrity' },
  { id: 'operations', label: 'Operations' },
]

export function Badge({ children }: { children: ReactNode }) {
  if (children === null || children === undefined || children === '') return null
  return <span className="badge">{children}</span>
}

export function Hash({ value }: { value: string | null | undefined }) {
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

function ContextContributionItem({
  item,
  onSelectMemory,
}: {
  item: any
  onSelectMemory: (id: string) => void
}) {
  const [attachments, setAttachments] = useState<any[]>([])

  useEffect(() => {
    if (!item.memory?.id) return;
    fetch(`/api/memory/${encodeURIComponent(item.memory.id)}/attachments`)
      .then((res) => res.json())
      .then((data) => {
        if (Array.isArray(data)) {
          setAttachments(data)
        }
      })
      .catch((err) => console.error('Failed to fetch memory attachments', err))
  }, [item.memory?.id])

  return (
    <div className="context-contribution-card" style={{
      background: 'rgba(255, 255, 255, 0.02)',
      border: '1px solid rgba(255, 255, 255, 0.06)',
      borderRadius: '8px',
      padding: '12px',
      marginBottom: '8px',
      width: '100%'
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px', fontSize: '12px' }}>
        <button className="list-button" type="button" onClick={() => item.memory?.id && onSelectMemory(item.memory.id)} style={{ fontWeight: '600', padding: '4px 8px' }}>
          {item.contribution_id} · {item.context_kind} (Relevance: {item.relevance ?? 'n/a'})
        </button>
        {item.memory?.id && <span className="muted" style={{ fontSize: '11px' }}>Memory ID: {item.memory.id.slice(0, 8)}</span>}
      </div>

      <p style={{ margin: '0 0 8px 0', fontSize: '13px', lineHeight: '1.4', whiteSpace: 'pre-wrap', color: 'var(--text-muted)' }}>
        {item.memory?.content?.replace(/\\n/g, '\n').replace(/\\"/g, '"') ?? 'Memory content unavailable'}
      </p>

      {attachments.length > 0 && (
        <div className="attachments-grid" style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginTop: '8px' }}>
          {attachments.map((att) => {
            const isImage = att.media_type && att.media_type.startsWith('image/')
            const fileUrl = `/api/attachment/${encodeURIComponent(att.id)}/file`
            return (
              <div key={att.id} className="attachment-item" style={{
                background: 'rgba(0,0,0,0.2)',
                border: '1px solid rgba(255,255,255,0.05)',
                borderRadius: '6px',
                padding: '8px',
                width: '100%',
                maxWidth: '220px',
                fontSize: '11px'
              }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                  <span className="badge" style={{ fontSize: '9px', alignSelf: 'flex-start' }}>{att.media_type}</span>
                  {isImage ? (
                    <img 
                      src={fileUrl} 
                      alt="Attachment Preview" 
                      style={{ maxWidth: '100%', maxHeight: '120px', borderRadius: '4px', marginTop: '4px', objectFit: 'contain' }}
                    />
                  ) : (
                    <a href={fileUrl} target="_blank" rel="noreferrer" style={{ color: 'var(--brand)', textDecoration: 'underline', marginTop: '4px', wordBreak: 'break-all' }}>
                      Download File ({att.byte_size} bytes)
                    </a>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function OtelTreeNode({
  event,
  childrenMap,
}: {
  event: OtelEvent
  childrenMap: Map<string, OtelEvent[]>
}) {
  const [collapsed, setCollapsed] = useState(true)
  const children = childrenMap.get(event.span_id || '') || []
  
  const formatTime = (timeStr: string | null) => {
    if (!timeStr) return ''
    const d = new Date(timeStr.endsWith('Z') ? timeStr : timeStr + 'Z')
    return isNaN(d.getTime()) ? '' : d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
  }

  const startTimeStr = formatTime(event.start_time || event.created_at)
  
  return (
    <div style={{ marginLeft: '12px', marginTop: '6px', borderLeft: '1px dashed rgba(255,255,255,0.1)', paddingLeft: '8px' }}>
      <div 
        onClick={() => setCollapsed(!collapsed)}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          cursor: 'pointer',
          padding: '4px 6px',
          background: 'rgba(255,255,255,0.02)',
          borderRadius: '4px',
          fontSize: '13px'
        }}
      >
        <span style={{ fontSize: '10px', width: '12px', display: 'inline-block', color: 'var(--text-muted)' }}>
          {children.length > 0 ? (collapsed ? '▶' : '▼') : '•'}
        </span>
        <span className="badge" style={{ fontSize: '9px', background: 'rgba(245, 158, 11, 0.15)', color: '#fbbf24', border: 'none', padding: '3px 8px', borderRadius: '4px' }}>
          {event.kind}
        </span>
        <strong style={{ color: '#e2e8f0' }}>{event.name}</strong>
        {startTimeStr && <span className="muted" style={{ fontSize: '11px' }}>[{startTimeStr}]</span>}
      </div>

      {!collapsed && (
        <div style={{ marginTop: '4px', paddingLeft: '12px' }}>
          {event.attributes && Object.keys(event.attributes).length > 0 && (
            <pre style={{
              margin: '4px 0',
              padding: '6px 8px',
              background: 'rgba(0,0,0,0.3)',
              borderRadius: '4px',
              fontSize: '11px',
              overflowX: 'auto',
              color: '#a0aec0',
              whiteSpace: 'pre-wrap'
            }}>
              {JSON.stringify(event.attributes, null, 2)}
            </pre>
          )}

          {children.map((child) => (
            <OtelTreeNode key={child.id} event={child} childrenMap={childrenMap} />
          ))}
        </div>
      )}
    </div>
  )
}

function OtelTree({ events }: { events: OtelEvent[] }) {
  const childrenMap = useMemo(() => {
    const map = new Map<string, OtelEvent[]>()
    events.forEach((ev) => {
      if (ev.parent_span_id) {
        if (!map.has(ev.parent_span_id)) {
          map.set(ev.parent_span_id, [])
        }
        map.get(ev.parent_span_id)!.push(ev)
      }
    })
    return map
  }, [events])

  const roots = useMemo(() => {
    const spanIds = new Set(events.map((ev) => ev.span_id).filter(Boolean) as string[])
    return events.filter((ev) => !ev.parent_span_id || !spanIds.has(ev.parent_span_id))
  }, [events])

  if (events.length === 0) return <p className="muted small">No tool calls or events.</p>

  return (
    <div className="otel-tree" style={{ width: '100%' }}>
      {roots.map((root) => (
        <OtelTreeNode key={root.id} event={root} childrenMap={childrenMap} />
      ))}
    </div>
  )
}

function formatMemoryContent(rawContent: string): string {
  const content = rawContent.replace(/\\n/g, '\n').replace(/\\"/g, '"')
  let extractedText = ''
  let hasJsonL = false

  const lines = content.split('\n')
  for (const line of lines) {
    const trimmed = line.trim()
    if (!trimmed) continue
    if (trimmed.startsWith('{') && trimmed.endsWith('}')) {
      try {
        const parsed = JSON.parse(trimmed)
        hasJsonL = true
        if (parsed.message?.content) {
          const msg = parsed.message.content
          if (typeof msg === 'string') extractedText += msg + '\n\n'
          else if (Array.isArray(msg)) extractedText += msg.map((b: any) => b.text || b.type || '').join('\n') + '\n\n'
        } else if (parsed.text) {
          extractedText += parsed.text + '\n\n'
        }
      } catch {
        extractedText += line + '\n'
      }
    } else {
      extractedText += line + '\n'
    }
  }

  const finalOutput = extractedText.trim()
  if (hasJsonL && !finalOutput) {
    return "⚙️ [Internal System/Tool Data]"
  }
  return finalOutput || content
}

function CollapsibleExchange({
  exchange,
  onSelectMemory,
}: {
  exchange: any
  onSelectMemory: (id: string) => void
}) {
  const [showMetadata, setShowMetadata] = useState(true)

  const formatTime = (timeStr: string | null) => {
    if (!timeStr) return 'n/a'
    const d = new Date(timeStr.endsWith('Z') ? timeStr : timeStr + 'Z')
    return isNaN(d.getTime()) ? timeStr : d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
  }

  const timestamp = formatTime(exchange.created_at || (exchange.prompt_memories[0]?.created_at))

  return (
    <article className="exchange-thread" key={exchange.id} style={{ marginBottom: '24px' }}>
      
      {/* Chat Bubble: User (Prompt) */}
      {exchange.prompt_memories.length > 0 && (
        <div className="chat-bubble user" style={{
          maxWidth: '75%',
          marginLeft: 'auto',
          background: 'rgba(59, 130, 246, 0.15)',
          border: 'none',
          boxShadow: '0 2px 8px rgba(0,0,0,0.15)',
          padding: '12px 16px',
          borderRadius: '16px 16px 2px 16px',
          marginBottom: '12px'
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
            <span style={{ fontSize: '10px', textTransform: 'uppercase', opacity: 0.6, fontWeight: 'bold' }}>User</span>
            <span style={{ fontSize: '10px', opacity: 0.5 }}>{timestamp}</span>
          </div>
          {exchange.prompt_memories.map((memory: any) => (
            <div key={memory.id} style={{ cursor: 'pointer' }} onClick={() => onSelectMemory(memory.id)}>
              <p style={{ margin: 0, fontSize: '14px', lineHeight: '1.5', whiteSpace: 'pre-wrap' }}>
                {formatMemoryContent(memory.content)}
              </p>
            </div>
          ))}
        </div>
      )}

      {/* Chat Bubble: Assistant (Response) */}
      {exchange.response_memories.length > 0 && (
        <div className="chat-bubble assistant" style={{
          maxWidth: '75%',
          marginRight: 'auto',
          background: 'rgba(255, 255, 255, 0.05)',
          border: 'none',
          boxShadow: '0 2px 8px rgba(0,0,0,0.15)',
          padding: '12px 16px',
          borderRadius: '16px 16px 16px 2px',
          marginBottom: '12px'
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
            <span style={{ fontSize: '10px', textTransform: 'uppercase', opacity: 0.6, fontWeight: 'bold' }}>Assistant</span>
            {exchange.response_memories[0]?.created_at && (
              <span style={{ fontSize: '10px', opacity: 0.5 }}>
                {formatTime(exchange.response_memories[0].created_at)}
              </span>
            )}
          </div>
          {exchange.response_memories.map((memory: any) => (
            <div key={memory.id} style={{ cursor: 'pointer', marginBottom: '8px' }} onClick={() => onSelectMemory(memory.id)}>
              <p style={{ margin: 0, fontSize: '14px', lineHeight: '1.5', whiteSpace: 'pre-wrap', fontFamily: formatMemoryContent(memory.content).startsWith('⚙️') ? 'monospace' : 'inherit', opacity: formatMemoryContent(memory.content).startsWith('⚙️') ? 0.6 : 1 }}>
                {formatMemoryContent(memory.content)}
              </p>
            </div>
          ))}
        </div>
      )}

      {/* Metadata toggles (OTel, Context, Exchange Info) */}
      <div style={{ display: 'flex', justifyContent: 'center', margin: '8px 0' }}>
        <button onClick={() => setShowMetadata(!showMetadata)} className="small-button" style={{ background: 'transparent', border: '1px dashed rgba(255,255,255,0.2)' }}>
          {showMetadata ? 'Hide Technical Details' : 'Show Technical Details'} (Exchange {exchange.sequence_number})
        </button>
      </div>

      {showMetadata && (
        <div className="exchange-metadata" style={{ padding: '16px', background: 'rgba(255,255,255,0.02)', borderRadius: '8px', fontSize: '12px', border: 'none', boxShadow: 'inset 0 1px 4px rgba(0,0,0,0.2)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '16px', opacity: 0.7 }}>
            <span>Latency: {exchange.latency_ms?.toFixed(0) ?? 'n/a'} ms</span>
            <span>Node ID: <Hash value={exchange.node_id} /></span>
          </div>

          {exchange.tool_calls.length > 0 && (
            <div style={{ margin: '16px 0' }}>
              <Section title="Tools and OTel Events" empty={false}>
                <OtelTree events={exchange.tool_calls} />
              </Section>
            </div>
          )}

          {exchange.context_contributions.length > 0 && (
            <div style={{ marginTop: '16px' }}>
              <Section title="Context Contributions" empty={false}>
                <div className="exchange-context-cards" style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                  {exchange.context_contributions.map((item: any) => (
                    <ContextContributionItem 
                      key={item.contribution_id} 
                      item={item} 
                      onSelectMemory={onSelectMemory} 
                    />
                  ))}
                </div>
              </Section>
            </div>
          )}
        </div>
      )}
    </article>
  )
}

function formatSessionLabel(session: Session) {
  const d = new Date(session.started_at + 'Z')
  const f = isNaN(d.getTime()) ? session.started_at : d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
  const s = session.external_session_id.substring(0, 8)
  return `${f} (${s})`
}

export default function App() {
  const [stats, setStats] = useState<Stats | null>(null)
  const [storeStatus, setStoreStatus] = useState<StoreStatus | null>(null)
  const [operations, setOperations] = useState<OperationsSnapshot | null>(null)
  const [integrityLinks, setIntegrityLinks] = useState<IntegrityLinksStatus | null>(null)
  const [sessions, setSessions] = useState<Session[]>([])
  const [selectedSessionId, setSelectedSessionId] = useState('')
  const [root, setRoot] = useState<MerkleRoot | null>(null)
  const [exchanges, setExchanges] = useState<Exchange[]>([])
  const [sessionReplay, setSessionReplay] = useState<SessionReplay | null>(null)
  const [graph, setGraph] = useState<GraphPayload | null>(null)
  const [similarityThreshold, setSimilarityThreshold] = useState(0.75)
  const [graphFilterIntent, setGraphFilterIntent] = useState<GraphFilterIntent>({ nonce: 0 })
  const [query, setQuery] = useState('')
  const [searchResults, setSearchResults] = useState<Memory[]>([])
  const [searchLoading, setSearchLoading] = useState(false)
  const [searchError, setSearchError] = useState<string | null>(null)
  const [selectedMemoryId, setSelectedMemoryId] = useState<string | null>(null)
  const [selectedGraphNode, setSelectedGraphNode] = useState<DemoNode | null>(null)
  const [activeTab, setActiveTab] = useState<Tab>('graph')
  const [contextBundle, setContextBundle] = useState<Memory[]>([])
  const [manifest, setManifest] = useState<InferenceManifest | null>(null)
  const [tasks, setTasks] = useState<InferenceTask[]>([])
  const [paraClassifications, setParaClassifications] = useState<ParaClassification[]>([])
  const [extractionProposals, setExtractionProposals] = useState<ExtractionProposal[]>([])
  const [extractionProposalStatus, setExtractionProposalStatus] = useState('proposed')
  const [taskStatus, setTaskStatus] = useState('pending')
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [isNavOpen, setIsNavOpen] = useState(false)

  const refreshOverview = () => {
    api.stats().then(setStats).catch((e) => setError(String(e)))
    api.status().then(setStoreStatus).catch((e) => setError(String(e)))
    api.operations().then(setOperations).catch((e) => setError(String(e)))
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
    const timer = setTimeout(() => {
      window.dispatchEvent(new Event('resize'))
    }, 250)
    return () => clearTimeout(timer)
  }, [isNavOpen, selectedMemoryId])

  useEffect(() => {
    api.graph(500, similarityThreshold).then(setGraph).catch((e) => setError(String(e)))
  }, [similarityThreshold])

  useEffect(() => {
    // Clear stale state and inspector panels when session changes
    setExchanges([])
    setSessionReplay(null)
    setRoot(null)
    setSelectedGraphNode((prev) => {
      if (prev && prev.type === 'session' && (prev.payload as Session)?.external_session_id === selectedSessionId) {
        return prev
      }
      return null
    })
    setSelectedMemoryId(null)
    
    if (!selectedSessionId) {
      return
    }
    api.sessionExchanges(selectedSessionId).then(setExchanges).catch(() => setExchanges([]))
    api.sessionReplay(selectedSessionId).then(setSessionReplay).catch(() => setSessionReplay(null))
    api.sessionMerkleRoot(selectedSessionId).then(setRoot).catch(() => setRoot(null))
  }, [selectedSessionId])

  useEffect(() => {
    if (!query.trim()) {
      setSearchResults([])
      setSearchLoading(false)
      setSearchError(null)
      return
    }
    setSearchLoading(true)
    setSearchError(null)
    const timeout = setTimeout(() => {
      api.search(query).then(setSearchResults).catch((error) => {
        setSearchResults([])
        setSearchError(String(error))
      }).finally(() => setSearchLoading(false))
    }, 200)
    return () => clearTimeout(timeout)
  }, [query])

  useEffect(() => {
    api.inferenceTasks(taskStatus).then(setTasks).catch(() => setTasks([]))
  }, [taskStatus])

  useEffect(() => {
    api.paraClassifications().then(setParaClassifications).catch(() => setParaClassifications([]))
  }, [tasks])

  useEffect(() => {
    api.extractionProposals(extractionProposalStatus).then(setExtractionProposals).catch(() => setExtractionProposals([]))
  }, [extractionProposalStatus, tasks])


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
    const rawId = id.startsWith('memory:') ? id.slice('memory:'.length) : id
    setSelectedMemoryId(rawId)
    const node = demoGraph.nodes.find((item) => item.id === `memory:${rawId}`)
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
      const inputPayload: Record<string, unknown> = { subject_type: subjectType, subject_id: subjectId }
      if (taskType === 'classify_para' && subjectType === 'memory') {
        const memory = await api.memory(subjectId)
        inputPayload.source_content_hash = memory.content_hash
      }
      const task = await api.requestInferenceTask({
        task_type: taskType,
        subject_type: subjectType,
        subject_id: subjectId,
        input_payload: inputPayload,
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
      }, undefined, task.claim_owner, task.claim_token)
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
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <button className="menu-button" onClick={() => setIsNavOpen((open) => !open)} type="button" style={{ background: 'none', border: 'none', color: 'inherit', fontSize: '1.4rem', cursor: 'pointer', padding: '4px 8px' }}>☰</button>
          <div>
            <h1>xibalba-cortex</h1>
            <p className="subhead">Local provenance graph memory for agent harnesses</p>
          </div>
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

      <div className={`shell ${isNavOpen ? 'nav-open' : 'nav-closed'} ${selectedMemoryId ? 'inspector-open' : 'inspector-closed'}`}>
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
              sessionReplay={sessionReplay}
              contextBundle={contextBundle}
              selectedSessionId={selectedSessionId}
              onRecord={handleRecordExchange}
              onSelectMemory={selectMemory}
              sessions={sessions}
              setSelectedSessionId={setSelectedSessionId}
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
              sessions={sessions}
              selectedSessionId={selectedSessionId}
              setSelectedSessionId={setSelectedSessionId}
            />
          )}
          {activeTab === 'recall' && (
            <RecallTab
              query={query}
              results={searchResults}
              contradictionCounts={contradictionCounts}
              searchLoading={searchLoading}
              searchError={searchError}
              onQuery={setQuery}
              onSelectMemory={selectMemory}
              onUseAsContext={addContext}
            />
          )}
          {activeTab === 'inference' && (
            <>
              <InferenceTab
                manifest={manifest}
                tasks={tasks}
                taskStatus={taskStatus}
                selectedMemoryId={selectedMemoryId}
                selectedSessionId={selectedSessionId}
                sessions={sessions}
                setSelectedSessionId={setSelectedSessionId}
                onStatus={setTaskStatus}
                onQueue={queueInference}
                onClaim={async (task) => {
                  await api.claimInferenceTask(task.id, 'viewer')
                  api.inferenceTasks(taskStatus).then(setTasks)
                }}
                onComplete={completeTask}
                onWriteBack={applyWriteBack}
              />
              <ParaPanel
                proposals={paraClassifications}
                onDecision={async (taskId, decision) => {
                  try {
                    await api.decidePara(taskId, decision)
                    setParaClassifications(await api.paraClassifications())
                    setNotice(`PARA proposal ${decision === 'accept' ? 'accepted' : decision === 'dismiss' ? 'dismissed' : 'kept original'}.`)
                  } catch (e) {
                    setError(String(e))
                  }
                }}
                onSelectMemory={selectMemory}
              />
            </>
          )}
          {activeTab === 'provenance' && (
            <>
              <ExtractionProposalsPanel
                proposals={extractionProposals}
                status={extractionProposalStatus}
                onStatusChange={setExtractionProposalStatus}
                onDecision={async (proposalId, decision) => {
                  try {
                    await api.decideExtractionProposal(proposalId, decision, 'viewer')
                    setExtractionProposals(await api.extractionProposals(extractionProposalStatus))
                    setNotice(`Extraction proposal ${decision === 'accept' ? 'accepted' : 'dismissed'}.`)
                  } catch (e) {
                    setError(String(e))
                  }
                }}
                onSelectMemory={selectMemory}
              />
              <RetrievalTraceInspector onSelectMemory={selectMemory} />
              <ProjectionHealthPanel />
            </>
          )}
          {activeTab === 'operations' && (
            <OperationsTab operations={operations} onRefresh={() => api.operations().then(setOperations).catch((e) => setError(String(e)))} />
          )}
          {activeTab === 'integrity' && (
            <IntegrityTab
              root={root}
              exchanges={exchanges}
              storeStatus={storeStatus}
              integrityLinks={integrityLinks}
              sessions={sessions}
              selectedSessionId={selectedSessionId}
              setSelectedSessionId={setSelectedSessionId}
            />
          )}
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
  sessionReplay,

  selectedSessionId,
  onRecord,
  onSelectMemory,
  sessions,
  setSelectedSessionId,
}: {
  exchanges: Exchange[]
  sessionReplay: SessionReplay | null
  contextBundle: Memory[]
  selectedSessionId: string
  onRecord: (event: FormEvent<HTMLFormElement>) => void
  onSelectMemory: (id: string) => void
  sessions: Session[]
  setSelectedSessionId: (id: string) => void
}) {
  return (
    <section className="tab-panel">
      <div className="panel-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          <h2>Timeline</h2>
          <select
            className="session-select"
            value={selectedSessionId}
            onChange={(event) => setSelectedSessionId(event.target.value)}
          >
            <option value="">No session</option>
            {sessions.map((session) => (
              <option key={session.id} value={session.external_session_id}>
                {formatSessionLabel(session)}
              </option>
            ))}
          </select>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          <p>{exchanges.length} exchanges</p>
          {exchanges.length === 0 && selectedSessionId && (
            <button type="button" onClick={() => {
              fetch(`/api/session/${encodeURIComponent(selectedSessionId)}/exchanges/build`, { method: 'POST' })
                .then(() => window.location.reload())
            }}>Build Exchanges</button>
          )}
        </div>
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

      {sessionReplay && (
        <section className="replay-panel" aria-label="Session replay">
          <div className="panel-header">
            <h3>Replay transcript</h3>
            <span className={`status-pill `}>
              {sessionReplay.replayable ? "complete" : `incomplete:  gap(s)`}
            </span>
          </div>
          <p className="small muted">Ordered prompts, responses, tool calls, results, and recorded timestamps. {sessionReplay.disclaimer}</p>
          <div className="replay-events">
            {sessionReplay.events.map((event) => (
              <div className="replay-event" key={`-`}>
                <span className="replay-index">{event.replay_index + 1}</span>
                <strong>{event.event_type}</strong>
                <time>{event.timestamp ?? "timestamp unavailable"}</time>
                {event.event_type === "prompt" || event.event_type === "response" ? (
                  <span>{event.content}</span>
                ) : (
                  <span>{event.tool_name}: {JSON.stringify(event.event_type === "tool_call" ? event.tool_input : event.tool_output)}</span>
                )}
              </div>
            ))}
          </div>
        </section>
      )}
      <div className="timeline">
        {exchanges.length === 0 ? (
          <div className="empty-state">
            <h4>No Exchanges Found</h4>
            <p>This session has no recorded conversational history. To populate this timeline, either run a connected agent harness or manually record an exchange.</p>
            {selectedSessionId && (
              <button type="button" onClick={() => {
                fetch(`/api/session/${encodeURIComponent(selectedSessionId)}/exchanges/build`, { method: 'POST' })
                  .then(() => window.location.reload())
              }}>Build Unstructured Exchanges</button>
            )}
          </div>
        ) : (
          exchanges.map((exchange) => (
            <CollapsibleExchange 
              key={exchange.id} 
              exchange={exchange} 
              onSelectMemory={onSelectMemory} 
            />
          ))
        )}
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
  sessions,
  selectedSessionId,
  setSelectedSessionId,
}: {
  graph: DemoGraph
  selectedNodeId: string | null
  similarityThreshold: number
  filterIntent: GraphFilterIntent
  onSimilarityThresholdChange: (threshold: number) => void
  onSelectNode: (node: DemoNode) => void
  onSelectMemory: (id: string) => void
  sessions: Session[]
  selectedSessionId: string
  setSelectedSessionId: (id: string) => void
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
  const [showGrid, setShowGrid] = useState(true)

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
  const selectedNodeLabel = selectedNodeId ? graph.nodes.find((node) => node.id === selectedNodeId)?.label : undefined
  const options: GraphViewOptions = { background, zoom, panX, panY, fitMode, fitNonce, showGrid }
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
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          <h2>3D Memory Graph</h2>
          <select
            className="session-select"
            value={selectedSessionId}
            onChange={(event) => setSelectedSessionId(event.target.value)}
          >
            <option value="">No session</option>
            {sessions.map((session) => (
              <option key={session.id} value={session.external_session_id}>
                {formatSessionLabel(session)}
              </option>
            ))}
          </select>
        </div>
        <p>
          {filteredGraph.nodes.length} of {graph.nodes.length} nodes · {filteredGraph.edges.length} of {graph.edges.length} links · click a node to zoom and inspect
        </p>
      </div>
      {selectedNodeHidden && <p className="graph-note">The selected node is hidden by the current node filter. Switch to all nodes or fit the full graph.</p>}
      {selectedEdgeHidden && <p className="graph-note">The selected edge is hidden by the current filters. Clear the edge selection or reset filters.</p>}
      <div className="graph3d-area">
        <div className="graph-overlay-tools">
          <select value={background} onChange={(event) => setBackground(event.target.value as GraphBackground)} title="Background">
            {backgroundOptions.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
          </select>
          <select value={nodeType} onChange={(event) => setNodeType(event.target.value as DemoNodeType | 'all')} title="Node type">
            {nodeTypes.map((type) => <option key={type} value={type}>{type === 'all' ? 'All nodes' : type}</option>)}
          </select>
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} title="Lifecycle Status">
            {statusOptions.map((status) => <option key={status} value={status}>{status === 'all' ? 'All statuses' : status}</option>)}
          </select>
          <select value={evidenceFilter} onChange={(event) => setEvidenceFilter(event.target.value)} title="Evidence Class">
            {evidenceOptions.map((item) => <option key={item} value={item}>{item === 'all' ? 'All evidence' : item}</option>)}
          </select>
          <select value={sourceKindFilter} onChange={(event) => setSourceKindFilter(event.target.value)} title="Source Kind">
            {sourceKindOptions.map((item) => <option key={item} value={item}>{item === 'all' ? 'All sources' : item}</option>)}
          </select>
          <select value={edgeType} onChange={(event) => setEdgeType(event.target.value)} title="Connection Type">
            {edgeTypes.map((type) => <option key={type} value={type}>{type === 'all' ? 'All connections' : `${connectionReference[type]?.label ?? type} (${edgeCounts.get(type) ?? 0})`}</option>)}
          </select>
          <select value={predicateFilter} onChange={(event) => setPredicateFilter(event.target.value)} title="Relation Predicate">
            {predicateOptions.map((predicate) => <option key={predicate} value={predicate}>{predicate === 'all' ? 'All predicates' : predicate}</option>)}
          </select>
          <input
            title={`Similarity Threshold: ${similarityThreshold.toFixed(2)}`}
            max="0.99"
            min="0.2"
            onChange={(event) => onSimilarityThresholdChange(Number(event.target.value))}
            step="0.01"
            type="range"
            value={similarityThreshold}
            style={{ width: '80px', pointerEvents: 'auto', alignSelf: 'center' }}
          />
          <div className="button-group">
            <button onClick={() => setShowGrid((v) => !v)} type="button" title="Toggle 3D Grid">🌐</button>
            <button onClick={() => setZoom((value) => Math.min(2.4, value + 0.18))} type="button" title="Zoom In">➕</button>
            <button onClick={() => setZoom((value) => Math.max(0.55, value - 0.18))} type="button" title="Zoom Out">➖</button>
            <button onClick={() => setPanX((value) => value - 18)} type="button" title="Pan Left">⬅</button>
            <button onClick={() => setPanX((value) => value + 18)} type="button" title="Pan Right">➡</button>
            <button onClick={() => setPanY((value) => value + 12)} type="button" title="Pan Up">⬆</button>
            <button onClick={() => setPanY((value) => value - 12)} type="button" title="Pan Down">⬇</button>
            <button onClick={() => refit('all')} type="button" title="Fit All">⛶</button>
            <button disabled={!selectedNodeId || selectedNodeHidden} onClick={() => refit('selected')} type="button" title="Fit Selected">🎯</button>
          </div>
        </div>
        <div className="graph-overlay-key" style={{ display: 'flex', flexDirection: 'column', gap: '8px', pointerEvents: 'auto', background: 'rgba(15, 23, 42, 0.85)', padding: '8px 12px', borderRadius: '6px', backdropFilter: 'blur(4px)', minWidth: '180px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px' }}>
            <span style={{ fontSize: '11px', fontWeight: 'bold', textTransform: 'uppercase', letterSpacing: '0.05em', opacity: 0.8 }}>Connections</span>
            <select
              value={edgeType}
              onChange={(e) => setEdgeType(e.target.value)}
              style={{ background: 'rgba(255,255,255,0.1)', border: 'none', borderRadius: '4px', color: '#fff', fontSize: '11px', padding: '2px 6px', cursor: 'pointer' }}
            >
              <option value="all" style={{ background: '#0f172a' }}>All Connections</option>
              {edgeTypes.map((type) => {
                if (type === 'all') return null
                return (
                  <option key={type} value={type} style={{ background: '#0f172a' }}>
                    {connectionReference[type]?.label ?? type} ({edgeCounts.get(type) ?? 0})
                  </option>
                )
              })}
            </select>
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
            {Object.entries(connectionReference).map(([type, info]) => {
              const count = edgeCounts.get(type) ?? 0
              if (count === 0) return null
              const isActive = edgeType === 'all' || edgeType === type
              return (
                <span
                  className={`edge-key ${type}`}
                  key={type}
                  onClick={() => setEdgeType(edgeType === type ? 'all' : type)}
                  style={{
                    cursor: 'pointer',
                    opacity: isActive ? 1 : 0.35,
                    userSelect: 'none',
                    transition: 'opacity 0.2s',
                    padding: '2px 8px',
                    borderRadius: '999px',
                    fontSize: '11px',
                    margin: 0
                  }}
                  title={`Filter by connection: ${info.detail}`}
                >
                  {info.label}
                </span>
              )
            })}
          </div>
        </div>
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
          <label style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
            From
            <input value={pathFrom} onChange={(event) => setPathFrom(event.target.value)} placeholder={selectedNodeLabel ?? 'Entity name'} />
            {selectedNodeLabel && (
              <button onClick={() => setPathFrom(selectedNodeLabel)} type="button" style={{ padding: '2px 6px', fontSize: '10px', whiteSpace: 'nowrap' }} title="Use selected node as From">Use Selected</button>
            )}
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
            To
            <input value={pathTo} onChange={(event) => setPathTo(event.target.value)} placeholder="Entity name" />
            {selectedNodeLabel && (
              <button onClick={() => setPathTo(selectedNodeLabel)} type="button" style={{ padding: '2px 6px', fontSize: '10px', whiteSpace: 'nowrap' }} title="Use selected node as To">Use Selected</button>
            )}
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
                {node.tags?.map((tag) => (
                  <Badge key={tag}>{tag}</Badge>
                ))}
              </div>
              <h3>Neighborhood</h3>
              {node.relatedIds?.map((id) => (
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
                      {item.prompt_memories?.map((prompt) => (
                        <button className="dense-block" key={prompt.id} onClick={() => onSelectMemory(prompt.id)}>
                          {prompt.content}
                        </button>
                      ))}
                    </div>
                    <div>
                      <h4>LLM Output</h4>
                      {item.response_memories?.map((response) => (
                        <button className="dense-block" key={response.id} onClick={() => onSelectMemory(response.id)}>
                          {response.content}
                        </button>
                      ))}
                    </div>
                    <div>
                      <h4>Context</h4>
                      {item.context_contributions?.map((context) => (
                        <button className="dense-block" key={context.contribution_id} onClick={() => context.memory?.id && onSelectMemory(context.memory.id)}>
                          <strong>{context.contribution_id}</strong> · {context.context_kind} ·{' '}
                          {context.relevance ?? 'n/a'}
                          <br />
                          {context.memory?.content ?? 'Missing memory content'}
                        </button>
                      ))}
                    </div>
                    <div>
                      <h4>Tool Calls</h4>
                      {!item.tool_calls || item.tool_calls.length === 0 ? (
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
  searchLoading,
  searchError,
  onQuery,
  onSelectMemory,
  onUseAsContext,
}: {
  query: string
  results: Memory[]
  contradictionCounts: Map<string, number>
  searchLoading: boolean
  searchError: string | null
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
        aria-label="Search memories"
      />
      {searchError ? (
        <div className="empty-state error-state" role="alert"><h4>Recall unavailable</h4><p>{searchError}</p></div>
      ) : searchLoading ? (
        <div className="empty-state" role="status"><h4>Searching memories…</h4><p>Checking active and confirmed memory records.</p></div>
      ) : query.trim() && results.length === 0 ? (
        <div className="empty-state" role="status"><h4>No matching memories</h4><p>Try a broader phrase or confirm that the memory is active.</p></div>
      ) : !query.trim() ? (
        <div className="empty-state"><h4>Search your memory graph</h4><p>Enter a phrase to find active and confirmed memories.</p></div>
      ) : (
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
      )}
    </section>
  )
}

function ParaPanel({
  proposals,
  onDecision,
  onSelectMemory,
}: {
  proposals: ParaClassification[]
  onDecision: (taskId: string, decision: 'accept' | 'dismiss' | 'keep_original') => void
  onSelectMemory: (memoryId: string) => void
}) {
  return (
    <section className="tab-panel">
      <div className="panel-header">
        <div>
          <h2>PARA review</h2>
          <p>Derived organization suggestions. Nothing moves automatically.</p>
        </div>
        <Badge>{proposals.length} proposed</Badge>
      </div>
      {proposals.length === 0 ? (
        <div className="empty-state"><h4>No PARA proposals</h4><p>Queue a PARA classification for a selected memory.</p></div>
      ) : (
        <div className="item-list">
          {proposals.map((proposal) => (
            <article className="item" key={proposal.task_id}>
              <div className="item-head"><strong>{proposal.category}</strong><Badge>{proposal.confidence.toFixed(2)} confidence</Badge></div>
              <p>{proposal.rationale}</p>
              <p className="small muted">source hash <Hash value={proposal.source_content_hash} /></p>
              {proposal.signals.length > 0 && <p className="small muted">signals: {proposal.signals.join(', ')}</p>}
              <div className="action-row">
                <button type="button" onClick={() => onSelectMemory(proposal.memory_id)}>Inspect source</button>
                <button type="button" onClick={() => onDecision(proposal.task_id, 'accept')}>Accept</button>
                <button type="button" onClick={() => onDecision(proposal.task_id, 'keep_original')}>Keep original</button>
                <button type="button" onClick={() => onDecision(proposal.task_id, 'dismiss')}>Dismiss</button>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  )
}

function InferenceTab({
  manifest,
  tasks,
  taskStatus,
  selectedMemoryId,
  selectedSessionId,
  sessions,
  setSelectedSessionId,
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
  sessions: Session[]
  setSelectedSessionId: (id: string) => void
  onStatus: (status: string) => void
  onQueue: (subjectType: string, subjectId: string, taskType: string) => void
  onClaim: (task: InferenceTask) => void
  onComplete: (task: InferenceTask) => void
  onWriteBack: (action: string, payload: Record<string, unknown>) => void
}) {
  const defaultTask = manifest?.task_types[0] ?? 'extract_memory_metadata'
  const [selectedTaskType, setSelectedTaskType] = useState(defaultTask)

  return (
    <section className="tab-panel two-column">
      <div>
        <div className="panel-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
            <h2>Inference</h2>
            <select
              className="session-select"
              value={selectedSessionId}
              onChange={(event) => setSelectedSessionId(event.target.value)}
            >
              <option value="">No session</option>
              {sessions.map((session) => (
                <option key={session.id} value={session.external_session_id}>
                  {formatSessionLabel(session)}
                </option>
              ))}
            </select>
          </div>
          <p>{manifest?.name ?? 'xibalba-memory-inference'}</p>
        </div>
        {manifest && (
          <div className="manifest">
            <p>{manifest.role}</p>
            <p className="small muted">{manifest.input_rule}</p>
            <p className="small muted">{manifest.output_rule}</p>
            <div className="badges" style={{ marginTop: '12px' }}>
              <select
                value={selectedTaskType}
                onChange={(e) => setSelectedTaskType(e.target.value)}
                style={{ padding: '4px', borderRadius: '4px' }}
              >
                {manifest.task_types.map((type) => (
                  <option key={type} value={type}>{type}</option>
                ))}
              </select>
            </div>
          </div>
        )}
        <div className="action-row">
          <button disabled={!selectedMemoryId} onClick={() => selectedMemoryId && onQueue('memory', selectedMemoryId, selectedTaskType)}>
            Queue selected memory
          </button>
          <button disabled={!selectedSessionId} onClick={() => onQueue('session', selectedSessionId, selectedTaskType)}>
            Queue selected session
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

function OperationsTab({ operations, onRefresh }: { operations: OperationsSnapshot | null; onRefresh: () => void }) {
  if (!operations) return <section className="tab-panel"><h2>Operations</h2><p className="muted">Loading operational evidence...</p></section>
  const status = operations.health.status
  const coverage = operations.embedding_coverage as Record<string, unknown>
  const audit = operations.audit as Record<string, unknown>
  const taskStates = (audit.inference_task_states as Record<string, number> | undefined) || {}
  const proposalStates = (audit.proposal_states as Record<string, number> | undefined) || {}
  return <section className="tab-panel">
    <div className="panel-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}><div><h2>Operations</h2><p className="muted">Profile <code>{operations.profile_id}</code> · local control-plane evidence</p></div><button className="small-button" onClick={onRefresh} type="button">Refresh</button></div>
    <div className="card-grid">
      <section className="panel-card"><h3>Deployment health</h3><div className="badges"><Badge>{operations.health.state}</Badge><Badge>{operations.readiness.state}</Badge><Badge>{status.journal_mode}</Badge></div><dl className="detail-list"><dt>Schema</dt><dd>{status.schema_version}</dd><dt>Integrity</dt><dd>{status.integrity_check}</dd><dt>Foreign keys</dt><dd>{String(status.foreign_keys)}</dd><dt>FTS5</dt><dd>{String(status.fts5)}</dd><dt>Backup</dt><dd>{status.backup_ready ? "ready" : "pending"}</dd></dl></section>
      <section className="panel-card"><h3>Resources</h3><div className="badges"><Badge>{"memories: " + status.memory_count}</Badge><Badge>{"quota: " + (operations.quotas.max_memories === null ? "unlimited" : operations.quotas.max_memories)}</Badge></div><dl className="detail-list"><dt>Embedded</dt><dd>{String(coverage.current || 0)} / {String(coverage.eligible || 0)}</dd><dt>Missing</dt><dd>{String(coverage.missing || 0)}</dd><dt>Stale</dt><dd>{String(coverage.stale || 0)}</dd><dt>Failed</dt><dd>{String(coverage.failed || 0)}</dd></dl></section>
      <section className="panel-card"><h3>Feature policy</h3><div className="connector-grid">{Object.entries(operations.features).map(([name, enabled]) => <div className="connector-row" key={name}><strong>{name}</strong><Badge>{enabled ? "enabled" : "disabled"}</Badge></div>)}</div><p className="small muted">Configured per profile; disabled capabilities fail closed at their API boundary.</p></section>
      <section className="panel-card"><h3>Inference governance</h3><dl className="detail-list">{Object.entries(taskStates).map(([key, value]) => <><dt key={key + "-label"}>{key}</dt><dd key={key + "-value"}>{value}</dd></>)}{Object.entries(proposalStates).map(([key, value]) => <><dt key={"proposal-" + key + "-label"}>proposal {key}</dt><dd key={"proposal-" + key + "-value"}>{value}</dd></>)}</dl>{Object.keys(taskStates).length === 0 && <p className="muted">No inference tasks recorded.</p>}</section>
    </div>
    <section className="panel-card"><h3>Connectors</h3><div className="connector-grid">{Object.entries(operations.connectors).map(([name, connector]) => <div className="connector-row" key={name}><div><strong>{name}</strong><div className="small muted">{connector.entrypoint}</div></div><Badge>{connector.state}</Badge></div>)}</div></section>
    <p className="small muted">{operations.disclaimer}</p>
  </section>
}

function IntegrityTab({
  root,
  exchanges,
  storeStatus,
  integrityLinks,
  sessions,
  selectedSessionId,
  setSelectedSessionId,
}: {
  root: MerkleRoot | null
  exchanges: Exchange[]
  storeStatus: StoreStatus | null
  integrityLinks: IntegrityLinksStatus | null
  sessions: Session[]
  selectedSessionId: string
  setSelectedSessionId: (id: string) => void
}) {
  const linkStates = integrityLinks?.states ? Object.entries(integrityLinks.states) : []
  return (
    <section className="tab-panel">
      <div className="panel-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          <h2>Integrity</h2>
          <select
            className="session-select"
            value={selectedSessionId}
            onChange={(event) => setSelectedSessionId(event.target.value)}
          >
            <option value="">No session</option>
            {sessions.map((session) => (
              <option key={session.id} value={session.external_session_id}>
                {formatSessionLabel(session)}
              </option>
            ))}
          </select>
        </div>
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
          <strong data-tooltip="Integrity head for the session graph; proves structure and byte lineage">Session Merkle Root</strong>
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
      
      {exchanges.length === 0 ? (
        <div className="empty-state">
          <h4>No Graph Nodes</h4>
          <p>This session has no exchanges recorded in the cryptographic DAG.</p>
        </div>
      ) : (
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
      )}
    </section>
  )
}
