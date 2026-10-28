/**
 * Offline (demo) query engine.
 *
 * Mirrors the backend contracts closely enough that the UI behaves identically when
 * the FastAPI service is not running: intent heuristics, BFS path finding, cascade
 * simulation and grounded narrative with citation anchors. The header explicitly
 * labels the workspace as "demo data" whenever this engine is used.
 */

import type {
  Citation,
  GraphEdge,
  GraphNode,
  GraphViewport,
  ImpactResult,
  QueryCompleteEvent,
  QueryContextEvent,
  QueryMode,
} from "./types";

const VERBS: Record<string, string> = {
  CEO_OF: "serves as chief executive of",
  DEVELOPED: "developed",
  INVESTED_IN: "invested in",
  ACQUIRED: "acquired",
  SUPPLIES: "supplies",
  REGULATES: "regulates",
  REGULATED_BY: "is regulated by",
  PARTNERED_WITH: "partnered with",
  COMPETES_WITH: "competes with",
  FOUNDED: "founded",
  PUBLISHED: "published",
  OWNS: "owns",
  HOSTS: "hosts",
  USES: "uses",
  BUILT_ON: "is built on",
  TRAINED: "was used to train",
  MANUFACTURES: "manufactures",
  RESTRICTS: "restricts",
  EVALUATES: "evaluates",
  INVESTIGATES: "investigates",
  ALTERNATIVE_TO: "is an alternative to",
  REFERENCES: "references",
  SUSPENDED: "suspended",
};

interface LocalQueryInput {
  query: string;
  mode?: QueryMode | null;
  timeRange: [number, number];
  viewport: GraphViewport;
}

export function detectMode(query: string): QueryMode {
  const q = query.toLowerCase();
  if (/(what happens if|impact|cascade|ceases|disruption|shuts? down|goes? bankrupt|risk if|sever)/.test(q)) {
    return "IMPACT";
  }
  if (/(timeline|over time|history|evolv|progression|between \d{4} and \d{4}|\b(19|20)\d{2}\b|when did)/.test(q)) {
    return "TEMPORAL";
  }
  if (/(connect|relationship|related|path|linked|route|chain|how does .* to )/.test(q)) {
    return "CONNECTION";
  }
  return "GLOBAL";
}

function activeEdges(edges: GraphEdge[], maxYear: number): GraphEdge[] {
  return edges.filter((edge) => edge.status !== "DISSOLVED" && (edge.year == null || edge.year <= maxYear));
}

function findSeeds(query: string, nodes: GraphNode[]): GraphNode[] {
  const lowered = query.toLowerCase();
  const hits: { position: number; node: GraphNode }[] = [];
  for (const node of nodes) {
    const names = [node.name, ...node.aliases];
    for (const name of names) {
      const needle = name.toLowerCase();
      if (needle.length < 2) continue;
      const position = lowered.indexOf(needle);
      if (position >= 0) {
        hits.push({ position, node });
        break;
      }
    }
  }
  hits.sort((a, b) => a.position - b.position);
  const seen = new Set<string>();
  return hits
    .filter(({ node }) => {
      if (seen.has(node.id)) return false;
      seen.add(node.id);
      return true;
    })
    .slice(0, 4)
    .map(({ node }) => node);
}

function shortestPath(
  edges: GraphEdge[],
  sourceId: string,
  targetId: string,
  maxHops = 5,
): { nodeIds: string[]; edgeIds: string[] } | null {
  if (sourceId === targetId) return { nodeIds: [sourceId], edgeIds: [] };
  const adjacency = new Map<string, { id: string; edge: GraphEdge }[]>();
  for (const edge of edges) {
    if (!adjacency.has(edge.source)) adjacency.set(edge.source, []);
    if (!adjacency.has(edge.target)) adjacency.set(edge.target, []);
    adjacency.get(edge.source)!.push({ id: edge.target, edge });
    adjacency.get(edge.target)!.push({ id: edge.source, edge });
  }
  const queue: { id: string; nodes: string[]; edges: string[] }[] = [
    { id: sourceId, nodes: [sourceId], edges: [] },
  ];
  const visited = new Set([sourceId]);
  while (queue.length) {
    const current = queue.shift()!;
    if (current.edges.length >= maxHops) continue;
    for (const neighbour of adjacency.get(current.id) ?? []) {
      if (visited.has(neighbour.id)) continue;
      const nodes = [...current.nodes, neighbour.id];
      const edgesPath = [...current.edges, neighbour.edge.id];
      if (neighbour.id === targetId) return { nodeIds: nodes, edgeIds: edgesPath };
      visited.add(neighbour.id);
      queue.push({ id: neighbour.id, nodes, edges: edgesPath });
    }
  }
  return null;
}

function simulateLocalImpact(viewport: GraphViewport, nodeId: string): ImpactResult {
  const started = performance.now();
  const nodeMap = new Map(viewport.nodes.map((node) => [node.id, node]));
  const target = nodeMap.get(nodeId);
  if (!target) throw new Error(`Unknown entity: ${nodeId}`);

  const adjacency = new Map<string, { id: string; edge: GraphEdge }[]>();
  for (const node of viewport.nodes) adjacency.set(node.id, []);
  for (const edge of viewport.edges) {
    if (edge.status === "DISSOLVED") continue;
    adjacency.get(edge.source)?.push({ id: edge.target, edge });
    adjacency.get(edge.target)?.push({ id: edge.source, edge });
  }

  const neighbours = (adjacency.get(nodeId) ?? []).map((entry) => entry.id);
  const severed = viewport.edges.filter(
    (edge) => edge.status !== "DISSOLVED" && (edge.source === nodeId || edge.target === nodeId),
  );
  const baselineComponents = countComponents(viewport.nodes.map((node) => node.id), adjacency);
  const baselineDegree = new Map<string, number>();
  for (const [id, list] of adjacency) baselineDegree.set(id, list.length);

  // Remove the node.
  adjacency.delete(nodeId);
  for (const list of adjacency.values()) {
    for (let index = list.length - 1; index >= 0; index -= 1) {
      if (list[index].id === nodeId) list.splice(index, 1);
    }
  }

  const remaining = viewport.nodes.filter((node) => node.id !== nodeId).map((node) => node.id);
  const sizes = componentSizes(remaining, adjacency);
  const total = Math.max(1, remaining.length);
  const largest = sizes[0] ?? 0;
  const isolated = remaining.filter((id) => (adjacency.get(id) ?? []).length === 0).length;
  const disruptionRatio = 1 - largest / total;
  const risk = Math.min(1, disruptionRatio * 0.7 + (isolated / total) * 0.3);
  const severity: ImpactResult["severity"] =
    risk >= 0.55 ? "CRITICAL" : risk >= 0.3 ? "HIGH" : risk >= 0.12 ? "MODERATE" : "LOW";

  const orphaned = neighbours
    .filter((id) => (adjacency.get(id) ?? []).length === 0)
    .map((id) => {
      const node = nodeMap.get(id);
      return {
        id,
        name: node?.name ?? id,
        type: node?.type ?? "UNKNOWN",
        previous_degree: 1,
      };
    });

  const surges = remaining
    .map((id) => {
      const baseline = (baselineDegree.get(id) ?? 0) / Math.max(1, viewport.nodes.length);
      const projected = (adjacency.get(id) ?? []).length / Math.max(1, remaining.length);
      const delta = baseline > 0 ? ((projected - baseline) / baseline) * 100 : projected > 0 ? 100 : 0;
      const node = nodeMap.get(id);
      return {
        id,
        name: node?.name ?? id,
        type: node?.type ?? "UNKNOWN",
        baseline: Number(baseline.toFixed(4)),
        projected: Number(projected.toFixed(4)),
        delta_pct: Number(delta.toFixed(1)),
      };
    })
    .filter((surge) => surge.delta_pct > 0)
    .sort((a, b) => b.delta_pct - a.delta_pct)
    .slice(0, 5);

  return {
    removed_node: { id: target.id, name: target.name, type: target.type },
    severity,
    risk_score: Number(risk.toFixed(4)),
    disruption_ratio: Number(disruptionRatio.toFixed(4)),
    component_count_before: baselineComponents,
    component_count_after: sizes.length,
    largest_component_ratio_after: Number((largest / total).toFixed(4)),
    directly_disrupted: neighbours.map((id) => {
      const node = nodeMap.get(id);
      return { id, name: node?.name ?? id, type: node?.type ?? "UNKNOWN" };
    }),
    orphaned,
    centrality_surge: surges,
    severed_edges: severed.map((edge) => ({
      id: edge.id,
      source: nodeMap.get(edge.source)?.name ?? edge.source,
      target: nodeMap.get(edge.target)?.name ?? edge.target,
      type: edge.type,
    })),
    duration_ms: Number((performance.now() - started).toFixed(2)),
  };
}

function countComponents(nodeIds: string[], adjacency: Map<string, { id: string }[]>): number {
  return componentSizes(nodeIds, adjacency).length;
}

function componentSizes(nodeIds: string[], adjacency: Map<string, { id: string }[]>): number[] {
  const seen = new Set<string>();
  const sizes: number[] = [];
  for (const id of nodeIds) {
    if (seen.has(id)) continue;
    let size = 0;
    const stack = [id];
    seen.add(id);
    while (stack.length) {
      const current = stack.pop()!;
      size += 1;
      for (const neighbour of adjacency.get(current) ?? []) {
        if (!seen.has(neighbour.id) && adjacency.has(neighbour.id)) {
          seen.add(neighbour.id);
          stack.push(neighbour.id);
        }
      }
    }
    sizes.push(size);
  }
  return sizes.sort((a, b) => b - a);
}

function verb(edge: GraphEdge): string {
  return VERBS[edge.type] ?? `is linked via ${edge.type.toLowerCase().replace(/_/g, " ")}`;
}

function dateSuffix(edge: GraphEdge): string {
  return edge.year ? ` (${edge.year})` : "";
}

function buildNarrative(
  mode: QueryMode,
  query: string,
  viewport: GraphViewport,
  seeds: GraphNode[],
  path: { nodeIds: string[]; edgeIds: string[] } | null,
  impact: ImpactResult | null,
  year: number,
  highlightedEdges: GraphEdge[],
): string {
  const nodeMap = new Map(viewport.nodes.map((node) => [node.id, node]));
  const edgeMap = new Map(viewport.edges.map((edge) => [edge.id, edge]));

  if (mode === "CONNECTION") {
    if (path && path.edgeIds.length > 0) {
      const start = nodeMap.get(path.nodeIds[0]);
      const end = nodeMap.get(path.nodeIds[path.nodeIds.length - 1]);
      const lines = [
        `**${start?.name ?? path.nodeIds[0]}** reaches **${end?.name ?? path.nodeIds[path.nodeIds.length - 1]}** through a **${path.edgeIds.length}-hop verified route** in the knowledge graph.\n`,
      ];
      path.edgeIds.forEach((edgeId, index) => {
        const edge = edgeMap.get(edgeId);
        if (!edge) return;
        const source = nodeMap.get(path.nodeIds[index]);
        const target = nodeMap.get(path.nodeIds[index + 1]);
        lines.push(
          `- **${source?.name ?? edge.source}** ${verb(edge)} **${target?.name ?? edge.target}**${dateSuffix(edge)}. ${edge.description} [[${edge.id}]]`,
        );
      });
      const strongest = path.edgeIds
        .map((edgeId) => edgeMap.get(edgeId))
        .filter((edge): edge is GraphEdge => Boolean(edge))
        .sort((a, b) => b.strength - a.strength)[0];
      if (strongest) {
        const source = nodeMap.get(strongest.source);
        const target = nodeMap.get(strongest.target);
        lines.push(
          `\nThe strongest link is **${source?.name ?? strongest.source} → ${target?.name ?? strongest.target}** (${strongest.type}, strength ${strongest.strength}/10), supported by \`${strongest.source_doc ?? "the source corpus"}\`${strongest.source_page ? `, page ${strongest.source_page}` : ""}.`,
        );
      }
      return lines.join("\n");
    }
    const seed = seeds[0];
    if (!seed) {
      return "No entity in the graph matched this query strongly enough to anchor a path. Try an `@Entity` mention or ask about a specific organization, model or regulation.";
    }
    const neighbours = viewport.edges
      .filter((edge) => edge.status !== "DISSOLVED" && (edge.source === seed.id || edge.target === seed.id))
      .sort((a, b) => b.strength - a.strength)
      .slice(0, 6);
    const lines = [
      `No complete route was found within 5 hops. **${seed.name}** sits in a cluster with ${neighbours.length} direct relationship(s).\n`,
    ];
    for (const edge of neighbours) {
      const other = nodeMap.get(edge.source === seed.id ? edge.target : edge.source);
      lines.push(
        `- **${seed.name}** ${verb(edge)} **${other?.name ?? "another entity"}**${dateSuffix(edge)}. ${edge.description} [[${edge.id}]]`,
      );
    }
    return lines.join("\n");
  }

  if (mode === "IMPACT") {
    if (!impact) {
      return "Impact simulation did not return a result. Select an entity on the canvas and try again.";
    }
    const lines = [
      `Severing **${impact.removed_node.name}** produces **${impact.severity}** structural risk (${Math.round(impact.risk_score * 100)}/100) across ${impact.directly_disrupted.length} direct ${impact.directly_disrupted.length === 1 ? "dependency" : "dependencies"}.\n`,
      `${impact.severed_edges.length} relationship(s) are severed and the connected-component count moves from ${impact.component_count_before} to ${impact.component_count_after}.`,
    ];
    if (impact.orphaned.length) {
      lines.push(`\n**Orphaned entities (degree → 0):** ${impact.orphaned.map((node) => node.name).join(", ")}. These nodes lose every grounded link and would drop out of retrieval until reconnected.`);
    } else {
      lines.push("\nNo neighbour is fully orphaned: every dependent retains at least one alternative path, which limits cascade depth.");
    }
    if (impact.centrality_surge.length) {
      lines.push("\n**Centrality surge among surviving hubs:**");
      for (const surge of impact.centrality_surge.slice(0, 4)) {
        lines.push(`- **${surge.name}** absorbs +${Math.round(surge.delta_pct)}% centrality (${surge.baseline} → ${surge.projected}).`);
      }
    }
    lines.push(
      `\nLargest remaining component holds ${Math.round(impact.largest_component_ratio_after * 100)}% of nodes; disruption ratio is ${Math.round(impact.disruption_ratio * 100)}%. Simulation completed in ${impact.duration_ms.toFixed(1)} ms without touching the database.`,
    );
    return lines.join("\n");
  }

  if (mode === "TEMPORAL") {
    const visible = viewport.edges.filter((edge) => edge.status !== "DISSOLVED" && (edge.year == null || edge.year <= year));
    const introduced = viewport.edges.filter((edge) => edge.year === year);
    const lines = [
      `At the **${year}** time slice, ${visible.length} relationship(s) are active across ${new Set(visible.flatMap((edge) => [edge.source, edge.target])).size} entities.\n`,
    ];
    if (introduced.length) {
      lines.push(`**Introduced in ${year}:**`);
      for (const edge of introduced.sort((a, b) => b.strength - a.strength).slice(0, 8)) {
        const source = nodeMap.get(edge.source);
        const target = nodeMap.get(edge.target);
        lines.push(`- **${source?.name ?? edge.source}** ${verb(edge)} **${target?.name ?? edge.target}**. ${edge.description} [[${edge.id}]]`);
      }
    }
    const dissolved = viewport.edges.filter((edge) => edge.status === "DISSOLVED" && edge.year === year);
    if (dissolved.length) {
      lines.push(`\n**Dissolved in ${year}:**`);
      for (const edge of dissolved) lines.push(`- ${edge.description} [[${edge.id}]]`);
    }
    const byYear = new Map<number, number>();
    for (const edge of viewport.edges) {
      if (edge.year) byYear.set(edge.year, (byYear.get(edge.year) ?? 0) + 1);
    }
    lines.push(
      `\n**Edge creation timeline:** ${[...byYear.entries()].sort((a, b) => a[0] - b[0]).map(([key, value]) => `${key}: ${value}`).join(", ")}.`,
    );
    return lines.join("\n");
  }

  // GLOBAL
  const communities = viewport.communities.map((community) => {
    const members = viewport.nodes.filter((node) => node.community_id === community.id);
    const hubs = [...members].sort((a, b) => b.degree - a.degree).slice(0, 3);
    return { community, members, hubs };
  });
  const hubs = [...viewport.nodes].sort((a, b) => b.degree - a.degree).slice(0, 6);
  const lines = [
    `The graph currently holds **${viewport.nodes.length} entities** and **${viewport.edges.length} relationships** across ${communities.length} detected communities.\n`,
    `**Structural hubs:** ${hubs.map((node) => node.name).join(", ")}.`,
  ];
  for (const { community, members, hubs: top } of communities.slice(0, 5)) {
    lines.push(
      `\n**${community.name}** — ${members.length} entities. Anchored by ${top.map((node) => node.name).join(", ")}. ${community.summary}`,
    );
  }
  if (highlightedEdges.length) {
    lines.push("\n**Strongest cross-cluster evidence:**");
    for (const edge of highlightedEdges.slice(0, 5)) {
      const source = nodeMap.get(edge.source);
      const target = nodeMap.get(edge.target);
      lines.push(`- **${source?.name ?? edge.source}** ${verb(edge)} **${target?.name ?? edge.target}**${dateSuffix(edge)}. ${edge.description} [[${edge.id}]]`);
    }
  }
  return lines.join("\n");
}

function citationsFor(edges: GraphEdge[], nodeMap: Map<string, GraphNode>): Citation[] {
  const seen = new Set<string>();
  const citations: Citation[] = [];
  for (const edge of edges) {
    if (seen.has(edge.id)) continue;
    seen.add(edge.id);
    citations.push({
      edge_id: edge.id,
      label: `${nodeMap.get(edge.source)?.name ?? edge.source} → ${nodeMap.get(edge.target)?.name ?? edge.target}`,
      document: edge.source_doc ?? "Seed knowledge graph",
      page: edge.source_page,
      chunk_id: edge.source_chunk_id,
      date: edge.date,
      cosine_similarity: null,
    });
  }
  return citations;
}

export interface LocalQueryResult {
  context: QueryContextEvent;
  narrative: string;
  complete: QueryCompleteEvent;
}

export function runLocalQuery(input: LocalQueryInput): LocalQueryResult {
  const started = performance.now();
  const mode = (input.mode ?? detectMode(input.query)) as QueryMode;
  const maxYear = input.timeRange[1];
  const edges = activeEdges(input.viewport.edges, maxYear);
  const nodeMap = new Map(input.viewport.nodes.map((node) => [node.id, node]));
  const seeds = findSeeds(input.query, input.viewport.nodes);

  let highlightedNodes = new Set<string>();
  let highlightedEdges: GraphEdge[] = [];
  let path: { nodeIds: string[]; edgeIds: string[] } | null = null;
  let impact: ImpactResult | null = null;
  let year = maxYear;
  let explanation = `Local ${mode.toLowerCase()} reasoning over ${edges.length} active relationships.`;

  if (mode === "CONNECTION") {
    if (seeds.length >= 2) {
      path = shortestPath(edges, seeds[0].id, seeds[1].id);
      if (path) {
        path.nodeIds.forEach((id) => highlightedNodes.add(id));
        highlightedEdges = path.edgeIds
          .map((edgeId) => edges.find((edge) => edge.id === edgeId))
          .filter((edge): edge is GraphEdge => Boolean(edge));
        explanation = `Found a ${path.edgeIds.length}-hop route between ${seeds[0].name} and ${seeds[1].name}.`;
      }
    }
    if (!highlightedNodes.size) {
      const seed = seeds[0];
      if (seed) {
        highlightedNodes.add(seed.id);
        highlightedEdges = edges
          .filter((edge) => edge.source === seed.id || edge.target === seed.id)
          .sort((a, b) => b.strength - a.strength)
          .slice(0, 12);
        for (const edge of highlightedEdges) {
          highlightedNodes.add(edge.source);
          highlightedNodes.add(edge.target);
        }
      }
    }
  } else if (mode === "IMPACT") {
    const target = seeds[0];
    if (!target) {
      throw new Error("Impact simulation needs a recognised entity in the query");
    }
    impact = simulateLocalImpact(input.viewport, target.id);
    highlightedNodes.add(target.id);
    for (const neighbour of impact.directly_disrupted) highlightedNodes.add(neighbour.id);
    highlightedEdges = edges.filter((edge) => edge.source === target.id || edge.target === target.id);
    explanation = `Simulated severance of ${target.name} in ${impact.duration_ms.toFixed(1)} ms (${impact.severity.toLowerCase()} risk).`;
  } else if (mode === "TEMPORAL") {
    year = input.timeRange[1];
    const introduced = input.viewport.edges.filter((edge) => edge.year === year);
    const visible = input.viewport.edges.filter((edge) => edge.year == null || edge.year <= year);
    highlightedEdges = (introduced.length ? introduced : visible).sort((a, b) => b.strength - a.strength).slice(0, 30);
    for (const edge of highlightedEdges) {
      highlightedNodes.add(edge.source);
      highlightedNodes.add(edge.target);
    }
    if (!seeds.length) {
      [...input.viewport.nodes]
        .sort((a, b) => b.degree - a.degree)
        .slice(0, 12)
        .forEach((node) => highlightedNodes.add(node.id));
    }
    explanation = `Time slice ${year}: ${introduced.length} relationship(s) introduced or highlighted.`;
  } else {
    const ranked = seeds.length
      ? seeds.flatMap((seed) => [seed, ...input.viewport.nodes.filter((node) => node.community_id === seed.community_id)])
      : [...input.viewport.nodes].sort((a, b) => b.degree - a.degree).slice(0, 24);
    ranked.slice(0, 30).forEach((node) => highlightedNodes.add(node.id));
    highlightedEdges = edges
      .filter((edge) => highlightedNodes.has(edge.source) && highlightedNodes.has(edge.target))
      .sort((a, b) => b.strength - a.strength)
      .slice(0, 30);
    explanation = `Synthesised the ${highlightedNodes.size} most structurally important entities and their strongest links.`;
  }

  if (!highlightedNodes.size) {
    throw new Error("No matching entities were found. Try an @Entity mention or a broader query.");
  }

  const narrative = buildNarrative(mode, input.query, input.viewport, seeds, path, impact, year, highlightedEdges);
  const citations = citationsFor(highlightedEdges, nodeMap);
  const elapsedMs = Number((performance.now() - started).toFixed(1));
  const confidence = Math.min(
    0.96,
    0.44 + (seeds.length ? 0.2 : 0) + (path?.edgeIds.length ? 0.16 : 0) + Math.min(0.12, citations.length * 0.012),
  );

  const context: QueryContextEvent = {
    type: "graph_context",
    query: input.query,
    mode,
    seed_node_ids: seeds.map((node) => node.id),
    highlighted_node_ids: [...highlightedNodes],
    highlighted_edge_ids: highlightedEdges.map((edge) => edge.id),
    path_node_ids: path?.nodeIds ?? [],
    path_edge_ids: path?.edgeIds ?? [],
    scores: {},
    explanation,
    elapsed_ms: elapsedMs,
    confidence: Number(confidence.toFixed(3)),
  };

  const complete: QueryCompleteEvent = {
    type: "complete",
    citations,
    confidence: Number(confidence.toFixed(3)),
    duration_ms: Number((performance.now() - started).toFixed(1)),
    mode,
  };

  return { context, narrative, complete };
}

export { simulateLocalImpact };

export interface LocalHandlers {
  onContext: (context: QueryContextEvent) => void;
  onToken: (text: string) => void;
  onComplete: (complete: QueryCompleteEvent) => void;
}

export async function streamLocalQuery(
  input: LocalQueryInput,
  handlers: LocalHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const result = runLocalQuery(input);
  handlers.onContext(result.context);
  const words = result.narrative.split(/(\s+)/);
  let buffer = "";
  for (const word of words) {
    if (signal?.aborted) return;
    buffer += word;
    if (word.trim()) {
      handlers.onToken(buffer);
      buffer = "";
      await new Promise((resolve) => setTimeout(resolve, 10));
    }
  }
  if (buffer) handlers.onToken(buffer);
  if (!signal?.aborted) handlers.onComplete(result.complete);
}
