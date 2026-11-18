# Super-Cortex Specification (v1.0)

## 1. System Architecture

Super-Cortex is a hybrid memory architecture designed for autonomous agents, combining high-throughput local neural indexing with deterministic cryptographic auditability.

```
+--------------------------------------------------------------------+
|                         Agent Runtimes                             |
|       (Hermes Agent, Claude Code, Antigravity, Open Interpreter)   |
+---------------------------------+----------------------------------+
                                  | MCP Protocol (stdio / SSE)
                                  v
+--------------------------------------------------------------------+
|                         Super-Cortex                               |
|                                                                    |
|   +------------------------------------------------------------+   |
|   |                  FastMCP / MCPServer Layer                 |   |
|   +-----------------------------+------------------------------+   |
|                                 |                                  |
|                 +---------------+---------------+                  |
|                 v                               v                  |
|   +---------------------------+   +----------------------------+   |
|   | Provenance Ledger & Graph |   | Supermemory Async Client   |   |
|   | - Append-only Event Chain |   | - Local Neural Embeddings  |   |
|   | - Session Merkle Roots    |   | - Namespace Routing        |   |
|   | - Epistemic State Machine |   | - Profile Synthesis        |   |
|   | - SQLite Storage Engine   |   | - Cosine Similarity Search |   |
|   +---------------------------+   +----------------------------+   |
+--------------------------------------------------------------------+
              |                                   |
              v                                   v
   ~/.super-cortex/provenance.db         http://127.0.0.1:6767
   (Deterministic SQLite)             (Supermemory Local Daemon)
```

The memory backend is whatever `SUPERMEMORY_URL` names: the SuperCortex engine (`super_cortex.engine`, default `127.0.0.1:6768`; see [docs/ENGINE.md](docs/ENGINE.md)) or Supermemory Local (`127.0.0.1:6767`). Both serve the same API. Learned memories in the engine are classed as metadata derived from content, and each carries a verbatim quote from its source, a kind, and a certainty-derived confidence.

## 2. Cryptographic Ledger Contract

### 2.1 Event Hash Chain
Every memory mutation emits an immutable `EventRecord`:
$$E_i = (\text{id}_i, H_{i-1}, H_i, \text{actor}, \text{transition}, t_i, P_i)$$
Where:
- $H_0 = 0^{64}$ (Genesis Hash)
- $P_i$ is the canonical JSON string of the transition payload (sorted keys, no extraneous whitespace)
- $H_i = \text{SHA256}(H_{i-1} \parallel t_i \parallel \text{actor} \parallel \text{transition} \parallel P_i)$

### 2.2 Session Merkle Roots
For any interaction session $S$ with $N$ exchange turns:
- Each exchange computes turn hash $T_k = \text{SHA256}(T_{k-1} \parallel \text{session\_id} \parallel H(\text{prompt}) \parallel H(\text{response}) \parallel \text{tools} \parallel \text{context} \parallel t_k)$
- Leaves $L = [T_1, T_2, \dots, T_N]$ form a binary Merkle tree yielding root $M(S)$.

## 3. Epistemic Classification

All stored memories carry an explicit epistemic class:
- **`fact`**: Empirically verified or ground-truth assertion.
- **`inference`**: Derived or reasoned output from LLM analysis.
- **`assumption`**: Operating premise with unverified truth value.
- **`belief`**: Prior confidence state subject to Bayesian update.
- **`goal`**: Desired future state or execution directive.
- **`observation`**: Sensor or runtime telemetry observation.
- **`rule`**: Binding policy or behavioral constraint.

## 4. Lifecycle Transitions

State transitions are strictly auditable:
- `active` $\rightarrow$ `superseded`: Memory replaced by newer assertion.
- `active` $\rightarrow$ `contradicted`: Memory proven invalid by conflicting evidence.
- `active` $\rightarrow$ `quarantined`: Memory isolated pending integrity verification.
- `active` $\rightarrow$ `forgotten`: Memory deleted from semantic index; preserved in provenance ledger.
