"use client";

import { Maximize2, Minus, Pause, Play, Plus } from "lucide-react";

import { useGraphStore } from "@/store/useGraphStore";

export function GraphControls() {
  const actions = useGraphStore((state) => state.graphActions);
  const physicsRunning = useGraphStore((state) => state.physicsRunning);

  const button =
    "flex h-8 w-8 items-center justify-center rounded-lg text-slate-300 transition-colors hover:bg-white/10 hover:text-white disabled:cursor-not-allowed disabled:opacity-40";

  return (
    <div className="pointer-events-auto absolute bottom-28 right-4 z-20 flex flex-col gap-1 rounded-xl border border-white/10 bg-[#0A0E17]/85 p-1 backdrop-blur-md shadow-glass">
      <button
        type="button"
        className={button}
        title="Zoom in"
        aria-label="Zoom in"
        disabled={!actions}
        onClick={() => actions?.zoomIn()}
      >
        <Plus size={15} />
      </button>
      <button
        type="button"
        className={button}
        title="Zoom out"
        aria-label="Zoom out"
        disabled={!actions}
        onClick={() => actions?.zoomOut()}
      >
        <Minus size={15} />
      </button>
      <button
        type="button"
        className={button}
        title="Fit graph to view"
        aria-label="Fit graph to view"
        disabled={!actions}
        onClick={() => actions?.fit()}
      >
        <Maximize2 size={14} />
      </button>
      <div className="my-0.5 h-px bg-white/10" />
      <button
        type="button"
        className={button}
        title={physicsRunning ? "Pause layout physics" : "Resume layout physics"}
        aria-label={physicsRunning ? "Pause layout physics" : "Resume layout physics"}
        disabled={!actions}
        onClick={() => {
          actions?.togglePhysics();
        }}
      >
        {physicsRunning ? <Pause size={14} /> : <Play size={14} />}
      </button>
    </div>
  );
}
