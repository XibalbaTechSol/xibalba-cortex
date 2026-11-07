"""Active Inference & Geometric Hypothesis Discovery Engine for Knowledge Graphs."""
from __future__ import annotations

import math
from typing import Any

import networkx as nx

from ..store import GraphStore


class ActiveInferenceEngine:
    """Performs geometric pathfinding, mechanistic pathway tracing, and link prediction."""

    def __init__(self, store: GraphStore):
        self.store = store

    def build_networkx_graph(self, *, agent_id: str | None = None) -> nx.DiGraph:
        """Constructs a NetworkX DiGraph representation of the Cortex store."""
        g = nx.DiGraph()

        with self.store._lock:
            # Query active relations and join with entity names
            rows = self.store._connection.execute(
                """
                SELECT r.id AS rel_id, r.predicate, r.confidence, r.evidence_memory_id,
                       se.canonical_name AS subject_name, se.entity_type AS subject_type,
                       oe.canonical_name AS object_name, oe.entity_type AS object_type,
                       r.object_literal
                FROM relations r
                JOIN entities se ON se.id = r.subject_entity_id
                LEFT JOIN entities oe ON oe.id = r.object_entity_id
                WHERE r.status = 'active'
                  AND (? IS NULL OR r.agent_id IN (?, ''))
                """,
                (agent_id, agent_id),
            ).fetchall()

            for row in rows:
                sub = row["subject_name"]
                obj = row["object_name"] or row["object_literal"]
                if not obj:
                    continue

                if not g.has_node(sub):
                    g.add_node(sub, entity_type=row["subject_type"])
                if not g.has_node(obj):
                    g.add_node(obj, entity_type=row["object_type"] or "literal")

                g.add_edge(
                    sub,
                    obj,
                    relation=row["predicate"],
                    confidence=row["confidence"],
                    evidence_memory_id=row["evidence_memory_id"],
                    rel_id=row["rel_id"],
                )

        return g

    def trace_mechanisms(
        self,
        source_entity: str,
        target_entity: str,
        *,
        max_depth: int = 4,
        agent_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Traces explicit causal and mechanistic pathways between source and target entities."""
        g = self.build_networkx_graph(agent_id=agent_id)

        # Resolve aliases if direct names not in graph
        src_canon = self.store.resolve_entity_alias(source_entity)
        tgt_canon = self.store.resolve_entity_alias(target_entity)

        resolved_src = source_entity
        resolved_tgt = target_entity

        if resolved_src not in g and src_canon:
            row = self.store.get_entity(src_canon)
            if row:
                resolved_src = row["canonical_name"]

        if resolved_tgt not in g and tgt_canon:
            row = self.store.get_entity(tgt_canon)
            if row:
                resolved_tgt = row["canonical_name"]

        if resolved_src not in g or resolved_tgt not in g:
            return []

        try:
            paths = list(nx.all_simple_paths(g, source=resolved_src, target=resolved_tgt, cutoff=max_depth))
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return []

        results = []
        for path in paths[:20]: # Limit to top 20 candidate mechanisms
            steps = []
            confidence_product = 1.0
            for i in range(len(path) - 1):
                u, v = path[i], path[i + 1]
                edge_data = g.get_edge_data(u, v) or {}
                conf = edge_data.get("confidence", 1.0)
                confidence_product *= conf
                steps.append({
                    "from": u,
                    "from_type": g.nodes[u].get("entity_type", "entity"),
                    "predicate": edge_data.get("relation", "relates_to"),
                    "to": v,
                    "to_type": g.nodes[v].get("entity_type", "entity"),
                    "confidence": conf,
                    "evidence_memory_id": edge_data.get("evidence_memory_id"),
                })
            results.append({
                "source": resolved_src,
                "target": resolved_tgt,
                "length": len(path) - 1,
                "path_nodes": path,
                "steps": steps,
                "aggregate_confidence": round(confidence_product, 4),
            })

        # Sort by aggregate confidence descending, then by shortest length
        results.sort(key=lambda x: (-x["aggregate_confidence"], x["length"]))
        return results

    def predict_links(
        self,
        source_entity: str,
        target_entity: str,
        *,
        relation: str = "associated_with",
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        """Calculates topological link prediction scores and latent relationship probabilities."""
        g = self.build_networkx_graph(agent_id=agent_id)
        undirected = g.to_undirected()

        resolved_src = source_entity
        resolved_tgt = target_entity

        if resolved_src not in undirected or resolved_tgt not in undirected:
            return {
                "source": source_entity,
                "target": target_entity,
                "probability": 0.0,
                "rationale": "One or both entities not found in knowledge graph",
                "common_neighbors": [],
            }

        # 1. Common neighbors
        common = sorted(list(nx.common_neighbors(undirected, resolved_src, resolved_tgt)))

        # 2. Jaccard coefficient
        jaccard_gen = nx.jaccard_coefficient(undirected, [(resolved_src, resolved_tgt)])
        jaccard_score = 0.0
        for _, _, p in jaccard_gen:
            jaccard_score = p

        # 3. Adamic-Adar Index
        adamic_adar_score = 0.0
        try:
            aa_gen = nx.adamic_adar_index(undirected, [(resolved_src, resolved_tgt)])
            for _, _, p in aa_gen:
                adamic_adar_score = p
        except Exception:
            pass

        # 4. Resource Allocation Index
        ra_score = 0.0
        try:
            ra_gen = nx.resource_allocation_index(undirected, [(resolved_src, resolved_tgt)])
            for _, _, p in ra_gen:
                ra_score = p
        except Exception:
            pass

        # Normalized composite probability score in [0.0, 1.0]
        # Sigmoid of weighted topological signals
        raw_z = 2.5 * jaccard_score + 1.2 * adamic_adar_score + 0.8 * ra_score
        probability = 1.0 / (1.0 + math.exp(-raw_z)) if common else 0.05

        return {
            "source": resolved_src,
            "target": resolved_tgt,
            "predicted_relation": relation,
            "probability": round(probability, 4),
            "common_neighbors": common,
            "metrics": {
                "common_neighbors_count": len(common),
                "jaccard_coefficient": round(jaccard_score, 4),
                "adamic_adar_index": round(adamic_adar_score, 4),
                "resource_allocation_index": round(ra_score, 4),
            },
            "rationale": f"Identified {len(common)} shared mechanistic intermediaries ({', '.join(common[:3])}) linking {resolved_src} and {resolved_tgt}.",
        }

    def suggest_drug_repurposing(
        self,
        disease_entity: str,
        *,
        top_k: int = 5,
        agent_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Surfaces candidate drug repurposing hypotheses for a specified disease."""
        g = self.build_networkx_graph(agent_id=agent_id)
        undirected = g.to_undirected()

        if disease_entity not in undirected:
            return []

        # Find all drug nodes
        drug_nodes = [
            n for n, d in g.nodes(data=True)
            if d.get("entity_type") == "drug" and n != disease_entity
        ]

        candidates = []
        for drug in drug_nodes:
            # Check if there is already a direct 'treats' relation
            has_direct_treats = False
            if g.has_edge(drug, disease_entity):
                edge = g.get_edge_data(drug, disease_entity)
                if edge and edge.get("relation") == "treats":
                    has_direct_treats = True

            if has_direct_treats:
                continue

            # Trace mechanisms and predict link
            mechanisms = self.trace_mechanisms(drug, disease_entity, max_depth=3, agent_id=agent_id)
            link_pred = self.predict_links(drug, disease_entity, relation="treats", agent_id=agent_id)

            if mechanisms or link_pred["common_neighbors"]:
                candidates.append({
                    "drug": drug,
                    "target_disease": disease_entity,
                    "prediction_score": link_pred["probability"],
                    "common_targets_count": len(link_pred["common_neighbors"]),
                    "common_targets": link_pred["common_neighbors"],
                    "primary_mechanism": mechanisms[0]["steps"] if mechanisms else [],
                    "mechanism_depth": mechanisms[0]["length"] if mechanisms else None,
                })

        candidates.sort(key=lambda x: (-x["prediction_score"], -(x["common_targets_count"])))
        return candidates[:top_k]

    def get_ego_subgraph(
        self,
        center_entity: str,
        *,
        radius: int = 2,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        """Extracts ego subgraph for visualization."""
        g = self.build_networkx_graph(agent_id=agent_id)

        if center_entity not in g:
            return {"nodes": [], "edges": []}

        ego = nx.ego_graph(g.to_undirected(), center_entity, radius=radius)
        sub_di = g.subgraph(ego.nodes())

        nodes = [
            {
                "id": n,
                "label": n,
                "entity_type": g.nodes[n].get("entity_type", "entity"),
                "degree": g.degree(n),
            }
            for n in sub_di.nodes()
        ]

        edges = [
            {
                "source": u,
                "target": v,
                "predicate": data.get("relation", "relates_to"),
                "confidence": data.get("confidence", 1.0),
                "evidence_memory_id": data.get("evidence_memory_id"),
            }
            for u, v, data in sub_di.edges(data=True)
        ]

        return {"center": center_entity, "radius": radius, "nodes": nodes, "edges": edges}
