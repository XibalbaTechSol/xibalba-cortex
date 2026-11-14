export type NodeType = 'document' | 'memory-latest' | 'memory-older';
export type NodeStatus = 'active' | 'forgotten' | 'expiring' | 'new';
export type LinkType = 'doc-to-memory' | 'doc-similarity' | 'version-chain';

export interface GraphNode {
  id: string;
  label: string;
  type: NodeType;
  status: NodeStatus;
  space: string;
  version: string;
  relevanceScore: number;
  date: string;
  hash: string;
  content: string;
  x?: number;
  y?: number;
  vx?: number;
  vy?: number;
  clusterId?: string;
  radius?: number;
}

export interface GraphLink {
  source: string | GraphNode;
  target: string | GraphNode;
  type: LinkType;
  strength?: 'weak' | 'strong';
}

export interface GraphData {
  nodes: GraphNode[];
  links: GraphLink[];
}
