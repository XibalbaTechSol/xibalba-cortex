import sqlite3
import uuid
from datetime import datetime, timedelta

db_path = "/home/xibalba/.hermes/xibalba-cortex/default/graph-memory.sqlite3"
conn = sqlite3.connect(db_path)

conn.execute("""
INSERT INTO meta_nodes (id, memory_id, type, relevance_score, status, created_at, updated_at)
SELECT 
    lower(hex(randomblob(16))) as id, 
    m.id as memory_id, 
    'semantic_decay' as type, 
    1.0 as relevance_score, 
    'active' as status, 
    m.created_at as created_at, 
    m.created_at as updated_at
FROM memories m
LEFT JOIN meta_nodes mn ON m.id = mn.memory_id
WHERE mn.id IS NULL
""")
conn.commit()

conn.execute("""
UPDATE meta_nodes
SET relevance_score = MAX(0.0, 1.0 - (
    (julianday(CURRENT_TIMESTAMP) - julianday(created_at)) * 24.0 * 0.05
)),
updated_at = CURRENT_TIMESTAMP
""")
conn.commit()

conn.execute("""
UPDATE meta_nodes
SET status = 'archived'
WHERE relevance_score <= 0.2 AND status = 'active'
""")
conn.commit()

total_nodes = conn.execute("SELECT COUNT(*) FROM meta_nodes").fetchone()[0]
archived_nodes = conn.execute("SELECT COUNT(*) FROM meta_nodes WHERE status = 'archived'").fetchone()[0]
avg_relevance = conn.execute("SELECT AVG(relevance_score) FROM meta_nodes").fetchone()[0]

print(f"Decay pass complete.")
print(f"Total Meta-Nodes: {total_nodes}")
print(f"Archived Nodes: {archived_nodes}")
print(f"Average Relevance Score: {avg_relevance:.2f}")
