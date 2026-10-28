"use client";

import { Activity, Database, FileText, Layers, Network, Upload } from "lucide-react";

import { useGraphStore } from "@/store/useGraphStore";

function StatPill({
  icon,
  value,
  label,
  dotClass,
}: {
  icon: React.ReactNode;
  value: number;
  label: string;
  dotClass: string;
}) {
  return (
    <div className="flex items-center gap-2 rounded-full border border-white/10 bg-slate-900/80 px-3 py-1 font-mono text-[11px] text-slate-400">
      <span className={`flex h-1.5 w-1.5 shrink-0 rounded-full ${dotClass}`} />
      <span className="text-white">{value.toLocaleString()}</span>
      <span className="hidden whitespace-nowrap xl:inline">{label}</span>
      {icon}
    </div>
  );
}

export function TelemetryHeader() {
  const viewport = useGraphStore((state) => state.viewport);
  const source = useGraphStore((state) => state.source);
  const fps = useGraphStore((state) => state.fps);
  const actions = useGraphStore((state) => state.graphActions);
  const setIngestionOpen = useGraphStore((state) => state.setIngestionOpen);
  const setQueryText = useGraphStore((state) => state.setQueryText);

  const stats = viewport?.stats;
  const nodeCount = stats?.node_count ?? 0;
  const edgeCount = stats?.edge_count ?? 0;
  const communityCount = stats?.community_count ?? 0;
  const documentCount = stats?.document_count ?? 0;

  return (
    <header className="z-30 flex h-14 shrink-0 items-center justify-between gap-3 border-b border-white/10 bg-[#0A0E17]/90 px-3 backdrop-blur-md md:px-4">
      <div className="flex min-w-0 items-center gap-3">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-blue-600 via-indigo-600 to-purple-600 text-sm font-bold text-white shadow-lg shadow-blue-500/25">
          <Network size={16} />
        </div>
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="truncate text-sm font-bold tracking-tight text-white">GraphRAG Studio</span>
            <span className="hidden whitespace-nowrap rounded border border-blue-500/30 bg-blue-500/20 px-1.5 py-0.5 font-mono text-[9px] font-semibold uppercase tracking-wider text-blue-300 sm:inline">
              v1.0
            </span>
            <span
              className={`whitespace-nowrap rounded border px-1.5 py-0.5 font-mono text-[9px] font-semibold uppercase tracking-wider ${
                source === "api"
                  ? "border-emerald-500/30 bg-emerald-500/15 text-emerald-300"
                  : "border-amber-500/40 bg-amber-500/15 text-amber-300"
              }`}
              title={
                source === "api"
                  ? "Connected to the FastAPI graph engine"
                  : "Backend unreachable — the bundled seed graph and local reasoning engine are in use"
              }
            >
              {source === "api" ? "live api" : "demo data"}
            </span>
          </div>
          <p className="hidden truncate text-[10px] text-slate-500 lg:block">
            Hybrid graph retrieval · PPR · cascade simulation
          </p>
        </div>
      </div>

      <div className="hidden items-center gap-2 font-mono text-[11px] lg:flex">
        <StatPill icon={<Layers size={11} className="text-slate-600" />} value={nodeCount} label="Nodes" dotClass="bg-emerald-400" />
        <StatPill icon={<Activity size={11} className="text-slate-600" />} value={edgeCount} label="Edges" dotClass="bg-blue-400" />
        <StatPill icon={<Database size={11} className="text-slate-600" />} value={communityCount} label="Clusters" dotClass="bg-purple-400" />
        <StatPill icon={<FileText size={11} className="text-slate-600" />} value={documentCount} label="Docs" dotClass="bg-amber-400" />
        <div
          className="flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 text-[10px] font-semibold text-emerald-400"
          title="Measured requestAnimationFrame rate"
        >
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse-slow" />
          {fps > 0 ? `${fps} FPS` : "— FPS"}
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-2">
        <div
          className="mr-1 flex items-center gap-2 font-mono text-[10px] text-slate-400 lg:hidden"
          aria-label={`${nodeCount} nodes, ${edgeCount} edges, ${communityCount} clusters, ${documentCount} documents, ${fps} frames per second`}
        >
          <span className="flex items-center gap-1" title="Nodes">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
            {nodeCount}
          </span>
          <span className="flex items-center gap-1" title="Edges">
            <span className="h-1.5 w-1.5 rounded-full bg-blue-400" />
            {edgeCount}
          </span>
          <span className="flex items-center gap-1" title="Clusters">
            <span className="h-1.5 w-1.5 rounded-full bg-purple-400" />
            {communityCount}
          </span>
          <span className="flex items-center gap-1" title="Documents">
            <span className="h-1.5 w-1.5 rounded-full bg-amber-400" />
            {documentCount}
          </span>
          <span className="flex items-center gap-1 text-emerald-400" title="Measured requestAnimationFrame rate">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse-slow" />
            {fps > 0 ? `${fps} FPS` : "— FPS"}
          </span>
        </div>
        <button
          type="button"
          onClick={() => setIngestionOpen(true)}
          className="flex items-center gap-1.5 rounded-lg bg-blue-600 px-2.5 py-1.5 text-[11px] font-semibold text-white shadow-md shadow-blue-600/25 transition-colors hover:bg-blue-500 sm:px-3"
        >
          <Upload size={12} />
          <span className="hidden sm:inline">Ingest Document</span>
          <span className="sm:hidden">Ingest</span>
        </button>
        <button
          type="button"
          onClick={() => {
            actions?.fit();
          }}
          disabled={!actions}
          className="rounded-lg border border-white/10 bg-slate-800/80 px-2.5 py-1.5 text-[11px] font-medium text-slate-300 transition-colors hover:bg-slate-700 hover:text-white disabled:opacity-40"
        >
          Fit View
        </button>
        <button
          type="button"
          onClick={() => {
            setQueryText("");
            const input = document.getElementById("omnibar-input") as HTMLInputElement | null;
            input?.focus();
            input?.select();
          }}
          className="hidden rounded-lg border border-white/10 bg-slate-800/80 px-2 py-1.5 font-mono text-[10px] text-slate-400 transition-colors hover:text-white lg:block"
          title="Focus the command bar (press /)"
        >
          ⌘K
        </button>
      </div>
    </header>
  );
}
