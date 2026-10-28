"use client";

import { create } from "zustand";
import type {
  Citation,
  ColorMode,
  DrawerTab,
  EntityType,
  GraphViewport,
  ImpactResult,
  JobProgress,
  QueryMode,
} from "@/lib/types";

export type DataSource = "api" | "demo";

export interface HighlightState {
  nodeIds: Set<string>;
  edgeIds: Set<string>;
  pathNodeIds: string[];
  pathEdgeIds: string[];
  seedNodeIds: Set<string>;
  mode: QueryMode | null;
  explanation: string;
  confidence: number;
  elapsedMs: number;
}

export interface QueryState {
  text: string;
  status: "idle" | "streaming" | "complete" | "error";
  narrative: string;
  citations: Citation[];
  mode: QueryMode | null;
  explanation: string;
  elapsedMs: number;
  confidence: number;
  error: string | null;
}

export interface IngestionState {
  open: boolean;
  filename: string | null;
  stage: string;
  percent: number;
  uploadPercent: number;
  totalChunks: number;
  processedChunks: number;
  entities: number;
  relationships: number;
  nodesAdded: number;
  edgesAdded: number;
  documentCount: number;
  error: string | null;
  running: boolean;
  completed: boolean;
}

export interface Toast {
  id: number;
  message: string;
  tone: "info" | "success" | "error";
}

export interface GraphActions {
  zoomIn: () => void;
  zoomOut: () => void;
  fit: () => void;
  focus: (nodeId: string) => void;
  togglePhysics: () => void;
}

interface GraphStore {
  viewport: GraphViewport | null;
  source: DataSource;
  loading: boolean;
  fps: number;

  selectedNodeId: string | null;
  hoveredNodeId: string | null;
  hoveredEdgeId: string | null;

  highlight: HighlightState;
  query: QueryState;

  colorMode: ColorMode;
  hiddenTypes: Set<EntityType>;
  layers: { labels: boolean; edges: boolean; particles: boolean; minimap: boolean };
  physicsRunning: boolean;

  timeRange: [number, number];
  activeYear: number;
  playing: boolean;

  impact: ImpactResult | null;
  impactLoading: boolean;

  drawerTab: DrawerTab;
  ingestion: IngestionState;
  toast: Toast | null;

  graphActions: GraphActions | null;

  setViewport: (viewport: GraphViewport, source: DataSource) => void;
  setLoading: (loading: boolean) => void;
  setFps: (fps: number) => void;

  selectNode: (nodeId: string | null) => void;
  hoverNode: (nodeId: string | null) => void;
  hoverEdge: (edgeId: string | null) => void;

  setHighlight: (partial: Partial<HighlightState>) => void;
  clearHighlight: () => void;

  setQueryText: (text: string) => void;
  beginQuery: (text: string) => void;
  appendToken: (token: string) => void;
  setQueryContext: (partial: Partial<QueryState>) => void;
  completeQuery: (partial: Partial<QueryState>) => void;
  failQuery: (message: string) => void;
  resetQuery: () => void;

  setColorMode: (mode: ColorMode) => void;
  toggleType: (type: EntityType) => void;
  toggleLayer: (layer: keyof GraphStore["layers"]) => void;
  setPhysicsRunning: (running: boolean) => void;

  setTimeRange: (range: [number, number]) => void;
  setActiveYear: (year: number) => void;
  setPlaying: (playing: boolean) => void;

  setImpact: (impact: ImpactResult | null) => void;
  setImpactLoading: (loading: boolean) => void;

  setDrawerTab: (tab: DrawerTab) => void;

  setIngestionOpen: (open: boolean) => void;
  setIngestion: (partial: Partial<IngestionState>) => void;
  resetIngestion: () => void;

  showToast: (message: string, tone?: Toast["tone"]) => void;
  dismissToast: () => void;

  setGraphActions: (actions: GraphActions | null) => void;
}

const emptyHighlight: HighlightState = {
  nodeIds: new Set(),
  edgeIds: new Set(),
  pathNodeIds: [],
  pathEdgeIds: [],
  seedNodeIds: new Set(),
  mode: null,
  explanation: "",
  confidence: 0,
  elapsedMs: 0,
};

const initialQuery: QueryState = {
  text: "",
  status: "idle",
  narrative: "",
  citations: [],
  mode: null,
  explanation: "",
  elapsedMs: 0,
  confidence: 0,
  error: null,
};

const initialIngestion: IngestionState = {
  open: false,
  filename: null,
  stage: "IDLE",
  percent: 0,
  uploadPercent: 0,
  totalChunks: 0,
  processedChunks: 0,
  entities: 0,
  relationships: 0,
  nodesAdded: 0,
  edgesAdded: 0,
  documentCount: 0,
  error: null,
  running: false,
  completed: false,
};

let toastCounter = 0;
let toastTimer: ReturnType<typeof setTimeout> | null = null;

export const useGraphStore = create<GraphStore>((set, get) => ({
  viewport: null,
  source: "demo",
  loading: true,
  fps: 0,

  selectedNodeId: null,
  hoveredNodeId: null,
  hoveredEdgeId: null,

  highlight: emptyHighlight,
  query: initialQuery,

  colorMode: "DOCUMENT",
  hiddenTypes: new Set(),
  layers: { labels: true, edges: true, particles: true, minimap: true },
  physicsRunning: true,

  timeRange: [2018, 2026],
  activeYear: 2026,
  playing: false,

  impact: null,
  impactLoading: false,

  drawerTab: "story",
  ingestion: initialIngestion,
  toast: null,

  graphActions: null,

  setViewport: (viewport, source) =>
    set((state) => {
      const years = viewport.edges
        .map((edge) => edge.year)
        .filter((year): year is number => typeof year === "number");
      const minYear = years.length ? Math.min(...years) : 2015;
      const maxYear = years.length ? Math.max(...years) : 2026;
      const timeRange: [number, number] = [
        Math.min(state.timeRange[0], minYear),
        Math.max(state.timeRange[1], maxYear, 2026),
      ];
      return {
        viewport,
        source,
        loading: false,
        timeRange,
        activeYear: timeRange[1],
      };
    }),
  setLoading: (loading) => set({ loading }),
  setFps: (fps) => set({ fps }),

  selectNode: (nodeId) =>
    set((state) => ({
      selectedNodeId: nodeId,
      drawerTab: state.drawerTab === "impact" ? "story" : state.drawerTab,
    })),
  hoverNode: (nodeId) => set({ hoveredNodeId: nodeId }),
  hoverEdge: (edgeId) => set({ hoveredEdgeId: edgeId }),

  setHighlight: (partial) =>
    set((state) => ({
      highlight: {
        ...state.highlight,
        ...partial,
        nodeIds: new Set([...state.highlight.nodeIds, ...(partial.nodeIds ?? [])]),
        edgeIds: new Set([...state.highlight.edgeIds, ...(partial.edgeIds ?? [])]),
      },
    })),
  clearHighlight: () => set({ highlight: emptyHighlight }),

  setQueryText: (text) => set((state) => ({ query: { ...state.query, text } })),
  beginQuery: (text) =>
    set({
      query: {
        ...initialQuery,
        text,
        status: "streaming",
      },
      impact: null,
      selectedNodeId: null,
      drawerTab: "story",
    }),
  appendToken: (token) =>
    set((state) => ({ query: { ...state.query, narrative: state.query.narrative + token } })),
  setQueryContext: (partial) =>
    set((state) => ({ query: { ...state.query, ...partial } })),
  completeQuery: (partial) =>
    set((state) => ({ query: { ...state.query, ...partial, status: "complete" } })),
  failQuery: (message) =>
    set((state) => ({ query: { ...state.query, status: "error", error: message } })),
  resetQuery: () => set({ query: initialQuery, impact: null, highlight: emptyHighlight }),

  setColorMode: (mode) => set({ colorMode: mode }),
  toggleType: (type) =>
    set((state) => {
      const next = new Set(state.hiddenTypes);
      if (next.has(type)) next.delete(type);
      else next.add(type);
      return { hiddenTypes: next };
    }),
  toggleLayer: (layer) =>
    set((state) => ({ layers: { ...state.layers, [layer]: !state.layers[layer] } })),
  setPhysicsRunning: (running) => set({ physicsRunning: running }),

  setTimeRange: (range) => set({ timeRange: range, activeYear: range[1] }),
  setActiveYear: (year) =>
    set((state) => ({
      activeYear: Math.min(state.timeRange[1], Math.max(state.timeRange[0], year)),
    })),
  setPlaying: (playing) => set({ playing }),

  setImpact: (impact) => set({ impact }),
  setImpactLoading: (loading) => set({ impactLoading: loading }),

  setDrawerTab: (tab) => set({ drawerTab: tab }),

  setIngestionOpen: (open) =>
    set((state) => ({ ingestion: { ...state.ingestion, open } })),
  setIngestion: (partial) =>
    set((state) => ({ ingestion: { ...state.ingestion, ...partial } })),
  resetIngestion: () =>
    set((state) => ({ ingestion: { ...initialIngestion, open: state.ingestion.open } })),

  showToast: (message, tone = "info") => {
    toastCounter += 1;
    if (toastTimer) clearTimeout(toastTimer);
    set({ toast: { id: toastCounter, message, tone } });
    toastTimer = setTimeout(() => {
      if (get().toast?.id === toastCounter) set({ toast: null });
    }, 4200);
  },
  dismissToast: () => {
    if (toastTimer) clearTimeout(toastTimer);
    set({ toast: null });
  },

  setGraphActions: (actions) => set({ graphActions: actions }),
}));
