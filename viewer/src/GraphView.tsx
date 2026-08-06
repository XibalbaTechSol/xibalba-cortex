import { useMemo } from 'react'
import ForceGraph2D, { type NodeObject, type LinkObject } from 'react-force-graph-2d'
import type { GraphPayload } from './api'

// Type-color pairs, distinct per node type / relation vs. similarity edge -- picked for
// contrast against both the light and dark backgrounds this page supports, not a brand palette.
const NODE_COLORS: Record<string, string> = {
  memory: '#5b8def',
  entity: '#e0a94a',
}
const EDGE_COLORS: Record<string, string> = {
  relation: '#8b93a7',
  similarity: '#4ad991',
}

interface Props {
  data: GraphPayload
  onNodeClick: (nodeId: string) => void
  selectedNodeId: string | null
}

export function GraphView({ data, onNodeClick, selectedNodeId }: Props) {
  const graphData = useMemo(
    () => ({
      nodes: data.nodes.map((n) => ({ ...n })),
      links: data.edges.map((e) => ({ ...e })),
    }),
    [data],
  )

  return (
    <ForceGraph2D
      graphData={graphData}
      nodeId="id"
      nodeLabel={(node: NodeObject) => (node as unknown as { label: string }).label}
      nodeColor={(node: NodeObject) => {
        const n = node as unknown as { id: string; type: string }
        if (n.id === selectedNodeId) return '#ff5c5c'
        return NODE_COLORS[n.type] ?? '#999'
      }}
      nodeRelSize={5}
      linkColor={(link: LinkObject) => EDGE_COLORS[(link as unknown as { type: string }).type] ?? '#666'}
      linkWidth={(link: LinkObject) => {
        const l = link as unknown as { type: string; cosine_similarity?: number }
        return l.type === 'similarity' ? Math.max(1, (l.cosine_similarity ?? 0.75) * 3) : 1
      }}
      linkDirectionalArrowLength={(link: LinkObject) =>
        (link as unknown as { type: string }).type === 'relation' ? 3 : 0
      }
      onNodeClick={(node: NodeObject) => onNodeClick((node as unknown as { id: string }).id)}
      backgroundColor="rgba(0,0,0,0)"
    />
  )
}
