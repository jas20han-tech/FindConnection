"use client";

import { useEffect, useRef } from "react";

export interface MinimapNode {
  id: string;
  x: number;
  y: number;
  color: string;
  size: number;
}

interface MinimapProps {
  getNodes: () => MinimapNode[];
  selectedNodeId: string | null;
  onSelect: (nodeId: string) => void;
}

const WIDTH = 172;
const HEIGHT = 112;
const PADDING = 12;

export function Minimap({ getNodes, selectedNodeId, onSelect }: MinimapProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const selectedRef = useRef(selectedNodeId);
  selectedRef.current = selectedNodeId;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const context = canvas.getContext("2d");
    if (!context) return;

    const ratio = window.devicePixelRatio || 1;
    canvas.width = WIDTH * ratio;
    canvas.height = HEIGHT * ratio;
    context.setTransform(ratio, 0, 0, ratio, 0, 0);

    let frame = 0;
    let raf = 0;
    let cached: MinimapNode[] = [];

    const draw = () => {
      const nodes = getNodes();
      if (frame % 30 === 0 || nodes.length !== cached.length) cached = nodes;
      frame += 1;

      context.clearRect(0, 0, WIDTH, HEIGHT);
      context.fillStyle = "rgba(7, 9, 14, 0.55)";
      context.fillRect(0, 0, WIDTH, HEIGHT);

      if (cached.length) {
        let minX = Infinity;
        let maxX = -Infinity;
        let minY = Infinity;
        let maxY = -Infinity;
        for (const node of cached) {
          minX = Math.min(minX, node.x);
          maxX = Math.max(maxX, node.x);
          minY = Math.min(minY, node.y);
          maxY = Math.max(maxY, node.y);
        }
        const spanX = Math.max(1, maxX - minX);
        const spanY = Math.max(1, maxY - minY);
        const scale = Math.min(
          (WIDTH - PADDING * 2) / spanX,
          (HEIGHT - PADDING * 2) / spanY,
        );

        for (const node of cached) {
          const x = PADDING + (node.x - minX) * scale;
          const y = PADDING + (node.y - minY) * scale;
          const isSelected = node.id === selectedRef.current;
          context.beginPath();
          context.fillStyle = isSelected ? "#FFFFFF" : node.color;
          context.globalAlpha = isSelected ? 1 : 0.78;
          context.arc(x, y, isSelected ? 2.6 : Math.min(2.1, 1.1 + node.size * 0.08), 0, Math.PI * 2);
          context.fill();
        }
        context.globalAlpha = 1;
      }

      raf = requestAnimationFrame(draw);
    };

    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [getNodes]);

  // Click-to-focus: pick the closest rendered node.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const handleClick = (event: MouseEvent) => {
      const rect = canvas.getBoundingClientRect();
      const clickX = ((event.clientX - rect.left) / rect.width) * WIDTH;
      const clickY = ((event.clientY - rect.top) / rect.height) * HEIGHT;
      const nodes = getNodes();
      if (!nodes.length) return;

      let minX = Infinity;
      let maxX = -Infinity;
      let minY = Infinity;
      let maxY = -Infinity;
      for (const node of nodes) {
        minX = Math.min(minX, node.x);
        maxX = Math.max(maxX, node.x);
        minY = Math.min(minY, node.y);
        maxY = Math.max(maxY, node.y);
      }
      const spanX = Math.max(1, maxX - minX);
      const spanY = Math.max(1, maxY - minY);
      const scale = Math.min((WIDTH - PADDING * 2) / spanX, (HEIGHT - PADDING * 2) / spanY);

      let best: { id: string; distance: number } | null = null;
      for (const node of nodes) {
        const x = PADDING + (node.x - minX) * scale;
        const y = PADDING + (node.y - minY) * scale;
        const distance = (x - clickX) ** 2 + (y - clickY) ** 2;
        if (!best || distance < best.distance) best = { id: node.id, distance };
      }
      if (best && best.distance < 900) onSelect(best.id);
    };
    canvas.addEventListener("click", handleClick);
    return () => canvas.removeEventListener("click", handleClick);
  }, [getNodes, onSelect]);

  return (
    <div className="pointer-events-auto absolute bottom-4 left-4 z-20 hidden overflow-hidden rounded-xl border border-white/10 bg-[#080B12]/85 backdrop-blur-md shadow-glass lg:block">
      <div className="flex items-center justify-between px-2.5 pt-1.5">
        <span className="font-mono text-[9px] font-semibold uppercase tracking-[0.18em] text-slate-500">
          Minimap
        </span>
        <span className="font-mono text-[9px] text-slate-600">click to focus</span>
      </div>
      <canvas ref={canvasRef} className="cursor-crosshair" style={{ width: WIDTH, height: HEIGHT }} />
    </div>
  );
}
