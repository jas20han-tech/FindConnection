"use client";

import {
  AlertTriangle,
  BookOpen,
  GitBranch,
  Layers,
  Loader2,
  Quote,
  RotateCcw,
  ShieldAlert,
  Sparkles,
  Waypoints,
} from "lucide-react";
import { useMemo } from "react";

import { useImpactSimulation } from "@/hooks/useQueryRunner";
import { ENTITY_COLORS, ENTITY_LABELS, communityColor } from "@/lib/colors";
import type { DrawerTab, ImpactResult } from "@/lib/types";
import { useGraphStore } from "@/store/useGraphStore";

import { Narrative } from "./Narrative";

const TABS: { id: DrawerTab; label: string; icon: React.ReactNode }[] = [
  { id: "story", label: "Story", icon: <Sparkles size={11} /> },
  { id: "impact", label: "Impact", icon: <ShieldAlert size={11} /> },
  { id: "sources", label: "Sources", icon: <BookOpen size={11} /> },
];

const SEVERITY_STYLE: Record<ImpactResult["severity"], { text: string; bg: string; border: string }> = {
  CRITICAL: { text: "text-rose-400", bg: "bg-rose-500/10", border: "border-rose-500/30" },
  HIGH: { text: "text-orange-400", bg: "bg-orange-500/10", border: "border-orange-500/30" },
  MODERATE: { text: "text-amber-400", bg: "bg-amber-500/10", border: "border-amber-500/30" },
  LOW: { text: "text-emerald-400", bg: "bg-emerald-500/10", border: "border-emerald-500/30" },
};

export function EntityDrawer({
  overlayOpen = false,
  onCloseOverlay,
}: {
  overlayOpen?: boolean;
  onCloseOverlay?: () => void;
}) {
  const viewport = useGraphStore((state) => state.viewport);
  const source = useGraphStore((state) => state.source);
  const query = useGraphStore((state) => state.query);
  const highlight = useGraphStore((state) => state.highlight);
  const selectedNodeId = useGraphStore((state) => state.selectedNodeId);
  const drawerTab = useGraphStore((state) => state.drawerTab);
  const setDrawerTab = useGraphStore((state) => state.setDrawerTab);
  const impact = useGraphStore((state) => state.impact);
  const impactLoading = useGraphStore((state) => state.impactLoading);
  const setImpact = useGraphStore((state) => state.setImpact);
  const hoverEdge = useGraphStore((state) => state.hoverEdge);
  const selectNode = useGraphStore((state) => state.selectNode);
  const setQueryText = useGraphStore((state) => state.setQueryText);
  const setQueryContext = useGraphStore((state) => state.setQueryContext);
  const { runImpact } = useImpactSimulation();

  const nodes = viewport?.nodes ?? [];
  const edges = viewport?.edges ?? [];
  const communities = viewport?.communities ?? [];

  const nodeMap = useMemo(() => new Map(nodes.map((node) => [node.id, node])), [nodes]);
  const edgeMap = useMemo(() => new Map(edges.map((edge) => [edge.id, edge])), [edges]);
  const selectedNode = selectedNodeId ? nodeMap.get(selectedNodeId) : undefined;

  const neighbours = useMemo(() => {
    if (!selectedNode) return [];
    return edges
      .filter((edge) => edge.source === selectedNode.id || edge.target === selectedNode.id)
      .sort((a, b) => b.strength - a.strength)
      .slice(0, 6)
      .map((edge) => {
        const otherId = edge.source === selectedNode.id ? edge.target : edge.source;
        return { edge, other: nodeMap.get(otherId) };
      });
  }, [edges, nodeMap, selectedNode]);

  const inferredConfidence =
    highlight.confidence || (query.mode ? query.confidence : 0) || (query.status === "complete" ? query.confidence : 0);

  const askAboutNode = () => {
    if (!selectedNode) return;
    setQueryContext({ mode: "CONNECTION" });
    setQueryText(`How is ${selectedNode.name} connected to the rest of the AI ecosystem?`);
    const input = document.getElementById("omnibar-input") as HTMLInputElement | null;
    input?.focus();
  };

  return (
    <aside
      className={`pointer-events-auto fixed inset-y-14 right-0 z-40 w-[min(92vw,22rem)] shrink-0 flex-col border-l border-white/10 bg-[#0A0E17]/95 shadow-2xl backdrop-blur-xl xl:static xl:z-20 xl:flex xl:w-[22rem] xl:shadow-none ${
        overlayOpen ? "flex" : "hidden"
      }`}
    >
      <div className="border-b border-white/10 p-3.5">
        <div className="mb-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="h-1.5 w-1.5 rounded-full bg-blue-400 animate-pulse-slow" />
            <span className="text-[10px] font-bold uppercase tracking-[0.16em] text-slate-200">
              Reasoning Context
            </span>
          </div>
          <span
            className={`rounded border px-1.5 py-0.5 font-mono text-[9.5px] font-semibold ${
              query.status === "error"
                ? "border-rose-500/30 bg-rose-500/15 text-rose-300"
                : inferredConfidence > 0
                  ? "border-emerald-500/30 bg-emerald-500/15 text-emerald-300"
                  : "border-white/10 bg-slate-800 text-slate-400"
            }`}
          >
            {query.status === "error"
              ? "no match"
              : inferredConfidence > 0
                ? `${(inferredConfidence * 100).toFixed(1)}% match`
                : "awaiting query"}
          </span>
          <button
            type="button"
            onClick={onCloseOverlay}
            className="rounded p-1 text-slate-400 transition-colors hover:bg-white/10 hover:text-white xl:hidden"
            aria-label="Close context drawer"
          >
            ✕
          </button>
        </div>

        <div className="grid grid-cols-3 gap-1 rounded-xl bg-slate-900/90 p-1 text-[10px] font-medium">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => setDrawerTab(tab.id)}
              className={`flex items-center justify-center gap-1 rounded-lg py-1.5 transition-colors ${
                drawerTab === tab.id
                  ? "bg-blue-600 font-semibold text-white"
                  : "text-slate-400 hover:text-white"
              }`}
            >
              {tab.icon}
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-3.5">
        {drawerTab === "story" && (
          <StoryTab
            selectedNode={selectedNode}
            neighbours={neighbours}
            onAsk={askAboutNode}
            onImpact={(nodeId) => void runImpact(nodeId)}
            onSelect={selectNode}
            onHoverEdge={hoverEdge}
          />
        )}
        {drawerTab === "impact" && (
          <ImpactTab
            impact={impact}
            loading={impactLoading}
            selectedNode={selectedNode}
            onRun={(nodeId) => void runImpact(nodeId)}
            onClear={() => setImpact(null)}
            onSelect={selectNode}
          />
        )}
        {drawerTab === "sources" && (
          <SourcesTab onHoverEdge={hoverEdge} onSelectEdgeSource={selectNode} edgeMap={edgeMap} />
        )}
      </div>

      <div className="flex items-center justify-between border-t border-white/10 bg-slate-900/40 px-3.5 py-2.5 font-mono text-[9.5px] text-slate-500">
        <span className="flex items-center gap-1.5">
          <span className={`h-1.5 w-1.5 rounded-full ${source === "api" ? "bg-emerald-400" : "bg-amber-400"}`} />
          {source === "api" ? "Neo4j / in-memory API" : "bundled demo graph"}
        </span>
        <span className="text-slate-400">
          {query.elapsedMs > 0 ? `${query.elapsedMs.toFixed(1)} ms` : `${edges.length} edges`}
        </span>
      </div>
    </aside>
  );

  // ---------------------------------------------------------------- story tab
  function StoryTab({
    selectedNode: node,
    neighbours: adjacent,
    onAsk,
    onImpact,
    onSelect,
    onHoverEdge,
  }: {
    selectedNode: ReturnType<typeof nodeMap.get>;
    neighbours: { edge: (typeof edges)[number]; other: ReturnType<typeof nodeMap.get> }[];
    onAsk: () => void;
    onImpact: (nodeId: string) => void;
    onSelect: (nodeId: string) => void;
    onHoverEdge: (edgeId: string | null) => void;
  }) {
    return (
      <div className="space-y-3.5">
        {node && (
          <div className="rounded-xl border border-white/10 bg-slate-900/70 p-3">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="flex items-center gap-1.5">
                  <span
                    className="h-2 w-2 shrink-0 rounded-full"
                    style={{ backgroundColor: ENTITY_COLORS[node.type] }}
                  />
                  <h3 className="truncate text-[12.5px] font-bold text-white">{node.name}</h3>
                </div>
                <div className="mt-1 flex items-center gap-1.5 font-mono text-[9px] uppercase tracking-wider text-slate-500">
                  <span style={{ color: ENTITY_COLORS[node.type] }}>{ENTITY_LABELS[node.type]}</span>
                  <span>·</span>
                  <span
                    className="inline-flex items-center gap-1"
                    style={{ color: communityColor(node.community_id, communities) }}
                  >
                    <Layers size={8} />
                    {communities.find((community) => community.id === node.community_id)?.name ??
                      `Cluster ${node.community_id + 1}`}
                  </span>
                </div>
              </div>
              <span className="shrink-0 rounded bg-white/5 px-1.5 py-0.5 font-mono text-[9px] text-slate-400">
                {node.degree} links
              </span>
            </div>
            <p className="mt-2 text-[10.5px] leading-relaxed text-slate-400">{node.description}</p>
            <div className="mt-2 grid grid-cols-3 gap-1.5 font-mono text-[9px] text-slate-500">
              <div className="rounded bg-black/30 px-1.5 py-1">
                <span className="block text-[8px] uppercase tracking-wider text-slate-600">PageRank</span>
                <span className="text-slate-300">{node.pagerank.toFixed(4)}</span>
              </div>
              <div className="rounded bg-black/30 px-1.5 py-1">
                <span className="block text-[8px] uppercase tracking-wider text-slate-600">Between</span>
                <span className="text-slate-300">{node.betweenness.toFixed(3)}</span>
              </div>
              <div className="rounded bg-black/30 px-1.5 py-1">
                <span className="block text-[8px] uppercase tracking-wider text-slate-600">Mentions</span>
                <span className="text-slate-300">{node.mention_count}</span>
              </div>
            </div>
            <div className="mt-2.5 flex gap-1.5">
              <button
                type="button"
                onClick={onAsk}
                className="flex flex-1 items-center justify-center gap-1 rounded-md border border-blue-500/30 bg-blue-500/15 px-2 py-1 text-[9.5px] font-semibold text-blue-300 transition-colors hover:bg-blue-500/25"
              >
                <GitBranch size={10} /> Trace links
              </button>
              <button
                type="button"
                onClick={() => onImpact(node.id)}
                className="flex flex-1 items-center justify-center gap-1 rounded-md border border-rose-500/30 bg-rose-500/15 px-2 py-1 text-[9.5px] font-semibold text-rose-300 transition-colors hover:bg-rose-500/25"
              >
                <ShieldAlert size={10} /> Simulate cut
              </button>
            </div>
          </div>
        )}

        {query.status === "idle" && !node && (
          <div className="rounded-xl border border-white/10 bg-slate-900/60 p-4 text-center">
            <Waypoints size={20} className="mx-auto text-slate-600" />
            <p className="mt-2 text-[11px] font-semibold text-slate-300">Nothing selected</p>
            <p className="mt-1 text-[10px] leading-relaxed text-slate-500">
              Click any entity on the canvas, or run a query to synthesise a grounded,
              citation-backed story.
            </p>
          </div>
        )}

        {query.mode && query.status !== "idle" && (
          <div className="rounded-xl border border-blue-500/20 bg-blue-500/10 p-2.5">
            <div className="flex items-center justify-between font-mono text-[9px] uppercase tracking-wider text-blue-300">
              <span>{query.mode.toLowerCase()} synthesis</span>
              <span className="text-slate-400">{query.elapsedMs.toFixed(1)} ms</span>
            </div>
            <p className="mt-1 text-[10px] leading-snug text-slate-400">
              {query.explanation || highlight.explanation || "Reasoning over the active graph slice."}
            </p>
          </div>
        )}

        {query.status === "error" && (
          <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-3">
            <div className="flex items-center gap-1.5 text-[10.5px] font-semibold text-rose-300">
              <AlertTriangle size={12} /> Query could not be grounded
            </div>
            <p className="mt-1 text-[10px] leading-relaxed text-slate-400">{query.error}</p>
          </div>
        )}

        {(query.narrative || query.status === "streaming") && (
          <div>
            <h4 className="mb-1.5 flex items-center gap-1.5 text-[9.5px] font-bold uppercase tracking-[0.16em] text-slate-500">
              <Quote size={10} /> Synthesised narrative
            </h4>
            <Narrative text={query.narrative} streaming={query.status === "streaming"} citations={query.citations} />
          </div>
        )}

        {highlight.pathNodeIds.length > 1 && (
          <div className="space-y-1.5 rounded-xl border border-white/10 bg-slate-900/80 p-3">
            <div className="font-mono text-[9px] font-semibold uppercase tracking-[0.14em] text-slate-500">
              Traversed knowledge route
            </div>
            <div className="space-y-0.5">
              {highlight.pathNodeIds.map((nodeId, index) => {
                const pathNode = nodeMap.get(nodeId);
                const edgeId = highlight.pathEdgeIds[index];
                const edge = edgeId ? edgeMap.get(edgeId) : undefined;
                return (
                  <div key={`${nodeId}-${index}`}>
                    <button
                      type="button"
                      onClick={() => onSelect(nodeId)}
                      className="flex w-full items-center gap-1.5 text-left font-mono text-[10px] font-semibold transition-opacity hover:opacity-80"
                      style={{ color: pathNode ? ENTITY_COLORS[pathNode.type] : "#94A3B8" }}
                    >
                      <span
                        className="h-1.5 w-1.5 rounded-full"
                        style={{ backgroundColor: pathNode ? ENTITY_COLORS[pathNode.type] : "#64748B" }}
                      />
                      <span className="truncate">{pathNode?.name ?? nodeId}</span>
                      <span className="ml-auto shrink-0 text-[8px] uppercase tracking-wider text-slate-600">
                        {pathNode ? ENTITY_LABELS[pathNode.type] : ""}
                      </span>
                    </button>
                    {edge && (
                      <button
                        type="button"
                        onMouseEnter={() => onHoverEdge(edge.id)}
                        onMouseLeave={() => onHoverEdge(null)}
                        onFocus={() => onHoverEdge(edge.id)}
                        onBlur={() => onHoverEdge(null)}
                        className="mt-0.5 pl-3 text-left font-mono text-[9px] text-slate-500 transition-colors hover:text-sky-300"
                      >
                        ↳ [{edge.type}]{edge.year ? ` (${edge.year})` : ""}
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {node && adjacent.length > 0 && (
          <div className="space-y-1.5">
            <div className="font-mono text-[9px] font-semibold uppercase tracking-[0.14em] text-slate-500">
              Direct relationships
            </div>
            {adjacent.map(({ edge, other }) => (
              <button
                key={edge.id}
                type="button"
                onMouseEnter={() => onHoverEdge(edge.id)}
                onMouseLeave={() => onHoverEdge(null)}
                onClick={() => other && onSelect(other.id)}
                className="flex w-full items-center justify-between gap-2 rounded-lg border border-white/5 bg-slate-900/60 px-2 py-1.5 text-left transition-colors hover:border-white/15 hover:bg-slate-900"
              >
                <span className="min-w-0">
                  <span className="block truncate text-[10px] text-slate-300">{other?.name ?? "unknown"}</span>
                  <span className="block font-mono text-[8.5px] uppercase tracking-wider text-slate-600">
                    {edge.type}
                    {edge.year ? ` · ${edge.year}` : ""}
                  </span>
                </span>
                <span className="shrink-0 font-mono text-[9px] text-slate-500">{edge.strength}/10</span>
              </button>
            ))}
          </div>
        )}

        {query.status === "complete" && (
          <div className="rounded-xl border border-white/5 bg-slate-900/60 p-2.5 text-[10px] leading-relaxed text-slate-500">
            💡 Hover a citation badge to lock the exact edge on the canvas; every claim is
            anchored to a retrieved relationship.
          </div>
        )}
      </div>
    );
  }

  // ---------------------------------------------------------------- impact tab
  function ImpactTab({
    impact: result,
    loading,
    selectedNode: node,
    onRun,
    onClear,
    onSelect,
  }: {
    impact: ImpactResult | null;
    loading: boolean;
    selectedNode: ReturnType<typeof nodeMap.get>;
    onRun: (nodeId: string) => void;
    onClear: () => void;
    onSelect: (nodeId: string) => void;
  }) {
    if (loading) {
      return (
        <div className="flex flex-col items-center justify-center gap-3 py-16 text-slate-500">
          <Loader2 size={18} className="animate-spin text-rose-400" />
          <span className="font-mono text-[9.5px] uppercase tracking-[0.2em]">
            simulating cascade
          </span>
        </div>
      );
    }

    if (!result) {
      return (
        <div className="space-y-3">
          <div className="rounded-xl border border-white/10 bg-slate-900/60 p-4 text-center">
            <ShieldAlert size={20} className="mx-auto text-slate-600" />
            <p className="mt-2 text-[11px] font-semibold text-slate-300">No active simulation</p>
            <p className="mt-1 text-[10px] leading-relaxed text-slate-500">
              NetworkX severs a node in memory and measures component fragmentation, orphaned
              dependencies and centrality surge — no database writes.
            </p>
          </div>
          {node ? (
            <button
              type="button"
              onClick={() => onRun(node.id)}
              className="w-full rounded-lg bg-rose-600 px-3 py-2 text-[10.5px] font-semibold text-white transition-colors hover:bg-rose-500"
            >
              Cut {node.name} and simulate cascade
            </button>
          ) : (
            <p className="text-center font-mono text-[9px] uppercase tracking-wider text-slate-600">
              select an entity on the canvas first
            </p>
          )}
        </div>
      );
    }

    const style = SEVERITY_STYLE[result.severity];

    return (
      <div className="space-y-3">
        <div className={`flex items-center justify-between rounded-xl border p-3 ${style.bg} ${style.border}`}>
          <div>
            <div className={`text-[9px] font-bold uppercase tracking-[0.16em] ${style.text}`}>
              Cascade severity
            </div>
            <div className={`mt-0.5 text-lg font-black tracking-tight ${style.text}`}>
              {result.severity}
            </div>
          </div>
          <div className="text-right">
            <div className={`font-mono text-xl font-bold ${style.text}`}>
              {Math.round(result.risk_score * 100)}%
            </div>
            <div className="text-[9px] text-slate-500">risk score</div>
          </div>
        </div>

        <div>
          <div className="mb-1.5 flex items-center justify-between text-[10px] font-semibold text-slate-300">
            <span>Severed node under test</span>
            <button
              type="button"
              onClick={onClear}
              className="flex items-center gap-1 font-mono text-[9px] text-slate-500 transition-colors hover:text-white"
            >
              <RotateCcw size={9} /> reset
            </button>
          </div>
          <div className="flex items-center justify-between rounded-xl border border-white/10 bg-slate-900 px-2.5 py-2 font-mono text-[10.5px]">
            <span className="text-blue-400">{result.removed_node.name}</span>
            <span className="text-rose-400">{result.severed_edges.length} edges cut</span>
          </div>
        </div>

        <div className="grid grid-cols-3 gap-1.5 text-center font-mono">
          <Metric label="disruption" value={`${Math.round(result.disruption_ratio * 100)}%`} tone="text-rose-400" />
          <Metric label="components" value={`${result.component_count_before}→${result.component_count_after}`} tone="text-amber-400" />
          <Metric label="largest" value={`${Math.round(result.largest_component_ratio_after * 100)}%`} tone="text-sky-400" />
        </div>

        <div className="space-y-1.5">
          <div className="text-[10px] font-semibold text-slate-300">
            Orphaned dependencies (degree → 0)
          </div>
          {result.orphaned.length === 0 && (
            <p className="rounded-lg border border-white/5 bg-slate-900/60 px-2.5 py-2 text-[10px] text-slate-500">
              No neighbour is fully orphaned — alternative paths absorb the cascade.
            </p>
          )}
          {result.orphaned.map((orphan) => (
            <button
              key={orphan.id}
              type="button"
              onClick={() => onSelect(orphan.id)}
              className="flex w-full items-center justify-between rounded-lg border border-white/10 bg-slate-900/80 px-2.5 py-1.5 text-left transition-colors hover:border-rose-500/30"
            >
              <span className="truncate text-[10px] text-rose-300">{orphan.name}</span>
              <span className="font-mono text-[8.5px] font-bold text-rose-400">ISOLATED</span>
            </button>
          ))}
        </div>

        {result.centrality_surge.length > 0 && (
          <div className="space-y-1.5">
            <div className="text-[10px] font-semibold text-slate-300">
              Centrality surge (surviving hubs)
            </div>
            {result.centrality_surge.slice(0, 5).map((surge) => (
              <button
                key={surge.id}
                type="button"
                onClick={() => onSelect(surge.id)}
                className="flex w-full items-center justify-between rounded-lg border border-white/10 bg-slate-900/80 px-2.5 py-1.5 text-left transition-colors hover:border-emerald-500/30"
              >
                <span className="truncate text-[10px] text-slate-300">{surge.name}</span>
                <span className="shrink-0 font-mono text-[9px] font-bold text-emerald-400">
                  +{Math.round(surge.delta_pct)}%
                </span>
              </button>
            ))}
          </div>
        )}

        <div className="rounded-xl border border-white/5 bg-slate-900/60 p-2.5 font-mono text-[9px] text-slate-500">
          computed in {result.duration_ms.toFixed(1)} ms · {result.directly_disrupted.length} direct
          dependencies · zero writes
        </div>
      </div>
    );
  }

  // --------------------------------------------------------------- sources tab
  function SourcesTab({
    onHoverEdge,
    onSelectEdgeSource,
    edgeMap: map,
  }: {
    onHoverEdge: (edgeId: string | null) => void;
    onSelectEdgeSource: (nodeId: string) => void;
    edgeMap: Map<string, (typeof edges)[number]>;
  }) {
    if (!query.citations.length) {
      return (
        <div className="rounded-xl border border-white/10 bg-slate-900/60 p-4 text-center">
          <BookOpen size={18} className="mx-auto text-slate-600" />
          <p className="mt-2 text-[11px] font-semibold text-slate-300">No citations yet</p>
          <p className="mt-1 text-[10px] leading-relaxed text-slate-500">
            Every retrieved relationship becomes a verifiable source chunk with document,
            page and cosine similarity.
          </p>
        </div>
      );
    }

    return (
      <div className="space-y-2.5">
        <div className="flex items-center justify-between">
          <span className="font-mono text-[9px] font-bold uppercase tracking-[0.16em] text-slate-500">
            {query.citations.length} verified ground-truth chunks
          </span>
          <span className="font-mono text-[9px] text-emerald-400">
            {(query.confidence * 100).toFixed(1)}% confidence
          </span>
        </div>
        {query.citations.map((citation, index) => {
          const edge = map.get(citation.edge_id);
          return (
            <div
              key={`${citation.edge_id}-${index}`}
              className="space-y-1.5 rounded-xl border border-white/10 bg-slate-900/90 p-2.5 transition-colors hover:border-sky-500/30"
              onMouseEnter={() => onHoverEdge(citation.edge_id)}
              onMouseLeave={() => onHoverEdge(null)}
            >
              <div className="flex items-start justify-between gap-2 text-[10px]">
                <span className="flex min-w-0 items-center gap-1.5">
                  <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded bg-sky-500/20 font-mono text-[8.5px] font-bold text-sky-300">
                    {index + 1}
                  </span>
                  <span className="truncate font-semibold text-white">{citation.document}</span>
                </span>
                {citation.page ? (
                  <span className="shrink-0 font-mono text-[9px] font-bold text-blue-400">
                    Page {citation.page}
                  </span>
                ) : null}
              </div>
              <p className="text-[10px] leading-relaxed text-slate-400">{citation.label}</p>
              <div className="flex items-center justify-between font-mono text-[8.5px] text-slate-600">
                <span>
                  {citation.cosine_similarity != null
                    ? `Cosine ${citation.cosine_similarity.toFixed(2)}`
                    : edge?.source_chunk_id
                      ? `Chunk ${edge.source_chunk_id.slice(-6)}`
                      : "graph relationship"}
                </span>
                {edge && (
                  <button
                    type="button"
                    onClick={() => onSelectEdgeSource(edge.source)}
                    className="text-emerald-400 transition-colors hover:text-emerald-300"
                  >
                    inspect edge →
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>
    );
  }
}

function Metric({ label, value, tone }: { label: string; value: string; tone: string }) {
  return (
    <div className="rounded-lg border border-white/5 bg-slate-900/70 px-1.5 py-1.5">
      <div className={`text-[11px] font-bold ${tone}`}>{value}</div>
      <div className="mt-0.5 text-[8px] uppercase tracking-wider text-slate-600">{label}</div>
    </div>
  );
}
