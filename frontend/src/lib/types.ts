export type EntityType =
  | "PERSON"
  | "COMPANY"
  | "PRODUCT"
  | "TECHNOLOGY"
  | "LOCATION"
  | "REGULATION"
  | "EVENT"
  | "ORGANIZATION";

export type QueryMode = "CONNECTION" | "IMPACT" | "TEMPORAL" | "GLOBAL" | "ENTITY";
export type ColorMode = "DOCUMENT" | "TYPE" | "COMMUNITY" | "CENTRALITY";
export type DrawerTab = "story" | "impact" | "sources";

export interface GraphNode {
  id: string;
  name: string;
  type: EntityType;
  description: string;
  community_id: number;
  mention_count: number;
  pagerank: number;
  betweenness: number;
  degree: number;
  year?: number | null;
  aliases: string[];
  documents?: string[];
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  type: string;
  description: string;
  strength: number;
  date?: string | null;
  date_confidence?: string;
  source_doc?: string | null;
  source_chunk_id?: string | null;
  source_page?: number | null;
  status: "ACTIVE" | "NEW" | "DISSOLVED";
  year?: number | null;
}

export interface Community {
  id: number;
  name: string;
  color: string;
  summary: string;
}

export interface GraphStats {
  node_count: number;
  edge_count: number;
  community_count: number;
  document_count: number;
  entity_type_counts: Record<string, number>;
}

export interface GraphViewport {
  nodes: GraphNode[];
  edges: GraphEdge[];
  communities: Community[];
  stats: GraphStats;
  source: string;
  documents?: string[];
  generated_at?: string | null;
}

export interface EntitySearchResult {
  id: string;
  name: string;
  type: EntityType;
  description: string;
}

export interface Citation {
  edge_id: string;
  label: string;
  document: string;
  page?: number | null;
  chunk_id?: string | null;
  date?: string | null;
  cosine_similarity?: number | null;
}

export interface QueryContextEvent {
  type: string;
  query: string;
  mode: QueryMode;
  seed_node_ids: string[];
  highlighted_node_ids: string[];
  highlighted_edge_ids: string[];
  path_node_ids: string[];
  path_edge_ids: string[];
  scores: Record<string, number>;
  explanation: string;
  elapsed_ms: number;
  confidence: number;
}

export interface QueryCompleteEvent {
  type: string;
  citations: Citation[];
  confidence: number;
  duration_ms: number;
  mode: QueryMode;
}

export interface QueryMeta {
  mode: QueryMode;
  elapsedMs: number;
  explanation: string;
  seedNames: string[];
  pathHops: number;
}

export interface OrphanedNode {
  id: string;
  name: string;
  type: string;
  previous_degree: number;
}

export interface CentralitySurge {
  id: string;
  name: string;
  type: string;
  baseline: number;
  projected: number;
  delta_pct: number;
}

export interface SeveredEdge {
  id: string;
  source: string;
  target: string;
  type: string;
}

export interface ImpactResult {
  removed_node: { id: string; name: string; type: string };
  severity: "LOW" | "MODERATE" | "HIGH" | "CRITICAL";
  risk_score: number;
  disruption_ratio: number;
  component_count_before: number;
  component_count_after: number;
  largest_component_ratio_after: number;
  directly_disrupted: { id: string; name: string; type: string }[];
  orphaned: OrphanedNode[];
  centrality_surge: CentralitySurge[];
  severed_edges: SeveredEdge[];
  duration_ms: number;
}

export type JobStatus =
  | "QUEUED"
  | "PARSING"
  | "CHUNKING"
  | "EXTRACTING"
  | "RESOLVING"
  | "INDEXING"
  | "CLUSTERING"
  | "COMPLETED"
  | "FAILED";

export interface JobProgress {
  job_id: string;
  filename: string;
  status: JobStatus;
  stage: string;
  stage_index: number;
  percent: number;
  total_chunks: number;
  processed_chunks: number;
  entities_extracted: number;
  relationships_extracted: number;
  node_count?: number;
  edge_count?: number;
  community_count?: number;
  document_count?: number;
  nodes_added?: number;
  edges_added?: number;
  counts_by_type?: Record<string, number>;
  error_message?: string | null;
  created_at?: string;
  completed_at?: string | null;
}

export interface UploadResponse {
  job_id: string;
  filename: string;
  size_bytes: number;
  status: JobStatus;
  dispatch: string;
  status_url: string;
  stream_url: string;
}
