"use client";

import { useCallback, useRef } from "react";

import { runQueryStream, simulateImpact } from "@/lib/api";
import { simulateLocalImpact, streamLocalQuery } from "@/lib/localEngine";
import type { QueryMode } from "@/lib/types";
import { useGraphStore } from "@/store/useGraphStore";

export interface RunQueryOptions {
  query?: string;
  mode?: QueryMode | null;
}

/** Runs a query against the API, transparently falling back to the local engine. */
export function useQueryRunner() {
  const abortRef = useRef<AbortController | null>(null);

  const run = useCallback(async (options: RunQueryOptions = {}) => {
    const store = useGraphStore.getState();
    const viewport = store.viewport;
    const text = (options.query ?? store.query.text).trim();
    if (!text || !viewport) return;

    const mode = options.mode !== undefined ? options.mode : store.query.mode;
    const timeRange = store.timeRange;
    const apiReady = store.source === "api";

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    store.clearHighlight();
    store.beginQuery(text);
    store.setQueryText(text);
    if (mode) store.setQueryContext({ mode });
    if (mode === "IMPACT") store.setDrawerTab("impact");

    const applyImpact = async (seedId: string) => {
      store.setImpactLoading(true);
      try {
        const impact = apiReady
          ? await simulateImpact(seedId).catch(() => simulateLocalImpact(viewport, seedId))
          : simulateLocalImpact(viewport, seedId);
        if (!controller.signal.aborted) store.setImpact(impact);
      } catch {
        if (!controller.signal.aborted) store.setImpact(null);
      } finally {
        store.setImpactLoading(false);
      }
    };

    if (apiReady) {
      let contextReceived = false;
      let completed = false;
      let streamError: string | null = null;
      try {
        await runQueryStream(
          {
            query: text,
            mode,
            timeRange,
            signal: controller.signal,
          },
          {
            onContext: (context) => {
              contextReceived = true;
              store.setHighlight({
                nodeIds: new Set(context.highlighted_node_ids),
                edgeIds: new Set(context.highlighted_edge_ids),
                pathNodeIds: context.path_node_ids,
                pathEdgeIds: context.path_edge_ids,
                seedNodeIds: new Set(context.seed_node_ids),
                mode: context.mode,
                explanation: context.explanation,
                confidence: context.confidence,
                elapsedMs: context.elapsed_ms,
              });
              store.setQueryContext({
                mode: context.mode,
                explanation: context.explanation,
                elapsedMs: context.elapsed_ms,
                confidence: context.confidence,
              });
              if (context.mode === "IMPACT" && context.seed_node_ids[0]) {
                void applyImpact(context.seed_node_ids[0]);
              }
            },
            onToken: (token) => store.appendToken(token),
            onComplete: (complete) => {
              completed = true;
              store.completeQuery({
                citations: complete.citations,
                confidence: complete.confidence,
                elapsedMs: complete.duration_ms,
                mode: complete.mode,
              });
            },
            onError: (message) => {
              streamError = message;
            },
          },
        );
      } catch (error) {
        if (controller.signal.aborted) return;
        if (contextReceived) {
          const message = error instanceof Error ? error.message : "Query failed";
          store.failQuery(message);
          return;
        }
        store.showToast("API unreachable — answering with the local reasoning engine", "info");
      }

      if (controller.signal.aborted) return;
      if (streamError) {
        store.failQuery(streamError);
        return;
      }
      if (completed) return;
      if (contextReceived) {
        store.failQuery("The response stream ended unexpectedly");
        return;
      }
    }

    try {
      await streamLocalQuery(
        { query: text, mode, timeRange, viewport },
        {
          onContext: (context) => {
            store.setHighlight({
              nodeIds: new Set(context.highlighted_node_ids),
              edgeIds: new Set(context.highlighted_edge_ids),
              pathNodeIds: context.path_node_ids,
              pathEdgeIds: context.path_edge_ids,
              seedNodeIds: new Set(context.seed_node_ids),
              mode: context.mode,
              explanation: context.explanation,
              confidence: context.confidence,
              elapsedMs: context.elapsed_ms,
            });
            store.setQueryContext({
              mode: context.mode,
              explanation: context.explanation,
              elapsedMs: context.elapsed_ms,
              confidence: context.confidence,
            });
            if (context.mode === "IMPACT" && context.seed_node_ids[0]) {
              void applyImpact(context.seed_node_ids[0]);
            }
          },
          onToken: (token) => store.appendToken(token),
          onComplete: (complete) => {
            if (controller.signal.aborted) return;
            store.completeQuery({
              citations: complete.citations,
              confidence: complete.confidence,
              elapsedMs: complete.duration_ms,
              mode: complete.mode,
            });
          },
        },
        controller.signal,
      );
    } catch (error) {
      if (controller.signal.aborted) return;
      store.failQuery(error instanceof Error ? error.message : "Local reasoning failed");
    }
  }, []);

  const cancel = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
  }, []);

  return { run, cancel };
}

/** Standalone cascade simulation used by the Impact drawer tab. */
export function useImpactSimulation() {
  const runImpact = useCallback(async (nodeId: string) => {
    const store = useGraphStore.getState();
    const viewport = store.viewport;
    if (!viewport) return;

    store.setImpactLoading(true);
    store.setDrawerTab("impact");
    store.selectNode(nodeId);
    try {
      const impact =
        store.source === "api"
          ? await simulateImpact(nodeId).catch(() => simulateLocalImpact(viewport, nodeId))
          : simulateLocalImpact(viewport, nodeId);
      store.setImpact(impact);
      store.hoverNode(null);
    } catch (error) {
      store.setImpact(null);
      store.showToast(error instanceof Error ? error.message : "Simulation failed", "error");
    } finally {
      store.setImpactLoading(false);
    }
  }, []);

  return { runImpact };
}
