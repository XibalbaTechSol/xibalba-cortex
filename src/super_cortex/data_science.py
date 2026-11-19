"""
Data Science & Quantitative Research Interoperability Engine for Super-Cortex.
Provides zero-dependency GraphML, NetworkX node-link, CSV tabular dataframes,
and PyTorch Geometric (PyG) tensor representations of the 3D knowledge manifold.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import xml.etree.ElementTree as ET
from typing import Any

from super_cortex.store import SuperCortexStore

logger = logging.getLogger("super_cortex.data_science")


def extract_graph_components(
    store: SuperCortexStore,
    scope: str = "all",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Extract clean, tabular node and edge datasets from the Super-Cortex store.
    Returns (nodes, edges).
    """
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    node_ids: set[str] = set()

    with store._get_conn() as conn:
        # 1. Scopes & Hubs
        scopes = [dict(r) for r in conn.execute("SELECT scope_id, name, scope_type FROM scopes").fetchall()]
        agents = [dict(r) for r in conn.execute("SELECT agent_id, name, default_scope_id, status FROM agents").fetchall()]

        # Shared Hub
        nodes.append({
            "id": "hub_shared",
            "title": "Shared Memory Fabric",
            "type": "hub",
            "epistemic_class": "rule",
            "category": "shared",
            "scope": "shared",
            "degree": 0,
            "created_at": "2026-01-01T00:00:00Z",
        })
        node_ids.add("hub_shared")

        # Agent Hubs
        for a in agents:
            hid = f"hub_agent_{a['agent_id']}"
            nodes.append({
                "id": hid,
                "title": f"Agent Hub: {a['name']}",
                "type": "agent_hub",
                "epistemic_class": "decision",
                "category": "agent",
                "scope": f"agent:{a['agent_id']}",
                "degree": 0,
                "created_at": "2026-01-01T00:00:00Z",
            })
            node_ids.add(hid)
            edges.append({
                "source": "hub_shared",
                "target": hid,
                "type": "federation",
                "predicate": "federates",
                "confidence": 1.0,
            })

        # 2. Memories
        m_query = """
            SELECT id, text, epistemic_class, lifecycle_status, metadata_json, created_at
            FROM memories
            WHERE lifecycle_status != 'forgotten'
        """
        mem_rows = [dict(r) for r in conn.execute(m_query).fetchall()]
        for m in mem_rows:
            mid = m["id"]
            meta = {}
            if m.get("metadata_json"):
                try:
                    meta = json.loads(m["metadata_json"])
                except Exception:
                    meta = {}
            m_scope = meta.get("scope") or "shared"
            m_agent = meta.get("agent_id")

            if scope != "all" and m_scope != scope:
                continue

            nodes.append({
                "id": mid,
                "title": m["text"][:60],
                "type": "memory",
                "epistemic_class": m["epistemic_class"] or "fact",
                "category": meta.get("category") or "general",
                "scope": m_scope,
                "degree": 0,
                "created_at": m["created_at"],
            })
            node_ids.add(mid)

            target_hub = f"hub_agent_{m_agent}" if m_agent and f"hub_agent_{m_agent}" in node_ids else "hub_shared"
            edges.append({
                "source": target_hub,
                "target": mid,
                "type": "scope-to-memory",
                "predicate": "belongs_to",
                "confidence": 1.0,
            })

        # 3. Reasoning Thoughts & Tool Actions from Exchanges
        ex_query = """
            SELECT exchange_id, session_id, prompt_text, response_text, thinking_text, tool_calls_json,
                   scope_id, agent_id, created_at
            FROM exchanges
            ORDER BY rowid DESC LIMIT 1500
        """
        ex_rows = [dict(r) for r in conn.execute(ex_query).fetchall()]
        last_thought_by_session: dict[str, str] = {}

        for ex in ex_rows:
            ex_id = ex["exchange_id"]
            th_text = (ex.get("thinking_text") or "").strip() or (ex.get("prompt_text") or "").strip()
            th_aid = ex.get("agent_id") or "agent"
            th_scope = ex.get("scope_id") or f"agent:{th_aid}"
            sess_id = ex.get("session_id")

            if scope != "all" and th_scope != scope:
                continue

            th_id = f"thought_{ex_id}"
            if th_text:
                nodes.append({
                    "id": th_id,
                    "title": f"Thought: {th_text[:50]}",
                    "type": "thought",
                    "epistemic_class": "inference",
                    "category": "thought",
                    "scope": th_scope,
                    "degree": 0,
                    "created_at": ex["created_at"],
                })
                node_ids.add(th_id)

                target_hub = f"hub_agent_{th_aid}" if f"hub_agent_{th_aid}" in node_ids else "hub_shared"
                edges.append({
                    "source": target_hub,
                    "target": th_id,
                    "type": "deliberation",
                    "predicate": "deliberates",
                    "confidence": 0.99,
                })

                if sess_id and sess_id in last_thought_by_session:
                    edges.append({
                        "source": last_thought_by_session[sess_id],
                        "target": th_id,
                        "type": "causal",
                        "predicate": "then_deliberates",
                        "confidence": 0.95,
                    })
                if sess_id:
                    last_thought_by_session[sess_id] = th_id

            # Action Nodes
            raw_tools = ex.get("tool_calls_json")
            if raw_tools and th_text:
                try:
                    calls = json.loads(raw_tools)
                    if isinstance(calls, dict):
                        calls = [calls]
                    if isinstance(calls, list):
                        for a_idx, call in enumerate(calls[:3]):
                            tname = call.get("name") or call.get("tool_name") or "tool"
                            act_id = f"act_{ex_id}_{a_idx}"
                            nodes.append({
                                "id": act_id,
                                "title": f"Action: {tname}",
                                "type": "action",
                                "epistemic_class": "action",
                                "category": "action",
                                "scope": th_scope,
                                "degree": 0,
                                "created_at": ex["created_at"],
                            })
                            node_ids.add(act_id)
                            edges.append({
                                "source": th_id,
                                "target": act_id,
                                "type": "executes",
                                "predicate": f"executes_{tname}",
                                "confidence": 1.0,
                            })
                except Exception:
                    pass

        # 4. Relational Triples & Knowledge Entities
        rel_query = "SELECT relation_id, subject, predicate, object, confidence, created_at FROM relations"
        rel_rows = [dict(r) for r in conn.execute(rel_query).fetchall()]
        for r in rel_rows:
            sub = r["subject"]
            obj = r["object"]
            pred = r["predicate"]
            conf = float(r.get("confidence") or 0.95)

            for ent in (sub, obj):
                if ent not in node_ids:
                    nodes.append({
                        "id": ent,
                        "title": ent,
                        "type": "entity",
                        "epistemic_class": "fact",
                        "category": "entity",
                        "scope": "shared",
                        "degree": 0,
                        "created_at": r["created_at"],
                    })
                    node_ids.add(ent)

            edges.append({
                "source": sub,
                "target": obj,
                "type": "relation",
                "predicate": pred,
                "confidence": conf,
            })

    # Calculate exact node in/out/total degrees
    deg_map: dict[str, int] = {}
    for e in edges:
        s = e["source"]
        t = e["target"]
        deg_map[s] = deg_map.get(s, 0) + 1
        deg_map[t] = deg_map.get(t, 0) + 1

    for n in nodes:
        n["degree"] = deg_map.get(n["id"], 0)

    return nodes, edges


def export_networkx_json(store: SuperCortexStore, scope: str = "all") -> dict[str, Any]:
    """
    Export the graph in NetworkX node-link format (RFC-standardized).
    Can be ingested directly via networkx.node_link_graph(data, edges='links').
    """
    nodes, edges = extract_graph_components(store, scope=scope)
    return {
        "directed": True,
        "multigraph": True,
        "graph": {
            "name": "Super-Cortex Knowledge Manifold",
            "scope": scope,
            "engine": "super-cortex",
        },
        "nodes": nodes,
        "links": [
            {
                "source": e["source"],
                "target": e["target"],
                "type": e["type"],
                "predicate": e["predicate"],
                "confidence": e["confidence"],
            }
            for e in edges
        ],
    }


def export_graphml_xml(store: SuperCortexStore, scope: str = "all") -> str:
    """
    Export the complete graph manifold in GraphML XML format for Gephi,
    Cytoscape, NetworkX (nx.read_graphml), and igraph.
    """
    nodes, edges = extract_graph_components(store, scope=scope)

    root = ET.Element(
        "graphml",
        attrib={
            "xmlns": "http://graphml.graphdrawing.org/xmlns",
            "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
            "xsi:schemaLocation": "http://graphml.graphdrawing.org/xmlns http://graphml.graphdrawing.org/xmlns/1.0/graphml.xsd",
        },
    )

    # Key declarations
    key_defs = [
        ("title", "node", "string"),
        ("type", "node", "string"),
        ("epistemic_class", "node", "string"),
        ("category", "node", "string"),
        ("scope", "node", "string"),
        ("degree", "node", "int"),
        ("created_at", "node", "string"),
        ("predicate", "edge", "string"),
        ("type", "edge", "string"),
        ("confidence", "edge", "double"),
    ]
    for kid, kfor, ktype in key_defs:
        ET.SubElement(root, "key", id=f"{kfor}_{kid}", attrib={"for": kfor, "attr.name": kid, "attr.type": ktype})

    graph_el = ET.SubElement(root, "graph", id="SuperCortex", edgedefault="directed")

    for n in nodes:
        node_el = ET.SubElement(graph_el, "node", id=str(n["id"]))
        for k in ["title", "type", "epistemic_class", "category", "scope", "degree", "created_at"]:
            if k in n and n[k] is not None:
                d = ET.SubElement(node_el, "data", key=f"node_{k}")
                d.text = str(n[k])

    for idx, e in enumerate(edges):
        edge_el = ET.SubElement(graph_el, "edge", id=f"e_{idx}", source=str(e["source"]), target=str(e["target"]))
        for k in ["predicate", "type", "confidence"]:
            if k in e and e[k] is not None:
                d = ET.SubElement(edge_el, "data", key=f"edge_{k}")
                d.text = str(e[k])

    xml_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return xml_bytes.decode("utf-8")


def export_tabular_csv(store: SuperCortexStore, table: str = "nodes", scope: str = "all") -> str:
    """
    Export either the 'nodes' table or the 'edges' table as standard CSV
    ready for Pandas (pd.read_csv), Polars (pl.read_csv), R, or Julia.
    """
    nodes, edges = extract_graph_components(store, scope=scope)
    output = io.StringIO()

    if table == "nodes":
        fieldnames = ["id", "title", "type", "epistemic_class", "category", "scope", "degree", "created_at"]
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for n in nodes:
            writer.writerow(n)
    else:
        fieldnames = ["source", "target", "predicate", "type", "confidence"]
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for e in edges:
            writer.writerow(e)

    return output.getvalue()


def export_pyg_specification(store: SuperCortexStore, scope: str = "all") -> dict[str, Any]:
    """
    Export the graph structure in tensor specification for PyTorch Geometric (PyG).
    Produces edge_index [[src, ...], [dst, ...]], node index mapping,
    epistemic category labels, and edge types.
    """
    nodes, edges = extract_graph_components(store, scope=scope)

    node_to_idx = {n["id"]: idx for idx, n in enumerate(nodes)}

    src_indices: list[int] = []
    dst_indices: list[int] = []
    edge_types: list[str] = []
    edge_confidences: list[float] = []

    for e in edges:
        s = e["source"]
        t = e["target"]
        if s in node_to_idx and t in node_to_idx:
            src_indices.append(node_to_idx[s])
            dst_indices.append(node_to_idx[t])
            edge_types.append(e.get("type", "relation"))
            edge_confidences.append(float(e.get("confidence", 1.0)))

    epistemic_classes = sorted(list({n.get("epistemic_class", "fact") for n in nodes}))
    epistemic_to_id = {cls_name: i for i, cls_name in enumerate(epistemic_classes)}
    node_y = [epistemic_to_id.get(n.get("epistemic_class", "fact"), 0) for n in nodes]

    return {
        "num_nodes": len(nodes),
        "num_edges": len(src_indices),
        "edge_index": [src_indices, dst_indices],
        "edge_attr": edge_confidences,
        "edge_types": edge_types,
        "y": node_y,
        "node_ids": [n["id"] for n in nodes],
        "node_types": [n["type"] for n in nodes],
        "class_labels": epistemic_classes,
        "documentation": "Ingest in PyTorch Geometric via: torch_geometric.data.Data(edge_index=torch.tensor(data['edge_index'], dtype=torch.long), y=torch.tensor(data['y']))",
    }
