import type { PresetMeta, SystemSpec } from "./types";

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
