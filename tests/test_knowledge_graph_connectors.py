"""Tests for Knowledge Graph Connectors & Active Inference Engine."""
import json
from pathlib import Path

import pytest

from xibalba_cortex.connectors import (
    ActiveInferenceEngine,
    BiomedicalConnector,
    FHIRConnector,
    TriplesConnector,
)
from xibalba_cortex.store import GraphStore


@pytest.fixture
def store(tmp_path: Path) -> GraphStore:
    return GraphStore(home=tmp_path / "cortex_test")


def test_triples_connector_tuples_and_dicts(store: GraphStore):
    connector = TriplesConnector(store)

    triples = [
        ("Imatinib", "inhibits", "BCR-ABL1", 0.99),
        ("BCR-ABL1", "associated_with", "Chronic Myeloid Leukemia", 0.95),
        ("Imatinib", "inhibits", "c-KIT", 0.98),
        {"subject": "c-KIT", "predicate": "associated_with", "object": "Gastrointestinal Stromal Tumor", "confidence": 0.92},
    ]

    result = connector.ingest_triples(triples, source_name="oncology_panel")
    assert result.success is True
    assert result.entities_created == 5
    assert result.relations_created == 4
    assert result.memories_created == 1

    # Verify entities in store
    entity_names = [e["canonical_name"] for e in store.list_entities()]
    assert "Imatinib" in entity_names
    assert "BCR-ABL1" in entity_names
    assert "Chronic Myeloid Leukemia" in entity_names
    assert "c-KIT" in entity_names
    assert "Gastrointestinal Stromal Tumor" in entity_names

    # Test ActiveInferenceEngine on this graph
    engine = ActiveInferenceEngine(store)
    mechanisms = engine.trace_mechanisms("Imatinib", "Chronic Myeloid Leukemia")
    assert len(mechanisms) == 1
    assert mechanisms[0]["path_nodes"] == ["Imatinib", "BCR-ABL1", "Chronic Myeloid Leukemia"]
    assert mechanisms[0]["length"] == 2

    # Predict links
    pred = engine.predict_links("Imatinib", "Gastrointestinal Stromal Tumor")
    assert pred["probability"] > 0.5
    assert "c-KIT" in pred["common_neighbors"]


def test_triples_connector_csv(store: GraphStore):
    connector = TriplesConnector(store)
    csv_data = """head,relation,tail,confidence
Pembrolizumab,blocks,PD-1,0.99
PD-1,downregulates,T-Cell Activation,0.92
T-Cell Activation,induces,Tumor Cell Apoptosis,0.95
Pembrolizumab,correlated_with,PD-L1 Expression,0.88
PD-L1 Expression,biomarker_for,Non-Small Cell Lung Cancer,0.91
"""
    result = connector.ingest_csv(csv_data, source_name="immunotherapy_csv")
    assert result.success is True
    assert result.relations_created == 5

    engine = ActiveInferenceEngine(store)
    mechanisms = engine.trace_mechanisms("Pembrolizumab", "Tumor Cell Apoptosis")
    assert len(mechanisms) >= 1
    assert mechanisms[0]["path_nodes"] == ["Pembrolizumab", "PD-1", "T-Cell Activation", "Tumor Cell Apoptosis"]


def test_biomedical_connector_article(store: GraphStore):
    connector = BiomedicalConnector(store)
    title = "Efficacy of Imatinib via BCR-ABL1 and c-KIT inhibition in leukemia and gastrointestinal tumors"
    abstract = (
        "Imatinib effectively inhibits BCR-ABL1 tyrosine kinase, which is associated with Chronic Myeloid Leukemia. "
        "Furthermore, Imatinib blocks c-KIT, a receptor tyrosine kinase overexpressed in Gastrointestinal Stromal Tumor. "
        "Pembrolizumab targets PD-1, promoting T-Cell Activation and Tumor Cell Apoptosis in Non-Small Cell Lung Cancer."
    )

    result = connector.ingest_article(
        title=title,
        abstract=abstract,
        pmid="12345678",
        doi="10.1016/j.cortex.2026.01.001",
    )
    assert result.success is True
    assert result.relations_created >= 4

    engine = ActiveInferenceEngine(store)
    # Check alias resolution ("cml" -> "Chronic Myeloid Leukemia")
    mechanisms = engine.trace_mechanisms("Imatinib", "Chronic Myeloid Leukemia")
    assert len(mechanisms) >= 1

    # Suggest drug repurposing
    repurposing = engine.suggest_drug_repurposing("Gastrointestinal Stromal Tumor")
    assert any(c["drug"] == "Imatinib" for c in repurposing)


def test_fhir_connector_patient_observations(store: GraphStore):
    connector = FHIRConnector(store)

    fhir_bundle = {
        "resourceType": "Bundle",
        "entry": [
            {
                "resource": {
                    "resourceType": "Patient",
                    "id": "pat-001",
                    "gender": "female",
                    "birthDate": "1980-05-12",
                }
            },
            {
                "resource": {
                    "resourceType": "Condition",
                    "id": "cond-101",
                    "subject": {"reference": "Patient/pat-001"},
                    "code": {
                        "text": "Chronic Myeloid Leukemia",
                        "coding": [{"system": "http://hl7.org/fhir/sid/icd-10", "code": "C92.1"}],
                    },
                }
            },
            {
                "resource": {
                    "resourceType": "MedicationRequest",
                    "id": "med-201",
                    "subject": {"reference": "Patient/pat-001"},
                    "medicationCodeableConcept": {
                        "text": "Imatinib",
                        "coding": [{"system": "http://www.nlm.nih.gov/research/umls/rxnorm", "code": "282388"}],
                    },
                }
            },
            {
                "resource": {
                    "resourceType": "Observation",
                    "id": "obs-301",
                    "subject": {"reference": "Patient/pat-001"},
                    "code": {"text": "BCR-ABL Transcript Ratio"},
                    "valueQuantity": {"value": 0.05, "unit": "%"},
                    "effectiveDateTime": "2026-03-15T10:30:00Z",
                }
            },
        ],
    }

    result = connector.ingest_bundle(fhir_bundle, source_name="oncology_ehr_sync", deidentify=True)
    assert result.success is True
    assert result.relations_created >= 4

    # Ensure patient ID was cryptographically anonymized (not "pat-001")
    entities = [e["canonical_name"] for e in store.list_entities()]
    assert "pat-001" not in entities
    patient_entities = [name for name in entities if name.startswith("Patient_")]
    assert len(patient_entities) == 1

    engine = ActiveInferenceEngine(store)
    # Check that patient is connected to Condition and Medication
    pat_name = patient_entities[0]
    subgraph = engine.get_ego_subgraph(pat_name, radius=2)
    labels = [n["label"] for n in subgraph["nodes"]]
    assert "Chronic Myeloid Leukemia" in labels
    assert "Imatinib" in labels


def test_ais_graph_reward_engine(store: GraphStore):
    # Setup knowledge graph with verified edges
    connector = TriplesConnector(store)
    connector.ingest_triples(
        [
            ("Imatinib", "inhibits", "BCR-ABL1", 0.98),
            ("BCR-ABL1", "associated_with", "Chronic Myeloid Leukemia", 0.95),
            ("Imatinib", "inhibits", "c-KIT", 0.90),
            ("c-KIT", "associated_with", "Gastrointestinal Stromal Tumor", 0.88),
        ],
        source_name="oncology_verified",
    )

    # 1. Verified step evaluation: full grounding, compliant, reward > 0
    step_verified = store.evaluate_step_reward(
        source="Imatinib",
        relation="inhibits",
        target="BCR-ABL1",
        task_reward=1.0,
        cost=0.02,
        bonded_stake=100.0,
    )
    assert step_verified["is_hallucination"] is False
    assert step_verified["is_policy_violation"] is False
    assert step_verified["grounding"] == 0.98
    assert step_verified["compliance"] == 1.0
    assert step_verified["ais"] > 0.8
    assert step_verified["total_reward"] > 2.0
    assert step_verified["slashing_penalty"] == 0.0
    assert step_verified["remaining_bonded_stake"] == 100.0

    # 2. Hallucinated step evaluation: nonexistent ungrounded connection collapses to 0.0
    step_hallucination = store.evaluate_step_reward(
        source="Imatinib",
        relation="cures",
        target="CompletelyFictitiousDiseaseXYZ",
        task_reward=5.0,  # Agent claims high task completion
        cost=0.01,
        bonded_stake=100.0,
    )
    assert step_hallucination["is_hallucination"] is True
    assert step_hallucination["grounding"] == 0.0
    assert step_hallucination["ais"] == 0.0
    assert step_hallucination["total_reward"] < 0.0  # Reward collapsed and penalized
    assert step_hallucination["slashing_penalty"] == 10.0  # 10% slashed
    assert step_hallucination["remaining_bonded_stake"] == 90.0

    # 3. Policy violation evaluation: prohibited relation triggers compliance=0 and 50% slash
    step_violation = store.evaluate_step_reward(
        source="Imatinib",
        relation="leak_phi",
        target="BCR-ABL1",
        bonded_stake=100.0,
    )
    assert step_violation["is_policy_violation"] is True
    assert step_violation["compliance"] == 0.0
    assert step_violation["ais"] == 0.0
    assert step_violation["total_reward"] <= -50.0
    assert step_violation["slashing_penalty"] == 50.0  # 50% slashed
    assert step_violation["remaining_bonded_stake"] == 50.0

    # 4. Multi-step trajectory evaluation
    trajectory = [
        {"source": "Imatinib", "relation": "inhibits", "target": "BCR-ABL1", "task_reward": 1.0},
        {"source": "BCR-ABL1", "relation": "associated_with", "target": "Chronic Myeloid Leukemia", "task_reward": 2.0},
    ]
    traj_result = store.evaluate_trajectory_reward(trajectory, discount_factor=0.9, initial_stake=100.0)
    assert traj_result["trajectory_length"] == 2
    assert traj_result["has_hallucination"] is False
    assert traj_result["has_policy_violation"] is False
    assert traj_result["mean_ais"] > 0.8
    assert traj_result["cumulative_reward"] > 0.0
    assert traj_result["final_bonded_stake"] == 100.0

