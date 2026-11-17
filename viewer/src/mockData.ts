import { GraphData, GraphNode, GraphLink } from './types';

// The exact memory from graph-view.webp
export const primaryMemoryNode: GraphNode = {
  id: 'mem_quantum_primary',
  label: 'Quantum computing is a paradigm shift...',
  type: 'memory-latest',
  status: 'new',
  space: '9c7w2SXLvSuk3hDh7b7dr4',
  version: 'v1',
  relevanceScore: 100,
  date: '24/08/2025',
  hash: '4aCa4oM8praVBCWdNksjxf',
  content:
    'Quantum computing is a paradigm shift in computational power, leveraging quantum mechanical phenomena like superposition and entanglement to solve problems intractable for classical computers.',
  clusterId: 'cluster_quantum',
};

export function generateInitialGraph(): GraphData {
  const nodes: GraphNode[] = [];
  const links: GraphLink[] = [];

  // Central Document for Cluster 1 (Quantum)
  const docQuantum: GraphNode = {
    id: 'doc_quantum_main',
    label: 'Quantum Physics & Computation Fundamentals',
    type: 'document',
    status: 'active',
    space: '9c7w2SXLvSuk3hDh7b7dr4',
    version: 'v1',
    relevanceScore: 100,
    date: '24/08/2025',
    hash: 'doc_9c7w2SX_qphysics',
    content: 'Full textbook chunk: Introduction to Quantum Superposition, Entanglement, and Quantum Logic Gates.',
    clusterId: 'cluster_quantum',
    radius: 28,
  };
  nodes.push(docQuantum);

  // Add the primary memory node
  nodes.push(primaryMemoryNode);
  links.push({
    source: docQuantum.id,
    target: primaryMemoryNode.id,
    type: 'doc-to-memory',
    strength: 'strong',
  });

  // Add 9 more satellite memories to cluster 1 around docQuantum
  const satelliteTexts = [
    'Superposition allows qubits to exist in a linear combination of |0⟩ and |1⟩ states simultaneously.',
    'Quantum entanglement creates instantaneous correlations between states across arbitrary physical distances.',
    'Shor algorithm provides polynomial-time integer factorization, breaking RSA cryptography.',
    'Grover search algorithm yields quadratic speedup O(√N) for unstructured database queries.',
    'Decoherence remains the primary physical engineering challenge for maintaining qubit coherence times.',
    'Quantum error correction relies on surface codes with topological fault tolerance thresholds.',
    'No-cloning theorem states an unknown arbitrary quantum state cannot be copied perfectly.',
    'Bell inequalities violation confirms non-local properties of entangled quantum systems.',
    'Adiabatic quantum computation is polynomially equivalent to the standard gate-based circuit model.',
  ];

  satelliteTexts.forEach((text, i) => {
    const id = `mem_quantum_${i + 1}`;
    nodes.push({
      id,
      label: text,
      type: i % 4 === 0 ? 'memory-older' : 'memory-latest',
      status: i === 3 ? 'expiring' : i === 6 ? 'forgotten' : 'new',
      space: '9c7w2SXLvSuk3hDh7b7dr4',
      version: `v${(i % 3) + 1}`,
      relevanceScore: Math.floor(95 - i * 3),
      date: '24/08/2025',
      hash: `hash_${i}aB${Math.random().toString(36).substring(2, 9)}`,
      content: text,
      clusterId: 'cluster_quantum',
      radius: 14,
    });
    links.push({
      source: docQuantum.id,
      target: id,
      type: 'doc-to-memory',
      strength: 'strong',
    });
  });

  // Cluster 2: Xibalba & Super-Cortex
  const docXibalba: GraphNode = {
    id: 'doc_xibalba_core',
    label: 'Xibalba Cortex Architecture Spec',
    type: 'document',
    status: 'active',
    space: 'xibalba',
    version: 'v2',
    relevanceScore: 98,
    date: '14/11/2026',
    hash: 'doc_xibalba_001',
    content: 'Xibalba Cortex Specification: Provenance-aware graph memory and append-only hash chains.',
    clusterId: 'cluster_xibalba',
    radius: 28,
  };
  nodes.push(docXibalba);

  const xibalbaMemories = [
    'Super-Cortex integrates Supermemory Local (port 6767) as its neural embedding and semantic search substrate.',
    'All state transitions are chained using SHA-256 prior_hash -> event_hash cryptographic integrity.',
    'Domain-separated Merkle roots guarantee tamper-evident verification across agent sessions.',
    'Directed entity graph maps subject-predicate-object relations with confidence metrics.',
    'Recalled memories are strictly bounded as untrusted reference evidence.',
  ];

  xibalbaMemories.forEach((text, idx) => {
    const id = `mem_xibalba_${idx + 1}`;
    nodes.push({
      id,
      label: text,
      type: 'memory-latest',
      status: 'new',
      space: 'xibalba',
      version: 'v1',
      relevanceScore: 99 - idx,
      date: '14/11/2026',
      hash: `hash_xib_${idx}_${Math.random().toString(36).substring(2, 8)}`,
      content: text,
      clusterId: 'cluster_xibalba',
      radius: 14,
    });
    links.push({
      source: docXibalba.id,
      target: id,
      type: 'doc-to-memory',
      strength: 'strong',
    });
  });

  // Version chain linking quantum to xibalba
  links.push({
    source: docQuantum.id,
    target: docXibalba.id,
    type: 'version-chain',
    strength: 'strong',
  });

  // Cluster 3 & 4 (Distant Constellations from readme-memory-graph.webp)
  for (let c = 1; c <= 3; c++) {
    const clusterDoc: GraphNode = {
      id: `doc_constellation_${c}`,
      label: `Knowledge Base Cluster ${c}`,
      type: 'document',
      status: 'active',
      space: `space_const_${c}`,
      version: 'v1',
      relevanceScore: 85,
      date: '12/10/2025',
      hash: `doc_hash_${c}`,
      content: `Distant cluster ${c} containing archival memory contexts and vector embeddings.`,
      clusterId: `cluster_c${c}`,
      radius: 22,
    };
    nodes.push(clusterDoc);

    // Similarity link to previous
    links.push({
      source: c === 1 ? docQuantum.id : `doc_constellation_${c - 1}`,
      target: clusterDoc.id,
      type: 'doc-similarity',
      strength: 'weak',
    });

    for (let k = 0; k < 6; k++) {
      const satId = `mem_c${c}_${k}`;
      nodes.push({
        id: satId,
        label: `Archival context ${c}-${k}`,
        type: k % 2 === 0 ? 'memory-latest' : 'memory-older',
        status: 'active',
        space: `space_const_${c}`,
        version: 'v1',
        relevanceScore: 80 + k,
        date: '12/10/2025',
        hash: `sat_hash_${c}_${k}`,
        content: `Synthetic memory embedding context for node ${c}-${k}.`,
        clusterId: `cluster_c${c}`,
        radius: 12,
      });
      links.push({
        source: clusterDoc.id,
        target: satId,
        type: 'doc-to-memory',
        strength: 'strong',
      });
    }
  }

  return { nodes, links };
}
