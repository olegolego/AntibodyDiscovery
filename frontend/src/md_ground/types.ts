// Mirrors backend/app/md/spec.py. Kept hand-synced (small, stable surface).

export type Boundary = "open" | "periodic" | "reflective";
export type IntegratorKind = "velocity_verlet" | "leapfrog";
export type ThermostatKind = "none" | "berendsen" | "velocity_rescale";
export type ForceKind =
  | "lennard_jones"
  | "harmonic_bond"
  | "coulomb"
  | "gravity"
  | "formula"
  | "python";

export interface ParticleType {
  name: string;
  mass: number;
  charge: number;
  radius: number;
  color: string;
}

export interface Bond {
  i: number;
  j: number;
  r0: number;
  k: number;
}

export interface ForceTerm {
  kind: ForceKind;
  enabled: boolean;
  epsilon?: number;
  sigma?: number;
  cutoff?: number | null;
  k_coulomb?: number;
  coulomb_cutoff?: number | null;
  g_constant?: number;
  softening?: number;
  expression?: string | null;
  script_id?: string | null;
  code?: string | null;
}

export interface Box {
  lengths: [number, number, number];
  boundary: Boundary;
}

export interface StreamConfig {
  frame_stride: number;
  max_fps: number;
}

export interface SystemSpec {
  name: string;
  n_particles: number;
  particle_types: ParticleType[];
  type_index: number[];
  positions?: number[][] | null;
  velocities?: number[][] | null;
  box: Box;
  bonds: Bond[];
  force_terms: ForceTerm[];
  integrator: IntegratorKind;
  thermostat: ThermostatKind;
  target_temperature: number;
  thermostat_coupling: number;
  dt: number;
  steps: number;
  temperature: number;
  seed: number;
  minimize_steps: number;
  equilibrate_steps: number;
  stream: StreamConfig;
}

export interface Energy {
  kinetic: number;
  potential: number;
  total: number;
  temperature: number;
}

// A decoded frame held in the playback buffer. positions is a flat Float32Array
// of length 3N for direct three.js InstancedMesh hydration.
export interface MDFrame {
  step: number;
  time: number;
  positions: Float32Array;
  energy: Energy;
}

export interface InitMessage {
  n_particles: number;
  particle_types: ParticleType[];
  type_index: number[];
  box: Box;
  total_steps: number;
}

export interface Summary {
  steps_run: number;
  final_energy: Energy;
  energy_drift: number;
  wall_seconds: number;
}

export interface PresetMeta {
  key: string;
  label: string;
  description: string;
}

export type SimStatus = "idle" | "connecting" | "running" | "done" | "error" | "cancelled";

export function defaultSpec(): SystemSpec {
  return {
    name: "Untitled simulation",
    n_particles: 256,
    particle_types: [
      { name: "A", mass: 1.0, charge: 0.0, radius: 0.5, color: "#6366f1" },
    ],
    type_index: [],
    positions: null,
    velocities: null,
    box: { lengths: [12, 12, 12], boundary: "periodic" },
    bonds: [],
    force_terms: [
      { kind: "lennard_jones", enabled: true, epsilon: 1.0, sigma: 1.0, cutoff: 2.5 },
    ],
    integrator: "velocity_verlet",
    thermostat: "none",
    target_temperature: 1.0,
    thermostat_coupling: 0.1,
    dt: 0.004,
    steps: 8000,
    temperature: 1.2,
    seed: 0,
    minimize_steps: 0,
    equilibrate_steps: 0,
    stream: { frame_stride: 4, max_fps: 30 },
  };
}
