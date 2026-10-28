import type { ColorMode, Community, EntityType, GraphNode, GraphViewport } from "./types";
import rawSeed from "./seedGraph.json";

export const ENTITY_COLORS: Record<EntityType, string> = {
  PERSON: "#F43F5E",
  COMPANY: "#3B82F6",
  PRODUCT: "#F59E0B",
  TECHNOLOGY: "#10B981",
  REGULATION: "#A855F7",
  LOCATION: "#06B6D4",
  EVENT: "#EC4899",
  ORGANIZATION: "#6366F1",
};

export const ENTITY_LABELS: Record<EntityType, string> = {
  PERSON: "Person",
  COMPANY: "Company",
  PRODUCT: "Product",
  TECHNOLOGY: "Technology",
  REGULATION: "Regulation",
  LOCATION: "Location",
  EVENT: "Event",
  ORGANIZATION: "Organization",
};

export const COMMUNITY_PALETTE = [
  "#38BDF8",
  "#34D399",
  "#C084FC",
  "#FBBF24",
  "#F472B6",
  "#22D3EE",
  "#FB7185",
  "#818CF8",
];

/**
 * One ramp per source document. Every document gets its own colour family and the
 * node's community picks a distinct tint inside that family, so a single upload
 * still reads as several clusters instead of one flat colour.
 */
export const DOCUMENT_PALETTES: string[][] = [
  ["#22D3EE", "#38BDF8", "#60A5FA", "#2DD4BF", "#0EA5E9", "#818CF8"],
  ["#34D399", "#4ADE80", "#A3E635", "#10B981", "#22C55E", "#84CC16"],
  ["#FBBF24", "#F59E0B", "#FB923C", "#FCD34D", "#F97316", "#FACC15"],
  ["#F472B6", "#FB7185", "#F43F5E", "#EC4899", "#FDA4AF", "#E879F9"],
  ["#C084FC", "#A855F7", "#818CF8", "#D8B4FE", "#7C3AED", "#6366F1"],
  ["#5EEAD4", "#2DD4BF", "#14B8A6", "#99F6E4", "#0D9488", "#67E8F9"],
  ["#FDBA74", "#FB923C", "#F97316", "#FED7AA", "#EA580C", "#FCD34D"],
  ["#A5B4FC", "#818CF8", "#6366F1", "#C7D2FE", "#4F46E5", "#7DD3FC"],
];

export function hashString(value: string): number {
  let hash = 0;
  for (let index = 0; index < value.length; index += 1) {
    hash = (hash * 31 + value.charCodeAt(index)) | 0;
  }
  return Math.abs(hash);
}

function paletteFor(document: string, documents?: string[]): string[] {
  const index = documents?.indexOf(document) ?? -1;
  const family = index >= 0 ? index : hashString(document || "unknown");
  return DOCUMENT_PALETTES[((family % DOCUMENT_PALETTES.length) + DOCUMENT_PALETTES.length) % DOCUMENT_PALETTES.length];
}

/** Family swatch used by the legend: the document's primary colour. */
export function documentSwatch(document: string, documents?: string[]): string {
  return paletteFor(document, documents)[0];
}

export function nodeDocument(node: GraphNode): string {
  return node.documents?.[0] ?? "";
}

export function documentColor(
  node: Pick<GraphNode, "community_id" | "documents">,
  documents?: string[],
): string {
  const document = node.documents?.[0];
  if (!document) return "#94A3B8";
  const ramp = paletteFor(document, documents);
  const index = ((node.community_id % ramp.length) + ramp.length) % ramp.length;
  return ramp[index];
}

export function entityColor(type: EntityType): string {
  return ENTITY_COLORS[type] ?? "#94A3B8";
}

export function communityColor(communityId: number, communities: Community[]): string {
  const found = communities.find((community) => community.id === communityId);
  return found?.color ?? COMMUNITY_PALETTE[communityId % COMMUNITY_PALETTE.length];
}

export function centralityColor(value: number, max: number): string {
  if (max <= 0) return "#64748B";
  const ratio = Math.min(1, Math.max(0, value / max));
  if (ratio > 0.66) return "#F43F5E";
  if (ratio > 0.36) return "#F59E0B";
  if (ratio > 0.16) return "#38BDF8";
  return "#475569";
}

export function nodeColor(
  node: GraphNode,
  mode: ColorMode,
  communities: Community[],
  maxCentrality: number,
  documents?: string[],
): string {
  if (mode === "DOCUMENT") {
    const color = documentColor(node, documents);
    return color === "#94A3B8" ? entityColor(node.type) : color;
  }
  if (mode === "COMMUNITY") return communityColor(node.community_id, communities);
  if (mode === "CENTRALITY") return centralityColor(node.betweenness || node.pagerank, maxCentrality);
  return entityColor(node.type);
}

export function hexToRgba(hex: string, alpha: number): string {
  const normalized = hex.replace("#", "");
  const value =
    normalized.length === 3
      ? normalized
          .split("")
          .map((character) => character + character)
          .join("")
      : normalized;
  const bigint = Number.parseInt(value, 16);
  const r = (bigint >> 16) & 255;
  const g = (bigint >> 8) & 255;
  const b = bigint & 255;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

export function relativeLuminance(hex: string): number {
  const normalized = hex.replace("#", "");
  const r = Number.parseInt(normalized.slice(0, 2), 16) / 255;
  const g = Number.parseInt(normalized.slice(2, 4), 16) / 255;
  const b = Number.parseInt(normalized.slice(4, 6), 16) / 255;
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

interface SeedNode {
  id: string;
  name: string;
  type: EntityType;
  description: string;
  community_id: number;
  mention_count: number;
  year?: number;
}

interface SeedEdge {
  id: string;
  source: string;
  target: string;
  type: string;
  description: string;
  strength: number;
  date?: string;
  date_confidence?: string;
  source_doc?: string;
  source_chunk_id?: string;
  source_page?: number;
  status?: "ACTIVE" | "NEW" | "DISSOLVED";
}

interface SeedPayload {
  communities: Community[];
  nodes: SeedNode[];
  edges: SeedEdge[];
}

const seed = rawSeed as unknown as SeedPayload;

let cached: GraphViewport | null = null;

export function getDemoViewport(): GraphViewport {
  if (cached) return cached;

  const degree = new Map<string, number>();
  const weightedDegree = new Map<string, number>();
  for (const edge of seed.edges) {
    if (edge.status === "DISSOLVED") continue;
    for (const nodeId of [edge.source, edge.target]) {
      degree.set(nodeId, (degree.get(nodeId) ?? 0) + 1);
      weightedDegree.set(nodeId, (weightedDegree.get(nodeId) ?? 0) + edge.strength);
    }
  }
  const totalWeight = [...weightedDegree.values()].reduce((sum, value) => sum + value, 0) || 1;

  // The seed carries document names on edges only; tag the nodes the same way the
  // backend does so "colour by document" works without the API.
  const documentsByNode = new Map<string, string[]>();
  for (const edge of seed.edges) {
    if (!edge.source_doc) continue;
    for (const nodeId of [edge.source, edge.target]) {
      const list = documentsByNode.get(nodeId) ?? [];
      if (!list.includes(edge.source_doc)) list.push(edge.source_doc);
      documentsByNode.set(nodeId, list);
    }
  }
  const documents = [...new Set(seed.edges.map((edge) => edge.source_doc).filter(Boolean))] as string[];

  const nodes: GraphNode[] = seed.nodes.map((node) => ({
    ...node,
    aliases: [],
    documents: documentsByNode.get(node.id) ?? [],
    pagerank: (weightedDegree.get(node.id) ?? 0) / totalWeight,
    betweenness: (degree.get(node.id) ?? 0) / Math.max(1, seed.nodes.length),
    degree: degree.get(node.id) ?? 0,
    year: node.year ?? null,
  }));

  const edges = seed.edges.map((edge) => {
    const year = edge.date ? Number(edge.date.slice(0, 4)) : null;
    return {
      id: edge.id,
      source: edge.source,
      target: edge.target,
      type: edge.type,
      description: edge.description,
      strength: edge.strength,
      date: edge.date ?? null,
      date_confidence: edge.date_confidence ?? "unknown",
      source_doc: edge.source_doc ?? null,
      source_chunk_id: edge.source_chunk_id ?? null,
      source_page: edge.source_page ?? null,
      status: edge.status ?? "ACTIVE",
      year,
    } satisfies GraphViewport["edges"][number];
  });

  const typeCounts: Record<string, number> = {};
  for (const node of nodes) typeCounts[node.type] = (typeCounts[node.type] ?? 0) + 1;
  const documentCount = new Set(edges.map((edge) => edge.source_doc).filter(Boolean)).size;

  cached = {
    nodes,
    edges,
    communities: seed.communities,
    stats: {
      node_count: nodes.length,
      edge_count: edges.length,
      community_count: seed.communities.length,
      document_count: documentCount,
      entity_type_counts: typeCounts,
    },
    source: "demo",
    documents,
    generated_at: new Date().toISOString(),
  };
  return cached;
}
