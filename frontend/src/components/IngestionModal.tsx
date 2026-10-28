"use client";

import { CheckCircle2, Circle, FileText, Loader2, UploadCloud, X, XCircle } from "lucide-react";
import { useRef, useState } from "react";

import { useIngestion } from "@/hooks/useIngestion";
import { useGraphStore } from "@/store/useGraphStore";

const STAGES = [
  { key: "PARSING", label: "Page Parser (PyMuPDF)", index: 1 },
  { key: "CHUNKING", label: "Token Chunker", index: 2 },
  { key: "EXTRACTING", label: "Structured Extraction", index: 3 },
  { key: "RESOLVING", label: "Entity Resolution", index: 4 },
  { key: "INDEXING", label: "Graph + Vector Index", index: 5 },
  { key: "CLUSTERING", label: "Community Detection", index: 6 },
];

const STATUS_ORDER = [
  "IDLE",
  "PARSING",
  "CHUNKING",
  "EXTRACTING",
  "RESOLVING",
  "INDEXING",
  "CLUSTERING",
  "COMPLETED",
];

export function IngestionModal() {
  const ingestion = useGraphStore((state) => state.ingestion);
  const setIngestionOpen = useGraphStore((state) => state.setIngestionOpen);
  const resetIngestion = useGraphStore((state) => state.resetIngestion);
  const { start } = useIngestion();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  if (!ingestion.open) return null;

  const currentIndex = STATUS_ORDER.indexOf(ingestion.stage);
  const failed = Boolean(ingestion.error) || ingestion.stage === "FAILED";

  const handleFiles = (files: FileList | null) => {
    const file = files?.[0];
    if (file) void start(file);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 backdrop-blur-md">
      <div className="glass-panel-strong rise-in w-full max-w-lg space-y-4 rounded-3xl p-5">
        <div className="flex items-start justify-between border-b border-white/10 pb-3.5">
          <div className="flex items-center gap-2.5">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-blue-600 to-indigo-600 text-white shadow-lg shadow-blue-600/25">
              <UploadCloud size={17} />
            </span>
            <div>
              <h3 className="text-[13px] font-bold text-white">Real-time ingestion pipeline</h3>
              <p className="font-mono text-[10px] text-slate-400">
                {ingestion.filename ?? "PDF · Markdown · TXT · CSV"}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => setIngestionOpen(false)}
            className="rounded-lg p-1 text-slate-400 transition-colors hover:bg-white/10 hover:text-white"
            aria-label="Close ingestion modal"
          >
            <X size={15} />
          </button>
        </div>

        {!ingestion.filename && (
          <div
            onDragOver={(event) => {
              event.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(event) => {
              event.preventDefault();
              setDragging(false);
              handleFiles(event.dataTransfer.files);
            }}
            onClick={() => inputRef.current?.click()}
            className={`cursor-pointer rounded-2xl border-2 border-dashed px-5 py-9 text-center transition-colors ${
              dragging
                ? "border-blue-400/70 bg-blue-500/10"
                : "border-white/15 bg-white/[0.02] hover:border-blue-500/40 hover:bg-white/[0.04]"
            }`}
          >
            <FileText size={22} className="mx-auto text-slate-500" />
            <p className="mt-2.5 text-[11.5px] font-semibold text-slate-200">
              Drop a document or click to browse
            </p>
            <p className="mt-1 text-[10px] text-slate-500">
              Extraction, resolution, Cypher UNWIND and community detection run automatically
            </p>
            <input
              ref={inputRef}
              type="file"
              accept=".pdf,.txt,.md,.markdown,.csv"
              className="hidden"
              onChange={(event) => handleFiles(event.target.files)}
            />
          </div>
        )}

        {ingestion.filename && (
          <>
            <div>
              <div className="mb-1.5 flex items-center justify-between font-mono text-[10px]">
                <span className={failed ? "text-rose-400" : ingestion.completed ? "text-emerald-400" : "text-blue-400"}>
                  {ingestion.completed
                    ? "Ingestion complete"
                    : failed
                      ? "Pipeline failed"
                      : ingestion.stage === "UPLOADING"
                        ? "Uploading document"
                        : ingestion.stage}
                </span>
                <span className="font-bold text-white">{ingestion.percent}%</span>
              </div>
              <div className="h-2.5 w-full overflow-hidden rounded-full bg-slate-800">
                <div
                  className={`relative h-full overflow-hidden rounded-full transition-all duration-300 ${
                    failed
                      ? "bg-gradient-to-r from-rose-600 to-rose-400"
                      : "bg-gradient-to-r from-blue-500 via-indigo-500 to-emerald-400"
                  }`}
                  style={{ width: `${Math.max(2, ingestion.percent)}%` }}
                >
                  {!failed && !ingestion.completed && <span className="sweep absolute inset-0" />}
                </div>
              </div>
              {ingestion.uploadPercent > 0 && ingestion.uploadPercent < 100 && (
                <p className="mt-1 font-mono text-[9px] text-slate-500">
                  upload {ingestion.uploadPercent}%
                </p>
              )}
            </div>

            <div className="grid grid-cols-2 gap-x-3 gap-y-1.5 font-mono text-[10px]">
              {STAGES.map((stage) => {
                const stageIndex = STATUS_ORDER.indexOf(stage.key);
                const state =
                  currentIndex > stageIndex
                    ? "done"
                    : currentIndex === stageIndex
                      ? "active"
                      : "pending";
                return (
                  <div
                    key={stage.key}
                    className={`flex items-center gap-1.5 ${
                      state === "done"
                        ? "text-emerald-400"
                        : state === "active"
                          ? "font-semibold text-blue-400"
                          : "text-slate-600"
                    }`}
                  >
                    {state === "done" ? (
                      <CheckCircle2 size={11} />
                    ) : state === "active" ? (
                      <Loader2 size={11} className="animate-spin" />
                    ) : (
                      <Circle size={9} />
                    )}
                    <span className="truncate">{stage.label}</span>
                  </div>
                );
              })}
            </div>

            <div className="grid grid-cols-3 gap-2 rounded-2xl border border-white/10 bg-slate-900 p-3 text-center font-mono text-[10px]">
              <div>
                <div className="text-[8.5px] uppercase tracking-wider text-slate-500">Chunks</div>
                <div className="mt-0.5 font-bold text-white">
                  {ingestion.processedChunks}/{ingestion.totalChunks || "—"}
                </div>
              </div>
              <div>
                <div className="text-[8.5px] uppercase tracking-wider text-slate-500">Entities</div>
                <div className="mt-0.5 font-bold text-emerald-400">{ingestion.entities}</div>
              </div>
              <div>
                <div className="text-[8.5px] uppercase tracking-wider text-slate-500">Relations</div>
                <div className="mt-0.5 font-bold text-blue-400">{ingestion.relationships}</div>
              </div>
            </div>

            {ingestion.completed && (
              <p
                className={`rounded-xl border px-3 py-2 font-mono text-[10px] ${
                  ingestion.nodesAdded > 0
                    ? "border-emerald-500/25 bg-emerald-500/10 text-emerald-300"
                    : "border-amber-500/25 bg-amber-500/10 text-amber-300"
                }`}
              >
                {ingestion.nodesAdded > 0
                  ? `Graph rebuilt · ${ingestion.nodesAdded} nodes · ${ingestion.edgesAdded} edges${
                      ingestion.documentCount > 0
                        ? ` · ${ingestion.documentCount} document${ingestion.documentCount === 1 ? "" : "s"}`
                        : ""
                    }`
                  : `No entities extracted — the previous graph was cleared${
                      ingestion.documentCount > 0
                        ? ` (${ingestion.documentCount} document${ingestion.documentCount === 1 ? "" : "s"})`
                        : ""
                    }`}
              </p>
            )}

            {ingestion.error && (
              <div className="flex items-start gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 p-2.5 text-[10px] leading-relaxed text-rose-300">
                <XCircle size={13} className="mt-0.5 shrink-0" />
                <span>{ingestion.error}</span>
              </div>
            )}
          </>
        )}

        <div className="flex items-center justify-between gap-2 pt-1">
          {ingestion.filename && !ingestion.running ? (
            <button
              type="button"
              onClick={() => {
                resetIngestion();
                window.setTimeout(() => inputRef.current?.click(), 80);
              }}
              className="rounded-lg border border-white/10 bg-slate-800 px-3 py-1.5 text-[10.5px] font-medium text-slate-300 transition-colors hover:bg-slate-700"
            >
              Ingest another
            </button>
          ) : (
            <span className="font-mono text-[9px] uppercase tracking-wider text-slate-600">
              {ingestion.running ? "you can close this — the job keeps running" : "max 25 MB"}
            </span>
          )}
          <button
            type="button"
            onClick={() => setIngestionOpen(false)}
            className="rounded-xl bg-blue-600 px-4 py-1.5 text-[10.5px] font-semibold text-white transition-colors hover:bg-blue-500"
          >
            {ingestion.running ? "Run in background" : "Close"}
          </button>
        </div>
      </div>
    </div>
  );
}
