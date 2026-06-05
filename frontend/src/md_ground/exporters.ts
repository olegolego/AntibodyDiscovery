import type { Energy, MDFrame, ParticleType, SystemSpec } from "./types";

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function safeName(name: string): string {
  return (name || "md-run").replace(/[^a-z0-9_-]+/gi, "_").slice(0, 60);
}

// ── Full run as JSON (re-loadable into MD Ground to replay) ────────────────────

export interface SavedRun {
  format: "md-ground-run";
  version: 1;
  name: string;
  spec: SystemSpec;
  particle_types: ParticleType[];
  type_index: number[];
  box_lengths: [number, number, number];
  energy_history: ({ step: number } & Energy)[];
  frames: { step: number; time: number; positions: number[] }[];
  summary: unknown;
}

export function downloadRunJSON(
  spec: SystemSpec,
  particleTypes: ParticleType[],
  typeIndex: number[],
  boxLengths: [number, number, number],
  energyHistory: ({ step: number } & Energy)[],
  frames: MDFrame[],
  summary: unknown
) {
  const payload: SavedRun = {
    format: "md-ground-run",
    version: 1,
    name: spec.name,
    spec,
    particle_types: particleTypes,
    type_index: typeIndex,
    box_lengths: boxLengths,
    energy_history: energyHistory,
    frames: frames.map((f) => ({ step: f.step, time: f.time, positions: Array.from(f.positions) })),
    summary,
  };
  triggerDownload(
    new Blob([JSON.stringify(payload)], { type: "application/json" }),
    `${safeName(spec.name)}.mdrun.json`
  );
}

// ── Trajectory as multi-frame XYZ (opens in PyMOL / VMD / Ovito) ───────────────

function elementSymbol(t: ParticleType | undefined): string {
  const n = (t?.name ?? "C").trim();
  // Use the name if it looks like an element (1-2 letters), else a generic carbon.
  if (/^[A-Za-z]{1,2}$/.test(n)) return n[0].toUpperCase() + (n[1]?.toLowerCase() ?? "");
  return "C";
}

export function downloadTrajectoryXYZ(
  name: string,
  particleTypes: ParticleType[],
  typeIndex: number[],
  frames: MDFrame[]
) {
  if (frames.length === 0) return;
  const n = frames[0].positions.length / 3;
  const symbols: string[] = [];
  for (let i = 0; i < n; i++) symbols.push(elementSymbol(particleTypes[typeIndex[i] ?? 0]));

  const lines: string[] = [];
  for (const f of frames) {
    lines.push(String(n));
    lines.push(`step=${f.step} time=${f.time.toFixed(4)}`);
    const p = f.positions;
    for (let i = 0; i < n; i++) {
      lines.push(`${symbols[i]} ${p[i * 3].toFixed(4)} ${p[i * 3 + 1].toFixed(4)} ${p[i * 3 + 2].toFixed(4)}`);
    }
  }
  triggerDownload(new Blob([lines.join("\n")], { type: "chemical/x-xyz" }), `${safeName(name)}.xyz`);
}
