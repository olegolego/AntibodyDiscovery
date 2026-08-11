// Binding-affinity estimation from a finished MD Ground trajectory.
//
// The engine never creates bonds BETWEEN the two docked bodies (see
// pdb_import.build_docked_complex_spec / combine_with_target): springs are
// intra-body only, and the sole cross-body interaction is the non-bonded
// Lennard-Jones (+ Coulomb) term. So the two binding partners are exactly the
// two connected components of the spring graph, and the interaction energy is
// the sum of the non-bonded pair potentials over every cross-body pair.
//
// This file mirrors the energy maths in backend/app/md/forces.py EXACTLY
// (shifted-force LJ, minimum-image displacement, Coulomb 1/r) so the number the
// panel shows is the same energy the engine integrated — just restricted to the
// antibody↔antigen pairs. Forces are not needed (energy only).
//
// Everything is in the engine's reduced (Lennard-Jones) units: kB = 1, energies
// in units of ε, temperature dimensionless. The result is a *relative* binding
// score for ranking poses/designs — not an absolute kcal/mol affinity.

import type { ForceTerm, MDFrame, ParticleType, SystemSpec } from "./types";

// LIE (Åqvist) linear-response coefficients. Defaults from the original
// parameterisation (α≈0.18 for van der Waals, β≈0.5 for electrostatics).
export const LIE_ALPHA = 0.18;
export const LIE_BETA = 0.5;

// Performance guards: cap pair count per frame and frames averaged.
const MAX_PAIRS = 120_000; // nA*nB above this → subsample groups (energy scaled)
const MAX_FRAMES = 24; // evenly-spaced frames averaged over

export interface BindingEstimate {
  available: boolean;
  reason?: string; // why it couldn't be computed (when !available)

  groupAName: string;
  groupBName: string;
  nA: number;
  nB: number;
  framesUsed: number;
  subsampled: boolean; // groups were subsampled for performance (energy scaled)

  eVdw: number; // ⟨cross-body Lennard-Jones energy⟩  (reduced units)
  eElec: number; // ⟨cross-body Coulomb energy⟩       (reduced units)
  eInt: number; // eVdw + eElec — the interaction energy / single-traj ΔE_MM
  eIntFinal: number; // interaction energy in the final frame

  dgLIE: number; // α·eVdw + β·eElec  (free-state interaction ≈ 0 by construction)
  kT: number; // thermal energy (= target temperature, kB = 1)
  scoreKT: number; // −eInt / kT — binding score in units of kT (positive = favourable)
  kdRel: number; // exp(eInt / kT) — relative dimensionless dissociation constant

  hasCharges: boolean; // any non-zero particle charge → electrostatics contribute
}

// ── group detection: two connected components of the spring graph ──────────────

function connectedComponents(n: number, bonds: SystemSpec["bonds"]): number[][] {
  const parent = Array.from({ length: n }, (_, i) => i);
  const find = (x: number): number => {
    while (parent[x] !== x) {
      parent[x] = parent[parent[x]];
      x = parent[x];
    }
    return x;
  };
  const union = (a: number, b: number) => {
    const ra = find(a);
    const rb = find(b);
    if (ra !== rb) parent[ra] = rb;
  };
  for (const b of bonds) {
    if (b.i >= 0 && b.i < n && b.j >= 0 && b.j < n) union(b.i, b.j);
  }
  const groups = new Map<number, number[]>();
  for (let i = 0; i < n; i++) {
    const r = find(i);
    const g = groups.get(r);
    if (g) g.push(i);
    else groups.set(r, [i]);
  }
  return [...groups.values()].sort((a, b) => b.length - a.length);
}

// Pick the two binding partners. Prefer the spring-graph components (works for
// both the docked-complex import and the add-target path); fall back to a
// two-particle-type split (antibody=0 / antigen=1) when there are no bonds.
function resolveBodies(
  n: number,
  spec: SystemSpec,
  typeIndex: number[],
): { a: number[]; b: number[] } | null {
  const comps = connectedComponents(n, spec.bonds || []);
  const significant = comps.filter((c) => c.length > 1);
  if (significant.length >= 2) {
    return { a: significant[0], b: significant[1] };
  }
  // No usable bond graph — split by particle type if there are exactly two.
  const ti = typeIndex.length === n ? typeIndex : spec.type_index;
  if (ti && ti.length === n) {
    const distinct = [...new Set(ti)].sort((x, y) => x - y);
    if (distinct.length === 2) {
      const a: number[] = [];
      const b: number[] = [];
      for (let i = 0; i < n; i++) (ti[i] === distinct[0] ? a : b).push(i);
      if (a.length && b.length) return { a, b };
    }
  }
  return null;
}

function groupName(idx: number[], typeIndex: number[], types: ParticleType[]): string {
  const names = new Set<string>();
  for (const i of idx) {
    const t = types[typeIndex[i]];
    if (t) names.add(t.name);
  }
  return names.size === 1 ? [...names][0] : null!;
}

function stride<T>(arr: T[], cap: number): T[] {
  if (arr.length <= cap) return arr;
  const out: T[] = [];
  const step = arr.length / cap;
  for (let k = 0; k < cap; k++) out.push(arr[Math.floor(k * step)]);
  return out;
}

// ── cross-body energy of one frame (mirrors forces.py) ─────────────────────────

interface PairContext {
  ljTerms: ForceTerm[];
  coulombTerms: ForceTerm[];
  charges: Float64Array; // per-particle charge
  periodic: boolean;
  L: [number, number, number];
}

function frameInteraction(
  pos: Float32Array,
  a: number[],
  b: number[],
  ctx: PairContext,
): { vdw: number; elec: number } {
  let vdw = 0;
  let elec = 0;
  const { ljTerms, coulombTerms, charges, periodic, L } = ctx;
  for (const i of a) {
    const xi = pos[3 * i];
    const yi = pos[3 * i + 1];
    const zi = pos[3 * i + 2];
    const qi = charges[i];
    for (const j of b) {
      let dx = xi - pos[3 * j];
      let dy = yi - pos[3 * j + 1];
      let dz = zi - pos[3 * j + 2];
      if (periodic) {
        dx -= L[0] * Math.round(dx / L[0]);
        dy -= L[1] * Math.round(dy / L[1]);
        dz -= L[2] * Math.round(dz / L[2]);
      }
      const r2 = Math.max(dx * dx + dy * dy + dz * dz, 1e-12);

      // Lennard-Jones, shifted-force form when a cutoff is set (matches forces.py).
      for (const t of ljTerms) {
        const eps = t.epsilon ?? 1;
        const sig = t.sigma ?? 1;
        const rc = t.cutoff != null ? t.cutoff * sig : null;
        if (rc != null && r2 >= rc * rc) continue;
        const invr2 = (sig * sig) / r2;
        const invr6 = invr2 * invr2 * invr2;
        const invr12 = invr6 * invr6;
        let u = 4 * eps * (invr12 - invr6);
        if (rc != null) {
          const r = Math.sqrt(r2);
          const sc6 = (sig / rc) ** 6;
          const sc12 = sc6 * sc6;
          const fRc = (24 * eps * (2 * sc12 - sc6)) / rc;
          const uRc = 4 * eps * (sc12 - sc6);
          u = u - uRc + fRc * (r - rc);
        }
        vdw += u;
      }

      // Coulomb 1/r between particle charges.
      for (const t of coulombTerms) {
        const qq = qi * charges[j];
        if (qq === 0) continue;
        const cut = t.coulomb_cutoff;
        const r = Math.sqrt(r2);
        if (cut != null && r >= cut) continue;
        elec += ((t.k_coulomb ?? 1) * qq) / r;
      }
    }
  }
  return { vdw, elec };
}

// ── public entry point ─────────────────────────────────────────────────────────

export function estimateBinding(
  frames: MDFrame[],
  typeIndex: number[],
  particleTypes: ParticleType[],
  spec: SystemSpec,
): BindingEstimate {
  const empty = (reason: string): BindingEstimate => ({
    available: false,
    reason,
    groupAName: "A",
    groupBName: "B",
    nA: 0,
    nB: 0,
    framesUsed: 0,
    subsampled: false,
    eVdw: 0,
    eElec: 0,
    eInt: 0,
    eIntFinal: 0,
    dgLIE: 0,
    kT: 1,
    scoreKT: 0,
    kdRel: 1,
    hasCharges: false,
  });

  if (!frames.length) return empty("Run or load a simulation first — no trajectory yet.");
  const n = frames[0].positions.length / 3;
  const bodies = resolveBodies(n, spec, typeIndex);
  if (!bodies)
    return empty(
      "Binding needs a two-body system. Open a docking run or add a target, then run.",
    );

  // Non-bonded force terms that act across the interface.
  const enabled = spec.force_terms.filter((t) => t.enabled);
  const ljTerms = enabled.filter((t) => t.kind === "lennard_jones");
  const coulombTerms = enabled.filter((t) => t.kind === "coulomb");
  if (!ljTerms.length && !coulombTerms.length)
    return empty("No non-bonded (Lennard-Jones / Coulomb) term is enabled to model contact.");

  const ti = typeIndex.length === n ? typeIndex : spec.type_index;
  const charges = new Float64Array(n);
  for (let i = 0; i < n; i++) charges[i] = particleTypes[ti?.[i] ?? 0]?.charge ?? 0;
  const hasCharges = charges.some((q) => q !== 0);

  // Subsample groups if the pair count is too large; scale energy back up so the
  // result estimates the full pairwise sum (an unbiased extensive estimator).
  let a = bodies.a;
  let b = bodies.b;
  const fullPairs = a.length * b.length;
  let scale = 1;
  let subsampled = false;
  if (fullPairs > MAX_PAIRS) {
    const ratio = Math.sqrt(MAX_PAIRS / fullPairs);
    const capA = Math.max(1, Math.floor(a.length * ratio));
    const capB = Math.max(1, Math.floor(b.length * ratio));
    a = stride(a, capA);
    b = stride(b, capB);
    scale = fullPairs / (a.length * b.length);
    subsampled = true;
  }

  const ctx: PairContext = {
    ljTerms,
    coulombTerms,
    charges,
    periodic: spec.box.boundary === "periodic",
    L: spec.box.lengths,
  };

  // Average over the equilibrated tail (last 50% of the trajectory), capped.
  const tailStart = frames.length >= 8 ? Math.floor(frames.length / 2) : 0;
  const tail = frames.slice(tailStart);
  const sample = stride(tail, MAX_FRAMES);
  let sumVdw = 0;
  let sumElec = 0;
  for (const f of sample) {
    const { vdw, elec } = frameInteraction(f.positions, a, b, ctx);
    sumVdw += vdw * scale;
    sumElec += elec * scale;
  }
  const eVdw = sumVdw / sample.length;
  const eElec = sumElec / sample.length;
  const eInt = eVdw + eElec;

  const last = frameInteraction(frames[frames.length - 1].positions, a, b, ctx);
  const eIntFinal = (last.vdw + last.elec) * scale;

  const kT = spec.target_temperature || spec.temperature || 1;
  const dgLIE = LIE_ALPHA * eVdw + LIE_BETA * eElec;

  const aName = groupName(bodies.a, ti || [], particleTypes) || "Body 1";
  const bName = groupName(bodies.b, ti || [], particleTypes) || "Body 2";

  return {
    available: true,
    groupAName: aName,
    groupBName: bName,
    nA: bodies.a.length,
    nB: bodies.b.length,
    framesUsed: sample.length,
    subsampled,
    eVdw,
    eElec,
    eInt,
    eIntFinal,
    dgLIE,
    kT,
    scoreKT: -eInt / kT,
    kdRel: Math.exp(eInt / kT),
    hasCharges,
  };
}
