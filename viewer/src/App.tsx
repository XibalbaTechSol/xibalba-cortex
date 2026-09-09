import React, { useCallback, useEffect, useMemo, useState } from "react"
import type { ChangeEvent, FormEvent, ReactNode } from 'react'
import {
  Database,
  Layers,
  Network,
  ShieldCheck,
  CheckCircle2,
  Cpu,
  HardDrive,
  Server,
  Clock,
  Sparkles,
  ChevronRight,
  Search,
  ArrowUpRight,
  LayoutDashboard,
  MessageSquare,
  GitFork,
  Sliders,
  Settings,
  ChevronLeft,
  Send,
  Terminal,
  User,
  RefreshCw,
  Copy,
  Check,
  Key,
  LogOut
} from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import {
  api,
  accountAuth,
  accountMe,
  accountLogout,
  accountChangePassword,
  accountSessions,
  accountRevokeSession,
  accountEvents,
  getApiToken,
  getApiBaseUrl,
  setApiBaseUrl,
  setApiToken,
  type Attachment,
  type EntityRelation,
  type Exchange,
  type ExtractionProposal,
  type GraphNode,
  type GraphPayload,
  type IntegrityLinksStatus,
  type InferenceManifest,
  type InferenceSettings,
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
import { Graph2DView } from './Graph2DView'
import { ProvenanceTab } from './ProvenancePanels'
import { MermaidDiagram } from './components/MermaidDiagram'
import './index.css'

type Tab = 'overview' | 'timeline' | 'graph' | 'recall' | 'inference' | 'provenance' | 'integrity' | 'operations' | 'settings'
type GraphFilterIntent = { nonce: number; status?: string; evidence?: string }
// The API returns a bounded memory sample plus relation endpoints. Keep the canvas projection
// intentionally small enough that session changes remain interactive; Recall remains the path
// for searching the complete memory store.
const GRAPH_RENDER_LIMIT = 1
const GRAPH_SESSION_LIMIT = 20

const tabs: Array<{ id: Tab; label: string; icon: React.ComponentType<{ size?: number; className?: string }> }> = [
  { id: 'overview', label: 'Overview', icon: LayoutDashboard },
  { id: 'timeline', label: 'Timeline', icon: MessageSquare },
  { id: 'graph', label: 'Graph', icon: Network },
  { id: 'recall', label: 'Recall', icon: Search },
  { id: 'inference', label: 'Inference', icon: Cpu },
  { id: 'provenance', label: 'Provenance', icon: GitFork },
  { id: 'integrity', label: 'Integrity Audit', icon: ShieldCheck },
  { id: 'operations', label: 'Operations', icon: Sliders },
]

import { Badge, Hash, Skeleton, EmptyState, ToastContainer, useToast } from './components/shared'
export { Badge, Hash, Skeleton, EmptyState, ToastContainer }

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

  const visibleSessions = sessions.filter((session) => session.external_session_id === selectedSessionId || sessions.indexOf(session) < GRAPH_SESSION_LIMIT)
  visibleSessions.forEach((session) => {
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
    api.attachments(item.memory.id)
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
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
        <button className="list-button" type="button" onClick={() => item.memory?.id && onSelectMemory(item.memory.id)} style={{ fontWeight: '600', padding: '4px 8px' }}>
          {item.contribution_id} · {item.context_kind} (Relevance: {item.relevance ?? 'n/a'})
        </button>
        {item.memory?.id && <span className="muted" >Memory ID: {item.memory.id.slice(0, 8)}</span>}
      </div>

      <p style={{ margin: '0 0 8px 0', lineHeight: '1.4', whiteSpace: 'pre-wrap', color: 'var(--text-muted)' }}>
        {item.memory?.content?.replace(/\\n/g, '\n').replace(/\\"/g, '"') ?? 'Memory content unavailable'}
      </p>

      {attachments.length > 0 && (
        <div className="attachments-grid" style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginTop: '8px' }}>
          {attachments.map((att) => {
            const isImage = att.media_type && att.media_type.startsWith('image/')
            return (
              <div key={att.id} className="attachment-item" style={{
                background: 'rgba(0,0,0,0.2)',
                border: '1px solid rgba(255,255,255,0.05)',
                borderRadius: '6px',
                padding: '8px',
                width: '100%',
                maxWidth: '220px' }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                  <span className="badge" style={{ alignSelf: 'flex-start' }}>{att.media_type}</span>
                  {isImage ? <AttachmentImage attachment={att} /> : <AttachmentDownload attachment={att} />}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function useAttachmentUrl(attachmentId: string) {
  const [url, setUrl] = useState('')
  useEffect(() => {
    let objectUrl = ''
    api.attachmentFile(attachmentId).then((blob) => {
      objectUrl = URL.createObjectURL(blob)
      setUrl(objectUrl)
    }).catch(() => setUrl(''))
    return () => {
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [attachmentId])
  return url
}

function AttachmentImage({ attachment }: { attachment: Attachment }) {
  const url = useAttachmentUrl(attachment.id)
  return url
    ? <img src={url} alt="Attachment preview" style={{ maxWidth: '100%', maxHeight: '120px', borderRadius: '4px', marginTop: '4px', objectFit: 'contain' }} />
    : <span className="muted">Loading preview…</span>
}

function AttachmentDownload({ attachment }: { attachment: Attachment }) {
  const url = useAttachmentUrl(attachment.id)
  return url
    ? <a href={url} download style={{ color: 'var(--brand)', textDecoration: 'underline', marginTop: '4px', wordBreak: 'break-all' }}>Download file ({attachment.byte_size} bytes)</a>
    : <span className="muted">Preparing download…</span>
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
          borderRadius: '4px' }}
      >
        <span style={{ width: '12px', display: 'inline-block', color: 'var(--text-muted)' }}>
          {children.length > 0 ? (collapsed ? '▶' : '▼') : '•'}
        </span>
        <span className="badge" style={{ background: 'rgba(245, 158, 11, 0.15)', color: '#fbbf24', border: 'none', padding: '3px 8px', borderRadius: '4px' }}>
          {event.kind}
        </span>
        <strong style={{ color: '#e2e8f0' }}>{event.name}</strong>
        {startTimeStr && <span className="muted" >[{startTimeStr}]</span>}
      </div>

      {!collapsed && (
        <div style={{ marginTop: '4px', paddingLeft: '12px' }}>
          {event.attributes && Object.keys(event.attributes).length > 0 && (
            <pre style={{
              margin: '4px 0',
              padding: '6px 8px',
              background: 'rgba(0,0,0,0.3)',
              borderRadius: '4px',
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

// @ts-ignore -- retained legacy component pending timeline consolidation
export function CollapsibleExchange({
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
            <span style={{ textTransform: 'uppercase', opacity: 0.6, fontWeight: 'bold' }}>User</span>
            <span style={{ opacity: 0.5 }}>{timestamp}</span>
          </div>
          {exchange.prompt_memories.map((memory: any) => (
            <div key={memory.id} style={{ cursor: 'pointer' }} onClick={() => onSelectMemory(memory.id)}>
              <p style={{ margin: 0, lineHeight: '1.5', whiteSpace: 'pre-wrap' }}>
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
            <span style={{ textTransform: 'uppercase', opacity: 0.6, fontWeight: 'bold' }}>Assistant</span>
            {exchange.response_memories[0]?.created_at && (
              <span style={{ opacity: 0.5 }}>
                {formatTime(exchange.response_memories[0].created_at)}
              </span>
            )}
          </div>
          {exchange.response_memories.map((memory: any) => (
            <div key={memory.id} style={{ cursor: 'pointer', marginBottom: '8px' }} onClick={() => onSelectMemory(memory.id)}>
              <p style={{ margin: 0, lineHeight: '1.5', whiteSpace: 'pre-wrap', fontFamily: formatMemoryContent(memory.content).startsWith('⚙️') ? 'monospace' : 'inherit', opacity: formatMemoryContent(memory.content).startsWith('⚙️') ? 0.6 : 1 }}>
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
        <div className="exchange-metadata" style={{ padding: '16px', background: 'rgba(255,255,255,0.02)', borderRadius: '8px', border: 'none', boxShadow: 'inset 0 1px 4px rgba(0,0,0,0.2)' }}>
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
  const [token, setToken] = useState(() =>
    new URLSearchParams(window.location.search).get('landing')
      ? ''
      : import.meta.env.DEV
      ? 'local-dev-proxy'
      : getApiToken()
  )
  const [entry, setEntry] = useState<'landing' | 'signin'>('landing')
  const [mode, setMode] = useState<'login' | 'signup' | 'token'>('login')
  const [authError, setAuthError] = useState(()=>sessionStorage.getItem('xibalba-cortex.auth-notice') || '')
  const [authenticating, setAuthenticating] = useState(false)
  if (token) return <><AuthenticatedApp /><ToastContainer /></>
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const endpoint = String(form.get('endpoint') || '').trim()
    setAuthenticating(true); setAuthError(''); setApiBaseUrl(endpoint)
    try {
      if (mode === 'token') {
        setApiToken(String(form.get('token') || '').trim())
        await api.status()
      } else {
        const payload = await accountAuth(mode, { email: String(form.get('email') || ''), password: String(form.get('password') || ''), display_name: String(form.get('displayName') || '') })
        const me = await accountMe()
        sessionStorage.setItem('xibalba-cortex.account', JSON.stringify({ ...(me.account ?? payload.account), session_expires_at: me.session_expires_at }))
        await api.status()
      }
      setToken(getApiToken())
    } catch (error) { setApiToken(''); setAuthError(error instanceof Error ? error.message : String(error)) }
    finally { setAuthenticating(false) }
  }
  if (entry === 'landing') return <CortexLanding connect={() => {
    sessionStorage.removeItem('xibalba-cortex.auth-notice')
    if (import.meta.env.DEV) {
      setToken('local-dev-proxy')
      return
    }
    setEntry('signin')
  }} />
  return <main className="cortex-auth"><button className="cortex-auth-back" onClick={()=>setEntry('landing')}>← Back to Cortex</button><section className="cortex-auth-story"><CortexBrand/><div><p className="cortex-kicker">PRIVATE BY ARCHITECTURE</p><h1>Your agents' memory.<br/>Under your control.</h1><p>Connect to a local Cortex profile and inspect the provenance behind every remembered fact.</p></div><aside><span>⌁</span><div><b>Session-scoped access</b><small>Your endpoint and credentials stay in this tab.</small></div></aside></section><section className="cortex-auth-form"><form onSubmit={submit}><span className="cortex-lock">⌘</span><div className="auth-tabs"><button type="button" className={mode==='login'?'active':''} onClick={()=>setMode('login')}>Sign in</button><button type="button" className={mode==='signup'?'active':''} onClick={()=>setMode('signup')}>Create account</button></div><h2>{mode==='signup'?'Create your Cortex account':mode==='token'?'Connect with bearer token':'Connect to Cortex'}</h2><p>{mode==='signup'?'Create a local operator account for this Cortex profile.':'Use your account credentials or an existing bearer token.'}</p><label>Profile endpoint<input name="endpoint" type="url" defaultValue={getApiBaseUrl()} required/></label>{mode !== 'token' ? <><label>Email<input name="email" type="email" autoFocus required/></label>{mode==='signup'&&<label>Display name<input name="displayName" required/></label>}<label>Password<input name="password" type="password" minLength={10} required/></label><button type="button" className="advanced" onClick={()=>setMode('token')}>Use bearer token instead</button></> : <><label>Bearer token<input name="token" type="password" autoFocus required/></label><button type="button" className="advanced" onClick={()=>setMode('login')}>Use account sign in</button></>}{authError&&<div className="auth-error">{authError}</div>}<button className="cortex-cta auth-submit" type="submit" disabled={authenticating}>{authenticating?'Connecting…':mode==='signup'?'Create account':'Enter workspace'} <span>→</span></button><small className="auth-security">◇ Session-only credentials · <button type="button" className="link-button" onClick={()=>setAuthError('Password reset is not configured for this local deployment yet.')}>Forgot password?</button></small></form><small className="auth-page-footer">© 2026 Xibalba Technology Solutions · Local-first memory infrastructure</small></section></main>
}
function CortexLanding({ connect }: { connect: () => void }) {
  const memoryFlow = `flowchart LR
    A[Prompts · responses · tools] --> B[Canonical exchange journal]
    B --> C[Source-linked memories]
    C --> D{Configurable inference}
    D --> E[Entities and relations]
    D --> F[PARA classification]
    D --> G[Contradiction proposals]
    E --> H[Reviewable knowledge graph]
    F --> H
    G --> H
    H --> I[Bounded recall and context]
    I -. retrieval trace .-> B`
  const causalFlow = `flowchart LR
    A[Observed sequence] --> B[Candidate relationship]
    B --> C{Temporal order?}
    C -->|no| D[Reject or relabel]
    C -->|yes| E[Search alternatives]
    E --> F[Check contradictions]
    F --> G[Add intervention evidence]
    G --> H[Human-reviewed hypothesis]
    H --> I[Versioned claim]
    I -. never promoted automatically .-> B`
  const comparison = [
    ['Memory model', 'Canonical exchanges plus derived, evidence-linked graph', 'Managed memory layer; graph capabilities depend on edition', 'Temporal context graph', 'Persistent editable memory blocks', 'Thread checkpoints plus namespaced long-term store'],
    ['Timeline', 'Ordered exchanges, events, replay, and explicit replay gaps', 'Memory history and filters', 'Bi-temporal facts and episodes', 'Agent message history with block state', 'Checkpoint history, replay, fork, and resume'],
    ['Organization', 'PARA proposals: projects, areas, resources, archives', 'Custom categories and metadata', 'Entities, episodes, communities, and edges', 'Named blocks attached to one or more agents', 'Application-defined JSON namespaces'],
    ['Retrieval', 'Lexical, vector, graph, provenance, and bounded context channels', 'Semantic retrieval with filters', 'Hybrid semantic, keyword, and graph search', 'Agent-managed block recall', 'Developer-defined store and retrieval strategy'],
    ['Inference control', 'Per-task providers, thresholds, review gates, and degraded-state reporting', 'Configurable extraction and categories', 'Developer-defined extraction and graph rules', 'Agent/model edits memory blocks', 'Developer implements extraction and consolidation'],
    ['Provenance', 'Snapshot hash, evidence quote, proposal lifecycle, and retrieval trace', 'Memory metadata and history', 'Episode and temporal source context', 'Block versions and message history', 'Checkpoint and store metadata'],
    ['Causal analysis', 'Review workflow over timing, paths, contradictions, and intervention evidence', 'Not a core documented primitive', 'Graph paths and temporal facts support investigation', 'Not a core documented primitive', 'Application-defined'],
    ['MCP boundary', 'Native stdio and authenticated HTTP with profile tool allowlists', 'Separate integrations and APIs', 'Library and service APIs', 'MCP server and SDK ecosystem', 'MCP through application integrations'],
  ]

  return <main className="cortex-landing">
    <header className="cortex-header"><nav className="cortex-site-nav" aria-label="Main navigation"><a href="#top" className="cortex-brand-link"><CortexBrand/></a><div className="cortex-links"><a href="#memory">Memory</a><a href="#inference">Inference</a><a href="#timeline">Timeline + PARA</a><a href="#mcp">MCP</a><a href="#compare">Compare</a></div><div><button className="ghost-cta" onClick={connect}>Sign in</button><button className="cortex-cta" onClick={connect}>Open workspace <span>→</span></button></div></nav></header>
    <section className="cortex-hero" id="top"><div className="cortex-hero-copy"><img src="/brain-logo.jpg" alt="Cortex Logo" className="cortex-hero-logo" /><p className="cortex-kicker"><span/> PROVENANCE-FIRST AGENT MEMORY</p><h1>Memory you can<br/><em>trace and trust.</em></h1><p>Xibalba Cortex turns every agent exchange into inspectable, retrieval-ready knowledge—without losing its source, context, or chain of evidence.</p><div className="cortex-actions"><button className="cortex-cta large" onClick={connect}>Explore your memory graph <span>→</span></button><a href="#memory">See how memory works</a></div><div className="cortex-trust"><span>✓ Local-first storage</span><span>✓ Source-linked history</span><span>✓ Bounded retrieval</span></div></div><div className="memory-visual"><div className="grid-plane"/><div className="memory-node node-core"><i>C</i><b>Active context</b><small>bounded recall</small></div><div className="memory-node node-a"><i>01</i><b>User intent</b><small>source linked</small></div><div className="memory-node node-b"><i>02</i><b>Entity relation</b><small>reviewed</small></div><div className="memory-node node-c"><i>03</i><b>Agent response</b><small>traceable</small></div><svg viewBox="0 0 600 430"><path d="M118 112 C240 90 250 200 310 215"/><path d="M310 215 C400 165 430 95 520 110"/><path d="M310 215 C390 275 400 350 495 350"/></svg></div></section>
    <section className="cortex-proof" aria-label="Cortex architectural properties"><div><b>Canonical</b><span>SQLite event record</span></div><div><b>Source-aware</b><span>derived knowledge</span></div><div><b>Replayable</b><span>agent sessions</span></div><div><b>Inspectable</b><span>retrieval context</span></div></section>

    <section className="cortex-story" id="memory"><div className="cortex-section-heading"><div><p className="cortex-kicker">HOW KNOWLEDGE BECOMES MEMORY</p><h2>Keep the source. Derive the intelligence.</h2></div><p>Cortex stores the original exchange as the canonical record, then builds reviewable projections around it. Entities, relations, PARA labels, and contradictions point back to the memory and evidence that produced them, so enrichment does not overwrite history.</p></div><MermaidDiagram chart={memoryFlow} label="Cortex ingestion, inference, knowledge graph, and retrieval flow"/><div className="cortex-detail-grid"><article><span>01</span><h3>Capture complete exchanges</h3><p>Prompts, responses, tool activity, attachments, contributed context, session identity, and timestamps remain connected instead of becoming isolated snippets.</p></article><article><span>02</span><h3>Build derived knowledge</h3><p>Inference workers propose metadata, entities, relations, PARA placement, and contradictions. The canonical memory remains unchanged while proposals move through validation and review.</p></article><article><span>03</span><h3>Recall with boundaries</h3><p>Context assembly can combine lexical, vector, graph, and provenance channels under explicit limits. Retrieval traces explain which memories were selected and why.</p></article></div><p className="cortex-boundary"><ShieldCheck size={15}/> Local hash chains and Merkle evidence demonstrate internal byte lineage and tamper evidence. They do not prove that a statement is true or externally finalized.</p></section>

    <section className="cortex-story cortex-tinted" id="inference"><div className="cortex-section-heading"><div><p className="cortex-kicker">CONFIGURABLE INFERENCE</p><h2>Add high-value metadata without surrendering control.</h2></div><p>Operators decide which inference tasks run, which provider handles each task, how confident a proposal must be, and when human review is required. Validation remains server-side: stale snapshots, unsupported output, and evidence quotes that do not match the source are rejected.</p></div><div className="inference-console"><div className="inference-tasks"><span>Inference task</span>{['Memory metadata','Entity extraction','Relation extraction','PARA classification','Contradiction detection'].map((task, index)=><div key={task}><i>{String(index + 1).padStart(2,'0')}</i><b>{task}</b><small>{index < 2 ? 'local provider · review' : 'routed provider · threshold'}</small></div>)}</div><div className="inference-policy"><p>Effective policy</p><dl><div><dt>Provider routing</dt><dd>Per task</dd></div><div><dt>Promotion</dt><dd>Proposal only</dd></div><div><dt>Evidence</dt><dd>Quote + snapshot hash</dd></div><div><dt>Failure mode</dt><dd>Visible degradation</dd></div></dl><button className="cortex-cta" onClick={connect}>Configure inference →</button></div></div></section>

    <section className="cortex-story" id="timeline"><div className="cortex-section-heading"><div><p className="cortex-kicker">TIMELINE · PARA · CORRELATION</p><h2>See what happened, what it belongs to, and what connects it.</h2></div><p>The timeline preserves sequence across sessions and exchanges. PARA turns inferred context into reviewable projects, areas, resources, or archives. Correlation connects recurring people, systems, decisions, and contradictions across time without silently turning correlation into causation.</p></div><div className="timeline-layout"><ol className="timeline-demo"><li><time>09:14</time><div><b>Requirement captured</b><span>Session exchange · source intact</span></div></li><li><time>09:18</time><div><b>Project relation proposed</b><span>PARA: Project · confidence 0.88</span></div></li><li><time>11:42</time><div><b>Conflicting constraint detected</b><span>Review required · two evidence links</span></div></li><li><time>14:07</time><div><b>Context recalled</b><span>Graph + lexical · retrieval trace recorded</span></div></li></ol><div className="para-grid">{[['P','Projects','Active outcomes with a finish line.'],['A','Areas','Ongoing responsibilities to maintain.'],['R','Resources','Reference knowledge for future work.'],['A','Archives','Inactive material retained for lineage.']].map(([letter,title,copy])=><article key={title}><span>{letter}</span><div><h3>{title}</h3><p>{copy}</p></div></article>)}</div></div></section>

    <section className="cortex-story cortex-tinted" id="mcp"><div className="cortex-section-heading"><div><p className="cortex-kicker">MCP AS A CONTROLLED MEMORY PORT</p><h2>Expose exactly the memory capabilities each agent needs.</h2></div><p>Cortex serves Model Context Protocol over local stdio or authenticated streamable HTTP. Profile-bound credentials and tool allowlists let operators separate read, write, proposal-decision, inference, and runtime-controller capabilities instead of exposing one universal memory endpoint.</p></div><div className="mcp-grid"><article><Terminal/><h3>Choose the transport</h3><p>Use stdio for local agent processes or authenticated HTTP for remote-capable clients. Deployment TLS and ingress remain an operator responsibility.</p></article><article><Key/><h3>Bind identity and scope</h3><p>Issue profile-specific tokens with memory read, memory write, or proposal-decision scope. Browser credentials remain session scoped.</p></article><article><Sliders/><h3>Allow only required tools</h3><p>Publish a narrow MCP surface for each runtime or worker. An extraction process does not need operational controls, and a reader does not need mutation tools.</p></article></div></section>

    <section className="cortex-story" id="causal"><div className="cortex-section-heading"><div><p className="cortex-kicker">CAUSAL INVESTIGATION</p><h2>Turn graph connections into testable hypotheses—not automatic claims.</h2></div><p>Cortex can help investigators assemble timing, graph paths, contradictions, and intervention evidence around a possible cause. The workflow is deliberately conservative: a connected or correlated event is not labeled causal without stronger evidence and review.</p></div><MermaidDiagram chart={causalFlow} label="Cortex causal hypothesis investigation and review flow"/><p className="cortex-boundary"><GitFork size={15}/> Causal relations are an investigation and review workflow built from existing evidence. Cortex does not automatically assert that correlation proves causation.</p></section>

    <section className="cortex-story cortex-tinted" id="compare"><div className="cortex-section-heading"><div><p className="cortex-kicker">PROVIDER LANDSCAPE</p><h2>Different memory systems optimize for different jobs.</h2></div><p>This descriptive matrix compares documented product models—not benchmark performance. Deployment model, edition, and custom implementation can materially change each capability.</p></div><div className="cortex-comparison-scroll"><table><thead><tr><th>Capability</th><th className="cortex-column">Cortex</th><th><a href="https://docs.mem0.ai/platform/overview" target="_blank" rel="noreferrer">Mem0 ↗</a></th><th><a href="https://help.getzep.com/graphiti/getting-started/overview" target="_blank" rel="noreferrer">Zep / Graphiti ↗</a></th><th><a href="https://docs.letta.com/tutorials/attaching-detaching-blocks/" target="_blank" rel="noreferrer">Letta ↗</a></th><th><a href="https://docs.langchain.com/oss/python/concepts/memory" target="_blank" rel="noreferrer">LangGraph ↗</a></th></tr></thead><tbody>{comparison.map(([capability,...cells])=><tr key={capability}><th>{capability}</th>{cells.map((cell,index)=><td key={cell + index} className={index===0?'cortex-column':''}>{cell}</td>)}</tr>)}</tbody></table></div><small>Source links point to each provider’s official documentation. Verify current edition and deployment details before selection.</small></section>

    <section className="cortex-banner" id="provenance"><div><p className="cortex-kicker">MEMORY WITH A RECEIPT</p><h2>Build agents that can explain what they remember.</h2><p>Start with the original exchange. Follow every proposal, retrieval, and decision from there.</p></div><button onClick={connect}>Connect to Cortex →</button></section>
    <footer className="cortex-footer"><div><CortexBrand/><p>Provenance-first memory infrastructure for autonomous systems.</p></div><div><b>Explore</b><a href="#memory">Knowledge graph</a><a href="#inference">Inference</a><a href="#timeline">Timeline + PARA</a></div><div><b>Connect</b><a href="#mcp">MCP</a><a href="#causal">Causal investigation</a><a href="#compare">Provider comparison</a></div><small>© 2026 Xibalba Technology Solutions</small></footer>
  </main>
}
function CortexBrand(){return <div className="cortex-brand"><img src="/brain-logo.jpg" alt="Xibalba Cortex"/><b>Xibalba <i>Cortex</i></b></div>}

function CortexOverview({
  stats,
  status,
  operations,
  sessions,
  onOpen,
  onSelectSession,
}: {
  stats: Stats | null
  status: StoreStatus | null
  operations: OperationsSnapshot | null
  sessions: Session[]
  onOpen: (tab: Tab) => void
  onSelectSession?: (id: string) => void
}) {
  const [sessionFilter, setSessionFilter] = useState('all')
  const [evidenceFilter, setEvidenceFilter] = useState('all')
  const [statusFilter, setStatusFilter] = useState('all')
  const [searchQuery, setSearchQuery] = useState('')

  const readiness = operations?.readiness.checks ?? {}
  const readyCount = Object.values(readiness).filter(Boolean).length
  const totalChecks = Object.keys(readiness).length || 4
  const connectorRows = Object.entries(operations?.connectors ?? {})
  const activeSessionsCount = sessions.filter(s => !s.ended_at).length

  const filteredSessions = useMemo(() => {
    return sessions.filter(session => {
      if (sessionFilter === 'active' && session.ended_at) return false
      if (sessionFilter === 'closed' && !session.ended_at) return false
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase()
        const matchId = session.external_session_id?.toLowerCase().includes(q)
        const matchTier = session.retention_tier?.toLowerCase().includes(q)
        if (!matchId && !matchTier) return false
      }
      return true
    })
  }, [sessions, sessionFilter, searchQuery])

  return (
    <section className="cortex-overview-panel">
      <header className="overview-welcome">
        <div className="overview-welcome-main">
          <div className="overview-kicker">
            <span className="kicker-pulse" />
            <span>COGNITIVE CONTROL PLANE</span>
            <span className="kicker-divider">/</span>
            <span className="kicker-live">LIVE TELEMETRY</span>
          </div>
          <h2>Memory Operations Center</h2>
          <div className="overview-meta-strip">
            <span className="meta-chip profile-chip">
              <span className="chip-label">Profile</span>
              <b>{operations?.profile_id ?? 'default'}</b>
            </span>
            <span className="meta-chip endpoint-chip">
              <span className="chip-label">Endpoint</span>
              <code>{getApiBaseUrl()}</code>
            </span>
            <span className="meta-chip status-chip good">
              <ShieldCheck size={13} />
              <span>Merkle: {status?.integrity_check ?? 'ok'}</span>
            </span>
            <span className="meta-chip status-chip good">
              <HardDrive size={13} />
              <span>Engine: SQLite WAL</span>
            </span>
          </div>
        </div>
        <div className="overview-quick-actions">
          <button className="cortex-cta" onClick={() => onOpen('graph')}>
            <Network size={15} />
            <span>Explore 3D Graph</span>
            <ArrowUpRight size={14} />
          </button>
          <button className="ghost-cta" onClick={() => onOpen('timeline')}>
            <Clock size={15} />
            <span>Replay Timeline</span>
          </button>
          <button className="ghost-cta" onClick={() => onOpen('integrity')}>
            <ShieldCheck size={15} />
            <span>Integrity Audit</span>
          </button>
        </div>
      </header>

      <div className="overview-filters" aria-label="Cortex dashboard filters">
        <div className="filter-input-wrap">
          <Search size={14} className="filter-icon" />
          <input
            className="form-input search-input"
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            placeholder="Search sessions or retention tiers..."
          />
        </div>
        <div className="filter-select-group">
          <label>
            <span>Scope:</span>
            <select
              className="form-select"
              value={sessionFilter}
              onChange={e => setSessionFilter(e.target.value)}
            >
              <option value="all">All Sessions ({sessions.length})</option>
              <option value="active">Active ({activeSessionsCount})</option>
              <option value="closed">Closed ({sessions.length - activeSessionsCount})</option>
            </select>
          </label>
          <label>
            <span>Evidence:</span>
            <select
              className="form-select"
              value={evidenceFilter}
              onChange={e => setEvidenceFilter(e.target.value)}
            >
              <option value="all">All Evidence Classes</option>
              <option value="observed_event">Observed Event</option>
              <option value="derived">Derived Knowledge</option>
              <option value="synthetic">Synthetic Seed</option>
            </select>
          </label>
          <label>
            <span>Integrity:</span>
            <select
              className="form-select"
              value={statusFilter}
              onChange={e => setStatusFilter(e.target.value)}
            >
              <option value="all">All Statuses</option>
              <option value="healthy">Healthy Only</option>
              <option value="degraded">Degraded Only</option>
              <option value="stale">Stale Only</option>
            </select>
          </label>
        </div>
        <div className="overview-filter-stats">
          <span className="live-dot" />
          <span><b>{filteredSessions.length}</b> sessions matching</span>
        </div>
      </div>

      <div className="overview-metrics">
        <article className="metric-card">
          <div className="metric-card-top">
            <span className="metric-title">TOTAL MEMORIES</span>
            <div className="metric-icon-box memory-color">
              <Database size={18} />
            </div>
          </div>
          <b className="metric-number">
            {stats ? stats.memories.toLocaleString() : <Skeleton width={64} height={32} />}
          </b>
          <div className="metric-footer">
            <span className="metric-badge primary">
              {stats ? `${stats.embedded_memories ?? 0} embedded` : <Skeleton width={72} height={14} />}
            </span>
            <span className="metric-caption">Vector indexed</span>
          </div>
        </article>

        <article className="metric-card">
          <div className="metric-card-top">
            <span className="metric-title">AGENT SESSIONS</span>
            <div className="metric-icon-box session-color">
              <Layers size={18} />
            </div>
          </div>
          <b className="metric-number">
            {stats ? (sessionFilter === 'all' ? (stats.sessions ?? sessions.length).toLocaleString() : filteredSessions.length.toLocaleString()) : <Skeleton width={64} height={32} />}
          </b>
          <div className="metric-footer">
            <span className="metric-badge success">{activeSessionsCount} active</span>
            <span className="metric-caption">Live cognitive runtime</span>
          </div>
        </article>

        <article className="metric-card">
          <div className="metric-card-top">
            <span className="metric-title">GRAPH RELATIONS</span>
            <div className="metric-icon-box graph-color">
              <Network size={18} />
            </div>
          </div>
          <b className="metric-number">
            {stats ? (stats.relations ?? 0).toLocaleString() : <Skeleton width={64} height={32} />}
          </b>
          <div className="metric-footer">
            <span className="metric-badge info">{stats ? `${stats.entities ?? 0} entities` : <Skeleton width={64} height={14} />}</span>
            <span className="metric-caption">Bidirectional edges</span>
          </div>
        </article>

        <article className="metric-card">
          <div className="metric-card-top">
            <span className="metric-title">ENGINE READINESS</span>
            <div className="metric-icon-box integrity-color">
              <ShieldCheck size={18} />
            </div>
          </div>
          <b className="metric-number">
            {stats ? `${readyCount}/${totalChecks}` : <Skeleton width={64} height={32} />}
          </b>
          <div className="metric-footer">
            <span className={`metric-badge ${readyCount === totalChecks ? 'success' : 'warn'}`}>
              {operations ? (operations.readiness.state ?? 'healthy') : 'verifying'}
            </span>
            <span className="metric-caption">Zero drift detected</span>
          </div>
        </article>
      </div>

      <div className="overview-grid">
        <article className="overview-card store-integrity-card">
          <header>
            <div className="card-header-titles">
              <div className="card-icon-title">
                <HardDrive size={18} className="card-header-icon" />
                <h3>Store Integrity & Persistence</h3>
              </div>
              <p>Canonical SQLite profile & cryptographic state journal</p>
            </div>
            <span className={`status-badge ${status?.integrity_check === 'ok' ? 'good' : 'warn'}`}>
              <CheckCircle2 size={12} />
              {status?.integrity_check === 'ok' ? 'Verified OK' : (status?.integrity_check ?? 'Unknown')}
            </span>
          </header>
          <div className="store-specs-list">
            <div className="spec-row">
              <span className="spec-label">Storage Engine</span>
              <span className="spec-value">SQLite 3.x with WAL mode</span>
            </div>
            <div className="spec-row">
              <span className="spec-label">Schema Version</span>
              <span className="spec-value code-font">v{status?.schema_version ?? '1.0.0'}</span>
            </div>
            <div className="spec-row">
              <span className="spec-label">Journal Mode</span>
              <span className="spec-value"><span className="chip-pill">{status?.journal_mode ?? 'wal'}</span></span>
            </div>
            <div className="spec-row">
              <span className="spec-label">Foreign Key Constraints</span>
              <span className="spec-value">{status?.foreign_keys ? <span className="text-good">✓ Enforced</span> : <span className="text-warn">Unverified</span>}</span>
            </div>
            <div className="spec-row">
              <span className="spec-label">Disaster Backup</span>
              <span className="spec-value">{status?.backup_ready ? <span className="text-good">✓ Synced & Ready</span> : <span className="text-warn">Pending</span>}</span>
            </div>
            <div className="spec-row">
              <span className="spec-label">Cryptographic Verification</span>
              <span className="spec-value code-font">Append-only Merkle DAG</span>
            </div>
          </div>
          <button className="card-action-btn" onClick={() => onOpen('integrity')}>
            <span>Inspect Merkle Audit & Evidence</span>
            <ChevronRight size={14} />
          </button>
        </article>

        <article className="overview-card capability-policy-card">
          <header>
            <div className="card-header-titles">
              <div className="card-icon-title">
                <Cpu size={18} className="card-header-icon" />
                <h3>Capability Policy & Engine Gates</h3>
              </div>
              <p>Explicit feature flags, cognitive filters, and boundaries</p>
            </div>
            <span className="status-badge good">
              <Sparkles size={12} />
              Configured
            </span>
          </header>
          <div className="feature-status-list">
            {Object.entries(operations?.features ?? {}).map(([name, enabled]) => (
              <div className="feature-row" key={name}>
                <div className="feature-info">
                  <span className="feature-name">{name.replaceAll('_', ' ')}</span>
                  <small className="feature-desc">Active cognitive subsystem gate</small>
                </div>
                <span className={`feature-pill ${enabled ? 'on' : 'off'}`}>
                  {enabled ? 'Enabled' : 'Disabled'}
                </span>
              </div>
            ))}
          </div>
          <button className="card-action-btn" onClick={() => onOpen('operations')}>
            <span>View Subsystem Operations & Policy</span>
            <ChevronRight size={14} />
          </button>
        </article>
      </div>

      <article className="overview-card connectors-card">
        <header>
          <div className="card-header-titles">
            <div className="card-icon-title">
              <Server size={18} className="card-header-icon" />
              <h3>Connector Estate</h3>
            </div>
            <p>Active ingestion streams, protocol workers, and retrieval pipelines</p>
          </div>
          <span className="status-badge info">{connectorRows.length} pipelines active</span>
        </header>
        <div className="connector-overview">
          {connectorRows.length ? (
            connectorRows.map(([name, item]) => (
              <div className="connector-item" key={name}>
                <span className={`connector-dot ${item.state}`} />
                <div className="connector-details">
                  <b>{name}</b>
                  <small>{item.entrypoint}</small>
                </div>
                <em className={`connector-status ${item.state}`}>{item.state}</em>
              </div>
            ))
          ) : (
            <p className="muted">No active connector pipelines reported.</p>
          )}
        </div>
      </article>

      <article className="overview-card recent-sessions-card">
        <header>
          <div className="card-header-titles">
            <div className="card-icon-title">
              <Clock size={18} className="card-header-icon" />
              <h3>Recent Agent Sessions</h3>
            </div>
            <p>Chronological agent interaction contexts stored in memory</p>
          </div>
          <div className="header-actions-inline">
            <button className="tiny-link-btn" onClick={() => onOpen('timeline')}>
              <span>View all in Timeline</span>
              <ChevronRight size={13} />
            </button>
          </div>
        </header>
        <div className="recent-sessions-table-wrapper">
          <table className="recent-sessions-table">
            <thead>
              <tr>
                <th>Session ID</th>
                <th>Retention Tier</th>
                <th>Started</th>
                <th>Status</th>
                <th style={{ textAlign: 'right' }}>Action</th>
              </tr>
            </thead>
            <tbody>
              {filteredSessions.slice(0, 7).map(session => {
                const isActive = !session.ended_at
                const startDate = new Date(session.started_at + 'Z')
                const formattedDate = isNaN(startDate.getTime())
                  ? session.started_at
                  : startDate.toLocaleDateString(undefined, {
                      month: 'short',
                      day: 'numeric',
                      hour: '2-digit',
                      minute: '2-digit',
                    })
                return (
                  <tr key={session.id}>
                    <td>
                      <div className="session-id-cell">
                        <code title={session.external_session_id}>
                          {session.external_session_id.length > 28
                            ? `${session.external_session_id.substring(0, 26)}…`
                            : session.external_session_id}
                        </code>
                      </div>
                    </td>
                    <td>
                      <span className={`tier-badge ${session.retention_tier}`}>
                        {session.retention_tier || 'standard'}
                      </span>
                    </td>
                    <td>
                      <span className="session-date">{formattedDate}</span>
                    </td>
                    <td>
                      <span className={`session-status-badge ${isActive ? 'active' : 'closed'}`}>
                        <span className={`mini-dot ${isActive ? 'pulse' : ''}`} />
                        {isActive ? 'Active' : 'Closed'}
                      </span>
                    </td>
                    <td style={{ textAlign: 'right' }}>
                      <button
                        className="session-replay-btn"
                        onClick={() => {
                          if (onSelectSession) {
                            onSelectSession(session.external_session_id)
                          } else {
                            onOpen('timeline')
                          }
                        }}
                      >
                        Replay
                        <ArrowUpRight size={12} />
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </article>

      {stats?.memories === 0 && (
        <article className="overview-empty">
          <h3>Your Cortex profile is ready.</h3>
          <p>Record an exchange or connect an agent harness to start building a provenance-backed memory graph.</p>
          <button onClick={() => onOpen('timeline')}>Record first exchange →</button>
        </article>
      )}
      {operations?.disclaimer && <p className="overview-disclaimer">{operations.disclaimer}</p>}
    </section>
  )
}

type OperatorProfile = { displayName: string; email: string; role: string; avatar: string; compactMode: boolean }
const PROFILE_KEY = 'xibalba-cortex.operator-profile'
function loadOperatorProfile(): OperatorProfile {
  const fallback = { displayName: 'Cortex Operator', email: '', role: 'Operator', avatar: '', compactMode: false }
  try {
    const account = JSON.parse(sessionStorage.getItem('xibalba-cortex.account') || '{}')
    const preferences = JSON.parse(localStorage.getItem(PROFILE_KEY) || '{}')
    return { ...fallback, displayName: account.display_name || fallback.displayName, email: account.email || '', role: account.role || fallback.role, ...preferences }
  } catch { return fallback }
}
function saveOperatorProfile(profile: OperatorProfile) {
  try { localStorage.setItem(PROFILE_KEY, JSON.stringify(profile)) } catch { /* storage may be disabled in isolated previews */ }
}
function ProfileAvatar({ profile }: { profile: OperatorProfile }) {
  const initials = profile.displayName.split(/\s+/).filter(Boolean).slice(0,2).map(part => part[0]).join('').toUpperCase() || 'CO'
  return profile.avatar ? <img className="profile-avatar-image" src={profile.avatar} alt={`${profile.displayName} profile`} /> : <span className="profile-avatar-fallback">{initials}</span>
}
const INFERENCE_TASKS = ['extract_memory_metadata', 'extract_entities', 'extract_relations', 'classify_para', 'detect_contradictions'] as const

function SettingsTab({
  profile,
  setProfile,
  profileId,
  onNotice,
  onError,
}: {
  profile: OperatorProfile
  setProfile: (value: OperatorProfile) => void
  profileId: string
  onNotice: (msg: string) => void
  onError: (msg: string) => void
}) {
  const [activeSection, setActiveSection] = useState<'all' | 'profile' | 'inference' | 'security'>('all')
  const [draft, setDraft] = useState(profile)
  const [profileMsg, setProfileMsg] = useState('')
  const [passwordMsg, setPasswordMsg] = useState('')
  const [sessions, setSessions] = useState<Array<Record<string, unknown>>>([])
  const [events, setEvents] = useState<Array<Record<string, unknown>>>([])
  const [settings, setSettings] = useState<InferenceSettings | null>(null)
  const [inferenceMsg, setInferenceMsg] = useState('')
  const [isSavingInference, setIsSavingInference] = useState(false)

  const loadSessionsAndEvents = useCallback(() => {
    accountSessions().then(result => setSessions(result.sessions || [])).catch(() => setSessions([]))
    accountEvents().then(result => setEvents(result.events || [])).catch(() => setEvents([]))
  }, [])

  useEffect(() => {
    loadSessionsAndEvents()
    api.inferenceSettings().then(setSettings).catch(error => setInferenceMsg(String(error)))
  }, [loadSessionsAndEvents])

  const updateDraft = (key: keyof OperatorProfile, value: string | boolean) =>
    setDraft(current => ({ ...current, [key]: value }))

  const chooseAvatar = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file) return
    if (!file.type.startsWith('image/')) {
      onError('Choose an image file.')
      return
    }
    if (file.size > 2_000_000) {
      onError('Profile image must be smaller than 2 MB.')
      return
    }
    const reader = new FileReader()
    reader.onload = () => updateDraft('avatar', String(reader.result || ''))
    reader.readAsDataURL(file)
  }

  const submitProfile = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    saveOperatorProfile(draft)
    setProfile(draft)
    setProfileMsg('Profile settings saved in this browser.')
    onNotice('Operator profile updated.')
  }

  const changePassword = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    setPasswordMsg('Updating…')
    try {
      await accountChangePassword(String(form.get('currentPassword') || ''), String(form.get('newPassword') || ''))
      event.currentTarget.reset()
      setPasswordMsg('Password updated.')
      onNotice('Password updated successfully.')
    } catch (error) {
      const err = error instanceof Error ? error.message : String(error)
      setPasswordMsg(err)
      onError(err)
    }
  }

  const revokeSession = async (id: string) => {
    try {
      await accountRevokeSession(id)
      onNotice('Session revoked.')
      loadSessionsAndEvents()
    } catch (error) {
      const err = error instanceof Error ? error.message : String(error)
      onError(err)
    }
  }

  const updateInference = <K extends keyof InferenceSettings>(key: K, value: InferenceSettings[K]) =>
    setSettings(current => current ? { ...current, [key]: value } : current)

  const updateThreshold = (task: string, value: number) => {
    if (!settings) return
    updateInference('task_confidence_thresholds', { ...settings.task_confidence_thresholds, [task]: value })
  }

  const toggleTaskType = (task: string) => {
    if (!settings) return
    const next = settings.task_types.includes(task)
      ? settings.task_types.filter(item => item !== task)
      : [...settings.task_types, task]
    updateInference('task_types', next)
  }

  const submitInference = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!settings) return
    setIsSavingInference(true)
    setInferenceMsg('Saving…')
    try {
      const result = await api.updateInferenceSettings(settings)
      setSettings(result.inference)
      setInferenceMsg(result.message)
      onNotice(result.message || 'Inference policy updated.')
    } catch (error) {
      const err = error instanceof Error ? error.message : String(error)
      setInferenceMsg(err)
      onError(err)
    } finally {
      setIsSavingInference(false)
    }
  }

  const handleSignOut = () => {
    accountLogout().catch(() => {}).finally(() => {
      setApiToken('')
      window.location.reload()
    })
  }

  const activeTokensCount = sessions.filter(s => !s.revoked_at).length || 1

  return (
    <div className="tab-panel settings-tab">
      <div className="overview-header" style={{ marginBottom: '20px' }}>
        <div>
          <div className="overview-kicker">SYSTEM CONFIGURATION &amp; GOVERNANCE</div>
          <h2 className="overview-title">Settings &amp; Operational Policies</h2>
          <p className="overview-subtitle">
            Configure operator presentation, manage live inference daemon rules, and govern active session tokens and security audits.
          </p>
        </div>
      </div>

      <div className="overview-kpi-grid" style={{ marginBottom: '24px' }}>
        <div className="kpi-card">
          <div className="kpi-icon-wrap memories">
            <User size={20} />
          </div>
          <div className="kpi-content">
            <div className="kpi-value">{draft.displayName || 'Cortex Operator'}</div>
            <div className="kpi-label">Operator Profile</div>
            <div className="kpi-subtext">Role: {draft.role}</div>
          </div>
        </div>

        <div className="kpi-card">
          <div className="kpi-icon-wrap relations">
            <Cpu size={20} />
          </div>
          <div className="kpi-content">
            <div className="kpi-value">{settings?.enabled ? 'Active Daemon' : 'Daemon Paused'}</div>
            <div className="kpi-label">Inference Engine</div>
            <div className="kpi-subtext">{settings?.batch_size ?? 5} memories/batch · {settings?.interval_seconds ?? 5}s cycle</div>
          </div>
        </div>

        <div className="kpi-card">
          <div className="kpi-icon-wrap readiness">
            <ShieldCheck size={20} />
          </div>
          <div className="kpi-content">
            <div className="kpi-value">{settings?.promotion_policy === 'confidence_gated' ? 'Confidence Gated' : 'Manual Review'}</div>
            <div className="kpi-label">Promotion Policy</div>
            <div className="kpi-subtext">Threshold: {Math.round((settings?.human_review_confidence_threshold ?? 0.75) * 100)}%</div>
          </div>
        </div>

        <div className="kpi-card">
          <div className="kpi-icon-wrap sessions">
            <Key size={20} />
          </div>
          <div className="kpi-content">
            <div className="kpi-value">{activeTokensCount} Active Token{activeTokensCount === 1 ? '' : 's'}</div>
            <div className="kpi-label">Session Security</div>
            <div className="kpi-subtext">{sessionStorage.getItem('xibalba-cortex.account') ? 'Account Authenticated' : 'Bearer Authenticated'}</div>
          </div>
        </div>
      </div>

      <div className="settings-subnav">
        <button
          type="button"
          className={`settings-subnav-btn ${activeSection === 'all' ? 'active' : ''}`}
          onClick={() => setActiveSection('all')}
        >
          All Settings
        </button>
        <button
          type="button"
          className={`settings-subnav-btn ${activeSection === 'profile' ? 'active' : ''}`}
          onClick={() => setActiveSection('profile')}
        >
          <User size={13} /> Operator Profile
        </button>
        <button
          type="button"
          className={`settings-subnav-btn ${activeSection === 'inference' ? 'active' : ''}`}
          onClick={() => setActiveSection('inference')}
        >
          <Cpu size={13} /> Inference Policy
        </button>
        <button
          type="button"
          className={`settings-subnav-btn ${activeSection === 'security' ? 'active' : ''}`}
          onClick={() => setActiveSection('security')}
        >
          <ShieldCheck size={13} /> Security &amp; Sessions
        </button>
      </div>

      {/* SECTION 1: OPERATOR PROFILE */}
      {(activeSection === 'all' || activeSection === 'profile') && (
        <section className="overview-card" style={{ marginBottom: '24px' }}>
          <header className="overview-card-header">
            <div>
              <div className="overview-card-kicker">OPERATOR IDENTITY</div>
              <div className="overview-card-title">Profile &amp; Workspace Preferences</div>
            </div>
            <div className="overview-card-badge">{draft.role}</div>
          </header>
          <div className="overview-card-body">
            <p className="small muted" style={{ margin: '0 0 16px 0' }}>
              Server identity comes from the authenticated Cortex account. Browser-only presentation preferences remain local to this tab and device.
            </p>
            <form onSubmit={submitProfile}>
              <div className="avatar-editor" style={{ display: 'flex', alignItems: 'center', gap: '18px', paddingBottom: '20px', borderBottom: '1px solid var(--border)' }}>
                <ProfileAvatar profile={draft} />
                <div style={{ flex: 1 }}>
                  <b style={{ fontSize: '13px', color: 'var(--text)' }}>Profile Picture</b>
                  <p style={{ margin: '4px 0 10px', color: 'var(--text-muted)', fontSize: '11px' }}>PNG, JPEG, GIF, or WebP. Stored locally in this browser.</p>
                  <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                    <label className="upload-button" style={{ cursor: 'pointer', fontSize: '11px', padding: '5px 12px', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: '6px', color: 'var(--text)' }}>
                      Choose image
                      <input type="file" accept="image/png,image/jpeg,image/gif,image/webp" onChange={chooseAvatar} style={{ display: 'none' }} />
                    </label>
                    {draft.avatar && (
                      <button type="button" className="small-button" onClick={() => updateDraft('avatar', '')} style={{ fontSize: '11px', padding: '5px 10px', color: '#fca5a5' }}>
                        Remove
                      </button>
                    )}
                  </div>
                </div>
              </div>

              <div className="settings-fields" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', margin: '20px 0' }}>
                <div className="settings-field-group">
                  <label>Display Name</label>
                  <input
                    className="form-input"
                    value={draft.displayName}
                    onChange={(e) => updateDraft('displayName', e.target.value)}
                    required
                  />
                </div>
                <div className="settings-field-group">
                  <label>Email Address</label>
                  <input
                    className="form-input"
                    type="email"
                    value={draft.email}
                    readOnly
                    placeholder="operator@example.com"
                    style={{ opacity: 0.7 }}
                  />
                  <small style={{ fontSize: '10px', color: 'var(--text-muted)' }}>Managed by authenticated account.</small>
                </div>
                <div className="settings-field-group">
                  <label>Role</label>
                  <select
                    className="form-select"
                    value={draft.role}
                    onChange={(e) => updateDraft('role', e.target.value)}
                  >
                    <option>Operator</option>
                    <option>Administrator</option>
                    <option>Auditor</option>
                    <option>Developer</option>
                  </select>
                </div>
                <div className="settings-field-group" style={{ justifyContent: 'center' }}>
                  <label className="toggle-setting" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 14px', border: '1px solid var(--border)', borderRadius: '8px', cursor: 'pointer', margin: 0 }}>
                    <span>
                      <b style={{ fontSize: '12px', color: 'var(--text)' }}>Compact Workspace</b>
                      <small style={{ display: 'block', fontSize: '10px', color: 'var(--text-muted)' }}>Reduce padding and spacing in operational views.</small>
                    </span>
                    <input
                      type="checkbox"
                      checked={draft.compactMode}
                      onChange={(e) => updateDraft('compactMode', e.target.checked)}
                      style={{ width: '16px', height: '16px', cursor: 'pointer' }}
                    />
                  </label>
                </div>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                <button type="submit" className="small-button" style={{ background: '#858cf4', color: '#080a12', fontWeight: 600, padding: '8px 18px', border: 'none' }}>
                  Save Preferences
                </button>
                {profileMsg && <span style={{ color: '#4ade80', fontSize: '11px' }}>{profileMsg}</span>}
              </div>
            </form>
          </div>
        </section>
      )}

      {/* SECTION 2: INFERENCE DAEMON POLICY */}
      {(activeSection === 'all' || activeSection === 'inference') && (
        <section className="overview-card" style={{ marginBottom: '24px' }}>
          <header className="overview-card-header">
            <div>
              <div className="overview-card-kicker">AUTONOMOUS HARNESS</div>
              <div className="overview-card-title">Inference Engine Policy</div>
            </div>
            {settings && (
              <Badge>{settings.enabled ? 'Daemon Active' : 'Daemon Paused'}</Badge>
            )}
          </header>
          <div className="overview-card-body">
            <p className="small muted" style={{ margin: '0 0 16px 0' }}>
              Policy is stored in the active Cortex profile and dynamically hot-reloaded by the inference worker daemon after each cycle.
            </p>
            {!settings ? (
              <p className="small muted">{inferenceMsg || 'Loading effective inference policy…'}</p>
            ) : (
              <form onSubmit={submitInference}>
                {/* Switches Row */}
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '12px', marginBottom: '20px' }}>
                  <label className="toggle-setting" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 14px', border: '1px solid var(--border)', borderRadius: '8px', cursor: 'pointer', background: 'rgba(10, 14, 20, 0.5)' }}>
                    <span>
                      <b style={{ fontSize: '12px', color: 'var(--text)' }}>Background Inference</b>
                      <small style={{ display: 'block', fontSize: '10px', color: 'var(--text-muted)' }}>Process enabled metadata queues continuously.</small>
                    </span>
                    <input
                      type="checkbox"
                      checked={settings.enabled}
                      onChange={(e) => updateInference('enabled', e.target.checked)}
                      style={{ width: '16px', height: '16px', cursor: 'pointer' }}
                    />
                  </label>

                  <label className="toggle-setting" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 14px', border: '1px solid var(--border)', borderRadius: '8px', cursor: 'pointer', background: 'rgba(10, 14, 20, 0.5)' }}>
                    <span>
                      <b style={{ fontSize: '12px', color: 'var(--text)' }}>Combined Batching</b>
                      <small style={{ display: 'block', fontSize: '10px', color: 'var(--text-muted)' }}>Infer PARA, entities, and relations in one model call.</small>
                    </span>
                    <input
                      type="checkbox"
                      checked={settings.combined_batching}
                      onChange={(e) => updateInference('combined_batching', e.target.checked)}
                      style={{ width: '16px', height: '16px', cursor: 'pointer' }}
                    />
                  </label>

                  <label className="toggle-setting" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 14px', border: '1px solid var(--border)', borderRadius: '8px', cursor: 'pointer', background: 'rgba(10, 14, 20, 0.5)' }}>
                    <span>
                      <b style={{ fontSize: '12px', color: 'var(--text)' }}>Contradictions Review</b>
                      <small style={{ display: 'block', fontSize: '10px', color: 'var(--text-muted)' }}>Require operator sign-off before committing conflict resolutions.</small>
                    </span>
                    <input
                      type="checkbox"
                      checked={settings.contradictions_require_review}
                      onChange={(e) => updateInference('contradictions_require_review', e.target.checked)}
                      style={{ width: '16px', height: '16px', cursor: 'pointer' }}
                    />
                  </label>
                </div>

                {/* Worker Execution Parameters */}
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '14px', marginBottom: '20px' }}>
                  <div className="settings-field-group">
                    <label>Harness Executable</label>
                    <input
                      className="form-input"
                      value={settings.harness}
                      onChange={(e) => updateInference('harness', e.target.value)}
                      required
                    />
                  </div>

                  <div className="settings-field-group">
                    <label>Worker Profile</label>
                    <input
                      className="form-input"
                      value={settings.profile_name}
                      onChange={(e) => updateInference('profile_name', e.target.value)}
                      required
                    />
                  </div>

                  <div className="settings-field-group">
                    <label>Memories / Model Call</label>
                    <input
                      className="form-input"
                      type="number"
                      min="1"
                      value={settings.batch_size}
                      onChange={(e) => updateInference('batch_size', Number(e.target.value))}
                    />
                  </div>

                  <div className="settings-field-group">
                    <label>Promotion Policy</label>
                    <select
                      className="form-select"
                      value={settings.promotion_policy}
                      onChange={(e) => updateInference('promotion_policy', e.target.value as InferenceSettings['promotion_policy'])}
                    >
                      <option value="confidence_gated">Auto-accept above threshold</option>
                      <option value="review_required">Always require review</option>
                    </select>
                  </div>

                  <div className="settings-field-group">
                    <label>Cycle Interval (sec)</label>
                    <input
                      className="form-input"
                      type="number"
                      min="0.25"
                      step="0.25"
                      value={settings.interval_seconds}
                      onChange={(e) => updateInference('interval_seconds', Number(e.target.value))}
                    />
                  </div>

                  <div className="settings-field-group">
                    <label>Provider Timeout (sec)</label>
                    <input
                      className="form-input"
                      type="number"
                      min="1"
                      value={settings.timeout_seconds}
                      onChange={(e) => updateInference('timeout_seconds', Number(e.target.value))}
                    />
                  </div>

                  <div className="settings-field-group">
                    <label>Parallel Worker Families</label>
                    <input
                      className="form-input"
                      type="number"
                      min="1"
                      max="4"
                      value={settings.max_parallel_families}
                      onChange={(e) => updateInference('max_parallel_families', Number(e.target.value))}
                    />
                  </div>

                  <div className="settings-field-group">
                    <label>Max Attempts / Task</label>
                    <input
                      className="form-input"
                      type="number"
                      min="1"
                      value={settings.max_attempts}
                      onChange={(e) => updateInference('max_attempts', Number(e.target.value))}
                    />
                  </div>
                </div>

                {/* Confidence Review Thresholds */}
                <div style={{ background: 'rgba(10, 14, 20, 0.4)', border: '1px solid var(--border-subtle)', borderRadius: '8px', padding: '16px', marginBottom: '20px' }}>
                  <div style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '12px' }}>
                    Confidence Review Thresholds
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '14px' }}>
                    <div className="settings-field-group">
                      <label style={{ display: 'flex', justifyContent: 'space-between' }}>
                        <span>Global Review Threshold</span>
                        <span style={{ color: 'var(--accent)', fontWeight: 700 }}>{Math.round(settings.human_review_confidence_threshold * 100)}%</span>
                      </label>
                      <input
                        className="form-input"
                        type="number"
                        min="0"
                        max="1"
                        step="0.01"
                        value={settings.human_review_confidence_threshold}
                        onChange={(e) => updateInference('human_review_confidence_threshold', Number(e.target.value))}
                      />
                    </div>

                    <div className="settings-field-group">
                      <label style={{ display: 'flex', justifyContent: 'space-between' }}>
                        <span>PARA Threshold</span>
                        <span style={{ color: '#4ade80', fontWeight: 700 }}>{Math.round((settings.task_confidence_thresholds.classify_para ?? settings.human_review_confidence_threshold) * 100)}%</span>
                      </label>
                      <input
                        className="form-input"
                        type="number"
                        min="0"
                        max="1"
                        step="0.01"
                        value={settings.task_confidence_thresholds.classify_para ?? settings.human_review_confidence_threshold}
                        onChange={(e) => updateThreshold('classify_para', Number(e.target.value))}
                      />
                    </div>

                    <div className="settings-field-group">
                      <label style={{ display: 'flex', justifyContent: 'space-between' }}>
                        <span>Entity Threshold</span>
                        <span style={{ color: '#38bdf8', fontWeight: 700 }}>{Math.round((settings.task_confidence_thresholds.extract_entities ?? settings.human_review_confidence_threshold) * 100)}%</span>
                      </label>
                      <input
                        className="form-input"
                        type="number"
                        min="0"
                        max="1"
                        step="0.01"
                        value={settings.task_confidence_thresholds.extract_entities ?? settings.human_review_confidence_threshold}
                        onChange={(e) => updateThreshold('extract_entities', Number(e.target.value))}
                      />
                    </div>

                    <div className="settings-field-group">
                      <label style={{ display: 'flex', justifyContent: 'space-between' }}>
                        <span>Relation Threshold</span>
                        <span style={{ color: '#c084fc', fontWeight: 700 }}>{Math.round((settings.task_confidence_thresholds.extract_relations ?? settings.human_review_confidence_threshold) * 100)}%</span>
                      </label>
                      <input
                        className="form-input"
                        type="number"
                        min="0"
                        max="1"
                        step="0.01"
                        value={settings.task_confidence_thresholds.extract_relations ?? settings.human_review_confidence_threshold}
                        onChange={(e) => updateThreshold('extract_relations', Number(e.target.value))}
                      />
                    </div>
                  </div>
                </div>

                {/* Live Metadata Tasks Chips */}
                <div style={{ marginBottom: '20px' }}>
                  <div style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                    Active Metadata Tasks
                  </div>
                  <div className="task-chips-grid">
                    {INFERENCE_TASKS.map((task) => {
                      const isActive = settings.task_types.includes(task)
                      return (
                        <button
                          key={task}
                          type="button"
                          className={`task-chip-btn ${isActive ? 'active' : ''}`}
                          onClick={() => toggleTaskType(task)}
                        >
                          <span>{task.replaceAll('_', ' ')}</span>
                          {isActive ? <Check size={14} style={{ color: '#4ade80' }} /> : <span style={{ opacity: 0.3 }}>+</span>}
                        </button>
                      )
                    })}
                  </div>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                  <button
                    type="submit"
                    className="small-button"
                    disabled={isSavingInference}
                    style={{ background: '#858cf4', color: '#080a12', fontWeight: 600, padding: '8px 18px', border: 'none', display: 'flex', alignItems: 'center', gap: '6px' }}
                  >
                    {isSavingInference ? <RefreshCw size={13} className="spin-slow" /> : <CheckCircle2 size={13} />}
                    {isSavingInference ? 'Applying Policy…' : 'Apply Inference Policy'}
                  </button>
                  {inferenceMsg && <span style={{ color: '#4ade80', fontSize: '11px' }}>{inferenceMsg}</span>}
                </div>
              </form>
            )}
          </div>
        </section>
      )}

      {/* SECTION 3: SECURITY & SESSIONS */}
      {(activeSection === 'all' || activeSection === 'security') && (
        <div className="settings-card-grid" style={{ marginBottom: '24px' }}>
          {/* Authenticated Session Card */}
          <section className="overview-card">
            <header className="overview-card-header">
              <div>
                <div className="overview-card-kicker">AUTHORIZATION</div>
                <div className="overview-card-title">Session Identity</div>
              </div>
              <Badge>{sessionStorage.getItem('xibalba-cortex.account') ? 'Account' : 'Bearer'}</Badge>
            </header>
            <div className="overview-card-body">
              <dl className="detail-list" style={{ margin: '0 0 16px 0' }}>
                <dt>Cortex Profile</dt>
                <dd><code>{profileId || 'default'}</code></dd>
                <dt>API Endpoint</dt>
                <dd><code>{getApiBaseUrl()}</code></dd>
                <dt>Auth Mode</dt>
                <dd>{sessionStorage.getItem('xibalba-cortex.account') ? 'Account Session' : 'Bearer Token'}</dd>
                <dt>Session Expiration</dt>
                <dd>
                  {(() => {
                    try {
                      return JSON.parse(sessionStorage.getItem('xibalba-cortex.account') || '{}').session_expires_at || 'Until revoked'
                    } catch {
                      return 'Until revoked'
                    }
                  })()}
                </dd>
                <dt>Token Storage</dt>
                <dd>Current browser tab (sessionStorage)</dd>
              </dl>

              {sessionStorage.getItem('xibalba-cortex.account') && (
                <form onSubmit={changePassword} style={{ background: 'rgba(10, 14, 20, 0.5)', border: '1px solid var(--border)', borderRadius: '8px', padding: '14px', marginBottom: '16px' }}>
                  <h4 style={{ margin: '0 0 10px 0', fontSize: '12px', fontWeight: 600 }}>Change Password</h4>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px', marginBottom: '10px' }}>
                    <div className="settings-field-group">
                      <label>Current Password</label>
                      <input className="form-input" name="currentPassword" type="password" required />
                    </div>
                    <div className="settings-field-group">
                      <label>New Password</label>
                      <input className="form-input" name="newPassword" type="password" minLength={10} required />
                    </div>
                  </div>
                  <button type="submit" className="small-button" style={{ fontSize: '11px', padding: '5px 12px' }}>
                    Update Password
                  </button>
                  {passwordMsg && <span style={{ marginLeft: '10px', fontSize: '11px', color: '#4ade80' }}>{passwordMsg}</span>}
                </form>
              )}

              <button
                type="button"
                className="small-button"
                onClick={handleSignOut}
                style={{ width: '100%', padding: '10px', background: 'rgba(239, 68, 68, 0.1)', border: '1px solid rgba(239, 68, 68, 0.3)', color: '#fca5a5', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}
              >
                <LogOut size={14} /> Sign out of Cortex
              </button>
            </div>
          </section>

          {/* Active Sessions & Audit Events */}
          <section className="overview-card">
            <header className="overview-card-header">
              <div>
                <div className="overview-card-kicker">GOVERNANCE</div>
                <div className="overview-card-title">Active Tokens &amp; Audit Log</div>
              </div>
              <Badge>{sessions.length} tokens</Badge>
            </header>
            <div className="overview-card-body">
              <div style={{ marginBottom: '20px' }}>
                <div style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '8px' }}>
                  Active Sessions
                </div>
                {sessions.length === 0 ? (
                  <p className="small muted" style={{ margin: 0 }}>No explicit account sessions returned (using local environment token).</p>
                ) : (
                  sessions.map((sess) => (
                    <div key={String(sess.id)} className="session-token-row">
                      <div>
                        <b style={{ fontSize: '12px', color: 'var(--text)' }}>{String(sess.label || 'Account Session')}</b>
                        <small style={{ display: 'block', fontSize: '10px', color: 'var(--text-muted)', marginTop: '2px' }}>
                          Created: {String(sess.created_at || 'unknown')} · Used: {String(sess.last_used_at || 'never')}
                        </small>
                      </div>
                      {sess.revoked_at ? (
                        <span style={{ fontSize: '11px', color: 'var(--text-muted)', fontStyle: 'italic' }}>Revoked</span>
                      ) : (
                        <button
                          type="button"
                          className="small-button"
                          onClick={() => revokeSession(String(sess.id))}
                          style={{ fontSize: '11px', padding: '3px 10px', color: '#fca5a5', borderColor: 'rgba(239, 68, 68, 0.3)' }}
                        >
                          Revoke
                        </button>
                      )}
                    </div>
                  ))
                )}
              </div>

              <div>
                <div style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '8px' }}>
                  Recent Security Events
                </div>
                {events.length === 0 ? (
                  <p className="small muted" style={{ margin: 0 }}>No recent audit events logged.</p>
                ) : (
                  <div style={{ maxHeight: '200px', overflowY: 'auto' }}>
                    <table className="audit-events-table">
                      <thead>
                        <tr>
                          <th>Event</th>
                          <th>Detail</th>
                          <th>Timestamp</th>
                        </tr>
                      </thead>
                      <tbody>
                        {events.slice(0, 6).map((ev, idx) => (
                          <tr key={`${String(ev.created_at)}-${idx}`}>
                            <td><strong style={{ color: 'var(--accent)' }}>{String(ev.event_type)}</strong></td>
                            <td style={{ color: 'var(--text-subtle)' }}>{String(ev.detail || '—')}</td>
                            <td style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{String(ev.created_at || '')}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </div>
          </section>
        </div>
      )}
    </div>
  )
}

function AuthenticatedApp() {
  const [stats, setStats] = useState<Stats | null>(null)
  const [storeStatus, setStoreStatus] = useState<StoreStatus | null>(null)
  const [operations, setOperations] = useState<OperationsSnapshot | null>(null)
  const [integrityLinks, setIntegrityLinks] = useState<IntegrityLinksStatus | null>(null)
  const [sessions, setSessions] = useState<Session[]>([])
  const [selectedSessionId, setSelectedSessionId] = useState('')
  const [loadedSessionId, setLoadedSessionId] = useState('')
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
  const [activeTab, setActiveTab] = useState<Tab>('overview')
  const [contextBundle, setContextBundle] = useState<Memory[]>([])
  const [manifest, setManifest] = useState<InferenceManifest | null>(null)
  const [tasks, setTasks] = useState<InferenceTask[]>([])
  const [paraClassifications, setParaClassifications] = useState<ParaClassification[]>([])
  const [extractionProposals, setExtractionProposals] = useState<ExtractionProposal[]>([])
  const [extractionProposalStatus, setExtractionProposalStatus] = useState('proposed')
  const [taskStatus, setTaskStatus] = useState('pending')
  const { toast } = useToast()
  const setError = useCallback((msg: string | null) => { if (msg) toast(msg, 'error') }, [toast])
  const setNotice = useCallback((msg: string | null) => { if (msg) toast(msg, 'success') }, [toast])
  const [isNavOpen, setIsNavOpen] = useState(false)
  const [isNavCollapsed, setIsNavCollapsed] = useState(() => {
    try {
      return localStorage.getItem('xibalba-cortex.nav-collapsed') === 'true'
    } catch {
      return false
    }
  })
  const toggleNavCollapse = useCallback(() => {
    setIsNavCollapsed(prev => {
      const next = !prev
      try {
        localStorage.setItem('xibalba-cortex.nav-collapsed', String(next))
      } catch {}
      return next
    })
  }, [])
  const [operatorProfile, setOperatorProfile] = useState<OperatorProfile>(loadOperatorProfile)
  const [lastRefreshed, setLastRefreshed] = useState<Date | null>(null)
  const [refreshing, setRefreshing] = useState(false)

  const refreshOverview = () => {
    setRefreshing(true)
    api.stats().then(setStats).catch((e) => setError(String(e)))
    api.status().then(setStoreStatus).catch((e) => setError(String(e)))
    api.operations().then(setOperations).catch((e) => setError(String(e)))
    api.integrityLinks().then(setIntegrityLinks).catch(() => setIntegrityLinks(null))
    api.sessions().then((items) => {
      setSessions(items)
      setSelectedSessionId((current) => current || items[0]?.external_session_id || '')
    }).catch((e) => setError(String(e)))
    api.graph(GRAPH_RENDER_LIMIT, similarityThreshold).then(setGraph).catch((e) => setError(String(e)))
    setLastRefreshed(new Date())
    window.setTimeout(() => setRefreshing(false), 350)
  }

  useEffect(() => {
    const accountSession = sessionStorage.getItem('xibalba-cortex.account')
    if (accountSession) {
      accountMe().catch((authError) => {
        const message = String(authError)
        if (/401|invalid|expired|unauthorized/i.test(message)) {
          sessionStorage.setItem('xibalba-cortex.auth-notice', 'Session expired. Sign in again to reconnect to this Cortex profile.')
          setApiToken('')
          window.location.reload()
        }
      })
    }
    refreshOverview()
    api.inferenceManifest().then(setManifest).catch(() => setManifest(null))
    // eslint-disable-next-line
  }, [])

  useEffect(() => {
    const timer = setTimeout(() => {
      window.dispatchEvent(new Event('resize'))
    }, 250)
    return () => clearTimeout(timer)
  }, [isNavOpen, selectedMemoryId])

  useEffect(() => {
    api.graph(GRAPH_RENDER_LIMIT, similarityThreshold).then(setGraph).catch((e) => setError(String(e)))
    setLastRefreshed(new Date())
  }, [similarityThreshold, setError])

  useEffect(() => {
    // Keep the rendered graph stable while the three session projections load. Replacing
    // these independently makes the large Three.js graph tear down and rebuild repeatedly.
    setSelectedGraphNode((prev) => {
      if (prev && prev.type === 'session' && (prev.payload as Session)?.external_session_id === selectedSessionId) {
        return prev
      }
      return null
    })
    setSelectedMemoryId(null)

    if (!selectedSessionId) {
      setLoadedSessionId('')
      setExchanges([])
      setSessionReplay(null)
      setRoot(null)
      return
    }

    let cancelled = false
    Promise.all([
      api.sessionExchanges(selectedSessionId).catch(() => [] as Exchange[]),
      api.sessionReplay(selectedSessionId).catch(() => null),
      api.sessionMerkleRoot(selectedSessionId).catch(() => null),
    ]).then(([nextExchanges, nextReplay, nextRoot]) => {
      if (cancelled) return
      setExchanges(nextExchanges)
      setSessionReplay(nextReplay)
      setRoot(nextRoot)
      setLoadedSessionId(selectedSessionId)
    })
    return () => {
      cancelled = true
    }
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
    let cancelled = false
    const refresh = () => api.inferenceTasks(taskStatus).then(value => { if (!cancelled) setTasks(value) }).catch(() => { if (!cancelled) setTasks([]) })
    refresh(); const timer = window.setInterval(refresh, 5000)
    return () => { cancelled = true; window.clearInterval(timer) }
  }, [taskStatus])

  useEffect(() => {
    let cancelled = false
    const refresh = () => api.paraClassifications().then(value => { if (!cancelled) setParaClassifications(value) }).catch(() => { if (!cancelled) setParaClassifications([]) })
    refresh(); const timer = window.setInterval(refresh, 5000)
    return () => { cancelled = true; window.clearInterval(timer) }
  }, [])

  useEffect(() => {
    let cancelled = false
    const refresh = () => api.extractionProposals(extractionProposalStatus).then(value => { if (!cancelled) setExtractionProposals(value) }).catch(() => { if (!cancelled) setExtractionProposals([]) })
    refresh(); const timer = window.setInterval(refresh, 5000)
    return () => { cancelled = true; window.clearInterval(timer) }
  }, [extractionProposalStatus])


  const demoGraph = useMemo(
    () => buildDemoGraph(graph, sessions, loadedSessionId, exchanges, root),
    [graph, sessions, loadedSessionId, exchanges, root],
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
    <main className={`console ${isNavCollapsed ? 'nav-collapsed' : ''}`}>
      <aside className={`side ${isNavOpen ? 'open' : ''} ${isNavCollapsed ? 'collapsed' : ''}`}>
        <header className="side-header">
          <div className="side-brand-wrap">
            <CortexBrand />
          </div>
          <button
            type="button"
            className="collapse-toggle-btn"
            onClick={toggleNavCollapse}
            title={isNavCollapsed ? "Expand sidebar" : "Collapse sidebar"}
            aria-label="Toggle sidebar width"
          >
            {isNavCollapsed ? <ChevronRight size={15} /> : <ChevronLeft size={15} />}
          </button>
          <button className="mobile-close-btn" onClick={() => setIsNavOpen(false)}>✕</button>
        </header>
        <nav className="side-nav">
          <small className="nav-section-title">VIEWS</small>
          {tabs.map((tab) => {
            const Icon = tab.icon
            const isActive = activeTab === tab.id
            return (
              <button
                key={tab.id}
                className={`nav-tab-btn ${isActive ? 'active' : ''}`}
                onClick={() => setActiveTab(tab.id)}
                title={tab.label}
              >
                <Icon size={17} className="nav-icon" />
                <span className="nav-label">{tab.label}</span>
              </button>
            )
          })}
          <small className="nav-section-title">LIFECYCLE</small>
          {railStatusCounts.map(([status, count]) => (
            <button
              className={`nav-rail-btn ${graphFilterIntent.status === status ? 'active' : ''}`}
              key={status}
              onClick={() => applyRailGraphFilter({ status })}
              type="button"
              title={`${status} (${count})`}
            >
              <span className={`rail-status-dot ${status}`} />
              <span className="nav-label">{status}</span>
              <i className="rail-count">{count}</i>
            </button>
          ))}
          <small className="nav-section-title">EVIDENCE</small>
          {railEvidenceCounts.map(([evidence, count]) => (
            <button
              className={`nav-rail-btn ${graphFilterIntent.evidence === evidence ? 'active' : ''}`}
              key={evidence}
              onClick={() => applyRailGraphFilter({ evidence })}
              type="button"
              title={`${evidence} (${count})`}
            >
              <span className="rail-evidence-icon">◇</span>
              <span className="nav-label">{evidence}</span>
              <i className="rail-count">{count}</i>
            </button>
          ))}
        </nav>
        <div className={`operator ${activeTab === 'settings' ? 'active' : ''}`}>
          <button
            type="button"
            className="operator-profile-btn"
            onClick={() => setActiveTab('settings')}
            title={`Operator Settings (${operatorProfile.displayName})`}
            aria-label="Operator Settings"
          >
            <ProfileAvatar profile={operatorProfile} />
            <div className="operator-info">
              <b>{operatorProfile.displayName}</b>
              <small>{operatorProfile.role}</small>
            </div>
          </button>
          <div className="operator-actions">
            <button
              type="button"
              className={`operator-action-btn ${activeTab === 'settings' ? 'active' : ''}`}
              title="Settings"
              aria-label="Settings"
              onClick={() => setActiveTab('settings')}
            >
              <Settings size={14} />
            </button>
            <button
              type="button"
              className="operator-action-btn signout"
              title="Sign out of Cortex"
              aria-label="Sign out"
              onClick={() => {
                accountLogout().catch(() => {}).finally(() => {
                  setApiToken('')
                  window.location.reload()
                })
              }}
            >
              <LogOut size={14} />
            </button>
          </div>
        </div>
      </aside>

      <section className="main">
        <header className="top">
          <div className="top-left">
            <button
              aria-label="Toggle navigation menu"
              className="hamb"
              onClick={() => setIsNavOpen(true)}
            >
              ☰
            </button>
            <div className="top-breadcrumbs">
              <span className="breadcrumb-brand">Xibalba Cortex</span>
              <span className="breadcrumb-sep">/</span>
              <span className="breadcrumb-tab">{tabs.find(t => t.id === activeTab)?.label || (activeTab === 'settings' ? 'Settings' : 'Overview')}</span>
            </div>
            {stats && (
              <div className="top-telemetry-badge">
                <span className="telemetry-live-dot" />
                <span>{stats.memories.toLocaleString()} memories</span>
                <span className="badge-divider">·</span>
                <span>{stats.sessions.toLocaleString()} sessions</span>
              </div>
            )}
          </div>
          <div className="tools">
            <button
              className="refresh-tool-btn"
              aria-label="Refresh data"
              title="Refresh telemetry"
              onClick={refreshOverview}
              disabled={refreshing}
            >
              <RefreshCw size={14} className={refreshing ? 'spinning' : ''} />
              <span className="btn-label">Refresh</span>
            </button>
            {lastRefreshed && (
              <div className="top-status-indicator live" title={`Updated ${lastRefreshed.toLocaleTimeString()}`}>
                <span className="status-live-indicator" />
                <span className="status-text">{storeStatus?.integrity_check ?? 'ok'}</span>
                <span className="engine-text">WAL</span>
              </div>
            )}
          </div>
        </header>


        <div className="content">
          {activeTab === 'overview' && (
            <CortexOverview
              stats={stats}
              status={storeStatus}
              operations={operations}
              sessions={sessions}
              onOpen={setActiveTab}
              onSelectSession={(id) => {
                setSelectedSessionId(id)
                setActiveTab('timeline')
              }}
            />
          )}
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
            <ProvenanceTab
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
          )}
          {activeTab === 'operations' && (
            <OperationsTab operations={operations} onRefresh={() => api.operations().then(setOperations).catch((e) => setError(String(e)))} />
          )}
          {activeTab === 'settings' && (
            <SettingsTab
              profile={operatorProfile}
              setProfile={setOperatorProfile}
              profileId={operations?.profile_id ?? 'default'}
              onNotice={setNotice}
              onError={setError}
            />
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
        </div>
      </section>

      <Inspector
        memoryId={selectedMemoryId}
        onSelectMemory={selectMemory}
        onClose={() => setSelectedMemoryId(null)}
      />

      {selectedGraphNode && (
        <NodePopup
          node={selectedGraphNode}
          exchanges={exchanges}
          root={root}
          onClose={() => setSelectedGraphNode(null)}
          onSelectMemory={selectMemory}
        />
      )}
    </main>
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
  const [minScore, setMinScore] = useState(0.0)
  const [showAdvancedComposer, setShowAdvancedComposer] = useState(false)
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null)
  const [expandedTools, setExpandedTools] = useState<Record<number, boolean>>({})

  const selectedSession = useMemo(() => {
    return sessions.find(s => s.external_session_id === selectedSessionId)
  }, [sessions, selectedSessionId])

  const toggleToolExpand = (idx: number) => {
    setExpandedTools(prev => ({ ...prev, [idx]: !prev[idx] }))
  }

  const copyToClipboard = (text: string, idx: number) => {
    navigator.clipboard.writeText(text).then(() => {
      setCopiedIndex(idx)
      setTimeout(() => setCopiedIndex(null), 2000)
    }).catch(() => {})
  }

  const replayEvents = useMemo(() => {
    return sessionReplay?.events.filter(
      e => e.relevance_score == null || e.relevance_score >= minScore
    ) ?? []
  }, [sessionReplay, minScore])

  const hasContent = replayEvents.length > 0 || exchanges.length > 0

  return (
    <section className="tab-panel chat-session-layout">
      {/* Session Top Bar */}
      <header className="chat-session-header">
        <div className="chat-session-header-left">
          <div className="session-selector-box">
            <MessageSquare size={16} className="session-icon" />
            <select
              className="session-select form-select"
              value={selectedSessionId}
              onChange={(event) => setSelectedSessionId(event.target.value)}
            >
              <option value="">Select an Agent Session…</option>
              {sessions.map((session) => (
                <option key={session.id} value={session.external_session_id}>
                  {formatSessionLabel(session)}
                </option>
              ))}
            </select>
          </div>

          {selectedSession && (
            <div className="session-status-chips">
              <span className={`chat-status-pill ${!selectedSession.ended_at ? 'active' : 'closed'}`}>
                <span className={`mini-dot ${!selectedSession.ended_at ? 'pulse' : ''}`} />
                {!selectedSession.ended_at ? 'Active Session' : 'Closed Session'}
              </span>
              <span className="chat-tier-pill">
                Tier: <b>{selectedSession.retention_tier || 'standard'}</b>
              </span>
            </div>
          )}
        </div>

        <div className="chat-session-header-right">
          <div className="semantic-filter-control">
            <span className="filter-slider-label">Score ≥ <b>{minScore.toFixed(2)}</b></span>
            <input
              type="range"
              min="0"
              max="1"
              step="0.05"
              value={minScore}
              onChange={e => setMinScore(Number(e.target.value))}
              title="Filter by memory relevance score"
              className="score-slider"
            />
          </div>

          {sessionReplay && (
            <span className={`merkle-lineage-badge ${sessionReplay.replayable ? 'verified' : 'unverified'}`}>
              <ShieldCheck size={13} />
              <span>{sessionReplay.replayable ? 'Merkle Lineage Verified' : 'Raw Trace'}</span>
            </span>
          )}

          {exchanges.length === 0 && selectedSessionId && (
            <button
              type="button"
              className="build-exchanges-btn"
              onClick={() => {
                api.buildSessionExchanges(selectedSessionId)
                  .then(() => window.location.reload())
              }}
            >
              Build DAG Exchanges
            </button>
          )}
        </div>
      </header>

      {/* Main Chat Conversation Scroll Area */}
      <div className="chat-conversation-viewport">
        {!hasContent ? (
          <div className="chat-empty-state">
            <div className="empty-chat-icon">
              <MessageSquare size={32} />
            </div>
            <h3>{selectedSessionId ? 'No exchanges recorded in this session yet' : 'Select a session to view conversation'}</h3>
            <p>
              {selectedSessionId
                ? 'Type a message below to record the first human-agent exchange in this session graph.'
                : 'Choose an active or recorded agent session from the dropdown above to inspect its verified prompt and response trail.'}
            </p>
          </div>
        ) : (
          <div className="chat-turns-stream">
            {replayEvents.length > 0 ? (
              replayEvents.map((event, idx) => {
                const isUser = event.role === 'user' || event.event_type === 'prompt'
                const isTool = event.event_type === 'tool_call' || event.event_type === 'tool_result'
                const summary = event.meta_json?.summary
                const isArchived = event.meta_status === 'archived'
                const displayContent = summary || (
                  event.event_type === 'tool_call'
                    ? (typeof event.tool_input === 'string' ? event.tool_input : JSON.stringify(event.tool_input, null, 2))
                    : event.event_type === 'tool_result'
                    ? (typeof event.tool_output === 'string' ? event.tool_output : JSON.stringify(event.tool_output, null, 2))
                    : event.content || ''
                )

                if (isUser) {
                  return (
                    <div className="chat-turn turn-user" key={idx}>
                      <div className="turn-avatar user-avatar" title="Human Operator">
                        <User size={16} />
                      </div>
                      <div className="turn-body">
                        <div className="turn-meta">
                          <span className="sender-name">Operator</span>
                          {event.timestamp && <time className="turn-time">{event.timestamp}</time>}
                        </div>
                        <div className="user-bubble">
                          <p>{displayContent}</p>
                        </div>
                      </div>
                    </div>
                  )
                }

                if (isTool) {
                  const isExpanded = !!expandedTools[idx]
                  return (
                    <div className="chat-turn turn-tool" key={idx}>
                      <div className="turn-avatar tool-avatar" title="Autonomous Tool Execution">
                        <Terminal size={15} />
                      </div>
                      <div className="tool-card-wrapper">
                        <div
                          className="tool-card-header"
                          onClick={() => toggleToolExpand(idx)}
                          role="button"
                          tabIndex={0}
                        >
                          <div className="tool-card-title">
                            <Terminal size={14} className="terminal-icon" />
                            <b>Tool Call: <code>{event.tool_name || 'agent_action'}</code></b>
                            <span className="tool-event-type">{event.event_type}</span>
                          </div>
                          <div className="tool-card-right">
                            {event.timestamp && <time className="turn-time">{event.timestamp}</time>}
                            <span className="expand-hint">{isExpanded ? 'Collapse' : 'Inspect'}</span>
                          </div>
                        </div>
                        {isExpanded && (
                          <div className="tool-payload-drawer">
                            <pre className="tool-code-block">
                              <code>{displayContent}</code>
                            </pre>
                          </div>
                        )}
                      </div>
                    </div>
                  )
                }

                // Default is Agent Response
                return (
                  <div className="chat-turn turn-agent" key={idx}>
                    <div className="turn-avatar agent-avatar" title="Cortex Agent">
                      <img src="/brain-logo.jpg" alt="Cortex Agent" />
                    </div>
                    <div className="turn-body">
                      <div className="turn-meta">
                        <span className="sender-name">Cortex Cognitive Agent</span>
                        <span className="agent-engine-chip">Memory-Augmented</span>
                        {event.timestamp && <time className="turn-time">{event.timestamp}</time>}
                        <button
                          type="button"
                          className="chat-copy-btn"
                          onClick={() => copyToClipboard(displayContent, idx)}
                          title="Copy response"
                        >
                          {copiedIndex === idx ? <Check size={13} className="text-good" /> : <Copy size={13} />}
                        </button>
                      </div>

                      <div className="agent-bubble">
                        <div className="agent-markdown">
                          <ReactMarkdown>{displayContent}</ReactMarkdown>
                        </div>

                        {(event.relevance_score != null || isArchived || event.memory_id) && (
                          <div className="agent-provenance-bar">
                            <Sparkles size={12} className="sparkle-icon" />
                            <span className="provenance-label">Grounded Lineage:</span>
                            {event.memory_id && (
                              <button
                                type="button"
                                className="grounded-memory-chip"
                                onClick={() => onSelectMemory(event.memory_id!)}
                                title="Inspect memory details"
                              >
                                Memory #{event.memory_id.substring(0, 8)}…
                              </button>
                            )}
                            {event.relevance_score != null && !Number.isNaN(Number(event.relevance_score)) && (
                              <span className="score-badge">Relevance {Number(event.relevance_score).toFixed(2)}</span>
                            )}
                            {isArchived && <span className="archived-badge">Archived</span>}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                )
              })
            ) : (
              // Fallback to exchanges if replay events are not parsed
              exchanges.map((exchange) => (
                <React.Fragment key={exchange.id}>
                  {/* Prompt Turn */}
                  <div className="chat-turn turn-user">
                    <div className="turn-avatar user-avatar"><User size={16} /></div>
                    <div className="turn-body">
                      <div className="turn-meta">
                        <span className="sender-name">Operator</span>
                        {exchange.prompt_time && <time className="turn-time">{exchange.prompt_time}</time>}
                      </div>
                      <div className="user-bubble">
                        <p>{exchange.prompt_memories?.[0]?.content || `Exchange #${exchange.sequence_number}`}</p>
                      </div>
                    </div>
                  </div>

                  {/* Context contributions if any */}
                  {exchange.context_contributions && exchange.context_contributions.length > 0 && (
                    <div className="context-turn-pill">
                      <Sparkles size={12} />
                      <span>{exchange.context_contributions.length} memory contexts supplied to model</span>
                    </div>
                  )}

                  {/* Response Turn */}
                  <div className="chat-turn turn-agent">
                    <div className="turn-avatar agent-avatar"><img src="/brain-logo.jpg" alt="Cortex Agent" /></div>
                    <div className="turn-body">
                      <div className="turn-meta">
                        <span className="sender-name">Cortex Cognitive Agent</span>
                        {exchange.latency_ms && <span className="agent-engine-chip">{exchange.latency_ms}ms</span>}
                        {exchange.response_time && <time className="turn-time">{exchange.response_time}</time>}
                      </div>
                      <div className="agent-bubble">
                        <div className="agent-markdown">
                          <ReactMarkdown>
                            {exchange.response_memories?.[0]?.content || 'Turn response committed to Merkle DAG.'}
                          </ReactMarkdown>
                        </div>
                        <div className="agent-provenance-bar">
                          <Hash value={exchange.node_id} />
                          <span className="score-badge">Seq #{exchange.sequence_number}</span>
                        </div>
                      </div>
                    </div>
                  </div>
                </React.Fragment>
              ))
            )}
          </div>
        )}
      </div>

      {/* Modern Fixed Chat Composer Dock */}
      <footer className="chat-composer-dock">
        <form className="chat-composer-form" onSubmit={onRecord}>
          <input
            type="hidden"
            name="session"
            value={selectedSessionId || (sessions[0]?.external_session_id ?? 'mvp-demo-session')}
          />

          <div className="composer-toolbar">
            <div className="composer-context-chips">
              <span className="context-chip session-chip">
                <MessageSquare size={12} />
                <span>Target: <b>{selectedSessionId || (sessions[0]?.external_session_id ?? 'mvp-demo-session')}</b></span>
              </span>
              {contextBundle.length > 0 && (
                <span className="context-chip bundle-chip">
                  <Sparkles size={12} />
                  <span>{contextBundle.length} memories attached as ground truth</span>
                </span>
              )}
            </div>
            <button
              type="button"
              className="toggle-advanced-mode-btn"
              onClick={() => setShowAdvancedComposer(!showAdvancedComposer)}
            >
              {showAdvancedComposer ? 'Simple prompt' : 'Advanced (Response & Context)'}
            </button>
          </div>

          <div className="composer-main-row">
            <textarea
              className="composer-textarea"
              name="prompt"
              required
              rows={showAdvancedComposer ? 2 : 1}
              placeholder="Type user prompt to record in session graph (or press Enter)..."
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey && !showAdvancedComposer) {
                  e.preventDefault();
                  (e.currentTarget.form as HTMLFormElement)?.requestSubmit();
                }
              }}
            />
            <button type="submit" className="composer-send-btn" title="Send Turn / Record Exchange">
              <Send size={15} />
              <span>Record</span>
            </button>
          </div>

          {showAdvancedComposer && (
            <div className="composer-advanced-fields">
              <div className="advanced-input-wrap">
                <label>Full Agent Response (Optional override)</label>
                <textarea
                  className="form-textarea"
                  name="response"
                  rows={2}
                  placeholder="Simulated or model response text..."
                  defaultValue="Observed agent response verified against session context."
                />
              </div>
              <div className="advanced-input-wrap">
                <label>Additional Contributed Context (one item per line)</label>
                <textarea
                  className="form-textarea"
                  name="context"
                  rows={2}
                  placeholder="Additional reference facts or background knowledge..."
                />
              </div>
            </div>
          )}
        </form>
      </footer>
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
  const [graphMode, setGraphMode] = useState<'3d' | '2d'>('3d')

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
  const options: GraphViewOptions = { background, zoom, panX, panY, fitMode, fitNonce, showGrid: true }
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
            className="session-select form-select"
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
          <select  className="form-select" value={background} onChange={(event) => setBackground(event.target.value as GraphBackground)} title="Background">
            {backgroundOptions.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
          </select>
          <select  className="form-select" value={nodeType} onChange={(event) => setNodeType(event.target.value as DemoNodeType | 'all')} title="Node type">
            {nodeTypes.map((type) => <option key={type} value={type}>{type === 'all' ? 'All nodes' : type}</option>)}
          </select>
          <select  className="form-select" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} title="Lifecycle Status">
            {statusOptions.map((status) => <option key={status} value={status}>{status === 'all' ? 'All statuses' : status}</option>)}
          </select>
          <select  className="form-select" value={evidenceFilter} onChange={(event) => setEvidenceFilter(event.target.value)} title="Evidence Class">
            {evidenceOptions.map((item) => <option key={item} value={item}>{item === 'all' ? 'All evidence' : item}</option>)}
          </select>
          <select  className="form-select" value={sourceKindFilter} onChange={(event) => setSourceKindFilter(event.target.value)} title="Source Kind">
            {sourceKindOptions.map((item) => <option key={item} value={item}>{item === 'all' ? 'All sources' : item}</option>)}
          </select>
          <select  className="form-select" value={edgeType} onChange={(event) => setEdgeType(event.target.value)} title="Connection Type">
            {edgeTypes.map((type) => <option key={type} value={type}>{type === 'all' ? 'All connections' : `${connectionReference[type]?.label ?? type} (${edgeCounts.get(type) ?? 0})`}</option>)}
          </select>
          <select  className="form-select" value={predicateFilter} onChange={(event) => setPredicateFilter(event.target.value)} title="Relation Predicate">
            {predicateOptions.map((predicate) => <option key={predicate} value={predicate}>{predicate === 'all' ? 'All predicates' : predicate}</option>)}
          </select>
          <input
             className="form-input" title={`Similarity Threshold: ${similarityThreshold.toFixed(2)}`}
            max="0.99"
            min="0.2"
            onChange={(event) => onSimilarityThresholdChange(Number(event.target.value))}
            step="0.01"
            type="range"
            value={similarityThreshold}
            style={{ width: '80px', pointerEvents: 'auto', alignSelf: 'center' }}
          />
          <div className="button-group">
            <button onClick={() => setGraphMode(m => m === '3d' ? '2d' : '3d')} type="button" title="Toggle 2D/3D">{graphMode === '3d' ? '2D' : '3D'}</button>
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
            <span style={{ fontWeight: 'bold', textTransform: 'uppercase', letterSpacing: '0.05em', opacity: 0.8 }}>Connections</span>
            <select
               className="form-select" value={edgeType}
              onChange={(e) => setEdgeType(e.target.value)}
              style={{ background: 'rgba(255,255,255,0.1)', border: 'none', borderRadius: '4px', color: '#fff', padding: '2px 6px', cursor: 'pointer' }}
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
        {graphMode === '3d' ? (
          <Graph3DView
            graph={filteredGraph}
            selectedNodeId={selectedNodeHidden ? null : selectedNodeId}
            selectedEdgeKey={selectedEdgeHidden ? null : selectedEdge ? graphEdgeKey(selectedEdge) : null}
            options={options}
            onSelectNode={onSelectNode}
            onSelectEdge={setSelectedEdge}
          />
        ) : (
          <Graph2DView
            graph={filteredGraph}
            selectedNodeId={selectedNodeHidden ? null : selectedNodeId}
            selectedEdgeKey={selectedEdgeHidden ? null : selectedEdge ? graphEdgeKey(selectedEdge) : null}
            options={options}
            onSelectNode={onSelectNode}
            onSelectEdge={setSelectedEdge}
            onBackgroundClick={() => {}}
          />
        )}
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
            <select  className="form-select" value={traversalDepth} onChange={(event) => setTraversalDepth(Number(event.target.value))}>
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
            <input  className="form-input" value={pathFrom} onChange={(event) => setPathFrom(event.target.value)} placeholder={selectedNodeLabel ?? 'Entity name'} />
            {selectedNodeLabel && (
              <button onClick={() => setPathFrom(selectedNodeLabel)} type="button" style={{ padding: '2px 6px', whiteSpace: 'nowrap' }} title="Use selected node as From">Use Selected</button>
            )}
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
            To
            <input  className="form-input" value={pathTo} onChange={(event) => setPathTo(event.target.value)} placeholder="Entity name" />
            {selectedNodeLabel && (
              <button onClick={() => setPathTo(selectedNodeLabel)} type="button" style={{ padding: '2px 6px', whiteSpace: 'nowrap' }} title="Use selected node as To">Use Selected</button>
            )}
          </label>
          <label>
            Path depth
            <select  className="form-select" value={pathDepth} onChange={(event) => setPathDepth(Number(event.target.value))}>
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
  const quickFilters = ['architecture', 'security', 'production', 'decision', 'cortex', 'shield']
  const totalContradictions = useMemo(() => {
    let count = 0
    contradictionCounts.forEach(c => count += c)
    return count
  }, [contradictionCounts])

  return (
    <section className="tab-panel">
      <header className="tab-hero-header">
        <div className="tab-hero-main">
          <div className="overview-kicker">
            <span className="kicker-pulse" />
            <span>COGNITIVE CONTROL PLANE</span>
            <span className="kicker-divider">/</span>
            <span className="kicker-live">RETRIEVAL ENGINE</span>
          </div>
          <h2>Memory Recall & Semantic Search</h2>
          <div className="overview-meta-strip">
            <span className="meta-chip">
              <Search size={13} />
              <span>Hybrid Lexical + Vector</span>
            </span>
            <span className="meta-chip status-chip good">
              <span className="mini-dot pulse" />
              <span>{results.length} memories matching</span>
            </span>
            {query && (
              <span className="meta-chip">
                <span>Query: <b>{query}</b></span>
              </span>
            )}
          </div>
        </div>
      </header>

      {/* KPI Stats Row */}
      <div className="overview-kpi-grid" style={{ marginBottom: '20px' }}>
        <div className="kpi-card">
          <div className="kpi-icon-wrap memories"><Database size={20} /></div>
          <div className="kpi-content">
            <div className="kpi-value">{results.length}</div>
            <div className="kpi-label">Matched Records</div>
            <div className="kpi-subtext">Active & confirmed memories</div>
          </div>
        </div>
        <div className="kpi-card">
          <div className="kpi-icon-wrap relations"><Sparkles size={20} /></div>
          <div className="kpi-content">
            <div className="kpi-value">{query.trim() ? results.filter(r => r.status === 'active').length : 'Ready'}</div>
            <div className="kpi-label">Active State</div>
            <div className="kpi-subtext">Direct context eligibility</div>
          </div>
        </div>
        <div className="kpi-card">
          <div className="kpi-icon-wrap sessions"><ShieldCheck size={20} /></div>
          <div className="kpi-content">
            <div className="kpi-value">{totalContradictions}</div>
            <div className="kpi-label">Contradictions</div>
            <div className="kpi-subtext">Automated dispute alerts</div>
          </div>
        </div>
        <div className="kpi-card">
          <div className="kpi-icon-wrap readiness"><Cpu size={20} /></div>
          <div className="kpi-content">
            <div className="kpi-value">FTS5 + Vector</div>
            <div className="kpi-label">Search Pipeline</div>
            <div className="kpi-subtext">Dual lexical & semantic</div>
          </div>
        </div>
      </div>

      {/* Search Hero Bar */}
      <div className="tab-search-hero">
        <Search size={18} style={{ color: 'var(--accent)', flexShrink: 0 }} />
        <input
          className="search-input"
          value={query}
          onChange={(event) => onQuery(event.target.value)}
          placeholder="Search active memories, code patterns, operational decisions, architectural facts..."
          aria-label="Search memories"
          autoFocus
        />
        {query && (
          <button
            type="button"
            className="small-button"
            onClick={() => onQuery('')}
            style={{ padding: '2px 8px', fontSize: '11px' }}
          >
            Clear
          </button>
        )}
        <span className="tab-search-shortcut">ESC / ENTER</span>
      </div>

      {/* Quick Filter Suggestion Chips */}
      <div className="quick-filter-chips">
        <span style={{ fontSize: '11px', color: 'var(--text-muted)', marginRight: '6px' }}>Quick search:</span>
        {quickFilters.map((term) => (
          <button
            key={term}
            type="button"
            className={`quick-filter-chip ${query === term ? 'active' : ''}`}
            onClick={() => onQuery(term)}
          >
            #{term}
          </button>
        ))}
      </div>

      {searchError ? (
        <div className="empty-state error-state" role="alert"><h4>Recall unavailable</h4><p>{searchError}</p></div>
      ) : searchLoading ? (
        <div className="empty-state" role="status"><h4>Searching memories…</h4><p>Checking active and confirmed memory records across database.</p></div>
      ) : query.trim() && results.length === 0 ? (
        <div className="empty-state" role="status"><h4>No matching memories</h4><p>Try a broader phrase or confirm that the memory is active.</p></div>
      ) : !query.trim() ? (
        <div className="empty-state">
          <div className="empty-chat-icon"><Search size={28} /></div>
          <h4>Search your memory graph</h4>
          <p>Enter a query above or click any tag to retrieve active knowledge facts with cryptographic provenance.</p>
        </div>
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
    <section className="overview-card" style={{ marginTop: '24px' }}>
      <header className="overview-card-header">
        <div>
          <div className="overview-card-kicker">AUTONOMOUS PARSER</div>
          <div className="overview-card-title">PARA Organization Review</div>
        </div>
        <div className="overview-card-badge">
          {proposals.length} proposed
        </div>
      </header>
      <div className="overview-card-body">
        <p className="small muted" style={{ margin: '0 0 16px 0' }}>
          Derived organization suggestions generated by background classification workers. Nothing moves without operator confirmation.
        </p>
        {proposals.length === 0 ? (
          <div className="empty-state"><h4>No pending PARA proposals</h4><p>Queue a PARA classification for any memory from the Inference tab.</p></div>
        ) : (
          <div className="item-list">
            {proposals.map((proposal) => (
              <article className="item" key={proposal.task_id}>
                <div className="item-head">
                  <strong style={{ color: 'var(--accent)', textTransform: 'capitalize' }}>{proposal.category}</strong>
                  <Badge>{(proposal.confidence * 100).toFixed(0)}% confidence</Badge>
                </div>
                <p style={{ margin: '8px 0', fontSize: '13px' }}>{proposal.rationale}</p>
                <p className="small muted">source hash <Hash value={proposal.source_content_hash} /></p>
                {proposal.signals.length > 0 && <p className="small muted">signals: {proposal.signals.join(', ')}</p>}
                <div className="action-row" style={{ marginTop: '12px' }}>
                  <button type="button" className="small-button" onClick={() => onSelectMemory(proposal.memory_id)}>Inspect source</button>
                  <button type="button" className="small-button" onClick={() => onDecision(proposal.task_id, 'accept')}>Accept</button>
                  <button type="button" className="small-button" onClick={() => onDecision(proposal.task_id, 'keep_original')}>Keep original</button>
                  <button type="button" className="small-button" onClick={() => onDecision(proposal.task_id, 'dismiss')}>Dismiss</button>
                </div>
              </article>
            ))}
          </div>
        )}
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
  const [taskSearch, setTaskSearch] = useState('')

  const filteredTasks = useMemo(() => {
    if (!taskSearch.trim()) return tasks
    const q = taskSearch.toLowerCase()
    return tasks.filter(
      t => t.task_type.toLowerCase().includes(q) || t.subject_id.toLowerCase().includes(q) || t.subject_type.toLowerCase().includes(q)
    )
  }, [tasks, taskSearch])

  return (
    <section className="tab-panel">
      <header className="tab-hero-header">
        <div className="tab-hero-main">
          <div className="overview-kicker">
            <span className="kicker-pulse" />
            <span>COGNITIVE CONTROL PLANE</span>
            <span className="kicker-divider">/</span>
            <span className="kicker-live">INFERENCE & GOVERNANCE</span>
          </div>
          <h2>Task Queue & Autonomous Workers</h2>
          <div className="overview-meta-strip">
            <span className="meta-chip">
              <Cpu size={13} />
              <span>Manifest: <b>{manifest?.name ?? 'xibalba-memory-inference'}</b></span>
            </span>
            <span className="meta-chip status-chip good">
              <span className="mini-dot pulse" />
              <span>{tasks.length} {taskStatus} tasks</span>
            </span>
            {selectedSessionId && (
              <span className="meta-chip">
                <span>Session: <b>{selectedSessionId}</b></span>
              </span>
            )}
          </div>
        </div>
      </header>

      {/* KPI Stats Row */}
      <div className="overview-kpi-grid" style={{ marginBottom: '20px' }}>
        <div className="kpi-card">
          <div className="kpi-icon-wrap memories"><Cpu size={20} /></div>
          <div className="kpi-content">
            <div className="kpi-value">{tasks.length}</div>
            <div className="kpi-label">Tasks in Filter</div>
            <div className="kpi-subtext">Current status: {taskStatus}</div>
          </div>
        </div>
        <div className="kpi-card">
          <div className="kpi-icon-wrap relations"><Layers size={20} /></div>
          <div className="kpi-content">
            <div className="kpi-value">{manifest?.task_types.length ?? 0}</div>
            <div className="kpi-label">Registered Types</div>
            <div className="kpi-subtext">Extraction & synthesis</div>
          </div>
        </div>
        <div className="kpi-card">
          <div className="kpi-icon-wrap sessions"><MessageSquare size={20} /></div>
          <div className="kpi-content">
            <div className="kpi-value">{selectedSessionId ? 'Bound' : 'Global'}</div>
            <div className="kpi-label">Target Session</div>
            <div className="kpi-subtext">{selectedSessionId || 'All sessions eligible'}</div>
          </div>
        </div>
        <div className="kpi-card">
          <div className="kpi-icon-wrap readiness"><ShieldCheck size={20} /></div>
          <div className="kpi-content">
            <div className="kpi-value">{selectedMemoryId ? 'Attached' : 'None'}</div>
            <div className="kpi-label">Selected Memory</div>
            <div className="kpi-subtext">{selectedMemoryId ? `#${selectedMemoryId.substring(0, 8)}…` : 'Select memory to queue'}</div>
          </div>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(320px, 1fr) minmax(420px, 1.5fr)', gap: '16px' }}>
        {/* Left Card: Manifest & Queue Actions */}
        <section className="overview-card">
          <header className="overview-card-header">
            <div>
              <div className="overview-card-kicker">WORKER REGISTRATION</div>
              <div className="overview-card-title">Manifest & Queue Trigger</div>
            </div>
            <select
              className="session-select form-select"
              value={selectedSessionId}
              onChange={(event) => setSelectedSessionId(event.target.value)}
              style={{ fontSize: '11px', padding: '3px 8px' }}
            >
              <option value="">All agent sessions</option>
              {sessions.map((session) => (
                <option key={session.id} value={session.external_session_id}>
                  {formatSessionLabel(session)}
                </option>
              ))}
            </select>
          </header>
          <div className="overview-card-body">
            {manifest && (
              <div className="manifest" style={{ marginBottom: '16px' }}>
                <p style={{ fontWeight: 600, color: '#fff', margin: '0 0 6px 0', fontSize: '13px' }}>{manifest.role}</p>
                <div style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid var(--border)', borderRadius: '6px', padding: '10px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  <p className="small muted" style={{ margin: 0 }}>
                    <b style={{ color: 'var(--text)' }}>Input rule:</b> {manifest.input_rule}
                  </p>
                  <p className="small muted" style={{ margin: 0 }}>
                    <b style={{ color: 'var(--text)' }}>Output rule:</b> {manifest.output_rule}
                  </p>
                </div>
                <div style={{ marginTop: '14px' }}>
                  <label style={{ display: 'block', fontSize: '11px', color: 'var(--text-muted)', marginBottom: '6px' }}>
                    Task Type to Enqueue:
                  </label>
                  <select
                    className="form-select"
                    value={selectedTaskType}
                    onChange={(e) => setSelectedTaskType(e.target.value)}
                    style={{ width: '100%', padding: '6px 10px', fontSize: '12px' }}
                  >
                    {manifest.task_types.map((type) => (
                      <option key={type} value={type}>{type}</option>
                    ))}
                  </select>
                </div>
              </div>
            )}
            <div className="action-row" style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', paddingTop: '10px', borderTop: '1px solid rgba(255,255,255,0.06)' }}>
              <button
                type="button"
                className="small-button"
                disabled={!selectedMemoryId}
                onClick={() => selectedMemoryId && onQueue('memory', selectedMemoryId, selectedTaskType)}
                title={selectedMemoryId ? 'Queue selected memory for inference' : 'Select a memory record first'}
              >
                Queue memory {selectedMemoryId ? `(#${selectedMemoryId.substring(0, 6)}…)` : '(none selected)'}
              </button>
              <button
                type="button"
                className="small-button"
                disabled={!selectedSessionId}
                onClick={() => onQueue('session', selectedSessionId, selectedTaskType)}
                title={selectedSessionId ? 'Queue selected session for inference' : 'Select a session first'}
              >
                Queue session {selectedSessionId ? `(#${selectedSessionId.substring(0, 8)}…)` : '(none selected)'}
              </button>
            </div>
          </div>
        </section>

        {/* Right Card: Tasks List */}
        <section className="overview-card">
          <header className="overview-card-header">
            <div>
              <div className="overview-card-kicker">PIPELINE EXECUTION</div>
              <div className="overview-card-title">Inference Tasks Queue</div>
            </div>
            <div className="task-status-filter-pills">
              {['pending', 'claimed', 'completed', 'failed', 'cancelled'].map((status) => (
                <button
                  key={status}
                  type="button"
                  className={`task-status-pill-btn ${taskStatus === status ? 'active' : ''}`}
                  onClick={() => onStatus(status)}
                >
                  {status}
                </button>
              ))}
            </div>
          </header>
          <div className="overview-card-body">
            <div className="tab-search-hero" style={{ padding: '6px 12px', marginBottom: '8px' }}>
              <Search size={14} style={{ color: 'var(--text-muted)' }} />
              <input
                className="search-input"
                style={{ fontSize: '12px' }}
                value={taskSearch}
                onChange={e => setTaskSearch(e.target.value)}
                placeholder="Filter tasks by subject ID or type..."
              />
              {taskSearch && (
                <button
                  type="button"
                  className="small-button"
                  style={{ padding: '1px 6px', fontSize: '10px' }}
                  onClick={() => setTaskSearch('')}
                >
                  ✕
                </button>
              )}
            </div>

            {filteredTasks.length === 0 ? (
              <div className="empty-state">
                <h4>No {taskStatus} tasks {taskSearch ? 'matching query' : ''}</h4>
                <p>Use the queue controls on the left to dispatch a memory or session to background inference.</p>
              </div>
            ) : (
              <div className="item-list" style={{ maxHeight: '520px', overflowY: 'auto' }}>
                {filteredTasks.map((task) => (
                  <article className="item" key={task.id} style={{ padding: '12px 14px' }}>
                    <div className="item-head">
                      <strong style={{ color: 'var(--accent)', fontFamily: 'monospace', fontSize: '13px' }}>
                        {task.task_type}
                      </strong>
                      <Badge>{task.status}</Badge>
                    </div>
                    <p className="small muted" style={{ margin: '4px 0' }}>
                      {task.subject_type} · <code>{task.subject_id}</code>
                    </p>
                    <div className="action-row" style={{ marginTop: '8px' }}>
                      <button className="small-button" disabled={task.status !== 'pending'} onClick={() => onClaim(task)}>
                        Claim Task
                      </button>
                      <button className="small-button" disabled={task.status === 'completed'} onClick={() => onComplete(task)}>
                        Complete demo output
                      </button>
                    </div>
                    <WriteBackActions task={task} selectedMemoryId={selectedMemoryId} onWriteBack={onWriteBack} />
                  </article>
                ))}
              </div>
            )}
          </div>
        </section>
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
  const [isOpen, setIsOpen] = useState(false)
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
    setIsOpen(false)
  }

  if (!isOpen) {
    return (
      <div style={{ marginTop: '6px' }}>
        <button
          type="button"
          className="link-button"
          style={{ fontSize: '11px', color: 'var(--text-muted)', display: 'inline-flex', alignItems: 'center', gap: '4px' }}
          onClick={() => setIsOpen(true)}
        >
          <span>+ Explicit Write Back</span>
        </button>
      </div>
    )
  }

  return (
    <section className="writeback-panel" style={{ marginTop: '10px', padding: '10px', background: 'rgba(0,0,0,0.3)', borderRadius: '6px', border: '1px solid var(--border)' }}>
      <div className="writeback-head">
        <strong style={{ fontSize: '12px' }}>Explicit Write Back</strong>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <select className="form-select" value={action} onChange={(event) => setAction(event.target.value)} style={{ fontSize: '11px', padding: '2px 6px' }}>
            <option value="proposition">Create proposition</option>
            <option value="link_entities">Link entities</option>
            <option value="contradiction">Mark contradiction</option>
            <option value="supersede">Supersede memory</option>
          </select>
          <button type="button" className="small-button" onClick={() => setIsOpen(false)} style={{ padding: '2px 6px', fontSize: '10px' }}>
            Cancel
          </button>
        </div>
      </div>
      {(action === 'proposition' || action === 'supersede') && (
        <textarea
          className="form-textarea"
          value={content}
          onChange={(event) => setContent(event.target.value)}
          placeholder="Operator-reviewed proposition or replacement memory"
          style={{ margin: '8px 0', fontSize: '12px' }}
        />
      )}
      {action === 'link_entities' && (
        <div className="writeback-grid" style={{ margin: '8px 0' }}>
          <input className="form-input" value={subject} onChange={(event) => setSubject(event.target.value)} placeholder="Subject entity" />
          <input className="form-input" value={predicate} onChange={(event) => setPredicate(event.target.value)} placeholder="Predicate" />
          <input className="form-input" value={object} onChange={(event) => setObject(event.target.value)} placeholder="Object entity" />
        </div>
      )}
      {action === 'contradiction' && (
        <div className="writeback-grid two" style={{ margin: '8px 0' }}>
          <input className="form-input" value={otherMemoryId} onChange={(event) => setOtherMemoryId(event.target.value)} placeholder="Other memory id" />
          <input className="form-input" value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Reason" />
        </div>
      )}
      <div className="writeback-foot" style={{ marginTop: '8px' }}>
        <span className="small muted">Target: {evidenceMemoryId ? `#${evidenceMemoryId.substring(0, 8)}…` : 'None'}</span>
        <button className="small-button" disabled={!canApply} onClick={apply} type="button">Apply write back</button>
      </div>
    </section>
  )
}

function OperationsTab({ operations, onRefresh }: { operations: OperationsSnapshot | null; onRefresh: () => void }) {
  if (!operations) {
    return (
      <section className="tab-panel">
        <header className="tab-hero-header">
          <div className="tab-hero-main">
            <div className="overview-kicker">
              <span className="kicker-pulse" />
              <span>LOCAL CONTROL PLANE</span>
              <span className="kicker-divider">/</span>
              <span className="kicker-live">TENANT RUNTIME</span>
            </div>
            <h2>Operations & Deployment Governance</h2>
          </div>
        </header>
        <div className="empty-state">
          <div className="spinning" style={{ marginBottom: '12px' }}><RefreshCw size={24} /></div>
          <h4>Loading operational evidence…</h4>
          <p>Polling local control-plane status, SQLite pragmas, and provider readiness.</p>
        </div>
      </section>
    )
  }

  const status = operations.health.status
  const coverage = operations.embedding_coverage as Record<string, unknown>
  const audit = operations.audit as Record<string, unknown>
  const taskStates = (audit.inference_task_states as Record<string, number> | undefined) || {}
  const proposalStates = (audit.proposal_states as Record<string, number> | undefined) || {}

  return (
    <section className="tab-panel">
      <header className="tab-hero-header">
        <div className="tab-hero-main">
          <div className="overview-kicker">
            <span className="kicker-pulse" />
            <span>LOCAL CONTROL PLANE</span>
            <span className="kicker-divider">/</span>
            <span className="kicker-live">TENANT RUNTIME</span>
          </div>
          <h2>Operations & Deployment Governance</h2>
          <div className="overview-meta-strip">
            <span className="meta-chip">
              <Server size={13} />
              <span>Profile: <b>{operations.profile_id}</b></span>
            </span>
            <span className="meta-chip status-chip good">
              <span className="mini-dot pulse" />
              <span>Health: {operations.health.state}</span>
            </span>
            <span className="meta-chip">
              <HardDrive size={13} />
              <span>Engine: {status.journal_mode}</span>
            </span>
          </div>
        </div>
        <button className="cortex-cta" onClick={onRefresh} type="button">
          <RefreshCw size={14} />
          <span>Refresh Snapshot</span>
        </button>
      </header>

      {/* KPI Stats Row */}
      <div className="overview-kpi-grid" style={{ marginBottom: '24px' }}>
        <div className="kpi-card">
          <div className="kpi-icon-wrap readiness"><CheckCircle2 size={20} /></div>
          <div className="kpi-content">
            <div className="kpi-value" style={{ textTransform: 'capitalize' }}>{operations.production.state}</div>
            <div className="kpi-label">Production Gate</div>
            <div className="kpi-subtext">{operations.production.open_gates.length} open gate checks</div>
          </div>
        </div>
        <div className="kpi-card">
          <div className="kpi-icon-wrap sessions"><ShieldCheck size={20} /></div>
          <div className="kpi-content">
            <div className="kpi-value">{operations.production.active_tokens}</div>
            <div className="kpi-label">Active Credentials</div>
            <div className="kpi-subtext">{operations.production.token_lifecycle}</div>
          </div>
        </div>
        <div className="kpi-card">
          <div className="kpi-icon-wrap memories"><Database size={20} /></div>
          <div className="kpi-content">
            <div className="kpi-value">{status.memory_count}</div>
            <div className="kpi-label">Memory Footprint</div>
            <div className="kpi-subtext">{String(coverage.current || 0)} embedded ({String(coverage.eligible || 0)} eligible)</div>
          </div>
        </div>
        <div className="kpi-card">
          <div className="kpi-icon-wrap relations"><HardDrive size={20} /></div>
          <div className="kpi-content">
            <div className="kpi-value">{status.integrity_check}</div>
            <div className="kpi-label">Store Integrity</div>
            <div className="kpi-subtext">Schema v{status.schema_version} · WAL Mode</div>
          </div>
        </div>
      </div>

      <div className="card-grid">
        {/* Card 1: Production Readiness */}
        <section className="overview-card">
          <header className="overview-card-header">
            <div>
              <div className="overview-card-kicker">GOVERNANCE</div>
              <div className="overview-card-title">Production Readiness</div>
            </div>
            <Badge>{operations.production.state}</Badge>
          </header>
          <div className="overview-card-body">
            <dl className="detail-list">
              <dt>Token lifecycle</dt><dd>{operations.production.token_lifecycle}</dd>
              <dt>Tenant onboarding</dt><dd>{operations.production.tenant_onboarding}</dd>
              <dt>Isolation</dt><dd>{operations.production.isolation_model}</dd>
            </dl>
            <h4 style={{ fontSize: '12px', textTransform: 'uppercase', color: 'var(--text-muted)', margin: '14px 0 6px' }}>
              Open production gates
            </h4>
            <ul className="small muted" style={{ margin: 0, paddingLeft: '18px' }}>
              {operations.production.open_gates.map((gate) => (
                <li key={gate} style={{ margin: '3px 0' }}>{gate}</li>
              ))}
            </ul>
            <p className="small muted" style={{ marginTop: '12px' }}>
              Local readiness evidence only. Tenant creation remains an operator-controlled action.
            </p>
          </div>
        </section>

        {/* Card 2: Deployment Health */}
        <section className="overview-card">
          <header className="overview-card-header">
            <div>
              <div className="overview-card-kicker">INFRASTRUCTURE</div>
              <div className="overview-card-title">Deployment & Engine Health</div>
            </div>
            <div className="badges">
              <Badge>{operations.health.state}</Badge>
              <Badge>{status.journal_mode}</Badge>
            </div>
          </header>
          <div className="overview-card-body">
            <dl className="detail-list">
              <dt>Schema version</dt><dd>v{status.schema_version}</dd>
              <dt>Integrity check</dt><dd style={{ color: 'var(--accent)' }}>{status.integrity_check}</dd>
              <dt>Foreign keys</dt><dd>{String(status.foreign_keys)}</dd>
              <dt>FTS5 engine</dt><dd>{String(status.fts5)}</dd>
              <dt>Backup status</dt><dd>{status.backup_ready ? 'ready' : 'pending'}</dd>
            </dl>
          </div>
        </section>

        {/* Card 3: Resources & Embedding Coverage */}
        <section className="overview-card">
          <header className="overview-card-header">
            <div>
              <div className="overview-card-kicker">VECTOR ENGINE</div>
              <div className="overview-card-title">Resources & Embedding Coverage</div>
            </div>
            <Badge>{operations.quotas.max_memories === null ? 'unlimited quota' : `limit ${operations.quotas.max_memories}`}</Badge>
          </header>
          <div className="overview-card-body">
            <dl className="detail-list">
              <dt>Total memories</dt><dd>{status.memory_count}</dd>
              <dt>Embedded</dt><dd style={{ color: 'var(--accent)' }}>{String(coverage.current || 0)} / {String(coverage.eligible || 0)}</dd>
              <dt>Missing</dt><dd>{String(coverage.missing || 0)}</dd>
              <dt>Stale</dt><dd>{String(coverage.stale || 0)}</dd>
              <dt>Failed</dt><dd>{String(coverage.failed || 0)}</dd>
            </dl>
          </div>
        </section>

        {/* Card 4: Feature Policy */}
        <section className="overview-card">
          <header className="overview-card-header">
            <div>
              <div className="overview-card-kicker">SECURITY POLICY</div>
              <div className="overview-card-title">Feature Capability Policies</div>
            </div>
          </header>
          <div className="overview-card-body">
            <div className="connector-grid">
              {Object.entries(operations.features).map(([name, enabled]) => (
                <div className="connector-row" key={name}>
                  <strong style={{ fontSize: '12px' }}>{name}</strong>
                  <Badge>{enabled ? 'enabled' : 'disabled'}</Badge>
                </div>
              ))}
            </div>
            <p className="small muted" style={{ marginTop: '12px' }}>
              Configured per profile; disabled capabilities fail closed at their API boundary.
            </p>
          </div>
        </section>

        {/* Card 5: Inference Governance */}
        <section className="overview-card">
          <header className="overview-card-header">
            <div>
              <div className="overview-card-kicker">AUDIT LOG</div>
              <div className="overview-card-title">Inference Task Governance</div>
            </div>
          </header>
          <div className="overview-card-body">
            <dl className="detail-list">
              {Object.entries(taskStates).map(([key, value]) => (
                <React.Fragment key={key}>
                  <dt>{key}</dt><dd>{value}</dd>
                </React.Fragment>
              ))}
              {Object.entries(proposalStates).map(([key, value]) => (
                <React.Fragment key={'proposal-' + key}>
                  <dt>proposal {key}</dt><dd>{value}</dd>
                </React.Fragment>
              ))}
            </dl>
            {Object.keys(taskStates).length === 0 && <p className="muted small">No inference tasks recorded.</p>}
          </div>
        </section>
      </div>

      {/* Connectors Estate Card */}
      <section className="overview-card" style={{ marginTop: '24px' }}>
        <header className="overview-card-header">
          <div>
            <div className="overview-card-kicker">INTEGRATION FABRIC</div>
            <div className="overview-card-title">Connectors Estate</div>
          </div>
          <div className="overview-card-badge">
            {Object.keys(operations.connectors).length} configured
          </div>
        </header>
        <div className="overview-card-body">
          <div className="connector-estate-grid">
            {Object.entries(operations.connectors).map(([name, connector]) => (
              <div className="connector-estate-card" key={name}>
                <div className="connector-head">
                  <div className="connector-icon-box">
                    <Layers size={16} />
                  </div>
                  <div className="connector-info">
                    <span className="connector-name">{name}</span>
                    <span className="connector-entrypoint">{connector.entrypoint}</span>
                  </div>
                </div>
                <div className="connector-status-row">
                  <span className={`status-pill ${connector.state === 'IMPLEMENTED' ? 'good' : 'neutral'}`}>
                    <span className="pill-dot" />
                    <span>{connector.state}</span>
                  </span>
                </div>
              </div>
            ))}
          </div>
          <p className="small muted" style={{ marginTop: '16px' }}>{operations.disclaimer}</p>
        </div>
      </section>
    </section>
  )
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
      <header className="tab-hero-header">
        <div className="tab-hero-main">
          <div className="overview-kicker">
            <span className="kicker-pulse" />
            <span>CRYPTOGRAPHIC PROVENANCE</span>
            <span className="kicker-divider">/</span>
            <span className="kicker-live">MERKLE DAG INTEGRITY</span>
          </div>
          <h2>Store & Exchange Lineage Verification</h2>
          <div className="overview-meta-strip">
            <span className="meta-chip status-chip good">
              <ShieldCheck size={13} />
              <span>Store: {storeStatus?.integrity_check ?? 'ok'}</span>
            </span>
            <span className="meta-chip">
              <HardDrive size={13} />
              <span>Engine: {storeStatus?.journal_mode ?? 'WAL'}</span>
            </span>
            <span className="meta-chip">
              <span>Schema: <b>v{storeStatus?.schema_version ?? '13'}</b></span>
            </span>
            {selectedSessionId && (
              <span className="meta-chip">
                <span>Session: <b>{selectedSessionId}</b></span>
              </span>
            )}
          </div>
        </div>

        <div className="session-selector-box">
          <MessageSquare size={16} className="session-icon" />
          <select
            className="session-select form-select"
            value={selectedSessionId}
            onChange={(event) => setSelectedSessionId(event.target.value)}
          >
            <option value="">Select Session to Inspect…</option>
            {sessions.map((session) => (
              <option key={session.id} value={session.external_session_id}>
                {formatSessionLabel(session)}
              </option>
            ))}
          </select>
        </div>
      </header>

      {/* KPI Stats Row */}
      <div className="overview-kpi-grid" style={{ marginBottom: '24px' }}>
        <div className="kpi-card">
          <div className="kpi-icon-wrap memories"><HardDrive size={20} /></div>
          <div className="kpi-content">
            <div className="kpi-value">{storeStatus?.integrity_check ?? 'ok'}</div>
            <div className="kpi-label">Store Integrity</div>
            <div className="kpi-subtext">SQLite pragma quick_check</div>
          </div>
        </div>
        <div className="kpi-card">
          <div className="kpi-icon-wrap readiness"><ShieldCheck size={20} /></div>
          <div className="kpi-content">
            <div className="kpi-value">{root?.valid ? 'Valid Root' : 'Unverified'}</div>
            <div className="kpi-label">Session Merkle Head</div>
            <div className="kpi-subtext">Kind: {root?.root_kind ?? 'none'}</div>
          </div>
        </div>
        <div className="kpi-card">
          <div className="kpi-icon-wrap relations"><Network size={20} /></div>
          <div className="kpi-content">
            <div className="kpi-value">
              {integrityLinks ? `${integrityLinks.linked_records} / ${integrityLinks.total_memories}` : 'Verified'}
            </div>
            <div className="kpi-label">Lineage Links</div>
            <div className="kpi-subtext">Associated DAG records</div>
          </div>
        </div>
        <div className="kpi-card">
          <div className="kpi-icon-wrap sessions"><Layers size={20} /></div>
          <div className="kpi-content">
            <div className="kpi-value">{root?.exchange_count ?? exchanges.length}</div>
            <div className="kpi-label">Exchange Chain</div>
            <div className="kpi-subtext">Cryptographic turn count</div>
          </div>
        </div>
      </div>

      <div className="card-grid">
        {/* Card 1: Store Health */}
        <section className="overview-card">
          <header className="overview-card-header">
            <div>
              <div className="overview-card-kicker">PRAGMAS</div>
              <div className="overview-card-title">Store Health & Isolation</div>
            </div>
            <Badge>{storeStatus?.integrity_check ?? 'unknown'}</Badge>
          </header>
          <div className="overview-card-body">
            <dl className="details wide">
              <dt>Schema version</dt><dd>v{storeStatus?.schema_version ?? 'unknown'}</dd>
              <dt>Journal mode</dt><dd>{storeStatus?.journal_mode ?? 'unknown'}</dd>
              <dt>Foreign keys</dt><dd>{storeStatus ? String(storeStatus.foreign_keys) : 'unknown'}</dd>
              <dt>FTS5 full-text</dt><dd>{storeStatus ? String(storeStatus.fts5) : 'unknown'}</dd>
              <dt>Identity mode</dt><dd>{storeStatus?.identity_mode ?? 'unknown'}</dd>
              <dt>Database file</dt><dd style={{ wordBreak: 'break-all', fontFamily: 'monospace', fontSize: '11px' }}>{storeStatus?.db_path ?? 'unknown'}</dd>
            </dl>
          </div>
        </section>

        {/* Card 2: Backup Readiness */}
        <section className="overview-card">
          <header className="overview-card-header">
            <div>
              <div className="overview-card-kicker">RECOVERY</div>
              <div className="overview-card-title">Backup Readiness</div>
            </div>
            <Badge>{storeStatus?.backup_ready ? 'ready' : 'pending'}</Badge>
          </header>
          <div className="overview-card-body">
            <dl className="details wide">
              <dt>Method</dt><dd>{storeStatus?.backup_method ?? 'unknown'}</dd>
              <dt>Memory count</dt><dd>{storeStatus?.memory_count ?? 'unknown'}</dd>
              <dt>Readiness note</dt>
              <dd style={{ color: 'var(--text-muted)', fontSize: '12px' }}>
                {storeStatus?.backup_ready ? 'SQLite online backup can run against this profile.' : 'Profile path is not ready for backup.'}
              </dd>
            </dl>
          </div>
        </section>

        {/* Card 3: Session Merkle Root */}
        <section className="overview-card">
          <header className="overview-card-header">
            <div>
              <div className="overview-card-kicker">PROVENANCE HEAD</div>
              <div className="overview-card-title">Session Merkle Root</div>
            </div>
            <Badge>{root?.valid ? 'valid' : 'unverified'}</Badge>
          </header>
          <div className="overview-card-body">
            <dl className="details">
              <dt>Root Node Hash</dt>
              <dd>
                <Hash value={root?.root_node_id} />
              </dd>
              <dt>Exchange count</dt>
              <dd>{root?.exchange_count ?? 0}</dd>
              <dt>Root kind</dt>
              <dd>{root?.root_kind ?? 'none'}</dd>
            </dl>
            <p className="small muted" style={{ marginTop: '14px' }}>
              Integrity head for the session graph; proves structure and cryptographic byte lineage.
            </p>
          </div>
        </section>

        {/* Card 4: Integrity Links */}
        <section className="overview-card">
          <header className="overview-card-header">
            <div>
              <div className="overview-card-kicker">LINKAGE MATRIX</div>
              <div className="overview-card-title">Integrity Links State</div>
            </div>
            <Badge>{integrityLinks ? `${integrityLinks.linked_records}/${integrityLinks.total_memories} linked` : 'unknown'}</Badge>
          </header>
          <div className="overview-card-body">
            <div className="integrity-state-grid" style={{ marginBottom: '12px' }}>
              {linkStates.map(([state, count]) => (
                <div className="state-chip" key={state}>
                  <span>{state}</span>
                  <strong>{count}</strong>
                </div>
              ))}
            </div>
            <p className="small muted" style={{ margin: 0 }}>
              `unlinked` means no Integrity DAG record has been associated locally. `content_unavailable` means a link exists but bytes were not available for verification.
            </p>
          </div>
        </section>
      </div>

      {/* Verified Exchange Chain Card */}
      <section className="overview-card" style={{ marginTop: '24px' }}>
        <header className="overview-card-header">
          <div>
            <div className="overview-card-kicker">SEQUENCE CHAIN</div>
            <div className="overview-card-title">Cryptographic DAG Exchanges</div>
          </div>
          <div className="overview-card-badge">
            {exchanges.length} recorded turns
          </div>
        </header>
        <div className="overview-card-body">
          {exchanges.length === 0 ? (
            <div className="empty-state">
              <h4>No DAG Nodes</h4>
              <p>This session has no exchanges recorded in the cryptographic DAG.</p>
            </div>
          ) : (
            <div className="item-list">
              {exchanges.map((exchange) => (
                <article className="item" key={exchange.id}>
                  <div className="item-head">
                    <strong style={{ color: 'var(--accent)' }}>Exchange #{exchange.sequence_number}</strong>
                    <Hash value={exchange.node_id} />
                  </div>
                  <p className="small muted" style={{ margin: '4px 0 0 0' }}>
                    parent node: {exchange.parent_node_id ? <Hash value={exchange.parent_node_id} /> : 'root / none'}
                  </p>
                </article>
              ))}
            </div>
          )}
        </div>
      </section>
    </section>
  )
}
