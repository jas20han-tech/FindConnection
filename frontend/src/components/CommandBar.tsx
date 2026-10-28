"use client";

import { CornerDownLeft, Loader2, Search, Sparkles, Square } from "lucide-react";
import { useEffect, useRef } from "react";

import { useQueryRunner } from "@/hooks/useQueryRunner";
import type { QueryMode } from "@/lib/types";
import { useGraphStore } from "@/store/useGraphStore";

const MODES: { id: QueryMode; label: string; icon: string; prompt: string }[] = [
  {
    id: "CONNECTION",
    label: "Connection Path",
    icon: "🔗",
    prompt: "How does Sundar Pichai connect to the EU AI Act?",
  },
  {
    id: "IMPACT",
    label: "Impact Simulation",
    icon: "💀",
    prompt: "What happens if Google LLC ceases operations?",
  },
  {
    id: "TEMPORAL",
    label: "Temporal Scrubber",
    icon: "⏳",
    prompt: "Show the timeline progression of foundation models and regulations",
  },
  {
    id: "GLOBAL",
    label: "Global Summary",
    icon: "🌍",
    prompt: "Summarize the primary AI ecosystem clusters and monopolies",
  },
];

const DEFAULT_QUERY = MODES[0].prompt;

export function CommandBar() {
  const inputRef = useRef<HTMLInputElement>(null);
  const bootstrapped = useRef(false);

  const viewport = useGraphStore((state) => state.viewport);
  const query = useGraphStore((state) => state.query);
  const setQueryText = useGraphStore((state) => state.setQueryText);
  const setQueryContext = useGraphStore((state) => state.setQueryContext);
  const { run, cancel } = useQueryRunner();

  useEffect(() => {
    if (!viewport || bootstrapped.current) return;
    bootstrapped.current = true;
    setQueryText(DEFAULT_QUERY);
    void run({ query: DEFAULT_QUERY, mode: "CONNECTION" });
  }, [viewport, run, setQueryText]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const isShortcut = (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k";
      const isSlash =
        event.key === "/" &&
        !(event.target instanceof HTMLInputElement) &&
        !(event.target instanceof HTMLTextAreaElement);
      if (isShortcut || isSlash) {
        event.preventDefault();
        inputRef.current?.focus();
        inputRef.current?.select();
      }
      if (event.key === "Escape" && document.activeElement === inputRef.current) {
        inputRef.current?.blur();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const activeMode = query.mode;
  const streaming = query.status === "streaming";
  const disabled = !viewport;

  const submit = () => {
    if (streaming) return;
    void run({ query: query.text, mode: query.mode });
  };

  const activateMode = (mode: QueryMode, prompt: string) => {
    setQueryContext({ mode });
    setQueryText(prompt);
    inputRef.current?.focus();
  };

  return (
    <div className="pointer-events-auto absolute bottom-5 left-1/2 z-20 w-[min(94%,42rem)] -translate-x-1/2">
      <div className="flex flex-col gap-2 rounded-2xl border border-white/15 bg-[#0A0E17]/92 p-2.5 shadow-2xl backdrop-blur-xl">
        <div className="flex items-center gap-2 px-1.5">
          <Sparkles size={14} className={streaming ? "text-emerald-400" : "text-blue-400"} />
          <input
            id="omnibar-input"
            ref={inputRef}
            value={query.text}
            onChange={(event) => setQueryText(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                submit();
              }
            }}
            placeholder="Ask about connections, cascades, timelines or the whole ecosystem…"
            className="w-full bg-transparent text-xs font-medium text-white placeholder-slate-500 outline-none sm:text-[13px]"
            disabled={disabled}
            aria-label="Graph query"
            autoComplete="off"
            spellCheck={false}
          />
          {streaming ? (
            <button
              type="button"
              onClick={cancel}
              className="flex items-center gap-1 rounded-md border border-rose-500/30 bg-rose-500/15 px-2 py-1 font-mono text-[10px] font-semibold text-rose-300 transition-colors hover:bg-rose-500/25"
            >
              <Square size={9} /> stop
            </button>
          ) : (
            <button
              type="button"
              onClick={submit}
              disabled={disabled}
              className="flex items-center gap-1 rounded-md bg-blue-600 px-2 py-1 font-mono text-[10px] font-semibold text-white transition-colors hover:bg-blue-500 disabled:opacity-40"
            >
              <CornerDownLeft size={10} /> run
            </button>
          )}
          <kbd className="hidden rounded border border-white/10 bg-slate-800/80 px-1.5 py-0.5 font-mono text-[10px] text-slate-400 sm:block">
            ⌘K
          </kbd>
        </div>

        <div className="flex items-center gap-1.5 overflow-x-auto border-t border-white/10 pt-2">
          {MODES.map((mode) => {
            const active = activeMode === mode.id;
            return (
              <button
                key={mode.id}
                type="button"
                onClick={() => activateMode(mode.id, mode.prompt)}
                className={`flex shrink-0 items-center gap-1.5 rounded-lg border px-2.5 py-1 text-[10.5px] font-medium transition-colors ${
                  active
                    ? "border-blue-500/40 bg-blue-600 text-white shadow-sm shadow-blue-600/30"
                    : "border-white/10 bg-slate-800/60 text-slate-400 hover:bg-slate-800 hover:text-white"
                }`}
              >
                <span aria-hidden>{mode.icon}</span>
                {mode.label}
              </button>
            );
          })}
          <span className="ml-auto hidden shrink-0 items-center gap-1 font-mono text-[9px] uppercase tracking-wider text-slate-600 sm:flex">
            {streaming ? (
              <>
                <Loader2 size={9} className="animate-spin" /> synthesising
              </>
            ) : (
              <>
                <Search size={9} /> {query.citations.length} citations
              </>
            )}
          </span>
        </div>
      </div>
    </div>
  );
}
