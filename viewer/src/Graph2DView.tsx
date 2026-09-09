import { useEffect, useRef, useMemo } from 'react'
import ForceGraph2D from 'react-force-graph-2d'
import type { ForceGraphMethods } from 'react-force-graph-2d'
import type { DemoGraph, DemoNode, DemoEdge, GraphViewOptions } from './Graph3DView'

export function Graph2DView({
  graph,
  selectedNodeId,
  selectedEdgeKey,
  options,
  onSelectNode,
  onSelectEdge,
  onBackgroundClick,
}: {
  graph: DemoGraph
  selectedNodeId: string | null
  selectedEdgeKey: string | null
  options: GraphViewOptions
  onSelectNode: (node: DemoNode) => void
  onSelectEdge: (edge: DemoEdge) => void
  onBackgroundClick: () => void
}) {
  const fgRef = useRef<ForceGraphMethods>(null)

  useEffect(() => {
    if (fgRef.current && options.fitNonce > 0) {
      if (options.fitMode === 'selected' && selectedNodeId) {
        const node = graph.nodes.find(n => n.id === selectedNodeId)
        if (node) fgRef.current.centerAt((node as any).x, (node as any).y, 1000)
      } else {
        fgRef.current.zoomToFit(1000, 50)
      }
    }
  }, [options.fitNonce, options.fitMode, selectedNodeId, graph.nodes])

  const colors = useMemo(() => ({
    memory: '#3b82f6',
    entity: '#facc15',
    session: '#52e096',
    exchange: '#8b5cf6',
    merkle: '#f87171'
  }), [])

  return (
    <ForceGraph2D
      ref={fgRef as any}
      graphData={{ nodes: graph.nodes, links: graph.edges } as any}
      backgroundColor={options.background === 'paper' ? '#f5f7f9' : options.background === 'midnight' ? '#090d12' : options.background === 'matrix' ? '#0a1012' : '#000000'}
      nodeLabel="label"
      nodeColor={(node: any) => node.id === selectedNodeId ? '#ffffff' : colors[node.type as keyof typeof colors] || '#475569'}
      nodeRelSize={6}
      linkColor={(edge: any) => `${edge.source.id || edge.source}|${edge.target.id || edge.target}|${edge.type}` === selectedEdgeKey ? '#ffffff' : options.background === 'paper' ? '#cbd5e1' : '#1e293b'}
      linkWidth={(edge: any) => `${edge.source.id || edge.source}|${edge.target.id || edge.target}|${edge.type}` === selectedEdgeKey ? 3 : 1}
      linkDirectionalArrowLength={3.5}
      linkDirectionalArrowRelPos={1}
      onNodeClick={(node: any) => onSelectNode(node)}
      onLinkClick={(link: any) => onSelectEdge(link)}
      onBackgroundClick={onBackgroundClick}
    />
  )
}
