import re

with open('viewer/src/App.tsx', 'r') as f:
    content = f.read()

old_render = '''<Graph3DView\n          graph={filteredGraph}\n          selectedNodeId={selectedNodeHidden ? null : selectedNodeId}\n          selectedEdgeKey={selectedEdgeHidden ? null : selectedEdge ? graphEdgeKey(selectedEdge) : null}\n          options={options}\n          onSelectNode={onSelectNode}\n          onSelectEdge={setSelectedEdge}\n        />'''

new_render = '''{graphMode === \'3d\' ? (\n          <Graph3DView\n            graph={filteredGraph}\n            selectedNodeId={selectedNodeHidden ? null : selectedNodeId}\n            selectedEdgeKey={selectedEdgeHidden ? null : selectedEdge ? graphEdgeKey(selectedEdge) : null}\n            options={options}\n            onSelectNode={onSelectNode}\n            onSelectEdge={setSelectedEdge}\n          />\n        ) : (\n          <Graph2DView\n            graph={filteredGraph}\n            selectedNodeId={selectedNodeHidden ? null : selectedNodeId}\n            selectedEdgeKey={selectedEdgeHidden ? null : selectedEdge ? graphEdgeKey(selectedEdge) : null}\n            options={options}\n            onSelectNode={onSelectNode}\n            onSelectEdge={setSelectedEdge}\n            onBackgroundClick={() => {}}\n          />\n        )}'''

content = content.replace(old_render, new_render)

# Fix showGrid in options
content = content.replace('fitNonce, showGrid }', 'fitNonce, showGrid: true }')

with open('viewer/src/App.tsx', 'w') as f:
    f.write(content)
