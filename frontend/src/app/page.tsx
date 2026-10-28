"use client";

import { PanelRight } from "lucide-react";
import dynamic from "next/dynamic";
import { useEffect, useState } from "react";

import { CommandBar } from "@/components/CommandBar";
import { EntityDrawer } from "@/components/EntityDrawer";
import { IngestionModal } from "@/components/IngestionModal";
import { LayerPanel } from "@/components/LayerPanel";
import { TelemetryHeader } from "@/components/TelemetryHeader";
import { TimelineScrubber } from "@/components/TimelineScrubber";
import { ToastHost } from "@/components/ToastHost";
import { useGraphData } from "@/hooks/useGraphData";
import { useGraphStore } from "@/store/useGraphStore";

// Sigma touches WebGL at module scope, so the canvas is client-only.
const GraphCanvas = dynamic(
  () => import("@/components/GraphCanvas").then((module) => module.GraphCanvas),
  {
    ssr: false,
    loading: () => (
      <div className="dot-grid absolute inset-0 flex items-center justify-center">
        <div className="flex flex-col items-center gap-3">
          <div className="h-7 w-7 animate-spin rounded-full border-2 border-blue-500/30 border-t-blue-400" />
          <span className="font-mono text-[10px] uppercase tracking-[0.24em] text-slate-500">
            initialising WebGL renderer
          </span>
        </div>
      </div>
    ),
  },
);

export default function WorkspacePage() {
  useGraphData();
  const [drawerOpen, setDrawerOpen] = useState(false);

  const queryMode = useGraphStore((state) => state.query.mode);
  const highlightMode = useGraphStore((state) => state.highlight.mode);
  const selectedNodeId = useGraphStore((state) => state.selectedNodeId);
  const streaming = useGraphStore((state) => state.query.status === "streaming");
  const showTimeline = (queryMode ?? highlightMode) === "TEMPORAL";

  useEffect(() => {
    if (selectedNodeId) setDrawerOpen(true);
  }, [selectedNodeId]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        const store = useGraphStore.getState();
        if (store.selectedNodeId) store.selectNode(null);
        else setDrawerOpen(false);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  return (
    <div className="flex h-screen w-screen flex-col overflow-hidden bg-[#07090E]">
      <TelemetryHeader />

      <div className="relative flex min-h-0 flex-1 overflow-hidden">
        <main className="relative min-w-0 flex-1 overflow-hidden">
          <GraphCanvas />
          <LayerPanel />

          {showTimeline && <TimelineScrubber />}

          <CommandBar />

          <button
            type="button"
            onClick={() => setDrawerOpen(true)}
            className={`absolute right-4 top-4 z-20 flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-[10px] font-semibold backdrop-blur-md transition-colors xl:hidden ${
              streaming
                ? "border-emerald-500/40 bg-emerald-500/15 text-emerald-300"
                : "border-white/10 bg-[#0A0E17]/85 text-slate-300 hover:text-white"
            }`}
          >
            <PanelRight size={12} />
            Context
          </button>
        </main>

        <EntityDrawer overlayOpen={drawerOpen} onCloseOverlay={() => setDrawerOpen(false)} />
      </div>

      <IngestionModal />
      <ToastHost />
    </div>
  );
}
