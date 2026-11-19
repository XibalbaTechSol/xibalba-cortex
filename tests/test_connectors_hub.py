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
    assert len(catalog) == 11
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
        "public_datasets",
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


@pytest.mark.asyncio
async def test_google_workspace_drive_batch_pdf_and_calendar_gmail(tmp_path):
    cfg = SuperCortexConfig(
        db_path=tmp_path / "gworkspace_batch_test.db",
        supermemory_url="http://127.0.0.1:59999",
    )
    cortex = SuperCortex(cfg)
    connectors = SuperCortexConnectors(cortex)

    # 1. Test Drive searching
    drive_search = connectors.search_google_drive(query="Strategy", page_size=10)
    assert "items" in drive_search
    assert isinstance(drive_search["items"], list)

    # 2. Test PDF extraction and batch ingest
    sample_pdf = tmp_path / "quantum_control_invariance.pdf"
    # Create valid minimal PDF using pypdf
    from pypdf import PdfWriter
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with open(sample_pdf, "wb") as f:
        writer.write(f)

    batch_items = [
        {
            "id": str(sample_pdf),
            "name": sample_pdf.name,
            "mimeType": "application/pdf",
            "is_folder": False,
            "source": "workspace_mirror",
        },
        {
            "id": str(tmp_path),
            "name": "Research_Folder",
            "mimeType": "application/vnd.google-apps.folder",
            "is_folder": True,
            "source": "workspace_mirror",
        },
    ]

    batch_res = await connectors.ingest_google_workspace_batch(items=batch_items, scope="shared")
    assert batch_res["status"] == "ingested"
    assert batch_res["items_ingested"] >= 1

    # 3. Test Calendar searching & batch ingest
    cal_res = connectors.search_google_calendar(query="Synthesis")
    assert len(cal_res["events"]) >= 1
    cal_ingest = await connectors.ingest_google_calendar_batch(events=cal_res["events"][:1], scope="shared")
    assert cal_ingest["status"] == "ingested"
    assert cal_ingest["events_ingested"] == 1

    # 4. Test Gmail searching & batch ingest
    gmail_res = connectors.search_gmail(query="Integrity")
    assert len(gmail_res["messages"]) >= 1
    gmail_ingest = await connectors.ingest_gmail_batch(messages=gmail_res["messages"][:1], scope="shared")
    assert gmail_ingest["status"] == "ingested"
    assert gmail_ingest["messages_ingested"] == 1


@pytest.mark.asyncio
async def test_github_reimagined_search_and_complete_repo(tmp_path):
    cfg = SuperCortexConfig(
        db_path=tmp_path / "github_reimagined_test.db",
        supermemory_url="http://127.0.0.1:59999",
    )
    cortex = SuperCortex(cfg)
    connectors = SuperCortexConnectors(cortex)

    # 1. Search public repos
    results = connectors.search_github_repos(query="super-cortex", limit=5)
    assert isinstance(results, list)

    # 2. Ingest complete repository
    repo_res = await connectors.ingest_github_complete_repo(repo="XibalbaTechSol/super-cortex", scope="shared")
    assert repo_res["status"] == "ingested"
    assert repo_res["repo"] == "XibalbaTechSol/super-cortex"
    assert "memory_id" in repo_res
    assert isinstance(repo_res.get("modules"), list)

    # Verify repository entity and relations in knowledge graph
    with cortex.store._get_conn() as conn:
        rel_cursor = conn.execute("SELECT subject, predicate, object FROM relations WHERE subject = 'XibalbaTechSol/super-cortex'")
        rels = rel_cursor.fetchall()
        assert len(rels) >= 1


@pytest.mark.asyncio
async def test_scientific_literature_search_and_linking(tmp_path):
    cfg = SuperCortexConfig(
        db_path=tmp_path / "literature_test.db",
        supermemory_url="http://127.0.0.1:59999",
    )
    cortex = SuperCortex(cfg)
    connectors = SuperCortexConnectors(cortex)

    # 1. Ingest base anchor node
    base_mem = await cortex.remember("PID Control Systems and Spectral Graph Routing", scope="shared")

    # 2. Ingest paper and link directly to base node
    paper_data = {
        "id": "2310.06825",
        "title": "Spectral Cheeger Bounds in Autonomous Agent Networks",
        "authors": ["J. S. Vickers", "A. Kolmogorov"],
        "summary": "We establish that the second smallest Laplacian eigenvalue governs cross-manifold information routing.",
        "source": "arxiv",
        "pdf_url": "https://arxiv.org/pdf/2310.06825.pdf",
    }
    link_res = await connectors.ingest_literature_and_link(
        paper=paper_data,
        link_to_node_id=base_mem["memory_id"],
        scope="shared",
    )
    assert link_res["status"] == "ingested"
    assert link_res["created_edge"] is not None
    assert link_res["created_edge"]["predicate"] == "cites_literature"


@pytest.mark.asyncio
async def test_public_datasets_demo_and_catalog(tmp_path):
    cfg = SuperCortexConfig(
        db_path=tmp_path / "public_datasets_test.db",
        supermemory_url="http://127.0.0.1:59999",
    )
    cortex = SuperCortex(cfg)
    connectors = SuperCortexConnectors(cortex)

    # 1. Catalog check
    catalog = connectors.get_public_datasets_catalog()
    assert len(catalog) >= 3
    demo_ds = next(d for d in catalog if d["id"] == "demo_ai_control")
    assert demo_ds["is_demo"] is True

    # 2. Preview check
    preview = connectors.get_public_dataset_preview("demo_ai_control")
    assert len(preview["nodes"]) >= 20
    assert len(preview["triples"]) >= 20

    # 3. Ingestion check
    ingest_res = await connectors.ingest_public_dataset("demo_ai_control", scope="shared")
    assert ingest_res["status"] == "ingested"
    assert ingest_res["nodes_ingested"] >= 20
    assert ingest_res["edges_ingested"] >= 20
    assert "memory" in ingest_res


@pytest.mark.asyncio
async def test_generic_file_viewer_and_docx_extraction(tmp_path):
    import io
    import zipfile
    from starlette.testclient import TestClient
    from super_cortex.api import create_app
    from super_cortex.connectors import _extract_docx_content

    cfg = SuperCortexConfig(
        db_path=tmp_path / "generic_viewer_test.db",
        supermemory_url="http://127.0.0.1:59999",
    )
    cortex = SuperCortex(cfg)
    connectors = SuperCortexConnectors(cortex)

    # 1. Test DOCX extraction from in-memory OpenXML zip archive
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        doc_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p>
      <w:pPr><w:pStyle w:val="Heading1"/></w:pPr>
      <w:r><w:t>Quantum Cryptographic Ledger</w:t></w:r>
    </w:p>
    <w:p>
      <w:r>
        <w:rPr><w:b/><w:i/></w:rPr>
        <w:t>Confidential Specification:</w:t>
      </w:r>
      <w:r>
        <w:t> Ed25519 signatures secure all state transitions.</w:t>
      </w:r>
    </w:p>
  </w:body>
</w:document>"""
        z.writestr("word/document.xml", doc_xml)
    docx_bytes = buf.getvalue()

    plain_txt, html_doc, p_count = _extract_docx_content(docx_bytes)
    assert p_count == 2
    assert "Quantum Cryptographic Ledger" in plain_txt
    assert "<h1" in html_doc
    assert "<strong><em>Confidential Specification:</em></strong>" in html_doc

    # 2. Test local files and preview API endpoint
    test_docx = tmp_path / "spec.docx"
    test_docx.write_bytes(docx_bytes)

    test_md = tmp_path / "architecture.md"
    test_md.write_text("# Merkle Architecture\nZero-knowledge verification is active.", encoding="utf-8")

    test_txt = tmp_path / "log.txt"
    test_txt.write_text("2026-11-18 22:00:00 [INFO] System verified.", encoding="utf-8")

    app = create_app(cfg)
    client = TestClient(app)

    # 2a. DOCX JSON preview
    r = client.get(f"/api/connectors/file/preview?path={test_docx}&format=json")
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "ok"
    assert d["kind"] == "docx"
    assert d["paragraphs"] == 2
    assert "Quantum Cryptographic Ledger" in d["text"]
    assert "<h1" in d["html"]

    # 2b. DOCX HTML preview
    r_html = client.get(f"/api/connectors/file/preview?path={test_docx}&format=html")
    assert r_html.status_code == 200
    assert "text/html" in r_html.headers.get("content-type", "")
    assert "<!DOCTYPE html>" in r_html.text

    # 2c. Markdown JSON preview
    r_md = client.get(f"/api/connectors/file/preview?path={test_md}&format=json")
    assert r_md.status_code == 200
    d_md = r_md.json()
    assert d_md["kind"] == "markdown"
    assert "Merkle Architecture" in d_md["text"]

    # 2d. Text raw preview
    r_txt = client.get(f"/api/connectors/file/preview?path={test_txt}")
    assert r_txt.status_code == 200
    assert "text/plain" in r_txt.headers.get("content-type", "")
    assert "System verified" in r_txt.text

    # 2e. Ingest batch of diverse file types via Workspace connector
    batch_items = [
        {"id": str(test_docx), "name": "spec.docx", "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "source": "workspace_mirror"},
        {"id": str(test_md), "name": "architecture.md", "mimeType": "text/markdown", "source": "workspace_mirror"},
        {"id": str(test_txt), "name": "log.txt", "mimeType": "text/plain", "source": "workspace_mirror"},
    ]
    batch_res = await connectors.ingest_google_workspace_batch(items=batch_items, scope="shared")
    assert batch_res["items_ingested"] == 3
    assert len(batch_res["items"]) == 3
    for it in batch_res["items"]:
        assert "file_url" in it
        assert it["file_url"].startswith("/api/connectors/file/preview")
