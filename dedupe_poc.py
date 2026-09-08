import sqlite3

db_path = "/home/xibalba/.hermes/xibalba-cortex/default/graph-memory.sqlite3"
conn = sqlite3.connect(db_path)

entities = [
    ("ent_1", "Cortex Project", "cortex project", "project"),
    ("ent_2", "Project Cortex", "project cortex", "project"),
    ("ent_3", "John Doe", "john doe", "person"),
    ("ent_4", "Jonathan Doe", "jonathan doe", "person"),
]

conn.executemany("""
INSERT OR IGNORE INTO entities (id, canonical_name, normalized_name, entity_type)
VALUES (?, ?, ?, ?)
""", entities)
conn.commit()

rows = conn.execute("SELECT id, normalized_name, entity_type FROM entities").fetchall()
proposed_edges = []

for i in range(len(rows)):
    for j in range(i + 1, len(rows)):
        id1, name1, type1 = rows[i]
        id2, name2, type2 = rows[j]
        
        if type1 == type2:
            words1 = set(name1.split())
            words2 = set(name2.split())
            overlap = words1.intersection(words2)
            if len(overlap) >= 1:
                proposed_edges.append((id1, id2, 'SAME_AS', 0.85))

if proposed_edges:
    conn.executemany("""
    INSERT OR IGNORE INTO meta_edges (source_id, target_id, relation_type, weight)
    VALUES (?, ?, ?, ?)
    """, proposed_edges)
    conn.commit()

edges = conn.execute("SELECT * FROM meta_edges WHERE relation_type = 'SAME_AS'").fetchall()
print(f"Proposed and inserted {len(edges)} SAME_AS meta-edges:")
for edge in edges:
    print(edge)
