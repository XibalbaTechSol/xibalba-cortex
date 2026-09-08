import re

with open('viewer/src/App.tsx', 'r') as f:
    content = f.read()

new_jsx = '''
      {sessionReplay && (
        <section className="timeline-newsfeed" aria-label="Agent Timeline">
          <div className="panel-header">
            <h3>Agent Timeline</h3>
            <span className={`status-pill `}>
              {sessionReplay.replayable ? "Verified" : `Unverified`}
            </span>
          </div>
          {sessionReplay.events.map((event, idx) => {
            const summary = event.meta_json?.summary;
            const isArchived = event.meta_status === 'archived';
            const displayContent = summary || (event.event_type === "tool_call" ? JSON.stringify(event.tool_input) : (event.event_type === "tool_result" ? JSON.stringify(event.tool_output) : event.content));
            
            return (
              <div className="timeline-card" key={idx}>
                <div className="timeline-card-header">
                  <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                    <span className="timeline-card-role">{event.role === 'user' ? 'Human' : (event.role === 'assistant' ? 'Agent' : 'Tool: ' + event.tool_name)}</span>
                    {isArchived && <span className="timeline-card-status archived">Archived (Score: {event.relevance_score?.toFixed(2)})</span>}
                    {!isArchived && event.relevance_score !== undefined && <span className="timeline-card-status active">Active (Score: {event.relevance_score?.toFixed(2)})</span>}
                  </div>
                  <time>{event.timestamp ?? "Unknown time"}</time>
                </div>
                
                <div className="timeline-card-content">
                  {displayContent}
                </div>
                
                <details className="timeline-card-actions">
                  <summary style={{ fontSize: '12px', color: '#888', cursor: 'pointer', marginTop: '8px' }}>Inspect Evidence</summary>
                  <div className="timeline-card-raw">
                    <strong>Merkle ID:</strong> {event.memory_id || 'N/A'}\n
                    <strong>Cryptographic Content:</strong>\n
                    {event.content || JSON.stringify(event.tool_input || event.tool_output, null, 2)}
                  </div>
                </details>
              </div>
            )
          })}
        </section>
      )}
    </section>
  )
}
'''

start_idx = content.find('{sessionReplay && (\n        <section className="replay-panel"')
end_idx = content.find('</section>\n  )\n}', start_idx)
content = content[:start_idx] + new_jsx.strip() + "\n" + content[end_idx + len('</section>\n  )\n}'):]

# Fix CollapsibleExchange unused error by adding ts-ignore above it
content = content.replace('function CollapsibleExchange({', '// @ts-ignore\nfunction CollapsibleExchange({')

# Fix TimelineTab's onSelectMemory unused error by replacing only the one in TimelineTab props
timeline_tab_def = '''function TimelineTab({
  exchanges,
  contextBundle,
  sessionReplay,

  selectedSessionId,
  onRecord,
  onSelectMemory,
'''

new_timeline_tab_def = '''function TimelineTab({
  exchanges,
  contextBundle,
  sessionReplay,

  selectedSessionId,
  onRecord,
  onSelectMemory: _onSelectMemory,
'''
content = content.replace(timeline_tab_def, new_timeline_tab_def)

with open('viewer/src/App.tsx', 'w') as f:
    f.write(content)
