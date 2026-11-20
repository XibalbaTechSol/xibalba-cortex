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

    # 2. Ingest complete repository with scoped file, PR, and commit manifolds
    repo_res = await connectors.ingest_github_complete_repo(
        repo="XibalbaTechSol/super-cortex",
        scope="shared",
        sync_files=True,
        sync_prs=True,
        sync_commits=True,
    )
    assert repo_res["status"] == "ingested"
    assert repo_res["repo"] == "XibalbaTechSol/super-cortex"
    assert "memory_id" in repo_res
    assert isinstance(repo_res.get("modules"), list)
    assert "scopes" in repo_res
    assert "github:XibalbaTechSol/super-cortex:txt" in repo_res["scopes"]
    assert "github:XibalbaTechSol/super-cortex:prs" in repo_res["scopes"]
    assert "github:XibalbaTechSol/super-cortex:commits" in repo_res["scopes"]

    # Verify repository scopes registered in store
    scope_ids = {s["scope_id"] if isinstance(s, dict) else s.scope_id for s in cortex.list_scopes()}
    assert "github:XibalbaTechSol/super-cortex:txt" in scope_ids
    assert "github:XibalbaTechSol/super-cortex:prs" in scope_ids
    assert "github:XibalbaTechSol/super-cortex:commits" in scope_ids

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


@pytest.mark.asyncio
async def test_github_browser_endpoints(tmp_path) -> None:
    """Verify dedicated GitHub browsing endpoints for repository tree, files, commits, PRs, and issues."""
    from starlette.testclient import TestClient
    from super_cortex.api import create_app

    cfg = SuperCortexConfig(
        db_path=tmp_path / "github_browser_test.db",
        supermemory_url="http://127.0.0.1:59999",
    )
    app = create_app(cfg)
    client = TestClient(app)
    # 1. Tree
    r_tree = client.get("/api/connectors/github/tree?repo=XibalbaTechSol/super-cortex")
    assert r_tree.status_code == 200
    d_tree = r_tree.json()
    assert "tree" in d_tree
    assert isinstance(d_tree["tree"], list)
    assert len(d_tree["tree"]) > 0
    assert any("pyproject.toml" in f for f in d_tree["tree"])

    # 2. File Content
    r_file = client.get("/api/connectors/github/file?repo=XibalbaTechSol/super-cortex&path=pyproject.toml")
    assert r_file.status_code == 200
    d_file = r_file.json()
    assert d_file["path"] == "pyproject.toml"
    assert "super-cortex" in d_file["content"]
    assert d_file["is_binary"] is False

    # 3. Commits
    r_commits = client.get("/api/connectors/github/commits?repo=XibalbaTechSol/super-cortex&limit=5")
    assert r_commits.status_code == 200
    d_commits = r_commits.json()
    assert "commits" in d_commits
    assert isinstance(d_commits["commits"], list)
    assert len(d_commits["commits"]) > 0
    assert "sha" in d_commits["commits"][0]
    assert "message" in d_commits["commits"][0]

    # 4. PRs
    r_prs = client.get("/api/connectors/github/prs?repo=XibalbaTechSol/super-cortex&limit=5")
    assert r_prs.status_code == 200
    d_prs = r_prs.json()
    assert "prs" in d_prs
    assert isinstance(d_prs["prs"], list)

    # 5. Issues
    r_issues = client.get("/api/connectors/github/issues?repo=XibalbaTechSol/super-cortex&limit=5")
    assert r_issues.status_code == 200
    d_issues = r_issues.json()
    assert "issues" in d_issues
    assert isinstance(d_issues["issues"], list)

    # 6. File Preview Resolution from local file path
    r_prev = client.get("/api/connectors/file/preview?repo=XibalbaTechSol/super-cortex&path=pyproject.toml&format=json")
    assert r_prev.status_code == 200
    d_prev = r_prev.json()
    assert d_prev["status"] == "ok"
    assert "super-cortex" in d_prev["text"]

    # 7. File Preview Resolution from memory ID
    from super_cortex.models import MemoryRecord
    from super_cortex.store import ProvenanceStore
    test_rec = MemoryRecord(
        id="mem_preview_test",
        text="# Test Document\n\nPreview verification text content.",
        source_id="file:///tmp/test_doc.md",
        epistemic_class="fact",
        content_hash="0123456789abcdef",
    )
    pstore = ProvenanceStore(cfg.db_path)
    pstore.save_memory(test_rec)

    r_mem_prev = client.get("/api/connectors/file/preview?file_id=mem_preview_test&format=json")
    assert r_mem_prev.status_code == 200
    d_mem_prev = r_mem_prev.json()
    assert d_mem_prev["status"] == "ok"
    assert d_mem_prev["kind"] == "markdown"
    assert "Preview verification text" in d_mem_prev["text"]


@pytest.mark.asyncio
async def test_agent_transcripts_connector_and_unique_node_types(tmp_path):
    from super_cortex.importers import SessionImporter
    from starlette.testclient import TestClient
    from super_cortex.api import create_app

    cfg = SuperCortexConfig(
        db_path=tmp_path / "agent_telemetry_test.db",
        supermemory_url="http://127.0.0.1:59999",
    )
    cortex = SuperCortex(cfg)
    connectors = SuperCortexConnectors(cortex)

    # 1. Test SessionImporter instantiation & import
    importer = SessionImporter(store=cortex.store)
    assert importer is not None
    assert importer.store is cortex.store

    # 2. Record mock turns for each agent harness to verify node types
    cortex.record_exchange(
        session_id="sess_agy_test_turn",
        prompt_text="Run optimization loop",
        response_text="Executing PID step",
        thinking_text="Need to evaluate stability margin via feedback control",
        tool_calls=[{"name": "run_command", "args": {"cmd": "status"}}],
        actor="did:integrity:b1a72980e8e45e97c7b92982a89b1963e470b45fa955c9bd245f046e1e32e39a",
        agent_id="agy",
        scope_id="agent:agy",
    )
    cortex.record_exchange(
        session_id="sess_claude_test_turn",
        prompt_text="Inspect graph architecture",
        response_text="Inspecting graph routes",
        thinking_text="Checking node type assignments across agent scopes",
        tool_calls=[{"name": "read_file", "args": {"path": "api.py"}}],
        actor="did:integrity:f07438ae1fb67f6ab1a21df87fb4771bead162c502c6e98cfa0bbdd7020a7e75",
        agent_id="claude",
        scope_id="agent:claude",
    )
    cortex.record_exchange(
        session_id="sess_codex_test_turn",
        prompt_text="Generate mathematical proof",
        response_text="Proof generated",
        thinking_text="Eigenvalues bounded by Cheeger constant",
        tool_calls=[{"name": "eval_pde", "args": {"order": 2}}],
        actor="did:integrity:d73b98dd869948c27c7cc16d53683779a23c46daf3020e221955d67d1a8723c5",
        agent_id="codex",
        scope_id="agent:codex",
    )

    # Add memory and relation
    await cortex.remember("Deterministic integrity rules enforce zero cross-scope drift.", scope="shared")
    cortex.store.add_entity("Spectral Graph", aliases=["Graph"], evidence_links=["proof"])
    cortex.store.add_relation("Spectral Graph", "has_bound", "Cheeger Constant", confidence=1.0)

    # 3. Test /api/graph endpoint returns unique node types for different scopes
    app = create_app(cfg)
    client = TestClient(app)
    graph_res = client.get("/api/graph")
    assert graph_res.status_code == 200
    graph_data = graph_res.json()
    assert "nodes" in graph_data
    assert "links" in graph_data

    nodes = graph_data["nodes"]
    node_types = {n.get("type") for n in nodes}
    unique_node_types = {n.get("node_type") for n in nodes}
    scope_node_types = {n.get("scope_node_type") for n in nodes if n.get("scope_node_type")}

    # Assert distinct types exist
    assert "thought_trace" in node_types
    assert "tool_call" in node_types
    assert "thought_trace" in unique_node_types
    assert "tool_call" in unique_node_types
    assert "shared_hub" in unique_node_types
    assert "knowledge_entity" in unique_node_types

    # Assert scope-qualified node types exist
    assert "agent:agy:thought_trace" in scope_node_types
    assert "agent:agy:tool_call" in scope_node_types
    assert "agent:claude:thought_trace" in scope_node_types
    assert "agent:claude:tool_call" in scope_node_types
    assert "agent:codex:thought_trace" in scope_node_types
    assert "agent:codex:tool_call" in scope_node_types
    assert "shared:hub" in scope_node_types
    assert "shared:knowledge_entity" in scope_node_types

    # 4. Test agent_transcripts connector sync
    sync_res = await connectors.sync_connector("agent_transcripts", scope="shared", limit_per_source=3)
    assert sync_res["status"] == "synced"
    assert sync_res["connector"] == "agent_transcripts"


@pytest.mark.asyncio
async def test_image_scope_nodes_and_previews(tmp_path):
    from starlette.testclient import TestClient
    from super_cortex.api import create_app

    cfg = SuperCortexConfig(
        db_path=tmp_path / "img_test.db",
        supermemory_url="http://127.0.0.1:59999",
    )
    cortex = SuperCortex(cfg)
    connectors = SuperCortexConnectors(cortex)

    # 1. Create a mock repo directory with image and txt files
    mock_repo_dir = tmp_path / "mock-repo"
    mock_repo_dir.mkdir()
    assets_dir = mock_repo_dir / "assets"
    assets_dir.mkdir()

    # Create dummy PNG image bytes (1x1 transparent PNG)
    png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    logo_file = assets_dir / "logo.png"
    logo_file.write_bytes(png_bytes)

    # Test get_github_file_bytes resolution
    connectors._resolve_local_repo = lambda r: mock_repo_dir
    raw_b, fname = connectors.get_github_file_bytes("XibalbaTechSol/mock-repo", "assets/logo.png")
    assert raw_b == png_bytes
    assert fname == "logo.png"

    # Test ingest_github_complete_repo with image scope
    connectors.get_github_tree = lambda r: {"tree": ["assets/logo.png", "README.md", "SPEC.txt"]}
    connectors.get_github_file_content = lambda r, p: {
        "repo": r,
        "path": p,
        "filename": p.split("/")[-1],
        "content": "Sample content",
        "size": 14,
        "is_binary": p.endswith(".png"),
    }
    connectors.get_github_prs = lambda r, limit=20: {"prs": []}
    connectors.get_github_commits = lambda r, limit=30: []

    res = await connectors.ingest_github_complete_repo(repo="XibalbaTechSol/mock-repo", scope="shared", sync_files=True)
    assert res["status"] == "ingested"
    assert "github:XibalbaTechSol/mock-repo" in res["scopes"]

    # Verify images scope was registered
    scopes = cortex.list_scopes()
    scope_ids = [s["scope_id"] if isinstance(s, dict) else s.scope_id for s in scopes]
    assert "github:XibalbaTechSol/mock-repo:images" in scope_ids

    # Verify API graph includes the image node with distinct visual properties
    app = create_app(cfg)
    client = TestClient(app)

    # Test file preview endpoint serves raw image bytes
    preview_res = client.get(f"/api/connectors/file/preview?path={logo_file}")
    assert preview_res.status_code == 200
    assert preview_res.headers["content-type"] == "image/png"
    assert preview_res.content == png_bytes

    # Test graph endpoint includes image node
    g_res = client.get("/api/graph")
    assert g_res.status_code == 200
    g_data = g_res.json()
    img_nodes = [n for n in g_data["nodes"] if n.get("is_image")]
    assert len(img_nodes) >= 1
    img_node = img_nodes[0]
    assert img_node["category"] == "image"
    assert img_node["node_type"] == "image_media"
    assert img_node["color"] == 0xf43f5e
    assert img_node["has_attachment"] is True
    assert "preview_url" in img_node


