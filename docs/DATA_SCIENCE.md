# Super-Cortex // Data Science, Graph ML & Reasoning Trajectory Hub

Super-Cortex provides native, zero-dependency data science interoperability, graph-theoretical quantitative analytics, and AI reasoning trajectory dataset exports for machine learning researchers and quantitative developers.

---

## 1. Direct Python SDK Methods

The `SuperCortex` client (`super_cortex.memory.SuperCortex`) converts the active 3D knowledge manifold directly into standard data science structures:

```python
from super_cortex.memory import SuperCortex

cortex = SuperCortex()

# 1. NetworkX Graph (DiGraph with node & edge attributes)
G = cortex.to_networkx(scope="shared")

# 2. Polars & Pandas DataFrames
nodes_df, edges_df = cortex.to_polars(scope="shared")
# or: nodes_df, edges_df = cortex.to_pandas(scope="shared")

# 3. PyTorch Geometric (PyG) Graph Tensor
pyg_data = cortex.to_pyg(scope="shared")
# Returns torch_geometric.data.Data(x=..., edge_index=..., y=...)

# 4. Quantitative Graph Theory & Spectral Analytics
scorecard = cortex.get_graph_analytics(scope="shared")
communities = cortex.get_communities(scope="shared")
spectral = cortex.get_spectral_properties(scope="shared")
pageranks = cortex.get_centrality(scope="shared", metric="pagerank")
betweenness = cortex.get_centrality(scope="shared", metric="betweenness")

# 5. AI Reasoning Trajectory Fine-Tuning Datasets
sft_dataset = cortex.export_sft_dataset(scope="shared")
dpo_pairs = cortex.export_dpo_dataset(scope="shared")
grpo_samples = cortex.export_grpo_dataset(scope="shared")

# 6. Dynamic Jupyter Notebook (.ipynb v4)
nb_dict = cortex.generate_jupyter_notebook(template="gnn", scope="shared")
```

---

## 2. REST API Endpoints

All endpoints support an optional `?scope=<scope>` filter (`all`, `shared`, or `agent:<id>`).

### Graph Structure & Data Science Exports
| Method | Endpoint | Format | Description |
|---|---|---|---|
| `GET` | `/api/export/networkx?format=json` | JSON | RFC-compliant Node-Link JSON for `networkx.node_link_graph(data, edges="links")`. |
| `GET` | `/api/export/networkx?format=graphml` | XML | Standard GraphML XML with typed node/edge attributes for **Gephi**, **Cytoscape**, and `igraph`. |
| `GET` | `/api/export/dataframe?table=nodes&format=csv` | CSV | Tabular node list with degrees, epistemic classes, scopes, and ISO timestamps. |
| `GET` | `/api/export/dataframe?table=edges&format=csv` | CSV | Tabular directed adjacency list with predicates, types, and confidence scores. |
| `GET` | `/api/export/pyg` | JSON | PyTorch Geometric specification: `num_nodes`, `num_edges`, `edge_index` (`[2, E]`), and class labels `y`. |
| `GET` | `/api/export/notebook?template=spectral\|gnn\|trajectories` | `.ipynb` | Dynamic Jupyter Notebook v4 pre-configured with active endpoints and code workflows. |

### Graph Theory & Quantitative Analytics
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/analytics/summary` | Executive topological scorecard: density, modularity $Q$, clustering coefficients, top PageRank hubs, and top betweenness bridges. |
| `GET` | `/api/analytics/communities` | Louvain-style greedy modularity maximization partitions with cluster sizes and hub nodes. |
| `GET` | `/api/analytics/centrality?metric=pagerank\|betweenness\|degree` | Ranked node centrality metrics. |
| `GET` | `/api/analytics/spectral` | Graph Laplacian eigenvalues, Fiedler algebraic connectivity ($\lambda_2$), and Fiedler vector coordinates. |

### AI Fine-Tuning & Reasoning Trajectory Hub
| Method | Endpoint | Format | Description |
|---|---|---|---|
| `GET` | `/api/export/trajectories?format=sft&as_jsonl=true` | JSONL | Supervised Fine-Tuning dataset in ChatML format containing chain-of-thought `thinking` traces and `tool_calls`. |
| `GET` | `/api/export/trajectories?format=dpo&as_jsonl=true` | JSONL | Direct Preference Optimization paired `{prompt, chosen, rejected, margin}` datasets scored via the AIS reward engine. |
| `GET` | `/api/export/trajectories?format=grpo&as_jsonl=true` | JSONL | Group Relative Policy Optimization (RLVR) samples with unit-test outcome verification flags. |

---

## 3. Pre-Packaged Jupyter Notebooks

Runnable notebooks are located in the [`notebooks/`](../notebooks/) directory:

1. **[`01_spectral_graph_analysis.ipynb`](../notebooks/01_spectral_graph_analysis.ipynb)**:
   - Connects to Super-Cortex REST API.
   - Computes Graph Laplacian $L = D - A$ spectrum.
   - Evaluates algebraic connectivity $\lambda_2$ and spectral gap.
   - Plots degree distribution and Louvain community partitions with NetworkX and Matplotlib.

2. **[`02_gnn_node_classification.ipynb`](../notebooks/02_gnn_node_classification.ipynb)**:
   - Ingests graph tensors (`edge_index`, `y`, `node_types`) into `torch_geometric.data.Data`.
   - Defines a 2-layer Graph Convolutional Network (`GCNConv`).
   - Executes 30 training epochs and tracks Cross-Entropy loss.
   - Visualizes learned node embeddings via t-SNE / PCA.

3. **[`03_reasoning_trajectory_analytics.ipynb`](../notebooks/03_reasoning_trajectory_analytics.ipynb)**:
   - Ingests SFT and DPO reasoning trajectories.
   - Analyzes reward margin distributions ($r_{\text{chosen}} - r_{\text{rejected}}$).
   - Generates summary statistics with Polars for fine-tuning readiness.

---

## 4. Fine-Tuning Pipeline Integration (Unsloth / Axolotl / TRL)

Stream DPO preference pairs directly into HuggingFace `datasets`:

```python
from datasets import load_dataset
import httpx

# Ingest DPO JSONL stream directly from Super-Cortex
url = "http://127.0.0.1:4174/api/export/trajectories?format=dpo&as_jsonl=true"
dataset = load_dataset("json", data_files={"train": url})

print(f"Loaded {len(dataset['train'])} DPO preference pairs")
print(dataset['train'][0])
```
