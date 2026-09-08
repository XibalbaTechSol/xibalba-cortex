import re

with open('viewer/src/App.tsx', 'r') as f:
    content = f.read()

# 1. Add Semantic Filtering to TimelineTab
# First, inject useState into TimelineTab
timeline_tab_def = '''function TimelineTab({
  exchanges,
  contextBundle,
  sessionReplay,

  selectedSessionId,
  onRecord,
  onSelectMemory: _onSelectMemory,
  sessions,
  setSelectedSessionId,
}: {
  exchanges: Exchange[]
  contextBundle: Memory[]
  sessionReplay: SessionReplay | null
  selectedSessionId: string
  onRecord: (event: FormEvent<HTMLFormElement>) => void
  onSelectMemory: (id: string) => void
  sessions: Session[]
  setSelectedSessionId: (id: string) => void
}) {'''

timeline_tab_new = timeline_tab_def + '''
  const [minScore, setMinScore] = useState(0.0);
'''
content = content.replace(timeline_tab_def, timeline_tab_new)

# Now add the slider and filtering to the render
old_timeline_render = '''      {sessionReplay && (
        <section className="timeline-newsfeed" aria-label="Agent Timeline">
          <div className="panel-header">
            <h3>Agent Timeline</h3>
            <span className={`status-pill `}>
              {sessionReplay.replayable ? "Verified" : `Unverified`}
            </span>
          </div>
          {sessionReplay.events.map((event, idx) => {'''

new_timeline_render = '''      {sessionReplay && (
        <section className="timeline-newsfeed" aria-label="Agent Timeline">
          <div className="panel-header">
            <h3>Agent Timeline</h3>
            <div style={{display: 'flex', alignItems: 'center', gap: '12px'}}>
              <label style={{fontSize: '12px', color: '#888'}}>Semantic Filter:</label>
              <input 
                type="range" min="0" max="1" step="0.05" 
                value={minScore} 
                onChange={e => setMinScore(Number(e.target.value))} 
                title="Hide decayed memories"
              />
              <span className={`status-pill `}>
                {sessionReplay.replayable ? "Verified" : `Unverified`}
              </span>
            </div>
          </div>
          {sessionReplay.events.filter(e => e.relevance_score === undefined || e.relevance_score >= minScore).map((event, idx) => {'''

content = content.replace(old_timeline_render, new_timeline_render)

# 2. Remove the Evidence details from Timeline cards
old_details = '''<details className="timeline-card-actions">
                  <summary style={{ fontSize: '12px', color: '#888', cursor: 'pointer', marginTop: '8px' }}>Inspect Evidence</summary>
                  <div className="timeline-card-raw">
                    <strong>Merkle ID:</strong> {event.memory_id || 'N/A'}\n
                    <strong>Cryptographic Content:</strong>\n
                    {event.content || JSON.stringify(event.tool_input || event.tool_output, null, 2)}
                  </div>
                </details>'''
content = content.replace(old_details, '')

with open('viewer/src/App.tsx', 'w') as f:
    f.write(content)
