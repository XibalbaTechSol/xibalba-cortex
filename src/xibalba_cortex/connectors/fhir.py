"""HL7 FHIR & Clinical Records Knowledge Graph Connector with Cryptographic PHI Gating."""
from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Mapping

from ..store import GraphStore
from .base import ConnectorResult


class FHIRConnector:
    """Connects FHIR clinical resources (Conditions, Observations, Medications) to Cortex Knowledge Graphs."""

    def __init__(self, store: GraphStore, *, salt: str = "cortex_phi_salt"):
        self.store = store
        self.salt = salt

    def _anonymize_id(self, raw_id: str, prefix: str = "Patient") -> str:
        """Cryptographically anonymize a patient identifier via salt + sha256."""
        h = hashlib.sha256(f"{self.salt}:{raw_id}".encode("utf-8")).hexdigest()[:12]
        return f"{prefix}_{h}"

    def ingest_bundle(
        self,
        bundle_json_or_dict: str | Mapping[str, Any],
        *,
        source_name: str = "fhir_bundle",
        deidentify: bool = True,
        agent_id: str | None = None,
        shared: bool = True,
    ) -> ConnectorResult:
        """Ingests a FHIR Bundle into Cortex with Temporal Event Reification and PHI gating."""
        result = ConnectorResult(connector="fhir_clinical")

        if isinstance(bundle_json_or_dict, str):
            bundle = json.loads(bundle_json_or_dict)
        else:
            bundle = dict(bundle_json_or_dict)

        entries = bundle.get("entry", [])
        if not entries and bundle.get("resourceType"):
            # Single resource passed instead of a Bundle
            entries = [{"resource": bundle}]

        triples: list[dict[str, Any]] = []

        patient_map: dict[str, str] = {}

        for item in entries:
            res = item.get("resource", {})
            rtype = res.get("resourceType")
            rid = res.get("id", str(uuid.uuid4())[:8])

            if rtype == "Patient":
                anon_id = self._anonymize_id(rid, "Patient") if deidentify else f"Patient_{rid}"
                patient_map[rid] = anon_id
                patient_map[f"Patient/{rid}"] = anon_id

                gender = res.get("gender")
                if gender:
                    triples.append({
                        "subject": anon_id,
                        "predicate": "has_gender",
                        "object": gender.capitalize(),
                        "subject_type": "patient",
                        "object_type": "demographic",
                        "confidence": 1.0,
                    })

                # Age / Birth Year (de-identified to year only for HIPAA Safe Harbor)
                birth_date = res.get("birthDate")
                if birth_date:
                    year = birth_date.split("-")[0]
                    triples.append({
                        "subject": anon_id,
                        "predicate": "birth_year",
                        "object": year,
                        "subject_type": "patient",
                        "object_type": "demographic",
                        "confidence": 1.0,
                    })

            elif rtype == "Condition":
                subject_ref = res.get("subject", {}).get("reference", "")
                pat_id = patient_map.get(subject_ref, patient_map.get(subject_ref.replace("Patient/", "")))
                if not pat_id and subject_ref:
                    raw = subject_ref.replace("Patient/", "")
                    pat_id = self._anonymize_id(raw, "Patient") if deidentify else f"Patient_{raw}"

                # Extract condition display or code
                code_obj = res.get("code", {})
                cond_name = code_obj.get("text")
                coding = code_obj.get("coding", [{}])[0] if code_obj.get("coding") else {}
                if not cond_name:
                    cond_name = coding.get("display") or coding.get("code") or "Unknown Condition"

                if pat_id and cond_name:
                    triples.append({
                        "subject": pat_id,
                        "predicate": "has_condition",
                        "object": cond_name.strip(),
                        "subject_type": "patient",
                        "object_type": "disease",
                        "confidence": 1.0,
                    })

            elif rtype in ("MedicationRequest", "MedicationStatement"):
                subject_ref = res.get("subject", {}).get("reference", "")
                pat_id = patient_map.get(subject_ref, patient_map.get(subject_ref.replace("Patient/", "")))
                if not pat_id and subject_ref:
                    raw = subject_ref.replace("Patient/", "")
                    pat_id = self._anonymize_id(raw, "Patient") if deidentify else f"Patient_{raw}"

                med_obj = res.get("medicationCodeableConcept", {})
                med_name = med_obj.get("text")
                med_coding = med_obj.get("coding", [{}])[0] if med_obj.get("coding") else {}
                if not med_name:
                    med_name = med_coding.get("display") or med_coding.get("code") or "Unknown Medication"

                if pat_id and med_name:
                    triples.append({
                        "subject": pat_id,
                        "predicate": "prescribed",
                        "object": med_name.strip(),
                        "subject_type": "patient",
                        "object_type": "drug",
                        "confidence": 1.0,
                    })

            elif rtype == "Observation":
                # Temporal Event Reification
                subject_ref = res.get("subject", {}).get("reference", "")
                pat_id = patient_map.get(subject_ref, patient_map.get(subject_ref.replace("Patient/", "")))
                if not pat_id and subject_ref:
                    raw = subject_ref.replace("Patient/", "")
                    pat_id = self._anonymize_id(raw, "Patient") if deidentify else f"Patient_{raw}"

                code_obj = res.get("code", {})
                obs_name = code_obj.get("text")
                obs_coding = code_obj.get("coding", [{}])[0] if code_obj.get("coding") else {}
                if not obs_name:
                    obs_name = obs_coding.get("display") or obs_coding.get("code") or "Clinical Observation"

                # Extract Value
                val_str = ""
                if "valueQuantity" in res:
                    vq = res["valueQuantity"]
                    val_str = f"{vq.get('value')} {vq.get('unit', '')}".strip()
                elif "valueString" in res:
                    val_str = str(res["valueString"])
                elif "valueCodeableConcept" in res:
                    val_str = res["valueCodeableConcept"].get("text", "")

                effective_dt = res.get("effectiveDateTime", res.get("issued", ""))
                event_node_id = f"ObsEvent_{rid[:8]}"

                if pat_id:
                    # Patient -> HAS_OBSERVATION -> EventNode
                    triples.append({
                        "subject": pat_id,
                        "predicate": "has_observation_event",
                        "object": event_node_id,
                        "subject_type": "patient",
                        "object_type": "clinical_event",
                        "confidence": 1.0,
                    })
                    # EventNode -> OF_TYPE -> Observation
                    triples.append({
                        "subject": event_node_id,
                        "predicate": "of_type",
                        "object": obs_name.strip(),
                        "subject_type": "clinical_event",
                        "object_type": "biomarker",
                        "confidence": 1.0,
                    })
                    # EventNode -> HAS_VALUE -> Value
                    if val_str:
                        triples.append({
                            "subject": event_node_id,
                            "predicate": "has_value",
                            "object": val_str,
                            "subject_type": "clinical_event",
                            "object_type": "measurement",
                            "confidence": 1.0,
                        })
                    # EventNode -> OCCURRED_AT -> Date
                    if effective_dt:
                        triples.append({
                            "subject": event_node_id,
                            "predicate": "occurred_at",
                            "object": effective_dt.split("T")[0],
                            "subject_type": "clinical_event",
                            "object_type": "temporal",
                            "confidence": 1.0,
                        })

        if not triples:
            result.success = True
            result.details = {"message": "No clinical triples parsed from bundle"}
            return result

        # Store into GraphStore
        with self.store._lock:
            mem_record = self.store.store_memory(
                content=f"FHIR clinical bundle ingested: {len(triples)} events/triples reified from {source_name}",
                source={
                    "kind": "fhir_connector",
                    "locator": source_name,
                    "agent_id": agent_id or "",
                    "metadata": {"deidentified": deidentify, "total_resources": len(entries), "triples_count": len(triples)},
                },
                status="confirmed",
                evidence_class="observed_event",
            )
            result.sources_created += 1
            result.memories_created += 1
            memory_id = str(mem_record["id"])
            source_id = str(mem_record["source"]["id"])

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
                    "source_id": source_id,
                    "memory_id": memory_id,
                    "deidentified": deidentify,
                    "triples_count": len(triples),
                }
            except Exception as e:
                self.store._connection.execute("ROLLBACK")
                result.success = False
                result.errors.append(f"FHIR ingestion transaction failed: {e}")
                raise

        return result
