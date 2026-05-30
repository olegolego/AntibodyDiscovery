// Canvas scatter plot of t-SNE projected state embeddings
// Color = visit frequency (gray → bright orange, inspired by visit-count visualisations)

import { useRef, useEffect } from "react";
import { useRLDesignerStore } from "../store";

function visitColor(count: number, maxCount: number): string {
  const t = Math.min(count / Math.max(maxCount, 1), 1);
  // slate → orange
  const r = Math.round(100 + 155 * t);
  const g = Math.round(116 - 57 * t);
  const b = Math.round(139 - 125 * t);
  return `rgba(${r},${g},${b},${0.5 + 0.5 * t})`;
}

export function ExplorationMap() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const { vizData } = useRLDesignerStore();

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !vizData?.tsne_coords) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const { tsne_coords, visit_counts } = vizData;
    const entries = Object.entries(tsne_coords) as [string, [number, number]][];
    if (entries.length === 0) return;

    const W = canvas.width;
    const H = canvas.height;
    ctx.clearRect(0, 0, W, H);

    // Normalise coords to canvas
    const xs = entries.map(([, [x]]) => x);
    const ys = entries.map(([, [, y]]) => y);
    const xMin = Math.min(...xs), xMax = Math.max(...xs);
    const yMin = Math.min(...ys), yMax = Math.max(...ys);
    const xRange = xMax - xMin || 1;
    const yRange = yMax - yMin || 1;
    const pad = 30;

    const toCanvas = (x: number, y: number) => ({
      cx: pad + ((x - xMin) / xRange) * (W - 2 * pad),
      cy: pad + ((y - yMin) / yRange) * (H - 2 * pad),
    });

    const maxCount = Math.max(...Object.values(visit_counts).map(Number), 1);

    // Draw points
    for (const [sid, [x, y]] of entries) {
      const count = Number(visit_counts[sid] ?? 1);
      const { cx, cy } = toCanvas(x, y);
      const r = 4 + 3 * Math.min(count / maxCount, 1);

      ctx.beginPath();
      ctx.arc(cx, cy, r, 0, Math.PI * 2);
      ctx.fillStyle = visitColor(count, maxCount);
      ctx.fill();

      // Label for high-visit points
      if (count >= maxCount * 0.8) {
        ctx.fillStyle = "#f59e0b";
        ctx.font = "9px monospace";
        ctx.fillText(sid.substring(0, 8), cx + r + 2, cy + 3);
      }
    }
  }, [vizData]);

  const hasData = vizData?.tsne_coords && Object.keys(vizData.tsne_coords).length > 0;

  return (
    <div className="p-4 h-full flex flex-col">
      <div className="flex items-center gap-3 mb-3">
        <p className="text-[10px] text-slate-500 font-semibold uppercase tracking-widest">
          Exploration Map — t-SNE state embeddings
        </p>
        <div className="ml-auto flex items-center gap-2">
          <span className="w-3 h-3 rounded-full bg-slate-500 inline-block" />
          <span className="text-[9px] text-slate-600">visited once</span>
          <span className="w-3 h-3 rounded-full bg-orange-400 inline-block" />
          <span className="text-[9px] text-slate-600">visited often</span>
        </div>
      </div>
      {hasData ? (
        <canvas
          ref={canvasRef}
          width={600}
          height={300}
          className="w-full rounded bg-slate-900/50 border border-slate-800"
        />
      ) : (
        <div className="flex-1 flex items-center justify-center text-[11px] text-slate-600">
          No exploration data yet. Run at least one loop iteration.
        </div>
      )}
    </div>
  );
}
