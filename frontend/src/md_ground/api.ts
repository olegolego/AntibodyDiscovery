import type { Checkpoint, PresetMeta, SystemSpec } from "./types";

const BASE = "/api/md-ground";

async function jget<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

async function jpost<T>(url: string, body: unknown): Promise<T> {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const detail = await r.json().catch(() => ({}));
    throw new Error(detail.detail ?? `${r.status}`);
  }
  return r.json();
}

export async function listPresets(): Promise<PresetMeta[]> {
  const { presets } = await jget<{ presets: PresetMeta[] }>(`${BASE}/presets`);
  return presets;
}

export async function getPreset(key: string): Promise<SystemSpec> {
  const { spec } = await jget<{ spec: SystemSpec }>(`${BASE}/presets/${key}`);
  return spec;
}

export interface FormulaSample {
  r: number;
  U: number;
  F: number;
}

export async function validateFormula(
  expression: string
): Promise<{ valid: boolean; samples: FormulaSample[] }> {
  return jpost(`${BASE}/validate-formula`, { expression });
}

export async function validatePython(
  code: string
): Promise<{ valid: boolean; force_shape: number[]; potential_energy: number }> {
  return jpost(`${BASE}/validate-python`, { code });
}

export async function codegen(prompt: string): Promise<string> {
  const { code } = await jpost<{ code: string }>(`${BASE}/codegen`, { prompt });
  return code;
}

export async function importPDB(
  pdb: string,
  name: string,
  springK = 1.0,
  temperature = 0.6
): Promise<{ spec: SystemSpec; n_particles: number; n_bonds: number }> {
  return jpost(`${BASE}/import-pdb`, { pdb, name, spring_k: springK, temperature });
}

export async function addTarget(
  spec: SystemSpec,
  pdb: string,
  name: string,
  gap = 5.0,
  bindEpsilon = 0.4
): Promise<{ spec: SystemSpec; n_particles: number; n_bonds: number }> {
  return jpost(`${BASE}/add-target`, { spec, pdb, name, gap, bind_epsilon: bindEpsilon });
}

export interface DockingRun {
  id: string;
  short_id: string;
  tool_id: string;
  antigen_label: string;
  created_at: string;
  score: number | null;
  vdw: number | null;
  n_models: number | null;
  molecule_name: string | null;
  vh_preview: string | null;
  vh_len: number | null;
  run_id: string | null;
}

export async function listDockingRuns(): Promise<DockingRun[]> {
  return jget(`${BASE}/docking-runs`);
}

export async function importDocking(
  dockingId: string
): Promise<{ spec: SystemSpec; n_particles: number; n_antibody: number; n_antigen: number }> {
  const r = await fetch(`${BASE}/import-docking/${dockingId}`, { method: "POST" });
  if (!r.ok) {
    const detail = await r.json().catch(() => ({}));
    throw new Error(detail.detail ?? `${r.status}`);
  }
  return r.json();
}

// ── Saved runs (persisted trajectories in the DB) ──────────────────────────────

export interface SavedRunMeta {
  id: string;
  name: string;
  n_particles: number;
  n_frames: number;
  created_at: string;
  resumable: boolean;
}

export interface SaveRunPayload {
  name: string;
  spec: SystemSpec;
  particle_types: unknown[];
  type_index: number[];
  box_lengths: number[];
  frames: { step: number; time: number; positions: number[] }[];
  energy_history: unknown[];
  summary: unknown;
  checkpoint: Checkpoint | null;
}

export async function listSavedRuns(): Promise<SavedRunMeta[]> {
  return jget(`${BASE}/runs`);
}

export async function saveRun(payload: SaveRunPayload): Promise<{ id: string; n_frames: number }> {
  return jpost(`${BASE}/runs`, payload);
}

export async function getSavedRun(id: string): Promise<unknown> {
  return jget(`${BASE}/runs/${id}`);
}

export async function deleteSavedRun(id: string): Promise<void> {
  await fetch(`${BASE}/runs/${id}`, { method: "DELETE" });
}

// Saved simulations
export interface SavedSim {
  id: string;
  name: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export async function listSimulations(): Promise<SavedSim[]> {
  return jget(`${BASE}/simulations`);
}

export async function createSimulation(name: string, spec: SystemSpec): Promise<string> {
  const { id } = await jpost<{ id: string }>(`${BASE}/simulations`, { name, spec });
  return id;
}

export async function getSimulation(
  id: string
): Promise<{ id: string; name: string; spec: SystemSpec; status: string }> {
  return jget(`${BASE}/simulations/${id}`);
}

export async function cancelSimulation(id: string): Promise<void> {
  await fetch(`${BASE}/simulations/${id}/cancel`, { method: "POST" });
}
