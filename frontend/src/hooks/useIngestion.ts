"use client";

import { useCallback, useRef } from "react";

import { fetchGraph, fetchJobStatus, streamJobProgress, uploadDocument } from "@/lib/api";
import type { GraphViewport, JobProgress } from "@/lib/types";
import { useGraphStore } from "@/store/useGraphStore";

const ALLOWED = [".pdf", ".txt", ".md", ".markdown", ".csv"];
const TERMINAL = new Set(["COMPLETED", "FAILED"]);
const POLL_INTERVAL_MS = 900;
const POLL_ATTEMPTS = 140;
const REFRESH_ATTEMPTS = 6;

const delay = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

function isTerminal(job: JobProgress | null): boolean {
  return Boolean(job && TERMINAL.has(job.status));
}

/** Mirror a job snapshot into the ingestion panel. */
function applyJob(job: JobProgress) {
  const state = useGraphStore.getState();
  state.setIngestion({
    stage: job.status,
    percent: Math.round(job.percent),
    totalChunks: job.total_chunks,
    processedChunks: job.processed_chunks,
    entities: job.entities_extracted,
    relationships: job.relationships_extracted,
    nodesAdded: job.nodes_added ?? 0,
    edgesAdded: job.edges_added ?? 0,
    documentCount: job.document_count ?? state.ingestion.documentCount,
    running: !isTerminal(job),
    completed: job.status === "COMPLETED",
    error: job.error_message ?? null,
  });
}

/**
 * Poll the status endpoint. The SSE stream normally delivers the terminal event,
 * but proxies can close the stream early — this guarantees we still learn the outcome.
 */
async function pollJob(jobId: string, signal: AbortSignal): Promise<JobProgress | null> {
  for (let attempt = 0; attempt < POLL_ATTEMPTS; attempt += 1) {
    if (signal.aborted) return null;
    await delay(POLL_INTERVAL_MS);
    if (signal.aborted) return null;
    const job = await fetchJobStatus(jobId);
    if (!job) continue;
    applyJob(job);
    if (isTerminal(job)) return job;
  }
  return null;
}

export function useIngestion() {
  const abortRef = useRef<AbortController | null>(null);

  const start = useCallback(async (file: File) => {
    const store = useGraphStore.getState();
    const extension = `.${file.name.split(".").pop()?.toLowerCase() ?? ""}`;

    if (!ALLOWED.includes(extension)) {
      store.showToast("Upload a PDF, Markdown, CSV or plain-text document", "error");
      return;
    }
    if (store.source !== "api") {
      store.setIngestion({
        open: true,
        filename: file.name,
        error: "The ingestion pipeline needs the FastAPI backend. Start it with `uv run uvicorn app.main:app --port 8000`.",
        running: false,
        completed: false,
        stage: "OFFLINE",
        percent: 0,
      });
      return;
    }

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    store.setIngestion({
      open: true,
      filename: file.name,
      stage: "UPLOADING",
      percent: 1,
      uploadPercent: 0,
      totalChunks: 0,
      processedChunks: 0,
      entities: 0,
      relationships: 0,
      nodesAdded: 0,
      edgesAdded: 0,
      error: null,
      running: true,
      completed: false,
    });

    try {
      const upload = await uploadDocument(file, (percent) => {
        store.setIngestion({ uploadPercent: percent, percent: Math.min(8, Math.round(percent * 0.08)) });
      });

      store.setIngestion({ stage: "QUEUED", percent: 8, uploadPercent: 100 });

      let last: JobProgress | null = null;
      try {
        last = await streamJobProgress(
          upload.job_id,
          {
            onProgress: (job) => applyJob(job),
          },
          controller.signal,
        );
      } catch {
        if (controller.signal.aborted) return;
        // The stream can be cut by a proxy; the status endpoint is authoritative.
      }

      if (controller.signal.aborted) return;

      if (!isTerminal(last)) {
        last = await pollJob(upload.job_id, controller.signal);
      }

      if (controller.signal.aborted) return;

      if (!last) {
        throw new Error("Lost contact with the ingestion job — check the backend and try again");
      }

      if (last.status === "FAILED") {
        const message = last.error_message ?? "Ingestion failed";
        store.setIngestion({ running: false, error: message, stage: "FAILED" });
        store.showToast(message, "error");
        return;
      }

      // ---------------------------------------------------------------- refresh
      const beforeNodes = useGraphStore.getState().viewport?.stats.node_count ?? 0;
      let remote: GraphViewport | null = null;
      for (let attempt = 0; attempt < REFRESH_ATTEMPTS; attempt += 1) {
        remote = await fetchGraph();
        if (remote) break;
        await delay(400 * (attempt + 1));
      }
      if (remote) store.setViewport(remote, "api");

      const addedNodes =
        last.nodes_added ?? (remote ? Math.max(0, remote.stats.node_count - beforeNodes) : 0);
      const addedEdges = last.edges_added ?? 0;
      const totalNodes = remote?.stats.node_count ?? last.node_count ?? beforeNodes + addedNodes;
      const totalDocs =
        remote?.stats.document_count ??
        last.document_count ??
        useGraphStore.getState().ingestion.documentCount;

      store.setIngestion({
        running: false,
        completed: true,
        stage: "COMPLETED",
        percent: 100,
        nodesAdded: addedNodes,
        edgesAdded: addedEdges,
        documentCount: totalDocs,
      });

      // Frame the replacement graph so the new document fills the canvas instead of
      // leaving the camera on the previous layout.
      if (remote) {
        // The pre-ingest query highlighted a slice of the old graph; clear it so the
        // refreshed graph is fully lit.
        store.clearHighlight();
        window.setTimeout(() => useGraphStore.getState().graphActions?.fit(), 350);
      }

      const docLabel = totalDocs > 0 ? ` · ${totalDocs} document${totalDocs === 1 ? "" : "s"}` : "";
      if (addedNodes > 0 || addedEdges > 0) {
        store.showToast(
          `Graph rebuilt from ${file.name} — ${addedNodes} nodes, ${addedEdges} edges (${totalNodes} nodes${docLabel})`,
          "success",
        );
      } else {
        store.showToast(
          `Graph rebuilt from ${file.name} — no entities found; previous document removed`,
          "info",
        );
      }
    } catch (error) {
      if (controller.signal.aborted) return;
      const message = error instanceof Error ? error.message : "Ingestion failed";
      store.setIngestion({ running: false, error: message, stage: "FAILED" });
      store.showToast(message, "error");
    }
  }, []);

  return { start };
}
