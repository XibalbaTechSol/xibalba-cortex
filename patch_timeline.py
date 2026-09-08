import re

with open('viewer/src/index.css', 'a') as f:
    f.write('''
.timeline-newsfeed {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 16px 0;
}
.timeline-card {
  background: #111111;
  border: 1px solid #333;
  border-radius: 8px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  transition: border-color 0.2s ease;
}
.timeline-card:hover {
  border-color: #555;
}
.timeline-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
  color: #888;
}
.timeline-card-role {
  font-weight: 600;
  color: #fff;
  text-transform: capitalize;
}
.timeline-card-status {
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 12px;
  background: #222;
  border: 1px solid #444;
}
.timeline-card-status.archived {
  color: #e6b300;
  border-color: #665000;
  background: #1a1400;
}
.timeline-card-content {
  font-size: 15px;
  line-height: 1.5;
  color: #ccc;
}
.timeline-card-raw {
  margin-top: 8px;
  padding: 12px;
  background: #000;
  border-radius: 6px;
  font-family: monospace;
  font-size: 12px;
  color: #888;
  white-space: pre-wrap;
  overflow-x: auto;
}
.timeline-card-actions {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}
.timeline-card-actions button {
  background: transparent;
  border: 1px solid #333;
  color: #888;
  font-size: 12px;
  padding: 4px 8px;
  border-radius: 4px;
  cursor: pointer;
}
.timeline-card-actions button:hover {
  background: #222;
  color: #ccc;
}
''')
