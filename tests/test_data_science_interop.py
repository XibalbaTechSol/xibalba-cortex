"""
Tests for Data Science & Quantitative Modeling Interoperability Engine.
Verifies GraphML XML, NetworkX node-link, CSV dataframes, and PyG tensor exports.
"""

import json
import xml.etree.ElementTree as ET
import pytest
from starlette.testclient import TestClient

from super_cortex.api import create_app
from super_cortex.config import SuperCortexConfig
from super_cortex.data_science import (
    export_graphml_xml,
    export_networkx_json,
    export_pyg_specification,
    export_tabular_csv,
    extract_graph_components,
)
from super_cortex.memory import SuperCortex


@pytest.fixture
def ds_cortex(tmp_path):
    db_file = tmp_path / "test_ds_interop.db"
    cfg = SuperCortexConfig(db_path=str(db_file))
    cortex = SuperCortex(config=cfg)

    # Scopes & Agents
    cortex.create_scope("shared", "Shared Memory Fabric", "shared")
    cortex.create_scope("agent:quant", "Quant Research Scope", "single_agent")
    cortex.register_agent("quant", "Hermes Quant", "hermes", "agent:quant")

    # Entities & Relations
    cortex.store.add_entity("StationaryDistribution")
    cortex.store.add_entity("MarkovTransitionMatrix")
    cortex.store.add_relation("MarkovTransitionMatrix", "converges_to", "StationaryDistribution", confidence=0.99)

    # Memories
    with cortex.store._get_conn() as conn:
        conn.execute(
            """
            INSERT INTO memories (id, source_id, text, epistemic_class, lifecycle_status, content_hash, namespace, metadata_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
            """,
            (
                "mem_test_pid",
                "quant:pid:rule",
                "PID control parameters set to Kp=1.85, Ki=0.22, Kd=0.08 for dynamic grid rebalancing.",
                "rule",
                "active",
                "0xPID12345",
                "agent:quant",
                json.dumps({"scope": "agent:quant", "category": "trading"}),
            ),
        )
        conn.commit()

    # Exchange with thought and tool call
    cortex.record_exchange(
        session_id="sess_quant_analysis",
        prompt_text="Compute Value-at-Risk across portfolios",
        response_text="VaR computed at 99% confidence interval.",
        thinking_text="Applying historical simulation and parametric Gaussian distribution to calculate 1-day 99% VaR.",
        tool_calls=[{"name": "compute_var", "args": {"confidence": 0.99, "horizon": 1}}],
        actor="did:integrity:quant-modeler",
    )

    return cortex


def test_extract_graph_components(ds_cortex):
    nodes, edges = extract_graph_components(ds_cortex.store)
    assert len(nodes) >= 4  # hub_shared, hub_agent_quant, entities, memory, thought, action
    assert len(edges) >= 3

    # Check node structure
    n_map = {n["id"]: n for n in nodes}
    assert "hub_shared" in n_map
    assert "hub_agent_quant" in n_map
    assert "StationaryDistribution" in n_map

    # Check that degrees are computed
    assert any(n["degree"] > 0 for n in nodes)


def test_export_networkx_json(ds_cortex):
    data = export_networkx_json(ds_cortex.store)
    assert data["directed"] is True
    assert "nodes" in data
    assert "links" in data
    assert len(data["nodes"]) >= 4
    assert len(data["links"]) >= 3

    # Verify links have source, target, predicate, confidence
    for l in data["links"]:
        assert "source" in l
        assert "target" in l
        assert "predicate" in l


def test_export_graphml_xml(ds_cortex):
    xml_str = export_graphml_xml(ds_cortex.store)
    assert xml_str.startswith("<?xml")
    assert "<graphml" in xml_str
    assert "</graphml>" in xml_str

    # Parse XML to verify valid schema
    root = ET.fromstring(xml_str)
    assert "graphml" in root.tag
    nodes = root.findall(".//{http://graphml.graphdrawing.org/xmlns}node")
    edges = root.findall(".//{http://graphml.graphdrawing.org/xmlns}edge")
    assert len(nodes) >= 4
    assert len(edges) >= 3


def test_export_tabular_csv(ds_cortex):
    # 1. Nodes table CSV
    nodes_csv = export_tabular_csv(ds_cortex.store, table="nodes")
    lines = nodes_csv.strip().split("\n")
    header = lines[0].split(",")
    assert "id" in header
    assert "type" in header
    assert "degree" in header
    assert len(lines) >= 5

    # 2. Edges table CSV
    edges_csv = export_tabular_csv(ds_cortex.store, table="edges")
    e_lines = edges_csv.strip().split("\n")
    e_header = e_lines[0].split(",")
    assert "source" in e_header
    assert "target" in e_header
    assert "predicate" in e_header
    assert len(e_lines) >= 4


def test_export_pyg_specification(ds_cortex):
    pyg_spec = export_pyg_specification(ds_cortex.store)
    assert "num_nodes" in pyg_spec
    assert "num_edges" in pyg_spec
    assert "edge_index" in pyg_spec
    assert "y" in pyg_spec
    assert len(pyg_spec["edge_index"]) == 2  # [src_indices, dst_indices]
    assert len(pyg_spec["edge_index"][0]) == pyg_spec["num_edges"]
    assert len(pyg_spec["edge_index"][1]) == pyg_spec["num_edges"]
    assert len(pyg_spec["y"]) == pyg_spec["num_nodes"]


def test_cortex_python_sdk_methods(ds_cortex):
    # Test to_networkx returns valid node-link dict or DiGraph
    nx_obj = ds_cortex.to_networkx()
    assert isinstance(nx_obj, dict) or hasattr(nx_obj, "nodes")

    # Test to_pandas / to_polars returns tuple (nodes, edges)
    nodes_res, edges_res = ds_cortex.to_pandas()
    assert len(nodes_res) >= 4
    assert len(edges_res) >= 3

    pl_nodes, pl_edges = ds_cortex.to_polars()
    assert len(pl_nodes) >= 4
    assert len(pl_edges) >= 3

    # Test to_pyg returns spec dict
    pyg_res = ds_cortex.to_pyg()
    assert "edge_index" in pyg_res or hasattr(pyg_res, "edge_index")


def test_http_export_endpoints(ds_cortex):
    app = create_app(config=ds_cortex.config)
    client = TestClient(app)

    # 1. /api/export/networkx (json)
    res_nx_json = client.get("/api/export/networkx?format=json")
    assert res_nx_json.status_code == 200
    assert "nodes" in res_nx_json.json()

    # 2. /api/export/networkx (graphml)
    res_nx_xml = client.get("/api/export/networkx?format=graphml")
    assert res_nx_xml.status_code == 200
    assert res_nx_xml.headers["content-type"].startswith("application/xml")
    assert "<graphml" in res_nx_xml.text

    # 3. /api/export/dataframe (nodes csv)
    res_df_nodes_csv = client.get("/api/export/dataframe?table=nodes&format=csv")
    assert res_df_nodes_csv.status_code == 200
    assert "text/csv" in res_df_nodes_csv.headers["content-type"]
    assert "id,title" in res_df_nodes_csv.text

    # 4. /api/export/dataframe (edges csv)
    res_df_edges_csv = client.get("/api/export/dataframe?table=edges&format=csv")
    assert res_df_edges_csv.status_code == 200
    assert "source,target" in res_df_edges_csv.text

    # 5. /api/export/pyg (tensor spec)
    res_pyg = client.get("/api/export/pyg")
    assert res_pyg.status_code == 200
    pyg_data = res_pyg.json()
    assert "edge_index" in pyg_data
    assert len(pyg_data["edge_index"]) == 2
