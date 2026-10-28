"use client";

import Graph from "graphology";
import { useCallback, useEffect, useMemo, useRef } from "react";
import Sigma from "sigma";
import type { NodeHoverDrawingFunction } from "sigma/rendering";

import { hexToRgba, nodeColor } from "@/lib/colors";
import { useGraphStore } from "@/store/useGraphStore";

import { GraphControls } from "./GraphControls";
import { Minimap, type MinimapNode } from "./Minimap";
import { ParticleOverlay } from "./ParticleOverlay";

const TYPE_FALLBACK = "#94A3B8";

interface SigmaNode extends Record<string, unknown> {
  x: number;
  y: number;
  size: number;
  label: string;
  baseColor: string;
  nodeType: string;
  community: number;
  pagerank: number;
  betweenness: number;
  degree: number;
  maxCentrality: number;
}

interface SigmaEdge extends Record<string, unknown> {
  label: string;
  size: number;
  color: string;
  strength: number;
  year: number | null;
  status: string;
  edgeType: string;
}

function hashString(value: string): number {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return Math.abs(hash);
}

function fade(hex: string, alpha: number): string {
  return hex.startsWith("#") ? hexToRgba(hex, alpha) : hex;
}

// Sigma's stock hover paint is a white pill, which fights the obsidian theme.
const drawNodeHover: NodeHoverDrawingFunction<SigmaNode, SigmaEdge> = (context, data, settings) => {
  const size = settings.labelSize;
  const font = settings.labelFont;
  const weight = settings.labelWeight;
  context.font = `${weight} ${size}px ${font}`;
  const padding = 3;

  if (typeof data.label === "string") {
    const textWidth = context.measureText(data.label).width;
    const boxWidth = Math.round(textWidth + 12);
    const boxHeight = Math.round(size + 2 * padding + 4);
    const radius = Math.max(data.size, size / 2) + padding;
    const angleRadian = Math.asin(Math.min(1, boxHeight / 2 / radius));
    const xDeltaCoord = Math.sqrt(Math.abs(radius ** 2 - (boxHeight / 2) ** 2));

    context.beginPath();
    context.moveTo(data.x + xDeltaCoord, data.y + boxHeight / 2);
    context.lineTo(data.x + radius + boxWidth, data.y + boxHeight / 2);
    context.lineTo(data.x + radius + boxWidth, data.y - boxHeight / 2);
    context.lineTo(data.x + xDeltaCoord, data.y - boxHeight / 2);
    context.arc(data.x, data.y, radius, angleRadian, -angleRadian);
    context.closePath();
    context.fillStyle = "rgba(10, 14, 23, 0.94)";
    context.shadowBlur = 18;
    context.shadowColor = "rgba(56, 189, 248, 0.35)";
    context.fill();
    context.shadowBlur = 0;
    context.strokeStyle = "rgba(56, 189, 248, 0.42)";
    context.lineWidth = 1;
    context.stroke();

    context.fillStyle = "#F8FAFC";
    context.font = `${weight} ${size}px ${font}`;
    context.fillText(data.label, data.x + data.size + 9, data.y + size / 3);
  } else {
    context.beginPath();
    context.arc(data.x, data.y, data.size + padding, 0, Math.PI * 2);
    context.closePath();
    context.fillStyle = "rgba(10, 14, 23, 0.94)";
    context.fill();
  }
};

export function GraphCanvas() {
  const containerRef = useRef<HTMLDivElement>(null);
  const sigmaRef = useRef<Sigma<SigmaNode, SigmaEdge> | null>(null);
  const graphRef = useRef<Graph<SigmaNode, SigmaEdge> | null>(null);
  const workerRef = useRef<Worker | null>(null);
  const interactedRef = useRef(false);
  const latestViewport = useRef(useGraphStore.getState().viewport);
  // Nodes that arrived with the latest ingest stay haloed and labelled briefly so
  // an upload visibly extends the graph instead of silently adding specks.
  const freshNodesRef = useRef(new Map<string, number>());
  const freshTimerRef = useRef<number | null>(null);

  const viewport = useGraphStore((state) => state.viewport);
  const colorMode = useGraphStore((state) => state.colorMode);
  const selectedNodeId = useGraphStore((state) => state.selectedNodeId);
  const hoveredNodeId = useGraphStore((state) => state.hoveredNodeId);
  const pathNodeIds = useGraphStore((state) => state.highlight.pathNodeIds);
  const layers = useGraphStore((state) => state.layers);
  const loading = useGraphStore((state) => state.loading);
  const source = useGraphStore((state) => state.source);

  latestViewport.current = viewport;

  // Sigma normalises the graph into a framed [0,1] space, so the camera always
  // centres on 0.5/0.5 and a ratio slightly above 1 leaves breathing room for labels.
  const resetView = useCallback((duration = 420) => {
    const sigma = sigmaRef.current;
    if (!sigma) return;
    void sigma.getCamera().animate({ x: 0.5, y: 0.5, ratio: 1.26 }, { duration });
  }, []);

  // ------------------------------------------------------------------ layout worker
  const startLayout = useCallback((graph: Graph<SigmaNode, SigmaEdge>) => {
    if (typeof Worker === "undefined") return;
    workerRef.current?.terminate();
    const worker = new Worker(new URL("../workers/forceLayout.worker.ts", import.meta.url));
    workerRef.current = worker;

    const nodes = graph.mapNodes((id, attributes) => ({
      id,
      x: Number(attributes.x) || 0,
      y: Number(attributes.y) || 0,
      size: Number(attributes.size) || 4,
    }));
    const edges = graph.mapEdges((_key, attributes, sourceId, targetId) => ({
      source: sourceId,
      target: targetId,
      weight: Number(attributes.strength) || 1,
    }));

    worker.onmessage = (event: MessageEvent<{ positions: { id: string; x: number; y: number }[]; done: boolean }>) => {
      if (!graphRef.current || !useGraphStore.getState().physicsRunning) {
        worker.terminate();
        return;
      }
      for (const position of event.data.positions) {
        if (!graph.hasNode(position.id)) continue;
        graph.setNodeAttribute(position.id, "x", position.x);
        graph.setNodeAttribute(position.id, "y", position.y);
      }
      sigmaRef.current?.refresh();
      if (event.data.done) {
        worker.terminate();
        if (workerRef.current === worker) workerRef.current = null;
        if (!interactedRef.current) resetView(450);
      }
    };

    worker.postMessage({ nodes, edges, rounds: 6, iterationsPerRound: 26 });
  }, [resetView]);

  // ------------------------------------------------------------------ sigma bootstrap
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const graph = new Graph<SigmaNode, SigmaEdge>({ multi: true, type: "directed" });
    graphRef.current = graph;

    const sigma = new Sigma<SigmaNode, SigmaEdge>(graph, container, {
      renderLabels: true,
      renderEdgeLabels: false,
      labelDensity: 0.42,
      labelGridCellSize: 90,
      labelRenderedSizeThreshold: 0,
      labelFont: "Inter, system-ui, sans-serif",
      labelSize: 11.5,
      labelWeight: "600",
      labelColor: { color: "#CBD5E1" },
      defaultDrawNodeHover: drawNodeHover,
      defaultEdgeType: "line",
      defaultEdgeColor: "rgba(51, 65, 85, 0.55)",
      zIndex: true,
      minCameraRatio: 0.08,
      maxCameraRatio: 7,
      allowInvalidContainer: true,
      stagePadding: 20,
      nodeReducer: (node: string, data: SigmaNode) => {
        const state = useGraphStore.getState();
        const attributes = graph.getNodeAttributes(node) as Record<string, unknown>;
        const type = String(attributes.nodeType ?? "ORGANIZATION");
        const baseColor = String(attributes.baseColor ?? TYPE_FALLBACK);
        const communityId = Number(attributes.community ?? 0);
        const betweenness = Number(attributes.betweenness ?? 0);
        const maxCentrality = Number(attributes.maxCentrality ?? 1);
        const viewportState = state.viewport;
        const nodeDocuments = Array.isArray(attributes.documents)
          ? (attributes.documents as string[])
          : [];

        const color = viewportState
          ? nodeColor(
              {
                id: node,
                name: String(attributes.label ?? node),
                type: type as never,
                description: "",
                community_id: communityId,
                mention_count: 1,
                pagerank: Number(attributes.pagerank ?? 0),
                betweenness,
                degree: Number(attributes.degree ?? 0),
                aliases: [],
                documents: nodeDocuments,
              },
              state.colorMode,
              viewportState.communities,
              maxCentrality,
              viewportState.documents,
            )
          : baseColor;

        if (state.hiddenTypes.has(type as never)) {
          return { ...data, hidden: true };
        }

        const highlight = state.highlight;
        const hasHighlight = highlight.nodeIds.size > 0;
        const isHighlighted = highlight.nodeIds.has(node);
        const isPath = highlight.pathNodeIds.includes(node);
        const isSeed = highlight.seedNodeIds.has(node);
        const isSelected = state.selectedNodeId === node;
        const isHovered = state.hoveredNodeId === node;
        const isRemoved = state.impact?.removed_node.id === node;
        const isOrphan = Boolean(state.impact?.orphaned.some((item) => item.id === node));
        const isFresh = (freshNodesRef.current.get(node) ?? 0) > Date.now();

        let size = Number(data.size) || 5;
        let label: string | null = String(attributes.label ?? node);
        let nodeColorValue = color;
        let zIndex = Number(data.zIndex) || 0;
        let forceLabel = isHovered || isSelected || isFresh;

        if (hasHighlight && !isHighlighted && !isHovered && !isSelected && !isPath && !isFresh) {
          nodeColorValue = fade(color, 0.2);
          size *= 0.72;
          label = null;
        }
        if (isHighlighted) {
          size += 1.4;
          zIndex = 3;
        }
        if (isSeed) {
          nodeColorValue = "#F8FAFC";
          zIndex = 5;
        }
        if (isPath) {
          size += 2.6;
          zIndex = 6;
          label = String(attributes.label ?? node);
          forceLabel = true;
        }
        if (isSelected) {
          size += 5;
          zIndex = 9;
          forceLabel = true;
          nodeColorValue = color;
        }
        if (isHovered) {
          size += 2.4;
          zIndex = 10;
        }
        if (isFresh) {
          size += 1.6;
          zIndex = Math.max(zIndex, 4);
          label = String(attributes.label ?? node);
          forceLabel = true;
        }
        if (isOrphan) {
          nodeColorValue = "#EF4444";
          size += 2;
          forceLabel = true;
          zIndex = 8;
        }
        if (isRemoved) {
          nodeColorValue = "#DC2626";
          size *= 0.85;
          zIndex = 7;
          forceLabel = true;
        }
        if (!state.layers.labels) label = null;

        return {
          ...data,
          label,
          size,
          color: nodeColorValue,
          zIndex,
          forceLabel,
          highlighted: isSelected || isPath || isHovered || isFresh,
        };
      },
      edgeReducer: (edge: string, data: SigmaEdge) => {
        const state = useGraphStore.getState();
        if (!state.layers.edges) return { ...data, hidden: true };

        const attributes = graph.getEdgeAttributes(edge) as Record<string, unknown>;
        const year = attributes.year == null ? null : Number(attributes.year);
        if (year !== null && year > state.activeYear) return { ...data, hidden: true };

        const sourceId = graph.source(edge);
        const targetId = graph.target(edge);
        const highlight = state.highlight;
        const isPath = highlight.pathEdgeIds.includes(edge);
        const isHovered = state.hoveredEdgeId === edge;
        const isHighlighted = highlight.edgeIds.has(edge);
        const hasHighlight = highlight.nodeIds.size > 0;
        const touchesSelection =
          state.selectedNodeId !== null &&
          (sourceId === state.selectedNodeId || targetId === state.selectedNodeId);

        if (isHovered || isPath) {
          return {
            ...data,
            color: "#38BDF8",
            size: 3.2,
            zIndex: 6,
            hidden: false,
            type: "line",
          };
        }
        if (touchesSelection) {
          return { ...data, color: "rgba(56, 189, 248, 0.8)", size: 2.2, zIndex: 4, hidden: false };
        }
        if (isHighlighted) {
          return { ...data, color: "rgba(125, 211, 252, 0.55)", size: 1.7, zIndex: 2, hidden: false };
        }
        if (hasHighlight) {
          return { ...data, color: "rgba(51, 65, 85, 0.24)", size: 0.7, zIndex: 0, hidden: false };
        }
        return {
          ...data,
          color: `rgba(51, 65, 85, ${0.28 + (Number(attributes.strength) || 4) * 0.035})`,
          size: 1,
          hidden: false,
        };
      },
    });

    sigmaRef.current = sigma;

    sigma.on("enterNode", ({ node }) => {
      useGraphStore.getState().hoverNode(node);
      if (container) container.style.cursor = "pointer";
    });
    sigma.on("leaveNode", () => {
      useGraphStore.getState().hoverNode(null);
      if (container) container.style.cursor = "grab";
    });
    sigma.on("clickNode", ({ node }) => {
      interactedRef.current = true;
      const store = useGraphStore.getState();
      store.selectNode(node);
      store.hoverNode(null);
    });
    sigma.on("doubleClickNode", ({ node }) => {
      const target = graph.getNodeAttributes(node);
      const point = sigma.graphToViewport({ x: Number(target.x), y: Number(target.y) });
      const framed = sigma.viewportToFramedGraph(point);
      void sigma.getCamera().animate(
        { x: framed.x, y: framed.y, ratio: 0.35 },
        { duration: 420 },
      );
    });
    sigma.on("clickStage", () => {
      useGraphStore.getState().selectNode(null);
    });
    sigma.on("enterEdge", ({ edge }) => {
      useGraphStore.getState().hoverEdge(edge);
      if (container) container.style.cursor = "pointer";
    });
    sigma.on("leaveEdge", () => {
      useGraphStore.getState().hoverEdge(null);
      if (container) container.style.cursor = "grab";
    });
    sigma.on("clickEdge", ({ edge }) => {
      const store = useGraphStore.getState();
      store.hoverEdge(edge);
      store.selectNode(graph.source(edge));
    });

    const markInteraction = () => {
      interactedRef.current = true;
    };
    container.addEventListener("pointerdown", markInteraction);
    container.addEventListener("wheel", markInteraction, { passive: true });

    // Register imperative camera controls for the HUD.
    useGraphStore.getState().setGraphActions({
      zoomIn: () => void sigma.getCamera().animatedZoom({ factor: 1.35, duration: 220 }),
      zoomOut: () => void sigma.getCamera().animatedZoom({ factor: 1 / 1.35, duration: 220 }),
      fit: () => resetView(320),
      focus: (nodeId: string) => {
        if (!graph.hasNode(nodeId)) return;
        const target = graph.getNodeAttributes(nodeId);
        const point = sigma.graphToViewport({ x: Number(target.x), y: Number(target.y) });
        const framed = sigma.viewportToFramedGraph(point);
        void sigma.getCamera().animate(
          { x: framed.x, y: framed.y, ratio: 0.42 },
          { duration: 460 },
        );
      },
      togglePhysics: () => {
        const store = useGraphStore.getState();
        store.setPhysicsRunning(!store.physicsRunning);
      },
    });

    // Measured frame rate (not a fabricated number).
    let frames = 0;
    let lastSample = performance.now();
    let raf = 0;
    const measure = (timestamp: number) => {
      frames += 1;
      if (timestamp - lastSample >= 900) {
        const fps = Math.round((frames * 1000) / (timestamp - lastSample));
        useGraphStore.getState().setFps(fps);
        frames = 0;
        lastSample = timestamp;
      }
      raf = requestAnimationFrame(measure);
    };
    raf = requestAnimationFrame(measure);

    return () => {
      cancelAnimationFrame(raf);
      container.removeEventListener("pointerdown", markInteraction);
      container.removeEventListener("wheel", markInteraction);
      if (freshTimerRef.current !== null) window.clearTimeout(freshTimerRef.current);
      freshTimerRef.current = null;
      workerRef.current?.terminate();
      workerRef.current = null;
      useGraphStore.getState().setGraphActions(null);
      sigma.kill();
      sigmaRef.current = null;
      graphRef.current = null;
    };
  }, []);

  // ------------------------------------------------------------------ graph build
  useEffect(() => {
    const graph = graphRef.current;
    const sigma = sigmaRef.current;
    if (!graph || !sigma || !viewport) return;

    // Keep the layout the user is already looking at. Rebuilding every position
    // from scratch made an upload look like a brand-new graph, so preserved nodes
    // keep their coordinates and only genuinely new nodes are seeded — beside the
    // neighbours that are already on screen.
    const previousPositions = new Map<string, { x: number; y: number }>();
    graph.forEachNode((id, attributes) => {
      previousPositions.set(id, { x: Number(attributes.x), y: Number(attributes.y) });
    });

    graph.clear();
    const communities = viewport.communities;
    const communityIds = [...new Set(viewport.nodes.map((node) => node.community_id))];
    const maxCentrality = Math.max(
      0.0001,
      ...viewport.nodes.map((node) => node.betweenness || node.pagerank),
    );

    const groups = new Map<number, typeof viewport.nodes>();
    for (const node of viewport.nodes) {
      const group = groups.get(node.community_id) ?? [];
      group.push(node);
      groups.set(node.community_id, group);
    }

    const preserved = [...previousPositions.values()];
    const anchor = { x: 0, y: 0 };
    for (const position of preserved) {
      anchor.x += position.x / preserved.length;
      anchor.y += position.y / preserved.length;
    }
    const spread = preserved.length
      ? Math.max(
          140,
          preserved.reduce(
            (total, position) => total + Math.hypot(position.x - anchor.x, position.y - anchor.y),
            0,
          ) / preserved.length,
        )
      : 0;

    const communityCenters = new Map<number, { x: number; y: number }>();
    for (const communityId of communityIds) {
      const placed = (groups.get(communityId) ?? [])
        .map((member) => previousPositions.get(member.id))
        .filter((position): position is { x: number; y: number } => Boolean(position));
      if (!placed.length) continue;
      communityCenters.set(communityId, {
        x: placed.reduce((total, position) => total + position.x, 0) / placed.length,
        y: placed.reduce((total, position) => total + position.y, 0) / placed.length,
      });
    }

    // Communities that arrived with the new document orbit the existing graph
    // instead of being pushed to a far corner of the canvas.
    const freshCommunities = communityIds.filter((id) => !communityCenters.has(id));
    freshCommunities.forEach((communityId, index) => {
      const angle =
        (index / Math.max(1, freshCommunities.length)) * Math.PI * 2 +
        (hashString(String(communityId)) % 360) * 0.0175;
      const orbit = preserved.length ? spread * 0.55 + 40 : 240 + communityIds.length * 6;
      communityCenters.set(communityId, {
        x: anchor.x + Math.cos(angle) * orbit,
        y: anchor.y + Math.sin(angle) * orbit * 0.72,
      });
    });

    const neighbours = new Map<string, string[]>();
    const connect = (source: string, target: string) => {
      const list = neighbours.get(source);
      if (list) list.push(target);
      else neighbours.set(source, [target]);
    };
    for (const edge of viewport.edges) {
      if (edge.source === edge.target) continue;
      connect(edge.source, edge.target);
      connect(edge.target, edge.source);
    }

    const placeNode = (node: (typeof viewport.nodes)[number], x: number, y: number) => {
      graph.addNode(node.id, {
        x,
        y,
        size: Math.min(15, 5.2 + Math.sqrt(Math.max(1, node.degree)) * 2.15),
        label: node.name,
        baseColor: nodeColor(node, "TYPE", communities, maxCentrality),
        nodeType: node.type,
        community: node.community_id,
        documents: node.documents ?? [],
        pagerank: node.pagerank,
        betweenness: node.betweenness,
        degree: node.degree,
        maxCentrality,
      });
    };

    for (const node of viewport.nodes) {
      const previous = previousPositions.get(node.id);
      if (previous) placeNode(node, previous.x, previous.y);
    }

    for (const node of viewport.nodes) {
      if (graph.hasNode(node.id)) continue;

      const placedNeighbours = (neighbours.get(node.id) ?? [])
        .filter((neighbour) => graph.hasNode(neighbour))
        .slice(0, 6)
        .map((neighbour) => graph.getNodeAttributes(neighbour) as { x: number; y: number });

      const base = placedNeighbours.length
        ? {
            x:
              placedNeighbours.reduce((total, position) => total + Number(position.x), 0) /
              placedNeighbours.length,
            y:
              placedNeighbours.reduce((total, position) => total + Number(position.y), 0) /
              placedNeighbours.length,
          }
        : (communityCenters.get(node.community_id) ?? anchor);

      const angle = (hashString(node.id) % 360) * (Math.PI / 180);
      const ring = 26 + (hashString(node.id) % 40);
      placeNode(node, base.x + Math.cos(angle) * ring, base.y + Math.sin(angle) * ring * 0.72);
    }

    // Halo the nodes this build introduced so the new document is visible on the
    // canvas without hunting for a few extra dots.
    if (previousPositions.size > 0) {
      const expiry = Date.now() + 9_000;
      for (const node of viewport.nodes) {
        if (!previousPositions.has(node.id)) freshNodesRef.current.set(node.id, expiry);
      }
      for (const [id, until] of freshNodesRef.current) {
        if (until <= Date.now()) freshNodesRef.current.delete(id);
      }
      if (freshTimerRef.current !== null) window.clearTimeout(freshTimerRef.current);
      freshTimerRef.current = window.setTimeout(() => {
        freshNodesRef.current.clear();
        sigmaRef.current?.refresh();
        freshTimerRef.current = null;
      }, 9_400);
    }

    const nodeIds = new Set(viewport.nodes.map((node) => node.id));
    for (const edge of viewport.edges) {
      if (!nodeIds.has(edge.source) || !nodeIds.has(edge.target)) continue;
      if (edge.source === edge.target) continue;
      if (graph.hasEdge(edge.id)) continue;
      try {
        graph.addEdgeWithKey(edge.id, edge.source, edge.target, {
          label: edge.type,
          size: 1,
          color: "rgba(51, 65, 85, 0.4)",
          strength: edge.strength,
          year: edge.year ?? null,
          status: edge.status,
          edgeType: edge.type,
        });
      } catch {
        /* duplicate parallel edge — skip */
      }
    }

    interactedRef.current = false;
    sigma.refresh();
    resetView(380);

    if (useGraphStore.getState().physicsRunning) {
      startLayout(graph);
    }
  }, [viewport, startLayout, resetView]);

  // ------------------------------------------------------------------ physics toggle
  useEffect(() => {
    const graph = graphRef.current;
    if (!graph) return;
    if (useGraphStore.getState().physicsRunning) {
      if (graph.order > 0) startLayout(graph);
    } else {
      workerRef.current?.terminate();
      workerRef.current = null;
    }
  }, [useGraphStore((state) => state.physicsRunning), startLayout]);

  // ------------------------------------------------------------------ refresh on state
  useEffect(
    () =>
      useGraphStore.subscribe((state, previous) => {
        if (
          state.selectedNodeId !== previous.selectedNodeId ||
          state.hoveredNodeId !== previous.hoveredNodeId ||
          state.hoveredEdgeId !== previous.hoveredEdgeId ||
          state.colorMode !== previous.colorMode ||
          state.hiddenTypes !== previous.hiddenTypes ||
          state.layers !== previous.layers ||
          state.activeYear !== previous.activeYear ||
          state.impact !== previous.impact ||
          state.highlight !== previous.highlight
        ) {
          sigmaRef.current?.refresh();
        }
      }),
    [],
  );

  // ------------------------------------------------------------------ helpers
  const getPoint = useCallback((nodeId: string) => {
    const sigma = sigmaRef.current;
    const graph = graphRef.current;
    if (!sigma || !graph || !graph.hasNode(nodeId)) return null;
    const attributes = graph.getNodeAttributes(nodeId);
    return sigma.graphToViewport({ x: Number(attributes.x), y: Number(attributes.y) });
  }, []);

  const getMinimapNodes = useCallback((): MinimapNode[] => {
    const graph = graphRef.current;
    const currentViewport = latestViewport.current;
    if (!graph || !currentViewport || graph.order === 0) return [];
    const maxCentrality = Math.max(
      0.0001,
      ...currentViewport.nodes.map((node) => node.betweenness || node.pagerank),
    );
    return graph.mapNodes((id, attributes) => {
      const node = currentViewport.nodes.find((item) => item.id === id);
      return {
        id,
        x: Number(attributes.x),
        y: Number(attributes.y),
        color: node
          ? nodeColor(
              node,
              useGraphStore.getState().colorMode,
              currentViewport.communities,
              maxCentrality,
              currentViewport.documents,
            )
          : TYPE_FALLBACK,
        size: Number(attributes.size) || 5,
      };
    });
  }, []);

  const focusNode = useCallback((nodeId: string) => {
    const store = useGraphStore.getState();
    store.selectNode(nodeId);
    store.graphActions?.focus(nodeId);
  }, []);

  const hoveredNode = useMemo(
    () => viewport?.nodes.find((node) => node.id === hoveredNodeId) ?? null,
    [viewport, hoveredNodeId],
  );

  const selectedNode = useMemo(
    () => viewport?.nodes.find((node) => node.id === selectedNodeId) ?? null,
    [viewport, selectedNodeId],
  );

  return (
    <div className="absolute inset-0">
      <div className="dot-grid absolute inset-0" />
      <div className="radial-vignette pointer-events-none absolute inset-0" />
      <div ref={containerRef} className="sigma-container z-[1]" />

      {layers.particles && (
        <ParticleOverlay getPoint={getPoint} pathNodeIds={pathNodeIds} enabled={pathNodeIds.length > 1} />
      )}

      <GraphControls />
      {layers.minimap && (
        <Minimap getNodes={getMinimapNodes} selectedNodeId={selectedNodeId} onSelect={focusNode} />
      )}

      {/* hover inspector */}
      {hoveredNode && hoveredNode.id !== selectedNodeId && (
        <div className="pointer-events-none absolute bottom-40 left-4 z-20 w-56 rounded-xl border border-white/10 bg-[#0A0E17]/95 p-2.5 shadow-glass backdrop-blur-md rise-in">
          <div className="flex items-center justify-between gap-2">
            <span className="truncate text-[11px] font-semibold text-white">{hoveredNode.name}</span>
            <span className="shrink-0 rounded bg-white/5 px-1.5 py-0.5 font-mono text-[8.5px] uppercase tracking-wider text-slate-400">
              {hoveredNode.type}
            </span>
          </div>
          <div className="mt-1 flex items-center gap-2 font-mono text-[9px] text-slate-500">
            <span>deg {hoveredNode.degree}</span>
            <span>·</span>
            <span>pr {hoveredNode.pagerank.toFixed(4)}</span>
          </div>
          <p className="mt-1 line-clamp-2 text-[10px] leading-snug text-slate-400">
            {hoveredNode.description || "No description in the graph."}
          </p>
        </div>
      )}

      {selectedNode && (
        <button
          type="button"
          onClick={() => useGraphStore.getState().selectNode(null)}
          className="pointer-events-auto absolute right-4 top-14 z-20 rounded-lg border border-white/10 bg-[#0A0E17]/85 px-2.5 py-1 font-mono text-[10px] text-slate-400 backdrop-blur-md transition-colors hover:text-white xl:top-4"
        >
          clear selection · esc
        </button>
      )}

      {/* empty / loading state */}
      {(loading || !viewport) && (
        <div className="pointer-events-none absolute inset-0 z-30 flex items-center justify-center">
          <div className="flex flex-col items-center gap-3 rounded-2xl border border-white/10 bg-[#0A0E17]/90 px-8 py-6 backdrop-blur-md">
            <div className="h-7 w-7 animate-spin rounded-full border-2 border-blue-500/30 border-t-blue-400" />
            <span className="font-mono text-[10px] uppercase tracking-[0.24em] text-slate-400">
              {loading ? "Connecting to graph engine" : "No graph data"}
            </span>
            {source === "demo" && (
              <span className="text-[10px] text-amber-400/80">falling back to bundled demo graph</span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
