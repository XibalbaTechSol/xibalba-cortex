"""Biomedical Literature & Scientific Discovery Knowledge Graph Connector."""
from __future__ import annotations

import re
import uuid
from typing import Any, Mapping

from ..store import GraphStore
from .base import ConnectorResult

# Canonical biomedical entity types
TYPE_DRUG = "drug"
TYPE_PROTEIN = "protein"
TYPE_GENE = "gene"
TYPE_DISEASE = "disease"
TYPE_PATHWAY = "pathway"
TYPE_BIOMARKER = "biomarker"
TYPE_CELL_TYPE = "cell_type"

# Standard biomedical vocabulary and normalization mapping
BIOMEDICAL_VOCABULARY: dict[str, tuple[str, str]] = {
    # Drug / Small molecule / Biologic
    "imatinib": ("Imatinib", TYPE_DRUG),
    "gleevec": ("Imatinib", TYPE_DRUG),
    "pembrolizumab": ("Pembrolizumab", TYPE_DRUG),
    "keytruda": ("Pembrolizumab", TYPE_DRUG),
    "nivolumab": ("Nivolumab", TYPE_DRUG),
    "opdivo": ("Nivolumab", TYPE_DRUG),
    "trastuzumab": ("Trastuzumab", TYPE_DRUG),
    "herceptin": ("Trastuzumab", TYPE_DRUG),
    "cisplatin": ("Cisplatin", TYPE_DRUG),
    "paclitaxel": ("Paclitaxel", TYPE_DRUG),
    "doxorubicin": ("Doxorubicin", TYPE_DRUG),
    "gefitinib": ("Gefitinib", TYPE_DRUG),
    "erlotinib": ("Erlotinib", TYPE_DRUG),
    "osimertinib": ("Osimertinib", TYPE_DRUG),
    "sorafenib": ("Sorafenib", TYPE_DRUG),
    "sunitinib": ("Sunitinib", TYPE_DRUG),
    "metformin": ("Metformin", TYPE_DRUG),
    "aspirin": ("Aspirin", TYPE_DRUG),
    "rituximab": ("Rituximab", TYPE_DRUG),

    # Genes / Proteins / Targets
    "bcr-abl": ("BCR-ABL1", TYPE_PROTEIN),
    "bcr-abl1": ("BCR-ABL1", TYPE_PROTEIN),
    "bcr/abl": ("BCR-ABL1", TYPE_PROTEIN),
    "c-kit": ("c-KIT", TYPE_PROTEIN),
    "ckit": ("c-KIT", TYPE_PROTEIN),
    "kit": ("c-KIT", TYPE_PROTEIN),
    "cd117": ("c-KIT", TYPE_PROTEIN),
    "pd-1": ("PD-1", TYPE_PROTEIN),
    "pd1": ("PD-1", TYPE_PROTEIN),
    "pdcd1": ("PD-1", TYPE_PROTEIN),
    "cd279": ("PD-1", TYPE_PROTEIN),
    "pd-l1": ("PD-L1", TYPE_PROTEIN),
    "pdl1": ("PD-L1", TYPE_PROTEIN),
    "cd274": ("PD-L1", TYPE_PROTEIN),
    "egfr": ("EGFR", TYPE_PROTEIN),
    "erbb1": ("EGFR", TYPE_PROTEIN),
    "her2": ("HER2", TYPE_PROTEIN),
    "erbb2": ("HER2", TYPE_PROTEIN),
    "kras": ("KRAS", TYPE_GENE),
    "tp53": ("TP53", TYPE_GENE),
    "p53": ("TP53", TYPE_PROTEIN),
    "brca1": ("BRCA1", TYPE_GENE),
    "brca2": ("BRCA2", TYPE_GENE),
    "vegf": ("VEGF", TYPE_PROTEIN),
    "vegfr2": ("VEGFR2", TYPE_PROTEIN),
    "braf": ("BRAF", TYPE_PROTEIN),
    "mek": ("MEK", TYPE_PROTEIN),
    "alk": ("ALK", TYPE_PROTEIN),
    "tnf-alpha": ("TNF-alpha", TYPE_PROTEIN),
    "il-6": ("IL-6", TYPE_PROTEIN),

    # Diseases / Conditions
    "chronic myeloid leukemia": ("Chronic Myeloid Leukemia", TYPE_DISEASE),
    "cml": ("Chronic Myeloid Leukemia", TYPE_DISEASE),
    "gastrointestinal stromal tumor": ("Gastrointestinal Stromal Tumor", TYPE_DISEASE),
    "gist": ("Gastrointestinal Stromal Tumor", TYPE_DISEASE),
    "non-small cell lung cancer": ("Non-Small Cell Lung Cancer", TYPE_DISEASE),
    "non-small cell lung carcinoma": ("Non-Small Cell Lung Cancer", TYPE_DISEASE),
    "nsclc": ("Non-Small Cell Lung Cancer", TYPE_DISEASE),
    "small cell lung cancer": ("Small Cell Lung Cancer", TYPE_DISEASE),
    "sclc": ("Small Cell Lung Cancer", TYPE_DISEASE),
    "melanoma": ("Melanoma", TYPE_DISEASE),
    "colorectal cancer": ("Colorectal Cancer", TYPE_DISEASE),
    "crc": ("Colorectal Cancer", TYPE_DISEASE),
    "breast cancer": ("Breast Cancer", TYPE_DISEASE),
    "pancreatic adenocarcinoma": ("Pancreatic Adenocarcinoma", TYPE_DISEASE),
    "glioblastoma": ("Glioblastoma", TYPE_DISEASE),
    "acute myeloid leukemia": ("Acute Myeloid Leukemia", TYPE_DISEASE),
    "aml": ("Acute Myeloid Leukemia", TYPE_DISEASE),
    "alzheimer's disease": ("Alzheimer's Disease", TYPE_DISEASE),
    "type 2 diabetes": ("Type 2 Diabetes", TYPE_DISEASE),

    # Biological Pathways
    "t-cell activation": ("T-Cell Activation", TYPE_PATHWAY),
    "tumor cell apoptosis": ("Tumor Cell Apoptosis", TYPE_PATHWAY),
    "apoptosis": ("Tumor Cell Apoptosis", TYPE_PATHWAY),
    "mapk signaling": ("MAPK Signaling Pathway", TYPE_PATHWAY),
    "mapk pathway": ("MAPK Signaling Pathway", TYPE_PATHWAY),
    "pi3k-akt pathway": ("PI3K-Akt Signaling Pathway", TYPE_PATHWAY),
    "angiogenesis": ("Angiogenesis", TYPE_PATHWAY),
    "dna repair": ("DNA Repair Pathway", TYPE_PATHWAY),

    # Phenotypes & Biomarkers
    "pd-l1 expression": ("PD-L1 Expression", TYPE_BIOMARKER),
    "bcr-abl transcript": ("BCR-ABL Transcript Level", TYPE_BIOMARKER),
    "tumor mutational burden": ("Tumor Mutational Burden", TYPE_BIOMARKER),
    "tmb": ("Tumor Mutational Burden", TYPE_BIOMARKER),
}

# Relation regex patterns
RELATION_PATTERNS = [
    (re.compile(r"\b(inhibits?|inhibition of|blocks?|antagonizes?|suppresses?)\b", re.I), "inhibits"),
    (re.compile(r"\b(activates?|activation of|stimulates?|induces?|promotes?)\b", re.I), "activates"),
    (re.compile(r"\b(associated with|correlated with|linked to|implicated in)\b", re.I), "associated_with"),
    (re.compile(r"\b(upregulates?|upregulation of|overexpressed in)\b", re.I), "upregulates"),
    (re.compile(r"\b(downregulates?|downregulation of)\b", re.I), "downregulates"),
    (re.compile(r"\b(biomarker for|marker for|diagnostic for|predictor of)\b", re.I), "biomarker_for"),
    (re.compile(r"\b(treats?|treatment of|indicated for|therapeutic efficacy in)\b", re.I), "treats"),
    (re.compile(r"\b(causes?|causative in|pathogenic in|drives?)\b", re.I), "causes"),
    (re.compile(r"\b(binds to|binding to|ligand for|complex with)\b", re.I), "binds_to"),
]


class BiomedicalConnector:
    """Connects biomedical research literature and ontologies to the Cortex Knowledge Graph."""

    def __init__(self, store: GraphStore):
        self.store = store

    def normalize_entity(self, term: str) -> tuple[str, str]:
        """Normalize biomedical term to (canonical_name, entity_type)."""
        clean = term.strip().lower()
        if clean in BIOMEDICAL_VOCABULARY:
            return BIOMEDICAL_VOCABULARY[clean]
        # Fallback heuristic
        return (term.strip(), TYPE_BIOMARKER if "mutation" in clean or "expression" in clean else "entity")

    def extract_triples_from_text(self, text: str) -> list[dict[str, Any]]:
        """Extract biomedical triples from raw literature prose."""
        triples = []
        sentences = re.split(r"(?<=[.!?])\s+", text)

        for sentence in sentences:
            sentence_clean = sentence.strip()
            if not sentence_clean:
                continue

            # Find matching entities in this sentence
            found_entities: list[tuple[int, int, str, str, str]] = [] # (start, end, raw, canonical, type)
            sentence_lower = sentence_clean.lower()

            for term, (canon, etype) in BIOMEDICAL_VOCABULARY.items():
                pattern = r"\b" + re.escape(term) + r"\b"
                for match in re.finditer(pattern, sentence_lower):
                    found_entities.append((match.start(), match.end(), match.group(0), canon, etype))

            # Deduplicate entities overlapping in position
            found_entities.sort(key=lambda x: (x[0], -(x[1] - x[0])))
            deduped: list[tuple[int, int, str, str, str]] = []
            for item in found_entities:
                if not any(item[0] >= existing[0] and item[1] <= existing[1] for existing in deduped):
                    deduped.append(item)

            if len(deduped) < 2:
                continue

            # Look for relational cues between entities in the same sentence
            for i in range(len(deduped) - 1):
                e1 = deduped[i]
                e2 = deduped[i + 1]

                # Don't link identical canonical entities to themselves
                if e1[3] == e2[3]:
                    continue

                segment = sentence_clean[e1[1]:e2[0]]
                predicate = None
                for rel_regex, rel_name in RELATION_PATTERNS:
                    if rel_regex.search(segment):
                        predicate = rel_name
                        break

                if not predicate:
                    # Default heuristic relation if both appear in proximity
                    if e1[4] == TYPE_DRUG and e2[4] in (TYPE_PROTEIN, TYPE_GENE):
                        predicate = "targets"
                    elif e1[4] in (TYPE_PROTEIN, TYPE_GENE) and e2[4] == TYPE_DISEASE:
                        predicate = "associated_with"
                    elif e1[4] == TYPE_DRUG and e2[4] == TYPE_DISEASE:
                        predicate = "investigated_in"
                    elif e1[4] == TYPE_BIOMARKER and e2[4] == TYPE_DISEASE:
                        predicate = "biomarker_for"
                    else:
                        predicate = "associated_with"

                triples.append({
                    "subject": e1[3],
                    "predicate": predicate,
                    "object": e2[3],
                    "subject_type": e1[4],
                    "object_type": e2[4],
                    "confidence": 0.95 if any(r[0].search(segment) for r in RELATION_PATTERNS) else 0.75,
                    "evidence_quote": sentence_clean,
                })

        return triples

    def ingest_article(
        self,
        *,
        title: str,
        abstract: str,
        pmid: str | None = None,
        doi: str | None = None,
        journal: str | None = None,
        year: int | None = None,
        agent_id: str | None = None,
        shared: bool = True,
    ) -> ConnectorResult:
        """Ingest a biomedical research article, extracting verified entities and relations."""
        result = ConnectorResult(connector="biomedical_literature")
        full_text = f"{title}\n\n{abstract}".strip()

        # Extract triples
        triples = self.extract_triples_from_text(full_text)

        locator = f"pmid:{pmid}" if pmid else (f"doi:{doi}" if doi else f"article:{uuid.uuid4().hex[:8]}")

        with self.store._lock:
            # 1. Create memory and source
            mem_record = self.store.store_memory(
                content=full_text,
                source={
                    "kind": "pubmed_article" if pmid else "biomedical_literature",
                    "locator": locator,
                    "agent_id": agent_id or "",
                    "metadata": {
                        "title": title,
                        "pmid": pmid,
                        "doi": doi,
                        "journal": journal,
                        "year": year,
                        "triples_extracted": len(triples),
                    },
                },
                status="confirmed",
                evidence_class="observed_event",
            )
            result.sources_created += 1
            result.memories_created += 1
            memory_id = str(mem_record["id"])
            source_id = str(mem_record["source"]["id"])

            # 3. Store entities and relations
            self.store._connection.execute("BEGIN IMMEDIATE")
            try:
                scope = "" if shared else (agent_id or "")
                created_entity_ids = set()
                created_relation_ids = []

                for t in triples:
                    sub = self.store._get_or_create_entity(
                        t["subject"],
                        entity_type=t["subject_type"],
                        agent_id=scope,
                        shared=shared,
                    )
                    created_entity_ids.add(sub["id"])

                    obj = self.store._get_or_create_entity(
                        t["object"],
                        entity_type=t["object_type"],
                        agent_id=scope,
                        shared=shared,
                    )
                    created_entity_ids.add(obj["id"])

                    # Register aliases for discovered terms
                    for raw_term, (canon, _) in BIOMEDICAL_VOCABULARY.items():
                        if canon == t["subject"] and raw_term.lower() != t["subject"].lower():
                            try:
                                self.store._connection.execute(
                                    """
                                    INSERT INTO entity_aliases(id, entity_id, alias, normalized_alias, evidence_memory_id, confidence)
                                    VALUES (?, ?, ?, ?, ?, 1.0)
                                    ON CONFLICT(entity_id, normalized_alias) DO NOTHING
                                    """,
                                    (str(uuid.uuid4()), sub["id"], raw_term, self.store._normalize_name(raw_term), memory_id)
                                )
                            except Exception:
                                pass

                    # Insert relation if not exists
                    existing = self.store._connection.execute(
                        """
                        SELECT id FROM relations
                        WHERE subject_entity_id = ? AND predicate = ? AND object_entity_id = ?
                          AND status = 'active' AND agent_id = ?
                        LIMIT 1
                        """,
                        (sub["id"], t["predicate"], obj["id"], scope),
                    ).fetchone()

                    if existing is None:
                        rel_id = str(uuid.uuid4())
                        self.store._connection.execute(
                            """
                            INSERT INTO relations(
                                id, subject_entity_id, predicate, object_entity_id,
                                evidence_memory_id, confidence, agent_id, status
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active')
                            """,
                            (rel_id, sub["id"], t["predicate"], obj["id"], memory_id, t["confidence"], scope),
                        )
                        created_relation_ids.append(rel_id)

                self.store._connection.execute("COMMIT")
                result.entities_created = len(created_entity_ids)
                result.relations_created = len(created_relation_ids)
                result.entity_ids = list(created_entity_ids)
                result.relation_ids = created_relation_ids
                result.details = {
                    "locator": locator,
                    "title": title,
                    "source_id": source_id,
                    "memory_id": memory_id,
                    "triples_count": len(triples),
                }
            except Exception as e:
                self.store._connection.execute("ROLLBACK")
                result.success = False
                result.errors.append(f"Biomedical ingestion failed: {e}")
                raise

        return result
