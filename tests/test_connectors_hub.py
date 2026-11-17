from __future__ import annotations

import pytest
from super_cortex.config import SuperCortexConfig
from super_cortex.connectors import SuperCortexConnectors
from super_cortex.memory import SuperCortex


@pytest.mark.asyncio
async def test_connectors_catalog_and_ten_pipelines(tmp_path):
    cfg = SuperCortexConfig(
        db_path=tmp_path / "connectors_test.db",
        supermemory_url="http://127.0.0.1:59999",
    )
    cortex = SuperCortex(cfg)
    connectors = SuperCortexConnectors(cortex)

    catalog = connectors.get_connectors_status()
    assert len(catalog) == 10
    ids = {c["id"] for c in catalog}
    assert ids == {
        "google_workspace",
        "github",
        "web_clipper",
        "local_files",
        "git_repos",
        "agent_transcripts",
        "csv_tabular",
        "rdf_triples",
        "scientific_literature",
        "fhir_enterprise",
    }


@pytest.mark.asyncio
async def test_google_workspace_mirror_and_directory_ingest(tmp_path):
    cfg = SuperCortexConfig(
        db_path=tmp_path / "gworkspace_test.db",
        supermemory_url="http://127.0.0.1:59999",
    )
    cortex = SuperCortex(cfg)
    connectors = SuperCortexConnectors(cortex)

    sample_doc = tmp_path / "xibalba_q4_strategy.md"
    sample_doc.write_text(
        "# Xibalba Solutions Q4 Strategy\nSuper-Cortex enforces Merkle provenance across all agent harnesses.",
        encoding="utf-8",
    )

    res = await connectors.ingest_google_workspace(
        mode="doc_url",
        target=str(sample_doc),
        scope="shared",
    )
    assert res["status"] == "ingested"
    assert res["memory"]["memory_id"].startswith("mem_")

    dir_res = await connectors.ingest_directory(
        str(tmp_path),
        glob_pattern="*.md",
        max_files=5,
        scope="shared",
    )
    assert dir_res["files_ingested"] == 1


@pytest.mark.asyncio
async def test_csv_triples_literature_and_fhir_connectors(tmp_path):
    cfg = SuperCortexConfig(
        db_path=tmp_path / "data_connectors.db",
        supermemory_url="http://127.0.0.1:59999",
    )
    cortex = SuperCortex(cfg)
    connectors = SuperCortexConnectors(cortex)

    # 1. CSV Connector
    csv_payload = "subject,predicate,object\nSuper-Cortex,replaces,Legacy Cortex\nXibalba Shield,protects,HIPAA Enclave"
    csv_res = await connectors.ingest_csv(csv_text=csv_payload, source_name="test_table", scope="shared")
    assert csv_res["success"] is True
    assert csv_res["rows_processed"] == 2
    assert csv_res["relations_created"] == 2

    # 2. RDF Triples Connector
    triples_res = await connectors.ingest_triples(
        triples=[
            {"subject": "AGY Agent", "predicate": "operates_under", "object": "Ed25519 DID"},
            ["PID Controller", "regulates", "Yield Execution"],
        ],
        source_name="unit_test_triples",
        scope="shared",
    )
    assert triples_res["triples_inserted"] == 2

    # 3. Scientific / Biomedical Literature Connector
    lit_res = await connectors.ingest_literature(
        title="Spectral Graph Partitioning in Autonomous Memory Fabrics",
        abstract="We prove that the Fiedler eigenvalue lambda_2 bounds cross-scope information leakage.",
        pmid="39876543",
        scope="shared",
    )
    assert lit_res["articles_ingested"] == 1

    # 4. HL7 FHIR R4 Bundle Connector
    fhir_bundle = {
        "resourceType": "Bundle",
        "entry": [
            {
                "resource": {
                    "resourceType": "Patient",
                    "id": "pt-001",
                    "name": [{"given": ["Elena"], "family": "Rostova"}],
                    "gender": "female",
                    "birthDate": "1985-04-12",
                }
            },
            {
                "resource": {
                    "resourceType": "Condition",
                    "id": "cond-001",
                    "code": {"text": "Type 2 Diabetes Mellitus"},
                }
            },
            {
                "resource": {
                    "resourceType": "MedicationRequest",
                    "id": "med-001",
                    "medicationCodeableConcept": {"text": "Metformin 500mg"},
                }
            },
        ],
    }
    fhir_res = await connectors.ingest_fhir_bundle(fhir_bundle, scope="agent:shield")
    assert fhir_res["resources_processed"] == 3
    assert fhir_res["relations_created"] == 2

    # 5. Verify Sync History Ledger recorded all 4 operations
    history = connectors.get_sync_history(limit=10)
    assert len(history) >= 4
    recorded_connectors = {h["connector_id"] for h in history}
    assert {"csv_tabular", "rdf_triples", "scientific_literature", "fhir_enterprise"}.issubset(recorded_connectors)
