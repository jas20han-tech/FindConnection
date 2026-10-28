"use client";

import { Check, Cpu, Eye, EyeOff, Sparkles } from "lucide-react";

import { ENTITY_COLORS, ENTITY_LABELS, documentSwatch } from "@/lib/colors";
import type { ColorMode, EntityType } from "@/lib/types";
import { useGraphStore } from "@/store/useGraphStore";

const COLOR_MODES: { id: ColorMode; label: string }[] = [
  { id: "DOCUMENT", label: "Doc" },
  { id: "TYPE", label: "Type" },
  { id: "COMMUNITY", label: "Cluster" },
  { id: "CENTRALITY", label: "Rank" },
];

export function LayerPanel() {
  const viewport = useGraphStore((state) => state.viewport);
  const hiddenTypes = useGraphStore((state) => state.hiddenTypes);
  const toggleType = useGraphStore((state) => state.toggleType);
  const colorMode = useGraphStore((state) => state.colorMode);
  const setColorMode = useGraphStore((state) => state.setColorMode);
  const physicsRunning = useGraphStore((state) => state.physicsRunning);
  const setPhysicsRunning = useGraphStore((state) => state.setPhysicsRunning);
  const layers = useGraphStore((state) => state.layers);
  const toggleLayer = useGraphStore((state) => state.toggleLayer);
  const highlight = useGraphStore((state) => state.highlight);

  const counts = new Map<EntityType, number>();
  for (const node of viewport?.nodes ?? []) {
    counts.set(node.type, (counts.get(node.type) ?? 0) + 1);
  }
  const entries = [...counts.entries()].sort((a, b) => b[1] - a[1]);

  const documents = viewport?.documents ?? [];
  const documentCounts = new Map<string, number>();
  for (const node of viewport?.nodes ?? []) {
    for (const document of node.documents ?? []) {
      documentCounts.set(document, (documentCounts.get(document) ?? 0) + 1);
    }
  }
  const documentEntries = [...documentCounts.entries()].sort((a, b) => b[1] - a[1]);

  return (
    <aside className="pointer-events-auto absolute left-4 top-4 z-20 hidden w-60 flex-col gap-3.5 rounded-2xl border border-white/10 bg-[#0A0E17]/85 p-3.5 shadow-glass backdrop-blur-xl lg:flex">
      <div className="flex items-center justify-between">
        <span className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-[0.16em] text-slate-300">
          <Sparkles size={11} className="text-blue-400" /> Entity Layers
        </span>
        <span className="font-mono text-[9px] uppercase tracking-wider text-slate-600">
          {entries.length ? `${entries.length} types` : "—"}
        </span>
      </div>

      <div className="space-y-0.5">
        {entries.length === 0 && (
          <div className="space-y-1.5">
            {[0, 1, 2, 3].map((row) => (
              <div key={row} className="h-6 animate-pulse rounded bg-white/5" />
            ))}
          </div>
        )}
        {entries.map(([type, count]) => {
          const hidden = hiddenTypes.has(type);
          return (
            <button
              key={type}
              type="button"
              onClick={() => toggleType(type)}
              className="flex w-full items-center justify-between rounded-lg px-1.5 py-1 text-left text-[11px] transition-colors hover:bg-white/5"
              aria-pressed={!hidden}
            >
              <span className="flex items-center gap-2">
                <span
                  className="flex h-3 w-3 items-center justify-center rounded-sm border"
                  style={{
                    borderColor: hidden ? "rgba(148,163,184,0.35)" : ENTITY_COLORS[type],
                    backgroundColor: hidden ? "transparent" : ENTITY_COLORS[type],
                  }}
                >
                  {!hidden && <Check size={8} className="text-[#07090E]" strokeWidth={3.5} />}
                </span>
                <span className={hidden ? "text-slate-500 line-through" : "text-slate-200"}>
                  {ENTITY_LABELS[type]}
                </span>
              </span>
              <span className="font-mono text-[10px] text-slate-500">{count}</span>
            </button>
          );
        })}
      </div>

      <div className="border-t border-white/10 pt-3">
        <div className="mb-2 text-[9px] font-bold uppercase tracking-[0.18em] text-slate-500">
          Colour encoding
        </div>
        <div className="grid grid-cols-4 gap-1 rounded-lg bg-slate-900/90 p-1 text-center font-mono text-[10px]">
          {COLOR_MODES.map((mode) => (
            <button
              key={mode.id}
              type="button"
              onClick={() => setColorMode(mode.id)}
              className={`rounded py-1 transition-colors ${
                colorMode === mode.id
                  ? "bg-blue-600 font-bold text-white"
                  : "text-slate-400 hover:text-white"
              }`}
            >
              {mode.label}
            </button>
          ))}
        </div>

        {colorMode === "DOCUMENT" && (
          <div className="mt-2 space-y-1">
            {documentEntries.length === 0 ? (
              <p className="font-mono text-[9px] text-slate-600">No documents in the graph</p>
            ) : (
              documentEntries.slice(0, 5).map(([document, count]) => (
                <div
                  key={document}
                  className="flex items-center justify-between gap-2 rounded px-1 py-0.5 text-[10px]"
                  title={document}
                >
                  <span className="flex min-w-0 items-center gap-1.5">
                    <span
                      className="h-2.5 w-2.5 shrink-0 rounded-sm"
                      style={{ backgroundColor: documentSwatch(document, documents) }}
                    />
                    <span className="truncate text-slate-300">{document || "Untitled"}</span>
                  </span>
                  <span className="shrink-0 font-mono text-[9px] text-slate-500">{count}</span>
                </div>
              ))
            )}
            {documentEntries.length > 5 && (
              <p className="px-1 font-mono text-[9px] text-slate-600">
                +{documentEntries.length - 5} more documents
              </p>
            )}
          </div>
        )}
      </div>

      <div className="border-t border-white/10 pt-3">
        <div className="mb-1.5 flex items-center justify-between text-[10px]">
          <span className="flex items-center gap-1.5 text-slate-300">
            <Cpu size={11} className="text-slate-500" /> ForceAtlas2
          </span>
          <button
            type="button"
            onClick={() => setPhysicsRunning(!physicsRunning)}
            className={`rounded border px-1.5 py-0.5 font-mono text-[9px] font-semibold transition-colors ${
              physicsRunning
                ? "border-emerald-500/30 bg-emerald-500/15 text-emerald-400 hover:bg-emerald-500/25"
                : "border-white/10 bg-slate-800 text-slate-400 hover:text-white"
            }`}
          >
            {physicsRunning ? "Running" : "Paused"}
          </button>
        </div>
        <p className="font-mono text-[9px] leading-relaxed text-slate-600">
          Off-main-thread layout · {viewport?.edges.length ?? 0} weighted springs
        </p>
      </div>

      <div className="grid grid-cols-2 gap-1 border-t border-white/10 pt-3">
        {(
          [
            ["edges", "Edges"],
            ["particles", "Flow"],
            ["labels", "Labels"],
            ["minimap", "Minimap"],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            type="button"
            onClick={() => toggleLayer(key)}
            className={`flex items-center gap-1 rounded-md px-1.5 py-1 font-mono text-[9px] transition-colors ${
              layers[key]
                ? "bg-white/5 text-slate-300 hover:bg-white/10"
                : "text-slate-600 hover:text-slate-400"
            }`}
          >
            {layers[key] ? <Eye size={9} /> : <EyeOff size={9} />}
            {label}
          </button>
        ))}
      </div>

      {highlight.mode && (
        <div className="rounded-xl border border-blue-500/20 bg-blue-500/10 p-2.5">
          <div className="flex items-center justify-between font-mono text-[9px] uppercase tracking-wider">
            <span className="text-blue-300">{highlight.mode.toLowerCase()} mode</span>
            <span className="text-emerald-400">{Math.round(highlight.confidence * 100)}%</span>
          </div>
          <p className="mt-1 text-[10px] leading-snug text-slate-400">
            {highlight.pathNodeIds.length > 0
              ? `${Math.max(0, highlight.pathNodeIds.length - 1)}-hop path · ${highlight.edgeIds.size} grounded edges`
              : `${highlight.nodeIds.size} entities highlighted`}
          </p>
        </div>
      )}
    </aside>
  );
}
