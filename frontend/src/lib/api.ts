/**
 * HTTP + SSE client for the FastAPI backend.
 *
 * Every call is best-effort: `fetchGraph` returns `null` (rather than throwing) when the
 * API is unreachable so the workspace can fall back to the bundled demo graph, and the
 * query runner falls back to `localEngine` instead of surfacing a network error.
 */

import type {
  EntitySearchResult,
  GraphViewport,
  ImpactResult,
  JobProgress,
  QueryCompleteEvent,
  QueryContextEvent,
  QueryMode,
  UploadResponse,
} from "./types";

const API_BASE = (process.env.NEXT_PUBLIC_API_URL ?? "").replace(/\/$/, "") + "/api/v1";
const HEALTH_URL = (process.env.NEXT_PUBLIC_API_URL ?? "").replace(/\/$/, "") + "/health";

const GRAPH_TIMEOUT_MS = 4000;

export interface HealthSnapshot {
  status: string;
  demo_mode: boolean;
  llm_enabled: boolean;
  celery_enabled: boolean;
  graph: { backend?: string; status?: string } & Record<string, unknown>;
  postgres: { status: string };
  redis: { status: string };
  vectors: { status: string };
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  timeoutMs = 15000,
): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      ...init,
      signal: init.signal ?? controller.signal,
      headers: {
        Accept: "application/json",
        ...(init.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
        ...init.headers,
      },
    });
    if (!response.ok) {
      let detail = `${response.status} ${response.statusText}`;
      try {
        const payload = (await response.json()) as { detail?: string };
        if (payload?.detail) detail = payload.detail;
      } catch {
        /* ignore non-JSON error bodies */
      }
      throw new Error(detail);
    }
    return (await response.json()) as T;
  } finally {
    clearTimeout(timer);
  }
}

export async function fetchHealth(): Promise<HealthSnapshot | null> {
  try {
    const response = await fetch(HEALTH_URL, {
      signal: AbortSignal.timeout(2500),
      cache: "no-store",
    });
    if (!response.ok) return null;
    return (await response.json()) as HealthSnapshot;
  } catch {
    return null;
  }
}

export async function fetchGraph(limit = 600): Promise<GraphViewport | null> {
  try {
    return await request<GraphViewport>(`/graph/viewport?limit=${limit}`, { cache: "no-store" }, GRAPH_TIMEOUT_MS);
  } catch {
    return null;
  }
}

export async function searchEntities(query: string, limit = 8): Promise<EntitySearchResult[]> {
  if (!query.trim()) return [];
  try {
    return await request<EntitySearchResult[]>(
      `/entity/search?q=${encodeURIComponent(query)}&limit=${limit}`,
      { cache: "no-store" },
      3000,
    );
  } catch {
    return [];
  }
}

export async function simulateImpact(nodeId: string): Promise<ImpactResult> {
  return request<ImpactResult>("/simulate/impact", {
    method: "POST",
    body: JSON.stringify({ node_id: nodeId }),
  });
}

export interface QueryStreamHandlers {
  onContext: (context: QueryContextEvent) => void;
  onToken: (text: string) => void;
  onComplete: (complete: QueryCompleteEvent) => void;
  onError?: (message: string) => void;
}

export interface QueryStreamOptions {
  query: string;
  mode?: QueryMode | null;
  timeRange: [number, number];
  maxHops?: number;
  maxNodes?: number;
  signal?: AbortSignal;
}

interface SseEvent {
  event: string;
  data: unknown;
}

function parseSseBlock(block: string): SseEvent | null {
  let event = "message";
  const dataLines: string[] = [];
  for (const rawLine of block.split("\n")) {
    const line = rawLine.replace(/\r$/, "");
    if (line.startsWith(":")) continue;
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
  }
  if (!dataLines.length) return null;
  const raw = dataLines.join("\n");
  try {
    return { event, data: JSON.parse(raw) };
  } catch {
    return null;
  }
}

async function readSse(
  response: Response,
  onEvent: (event: SseEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  if (!response.body) throw new Error("Streaming is not supported by this browser");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    if (signal?.aborted) {
      await reader.cancel();
      return;
    }
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let boundary = buffer.indexOf("\n\n");
    while (boundary >= 0) {
      const block = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const parsed = parseSseBlock(block);
      if (parsed) onEvent(parsed);
      boundary = buffer.indexOf("\n\n");
    }
  }
  const trailing = parseSseBlock(buffer);
  if (trailing) onEvent(trailing);
}

export async function runQueryStream(
  options: QueryStreamOptions,
  handlers: QueryStreamHandlers,
): Promise<void> {
  const response = await fetch(`${API_BASE}/query/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({
      query: options.query,
      mode: options.mode ?? null,
      time_range: options.timeRange,
      max_hops: options.maxHops ?? 5,
      max_nodes: options.maxNodes ?? 40,
    }),
    signal: options.signal,
  });

  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload?.detail) message = payload.detail;
    } catch {
      /* ignore */
    }
    throw new Error(message);
  }

  await readSse(
    response,
    ({ event, data }) => {
      const payload = data as Record<string, unknown>;
      if (event === "graph_context") {
        handlers.onContext(payload as unknown as QueryContextEvent);
      } else if (event === "token") {
        handlers.onToken(String(payload.text ?? ""));
      } else if (event === "complete") {
        handlers.onComplete(payload as unknown as QueryCompleteEvent);
      } else if (event === "error") {
        handlers.onError?.(String(payload.message ?? "Query failed"));
      }
    },
    options.signal,
  );
}

export async function uploadDocument(
  file: File,
  onProgress?: (percent: number) => void,
): Promise<UploadResponse> {
  const form = new FormData();
  form.append("file", file);

  return new Promise<UploadResponse>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}/upload`);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && onProgress) {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    };
    xhr.onload = () => {
      try {
        const payload = JSON.parse(xhr.responseText) as UploadResponse & { detail?: string };
        if (xhr.status >= 200 && xhr.status < 300) resolve(payload);
        else reject(new Error(payload.detail ?? `Upload failed (${xhr.status})`));
      } catch {
        reject(new Error(`Upload failed (${xhr.status})`));
      }
    };
    xhr.onerror = () => reject(new Error("Network error while uploading"));
    xhr.send(form);
  });
}

export async function streamJobProgress(
  jobId: string,
  handlers: {
    onProgress: (job: JobProgress) => void;
    onError?: (message: string) => void;
  },
  signal?: AbortSignal,
): Promise<JobProgress | null> {
  const response = await fetch(`${API_BASE}/upload/${jobId}/stream`, {
    headers: { Accept: "text/event-stream" },
    signal,
    cache: "no-store",
  });
  if (!response.ok) throw new Error(`Unable to follow job ${jobId}`);

  let last: JobProgress | null = null;

  await readSse(
    response,
    ({ event, data }) => {
      const payload = data as Record<string, unknown>;
      if (event === "progress") {
        last = payload as unknown as JobProgress;
        handlers.onProgress(last);
      }
      if (event === "error") handlers.onError?.(String(payload.message ?? "Job failed"));
    },
    signal,
  );

  return last;
}

/** Fallback used when the SSE stream ends early (proxy buffering, reconnect, etc.). */
export async function fetchJobStatus(jobId: string): Promise<JobProgress | null> {
  try {
    return await request<JobProgress>(`/upload/${jobId}/status`, { cache: "no-store" }, 8000);
  } catch {
    return null;
  }
}

export async function resetGraph(): Promise<boolean> {
  try {
    await request<{ status: string }>("/graph/reset", { method: "POST" }, 20000);
    return true;
  } catch {
    return false;
  }
}

export function apiAvailable(viewport: GraphViewport | null): boolean {
  return Boolean(viewport && viewport.source !== "demo");
}
