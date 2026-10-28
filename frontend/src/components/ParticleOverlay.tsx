"use client";

import { useEffect, useRef } from "react";

interface ParticleOverlayProps {
  getPoint: (nodeId: string) => { x: number; y: number } | null;
  pathNodeIds: string[];
  enabled: boolean;
}

/**
 * Animated data packets travelling along the retrieved reasoning path.
 * Positions come from Sigma's graph→viewport transform, so the overlay stays
 * locked to the WebGL canvas through pan, zoom and layout updates.
 */
export function ParticleOverlay({ getPoint, pathNodeIds, enabled }: ParticleOverlayProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const getPointRef = useRef(getPoint);
  const pathRef = useRef(pathNodeIds);

  getPointRef.current = getPoint;
  pathRef.current = pathNodeIds;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const context = canvas.getContext("2d");
    if (!context) return;

    let frame = 0;
    let raf = 0;
    let points: { x: number; y: number }[] = [];

    const resize = () => {
      const parent = canvas.parentElement;
      if (!parent) return;
      const ratio = window.devicePixelRatio || 1;
      canvas.width = Math.max(1, parent.clientWidth * ratio);
      canvas.height = Math.max(1, parent.clientHeight * ratio);
      canvas.style.width = `${parent.clientWidth}px`;
      canvas.style.height = `${parent.clientHeight}px`;
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
    };

    resize();
    const observer = new ResizeObserver(resize);
    if (canvas.parentElement) observer.observe(canvas.parentElement);

    const sample = () => {
      const ids = pathRef.current;
      points = ids
        .map((id) => getPointRef.current(id))
        .filter((point): point is { x: number; y: number } => Boolean(point));
    };

    const draw = (timestamp: number) => {
      const width = canvas.clientWidth;
      const height = canvas.clientHeight;
      context.clearRect(0, 0, width, height);

      if (enabled && points.length > 1) {
        sample();
        for (let index = 0; index < points.length - 1; index += 1) {
          const start = points[index];
          const end = points[index + 1];
          const packets = 2;
          for (let packet = 0; packet < packets; packet += 1) {
            const offset = packet / packets;
            const progress = ((timestamp / 1500 + offset + index * 0.17) % 1 + 1) % 1;
            const x = start.x + (end.x - start.x) * progress;
            const y = start.y + (end.y - start.y) * progress;
            const glow = context.createRadialGradient(x, y, 0, x, y, 9);
            glow.addColorStop(0, "rgba(125, 211, 252, 0.95)");
            glow.addColorStop(0.35, "rgba(56, 189, 248, 0.55)");
            glow.addColorStop(1, "rgba(56, 189, 248, 0)");
            context.fillStyle = glow;
            context.beginPath();
            context.arc(x, y, 9, 0, Math.PI * 2);
            context.fill();
            context.fillStyle = "#E0F2FE";
            context.beginPath();
            context.arc(x, y, 1.6, 0, Math.PI * 2);
            context.fill();
          }
        }
      }

      frame += 1;
      if (frame % 6 === 0) sample();
      raf = requestAnimationFrame(draw);
    };

    raf = requestAnimationFrame(draw);
    return () => {
      cancelAnimationFrame(raf);
      observer.disconnect();
    };
  }, [enabled]);

  return (
    <canvas
      ref={canvasRef}
      className="pointer-events-none absolute inset-0 z-10"
      aria-hidden
    />
  );
}
