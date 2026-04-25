import { useEffect, useRef } from "react";
import type { PAEData } from "@/api/analysis";

interface Props {
  pae: PAEData;
}

// Bilinear downscale to target NxN
function downscalePAE(matrix: number[][], target: number): number[][] {
  const n = matrix.length;
  if (n <= target) return matrix;
  const ratio = n / target;
  const out: number[][] = Array.from({ length: target }, () => new Array(target).fill(0));
  for (let i = 0; i < target; i++) {
    for (let j = 0; j < target; j++) {
      const si = Math.floor(i * ratio);
      const sj = Math.floor(j * ratio);
      out[i][j] = matrix[si][sj];
    }
  }
  return out;
}

// AlphaFold color scheme: green (low PAE) → white → orange (high PAE)
function paeColor(value: number, max: number): [number, number, number] {
  const t = Math.min(value / max, 1);
  if (t < 0.5) {
    // green → white
    const f = t * 2;
    return [
      Math.round(34 + (255 - 34) * f),
      Math.round(211 + (255 - 211) * f),
      Math.round(153 + (255 - 153) * f),
    ];
  } else {
    // white → orange-red
    const f = (t - 0.5) * 2;
    return [
      255,
      Math.round(255 + (69 - 255) * f),
      Math.round(255 + (0 - 255) * f),
    ];
  }
}

export function PAEHeatmap({ pae }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !pae.predicted_aligned_error?.length) return;

    const maxPAE = pae.max_predicted_aligned_error ?? 31.75;
    const TARGET = 300;
    const scaled = downscalePAE(pae.predicted_aligned_error, TARGET);
    const n = scaled.length;

    canvas.width = n;
    canvas.height = n;

    const ctx = canvas.getContext("2d")!;
    const imageData = ctx.createImageData(n, n);

    for (let i = 0; i < n; i++) {
      for (let j = 0; j < n; j++) {
        const [r, g, b] = paeColor(scaled[i][j], maxPAE);
        const idx = (i * n + j) * 4;
        imageData.data[idx] = r;
        imageData.data[idx + 1] = g;
        imageData.data[idx + 2] = b;
        imageData.data[idx + 3] = 255;
      }
    }
    ctx.putImageData(imageData, 0, 0);
  }, [pae]);

  const n = pae.predicted_aligned_error?.length ?? 0;

  return (
    <div className="flex flex-col gap-2">
      <canvas
        ref={canvasRef}
        className="w-full rounded-lg"
        style={{ imageRendering: "pixelated", aspectRatio: "1" }}
      />
      <div className="flex items-center gap-2 text-[10px] text-slate-500">
        <div className="w-20 h-2 rounded" style={{
          background: "linear-gradient(to right, #22d39a, #ffffff, #ff4500)"
        }} />
        <span>Low PAE → High PAE</span>
        <span className="ml-auto">{n}×{n} residues</span>
      </div>
    </div>
  );
}
