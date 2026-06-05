import { useEffect, useRef, useState } from "react";
import { Loader2, Plus, Trash2, Upload } from "lucide-react";
import { getPreset, importPDB, listPresets } from "./api";
import { useMDStore } from "./store";
import { FormulaInput } from "./FormulaInput";
import { PythonForceEditor } from "./PythonForceEditor";
import type { Boundary, ForceKind, ForceTerm, IntegratorKind, PresetMeta, ThermostatKind } from "./types";

const FORCE_LABELS: Record<ForceKind, string> = {
  lennard_jones: "Lennard-Jones",
  harmonic_bond: "Harmonic bond",
  coulomb: "Coulomb",
  gravity: "Gravity",
  formula: "Formula U(r)",
  python: "Python force",
};

function Num({ label, value, onChange, step = 0.1, min }: {
  label: string; value: number; onChange: (v: number) => void; step?: number; min?: number;
}) {
  return (
    <label className="flex flex-col gap-0.5">
      <span className="text-[10px] text-slate-500 uppercase tracking-wide">{label}</span>
      <input
        type="number"
        value={value}
        step={step}
        min={min}
        onChange={(e) => onChange(Number(e.target.value))}
        className="bg-canvas border border-border rounded-md px-2 py-1 text-sm text-slate-200 focus:outline-none focus:border-indigo-500/60"
      />
    </label>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-2">
      <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">{title}</div>
      {children}
    </div>
  );
}

export function ControlPanel() {
  const spec = useMDStore((s) => s.spec);
  const patchSpec = useMDStore((s) => s.patchSpec);
  const view = useMDStore((s) => s.view);
  const toggleView = useMDStore((s) => s.toggleView);
  const [presets, setPresets] = useState<PresetMeta[]>([]);
  const fileRef = useRef<HTMLInputElement | null>(null);
  const [pdbStatus, setPdbStatus] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);

  useEffect(() => {
    listPresets().then(setPresets).catch(() => {});
  }, []);

  async function onPdbFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = ""; // allow re-selecting the same file
    if (!file) return;
    setImporting(true);
    setPdbStatus(null);
    try {
      const text = await file.text();
      const name = file.name.replace(/\.(pdb|ent|cif)$/i, "");
      const out = await importPDB(text, name);
      patchSpec(out.spec);
      setPdbStatus(`Loaded ${out.n_particles} atoms · ${out.n_bonds} springs`);
    } catch (err) {
      setPdbStatus(`Error: ${(err as Error).message}`);
    } finally {
      setImporting(false);
    }
  }

  async function loadPreset(key: string) {
    if (!key) return;
    try {
      const s = await getPreset(key);
      patchSpec(s);
    } catch { /* ignore */ }
  }

  function updateTerm(i: number, patch: Partial<ForceTerm>) {
    const force_terms = spec.force_terms.map((t, k) => (k === i ? { ...t, ...patch } : t));
    patchSpec({ force_terms });
  }
  function addTerm() {
    patchSpec({
      force_terms: [
        ...spec.force_terms,
        { kind: "lennard_jones", enabled: true, epsilon: 1, sigma: 1, cutoff: 2.5 },
      ],
    });
  }
  function removeTerm(i: number) {
    patchSpec({ force_terms: spec.force_terms.filter((_, k) => k !== i) });
  }

  const dtWarn = spec.dt > 0.01;

  return (
    <div className="space-y-5 text-sm">
      <Section title="Preset">
        <select
          onChange={(e) => loadPreset(e.target.value)}
          defaultValue=""
          className="w-full bg-canvas border border-border rounded-md px-2 py-1.5 text-sm text-slate-200 focus:outline-none focus:border-indigo-500/60"
        >
          <option value="">Load a preset…</option>
          {presets.map((p) => (
            <option key={p.key} value={p.key} title={p.description}>{p.label}</option>
          ))}
        </select>
      </Section>

      <Section title="Structure (PDB)">
        <input ref={fileRef} type="file" accept=".pdb,.ent,.cif" onChange={onPdbFile} className="hidden" />
        <button
          onClick={() => fileRef.current?.click()}
          disabled={importing}
          className="flex items-center gap-1.5 text-xs text-slate-300 hover:text-white border border-dashed border-border hover:border-slate-500 rounded-md px-2 py-1.5 w-full justify-center disabled:opacity-40"
        >
          {importing ? <Loader2 size={13} className="animate-spin" /> : <Upload size={13} />}
          {importing ? "Importing…" : "Load PDB file"}
        </button>
        {pdbStatus && (
          <p className={`text-[11px] leading-snug ${pdbStatus.startsWith("Error") ? "text-red-400" : "text-emerald-400"}`}>
            {pdbStatus}
          </p>
        )}
        <p className="text-[10px] text-slate-600 leading-snug">
          Builds an elastic-network model: atoms become particles, nearby pairs become harmonic springs. Large structures coarse-grain to Cα.
        </p>
      </Section>

      <Section title="System">
        <div className="grid grid-cols-2 gap-2">
          <Num label="Particles" value={spec.n_particles} step={1} min={1}
            onChange={(v) => patchSpec({ n_particles: Math.max(1, Math.min(2000, Math.round(v))) })} />
          <Num label="Initial T" value={spec.temperature} step={0.1} min={0}
            onChange={(v) => patchSpec({ temperature: v })} />
          <Num label="dt" value={spec.dt} step={0.001} min={0.0001}
            onChange={(v) => patchSpec({ dt: v })} />
          <Num label="Steps" value={spec.steps} step={500} min={1}
            onChange={(v) => patchSpec({ steps: Math.max(1, Math.round(v)) })} />
        </div>
        {dtWarn && (
          <p className="text-[11px] text-amber-400">⚠ dt &gt; 0.01 may be unstable in reduced units.</p>
        )}
        {spec.n_particles > 1200 && (
          <p className="text-[11px] text-amber-400">⚠ O(N²) forces — &gt;1200 particles will be slow.</p>
        )}
      </Section>

      <Section title="Box">
        <div className="grid grid-cols-3 gap-2">
          {[0, 1, 2].map((axis) => (
            <Num key={axis} label={["Lx", "Ly", "Lz"][axis]} value={spec.box.lengths[axis]} step={1} min={1}
              onChange={(v) => {
                const lengths = [...spec.box.lengths] as [number, number, number];
                lengths[axis] = v;
                patchSpec({ box: { ...spec.box, lengths } });
              }} />
          ))}
        </div>
        <label className="flex flex-col gap-0.5">
          <span className="text-[10px] text-slate-500 uppercase tracking-wide">Boundary</span>
          <select value={spec.box.boundary}
            onChange={(e) => patchSpec({ box: { ...spec.box, boundary: e.target.value as Boundary } })}
            className="bg-canvas border border-border rounded-md px-2 py-1 text-sm text-slate-200 focus:outline-none focus:border-indigo-500/60">
            <option value="periodic">Periodic</option>
            <option value="reflective">Reflective</option>
            <option value="open">Open</option>
          </select>
        </label>
      </Section>

      <Section title="Integrator & thermostat">
        <div className="grid grid-cols-2 gap-2">
          <label className="flex flex-col gap-0.5">
            <span className="text-[10px] text-slate-500 uppercase tracking-wide">Integrator</span>
            <select value={spec.integrator}
              onChange={(e) => patchSpec({ integrator: e.target.value as IntegratorKind })}
              className="bg-canvas border border-border rounded-md px-2 py-1 text-sm text-slate-200 focus:outline-none focus:border-indigo-500/60">
              <option value="velocity_verlet">Velocity Verlet</option>
              <option value="leapfrog">Leapfrog</option>
            </select>
          </label>
          <label className="flex flex-col gap-0.5">
            <span className="text-[10px] text-slate-500 uppercase tracking-wide">Thermostat</span>
            <select value={spec.thermostat}
              onChange={(e) => patchSpec({ thermostat: e.target.value as ThermostatKind })}
              className="bg-canvas border border-border rounded-md px-2 py-1 text-sm text-slate-200 focus:outline-none focus:border-indigo-500/60">
              <option value="none">None (NVE)</option>
              <option value="berendsen">Berendsen</option>
              <option value="velocity_rescale">Velocity rescale</option>
            </select>
          </label>
        </div>
        {spec.thermostat !== "none" && (
          <div className="grid grid-cols-2 gap-2">
            <Num label="Target T" value={spec.target_temperature} step={0.1} min={0}
              onChange={(v) => patchSpec({ target_temperature: v })} />
            <Num label="Coupling" value={spec.thermostat_coupling} step={0.01} min={0}
              onChange={(v) => patchSpec({ thermostat_coupling: v })} />
          </div>
        )}
      </Section>

      <Section title="Force terms">
        {spec.force_terms.map((term, i) => (
          <div key={i} className="border border-border rounded-lg p-2 space-y-2 bg-canvas/40">
            <div className="flex items-center gap-2">
              <input type="checkbox" checked={term.enabled}
                onChange={(e) => updateTerm(i, { enabled: e.target.checked })}
                className="accent-indigo-500" />
              <select value={term.kind}
                onChange={(e) => updateTerm(i, { kind: e.target.value as ForceKind })}
                className="flex-1 bg-canvas border border-border rounded-md px-2 py-1 text-xs text-slate-200 focus:outline-none focus:border-indigo-500/60">
                {Object.entries(FORCE_LABELS).map(([k, label]) => (
                  <option key={k} value={k}>{label}</option>
                ))}
              </select>
              <button onClick={() => removeTerm(i)} className="p-1 text-slate-600 hover:text-red-400">
                <Trash2 size={13} />
              </button>
            </div>

            {term.kind === "lennard_jones" && (
              <div className="grid grid-cols-3 gap-2">
                <Num label="ε" value={term.epsilon ?? 1} step={0.1} onChange={(v) => updateTerm(i, { epsilon: v })} />
                <Num label="σ" value={term.sigma ?? 1} step={0.1} onChange={(v) => updateTerm(i, { sigma: v })} />
                <Num label="cutoff·σ" value={term.cutoff ?? 2.5} step={0.5} onChange={(v) => updateTerm(i, { cutoff: v })} />
              </div>
            )}
            {term.kind === "coulomb" && (
              <div className="grid grid-cols-2 gap-2">
                <Num label="k" value={term.k_coulomb ?? 1} step={0.5} onChange={(v) => updateTerm(i, { k_coulomb: v })} />
                <Num label="cutoff" value={term.coulomb_cutoff ?? 6} step={0.5} onChange={(v) => updateTerm(i, { coulomb_cutoff: v })} />
              </div>
            )}
            {term.kind === "gravity" && (
              <div className="grid grid-cols-2 gap-2">
                <Num label="G" value={term.g_constant ?? 1} step={0.1} onChange={(v) => updateTerm(i, { g_constant: v })} />
                <Num label="softening" value={term.softening ?? 0.1} step={0.05} onChange={(v) => updateTerm(i, { softening: v })} />
              </div>
            )}
            {term.kind === "formula" && (
              <FormulaInput value={term.expression ?? ""} onChange={(expr) => updateTerm(i, { expression: expr })} />
            )}
            {term.kind === "python" && (
              <PythonForceEditor value={term.code ?? ""} onChange={(code) => updateTerm(i, { code })} />
            )}
            {term.kind === "harmonic_bond" && (
              <p className="text-[11px] text-slate-600">Uses the bond list from the preset (i–j, r0, k).</p>
            )}
          </div>
        ))}
        <button onClick={addTerm}
          className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-white border border-dashed border-border hover:border-slate-500 rounded-md px-2 py-1.5 w-full justify-center">
          <Plus size={13} /> Add force term
        </button>
      </Section>

      <Section title="View">
        <div className="space-y-1.5">
          {([
            ["showBox", "Box wireframe"],
            ["showBonds", "Bonds"],
          ] as const).map(([k, label]) => (
            <label key={k} className="flex items-center gap-2 text-xs text-slate-300">
              <input type="checkbox" checked={view[k]} onChange={() => toggleView(k)} className="accent-indigo-500" />
              {label}
            </label>
          ))}
        </div>
      </Section>
    </div>
  );
}
