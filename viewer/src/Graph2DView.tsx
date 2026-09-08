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
    memory: '#1f77b4',
    entity: '#2ca02c',
    session: '#9467bd',
    exchange: '#ff7f0e',
    merkle: '#d62728'
  }), [])

  return (
    <ForceGraph2D
      ref={fgRef as any}
      graphData={graph as any}
      backgroundColor={options.background === 'paper' ? '#f8f9fa' : options.background === 'midnight' ? '#0f172a' : options.background === 'matrix' ? '#000000' : '#ffffff'}
      nodeLabel="label"
      nodeColor={(node: any) => node.id === selectedNodeId ? '#ff0000' : colors[node.type as keyof typeof colors] || '#999'}
      nodeRelSize={6}
      linkColor={(edge: any) => `${edge.source.id || edge.source}|${edge.target.id || edge.target}|${edge.type}` === selectedEdgeKey ? '#ff0000' : options.background === 'paper' ? '#999' : '#555'}
      linkWidth={(edge: any) => `${edge.source.id || edge.source}|${edge.target.id || edge.target}|${edge.type}` === selectedEdgeKey ? 3 : 1}
      linkDirectionalArrowLength={3.5}
      linkDirectionalArrowRelPos={1}
      onNodeClick={(node: any) => onSelectNode(node)}
      onLinkClick={(link: any) => onSelectEdge(link)}
      onBackgroundClick={onBackgroundClick}
    />
  )
}
