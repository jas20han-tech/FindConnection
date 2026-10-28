"use client";

import { Pause, Play } from "lucide-react";
import { useEffect } from "react";

import { useGraphStore } from "@/store/useGraphStore";

export function TimelineScrubber() {
  const timeRange = useGraphStore((state) => state.timeRange);
  const activeYear = useGraphStore((state) => state.activeYear);
  const setActiveYear = useGraphStore((state) => state.setActiveYear);
  const playing = useGraphStore((state) => state.playing);
  const setPlaying = useGraphStore((state) => state.setPlaying);
  const visibleEdges = useGraphStore((state) => state.highlight.edgeIds.size);

  useEffect(() => {
    if (!playing) return;
    const timer = setInterval(() => {
      const store = useGraphStore.getState();
      const next = store.activeYear + 1;
      store.setActiveYear(next);
      if (next >= store.timeRange[1]) store.setPlaying(false);
    }, 750);
    return () => clearInterval(timer);
  }, [playing]);

  const [minYear, maxYear] = timeRange;

  return (
    <div className="pointer-events-auto absolute left-1/2 top-4 z-20 flex -translate-x-1/2 items-center gap-3 rounded-2xl border border-purple-500/30 bg-[#0A0E17]/90 px-4 py-2 shadow-glass backdrop-blur-xl">
      <button
        type="button"
        onClick={() => {
          if (activeYear >= maxYear) setActiveYear(minYear);
          setPlaying(!playing);
        }}
        className="flex h-7 w-7 items-center justify-center rounded-full bg-purple-600 text-white shadow-md transition-colors hover:bg-purple-500"
        aria-label={playing ? "Pause timeline" : "Play timeline"}
      >
        {playing ? <Pause size={11} /> : <Play size={11} className="ml-0.5" />}
      </button>
      <span className="whitespace-nowrap font-mono text-[10px] text-slate-500">{minYear}</span>
      <input
        type="range"
        className="timeline w-36 cursor-pointer sm:w-56"
        min={minYear}
        max={maxYear}
        step={1}
        value={activeYear}
        onChange={(event) => {
          setPlaying(false);
          setActiveYear(Number(event.target.value));
        }}
        aria-label="Timeline year"
      />
      <span className="w-9 whitespace-nowrap font-mono text-[11px] font-bold text-purple-300">{activeYear}</span>
      <span className="hidden whitespace-nowrap rounded border border-purple-500/25 bg-purple-500/15 px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider text-purple-300 lg:block">
        live diff
      </span>
      <span className="hidden whitespace-nowrap font-mono text-[9px] text-slate-500 xl:block">
        {visibleEdges} highlighted
      </span>
    </div>
  );
}
