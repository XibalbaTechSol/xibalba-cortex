import re

with open('viewer/src/App.tsx', 'r') as f:
    content = f.read()

# replace showGrid with graphMode
content = content.replace('const [showGrid, setShowGrid] = useState(true)', 'const [graphMode, setGraphMode] = useState<\'3d\' | \'2d\'>(\'3d\')')

# replace grid toggle button
old_button = '<button onClick={() => setShowGrid((v) => !v)} type="button" title="Toggle 3D Grid">🌐</button>'
new_button = '<button onClick={() => setGraphMode(m => m === \'3d\' ? \'2d\' : \'3d\')} type="button" title="Toggle 2D/3D">{graphMode === \'3d\' ? \'2D\' : \'3D\'}</button>'
content = content.replace(old_button, new_button)

# Replace <Graph3DView with a conditional render
old_graph = '''<Graph3DView
          graph={filteredGraph}
          selectedNodeId={selectedNodeHidden ? null : selectedNodeId}
          selectedEdgeKey={selectedEdgeHidden ? null : selectedEdge ? graphEdgeKey(selectedEdge) : null}
          options={options}
          onSelectNode={onSelectNode}
          onSelectEdge={setSelectedEdge}
          onBackgroundClick={() => {
            onSelectNode(null as any)
            setSelectedEdge(null)
          }}
        />'''

new_graph = '''{graphMode === \'3d\' ? (
          <Graph3DView
            graph={filteredGraph}
            selectedNodeId={selectedNodeHidden ? null : selectedNodeId}
            selectedEdgeKey={selectedEdgeHidden ? null : selectedEdge ? graphEdgeKey(selectedEdge) : null}
            options={options}
            onSelectNode={onSelectNode}
            onSelectEdge={setSelectedEdge}
            onBackgroundClick={() => {
              onSelectNode(null as any)
              setSelectedEdge(null)
            }}
          />
        ) : (
          <Graph2DView
            graph={filteredGraph}
            selectedNodeId={selectedNodeHidden ? null : selectedNodeId}
            selectedEdgeKey={selectedEdgeHidden ? null : selectedEdge ? graphEdgeKey(selectedEdge) : null}
            options={options}
            onSelectNode={onSelectNode}
            onSelectEdge={setSelectedEdge}
            onBackgroundClick={() => {
              onSelectNode(null as any)
              setSelectedEdge(null)
            }}
          />
        )}'''
content = content.replace(old_graph, new_graph)

# Also fix options passed to Graph3DView
content = content.replace('showGrid, // we might need to remove this from options or just leave it', 'showGrid: true,')
# options is defined as:
# const options = useMemo<GraphViewOptions>(() => ({
#       background,
#       zoom,
#       panX,
#       panY,
#       showGrid,
#       fitMode,
#       fitNonce,
#     }), [background, zoom, panX, panY, showGrid, fitMode, fitNonce])
content = content.replace('showGrid,', 'showGrid: true,')
content = content.replace('[background, zoom, panX, panY, showGrid, fitMode, fitNonce]', '[background, zoom, panX, panY, fitMode, fitNonce]')

with open('viewer/src/App.tsx', 'w') as f:
    f.write(content)
