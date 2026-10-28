"use client";

import { useCallback, useEffect } from "react";

import { fetchGraph } from "@/lib/api";
import { getDemoViewport } from "@/lib/colors";
import { useGraphStore } from "@/store/useGraphStore";

/**
 * Loads the graph once per page session. Tries the API first; on any failure the
 * bundled demo graph is used and the header switches to "demo data".
 */
export function useGraphData() {
  const viewport = useGraphStore((state) => state.viewport);
  const source = useGraphStore((state) => state.source);

  useEffect(() => {
    let alive = true;
    void loadGraph().then((result) => {
      if (!alive) return;
      useGraphStore.getState().setViewport(result.viewport, result.source);
    });
    return () => {
      alive = false;
    };
  }, []);

  const refresh = useCallback(async () => {
    const remote = await fetchGraph();
    if (remote) {
      useGraphStore.getState().setViewport(remote, "api");
      return true;
    }
    useGraphStore.getState().showToast("API unreachable — keeping the local graph", "error");
    return false;
  }, []);

  return { viewport, source, refresh };
}

let graphPromise: Promise<{
  viewport: ReturnType<typeof getDemoViewport>;
  source: "api" | "demo";
}> | null = null;

function loadGraph() {
  if (!graphPromise) {
    graphPromise = (async () => {
      const remote = await fetchGraph();
      if (remote) return { viewport: remote, source: "api" as const };
      return { viewport: getDemoViewport(), source: "demo" as const };
    })();
  }
  return graphPromise;
}
