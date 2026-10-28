/**
 * ForceAtlas2 layout worker.
 *
 * The main thread never blocks: positions are computed off-thread in short rounds and
 * streamed back so the canvas settles progressively instead of freezing on load.
 */

import Graph from "graphology";
import forceAtlas2 from "graphology-layout-forceatlas2";

export interface LayoutNode {
  id: string;
  x: number;
  y: number;
  size: number;
}

export interface LayoutEdge {
  source: string;
  target: string;
  weight: number;
}

export interface LayoutRequest {
  nodes: LayoutNode[];
  edges: LayoutEdge[];
  rounds?: number;
  iterationsPerRound?: number;
}

export interface LayoutResponse {
  positions: { id: string; x: number; y: number }[];
  done: boolean;
}

const scope = self as unknown as {
  onmessage: ((event: MessageEvent<LayoutRequest>) => void) | null;
  postMessage: (message: LayoutResponse) => void;
};

scope.onmessage = (event) => {
  const { nodes, edges, rounds = 5, iterationsPerRound = 22 } = event.data;
  if (!nodes.length) {
    scope.postMessage({ positions: [], done: true });
    return;
  }

  const graph = new Graph({ type: "undirected", multi: false });
  for (const node of nodes) {
    if (graph.hasNode(node.id)) continue;
    graph.addNode(node.id, { x: node.x, y: node.y, size: Math.max(1, node.size) });
  }
  for (const edge of edges) {
    if (edge.source === edge.target) continue;
    if (!graph.hasNode(edge.source) || !graph.hasNode(edge.target)) continue;
    if (graph.hasEdge(edge.source, edge.target)) continue;
    graph.addEdge(edge.source, edge.target, { weight: Math.max(0.1, edge.weight) });
  }

  const settings = {
    gravity: 0.8,
    scalingRatio: 26,
    slowDown: 2.2,
    barnesHutOptimize: nodes.length > 220,
    adjustSizes: true,
    linLogMode: false,
    outboundAttractionDistribution: true,
  };

  const totalRounds = Math.max(1, rounds);
  for (let round = 0; round < totalRounds; round += 1) {
    try {
      forceAtlas2.assign(graph, {
        iterations: iterationsPerRound,
        settings,
        getEdgeWeight: "weight",
      });
    } catch {
      break;
    }
    const positions = graph.mapNodes((id, attributes) => ({
      id,
      x: Number(attributes.x) || 0,
      y: Number(attributes.y) || 0,
    }));
    scope.postMessage({ positions, done: round === totalRounds - 1 });
  }
};
