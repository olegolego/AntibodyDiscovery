import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, Atom, Database, Film, Play, Save, Sigma, Square, TrendingUp } from "lucide-react";
import { randomUUID } from "@/utils";
import { ControlPanel } from "./ControlPanel";
import { EnergyCharts } from "./EnergyCharts";
import { MathPanel } from "./MathPanel";
import { PlaybackControls } from "./PlaybackControls";
import { Viewer3D } from "./Viewer3D";
import { useMDSocket } from "./useMDSocket";
import { useMDStore } from "./store";
import { downloadTrajectoryXYZ } from "./exporters";
import { getSavedRun, listSavedRuns, saveRun, type SavedRunMeta } from "./api";
import type { SavedRunData } from "./store";

const PHASE_LABEL: Record<string, string> = {
  minimize: "Minimising",
  equilibrate: "Equilibrating",
  production: "Production",
};

const STATUS_LABEL: Record<string, { text: string; cls: string }> = {
  idle: { text: "Idle", cls: "text-slate-500" },
  connecting: { text: "Connecting…", cls: "text-amber-400" },
  running: { text: "Running", cls: "text-emerald-400" },
  done: { text: "Done", cls: "text-indigo-400" },
  error: { text: "Error", cls: "text-red-400" },
  cancelled: { text: "Cancelled", cls: "text-slate-400" },
};

export function MDGroundPage({ onBack }: { onBack: () => void }) {
  // Stable per-session sim id keys the WebSocket channel.
  const simId = useMemo(() => randomUUID(), []);
  const { start, cancel } = useMDSocket(simId);

  const spec = useMDStore((s) => s.spec);
  const status = useMDStore((s) => s.status);
  const error = useMDStore((s) => s.error);
  const phase = useMDStore((s) => s.phase);
  const resetPlayback = useMDStore((s) => s.resetPlayback);
  const [rightTab, setRightTab] = useState<"energy" | "math">("energy");
  const [savedRuns, setSavedRuns] = useState<SavedRunMeta[]>([]);
  const [saving, setSaving] = useState(false);

  const isRunning = status === "running" || status === "connecting";
  const st = STATUS_LABEL[status] ?? STATUS_LABEL.idle;
  const hasFrames = useMDStore((s) => s.frames.length > 0);

  const refreshSavedRuns = () => listSavedRuns().then(setSavedRuns).catch(() => {});
  useEffect(() => { refreshSavedRuns(); }, []);

  async function saveToDB() {
    const s = useMDStore.getState();
    const name = window.prompt("Name this run (saved to the database):", s.spec.name || "MD run");
    if (name === null) return;
    setSaving(true);
    try {
      await saveRun({
        name,
        spec: s.spec,
        particle_types: s.particleTypes,
        type_index: s.typeIndex,
        box_lengths: s.boxLengths,
        frames: s.frames.map((f) => ({ step: f.step, time: f.time, positions: Array.from(f.positions) })),
        energy_history: s.energyHistory,
        summary: s.summary,
      });
      await refreshSavedRuns();
      s.setStatus(s.status, null);
    } catch (err) {
      s.setStatus("error", `Save failed: ${(err as Error).message}`);
    } finally {
      setSaving(false);
    }
  }

  async function loadFromDB(id: string) {
    if (!id) return;
    try {
      const data = (await getSavedRun(id)) as SavedRunData;
      useMDStore.getState().loadRun(data);
    } catch (err) {
      useMDStore.getState().setStatus("error", `Load failed: ${(err as Error).message}`);
    }
  }

  function saveXYZ() {
    const s = useMDStore.getState();
    downloadTrajectoryXYZ(s.spec.name, s.particleTypes, s.typeIndex, s.frames);
  }

  function handleRun() {
    resetPlayback();
    start(spec);
  }

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-canvas">
      {/* Top bar */}
      <div className="h-12 border-b border-border bg-surface flex items-center px-4 gap-3 shrink-0"
        style={{ background: "linear-gradient(90deg, #0e1425 0%, #111830 100%)" }}>
        <button onClick={onBack} className="flex items-center gap-1.5 text-sm text-slate-400 hover:text-white">
          <ArrowLeft size={15} /> Canvas
        </button>
        <div className="flex items-center gap-2 ml-2">
          <Atom size={16} className="text-indigo-400" />
          <span className="text-sm font-semibold text-white">MD Ground</span>
          <span className="text-xs text-slate-600">molecular-dynamics sandbox</span>
        </div>

        <div className="flex-1" />

        <span className={`text-xs font-medium ${st.cls}`}>● {st.text}</span>
        {isRunning && phase && PHASE_LABEL[phase] && (
          <span className="text-[11px] font-medium text-amber-300 bg-amber-500/10 border border-amber-500/20 rounded px-1.5 py-0.5">
            {PHASE_LABEL[phase]}
          </span>
        )}
        {error && <span className="text-xs text-red-400 max-w-md truncate" title={error}>{error}</span>}

        {/* Saved runs: load from DB */}
        <select
          value=""
          onChange={(e) => loadFromDB(e.target.value)}
          title="Open a run saved in the database"
          className="bg-canvas border border-border rounded-lg px-2 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-indigo-500/60 max-w-[12rem]"
        >
          <option value="">Load run ({savedRuns.length})…</option>
          {savedRuns.map((r) => (
            <option key={r.id} value={r.id}>
              {r.name} · {r.n_frames}f · {new Date(r.created_at).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
            </option>
          ))}
        </select>
        <button onClick={saveToDB} disabled={!hasFrames || saving}
          title="Save this run to the database (pull it later from any machine)"
          className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium text-slate-300 hover:text-white border border-border hover:border-slate-500 disabled:opacity-40">
          {saving ? <Database size={13} className="animate-pulse" /> : <Save size={13} />} {saving ? "Saving…" : "Save run"}
        </button>
        <button onClick={saveXYZ} disabled={!hasFrames}
          title="Download the trajectory as multi-frame XYZ (PyMOL / VMD)"
          className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium text-slate-300 hover:text-white border border-border hover:border-slate-500 disabled:opacity-40">
          <Film size={13} /> XYZ
        </button>

        {isRunning ? (
          <button onClick={cancel}
            className="flex items-center gap-2 px-4 py-1.5 rounded-lg text-sm font-semibold text-white bg-red-600/90 hover:bg-red-500">
            <Square size={13} fill="white" /> Stop
          </button>
        ) : (
          <button onClick={handleRun}
            className="flex items-center gap-2 px-4 py-1.5 rounded-lg text-sm font-semibold text-white bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-500 hover:to-purple-500"
            style={{ boxShadow: "0 0 16px rgba(99,102,241,0.4)" }}>
            <Play size={13} fill="white" />
            Run
          </button>
        )}
      </div>

      {/* 3-pane body */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left: controls */}
        <div className="w-80 shrink-0 border-r border-border bg-surface overflow-y-auto p-4">
          <ControlPanel />
        </div>

        {/* Center: 3D viewer + playback */}
        <div className="flex-1 flex flex-col overflow-hidden">
          <div className="flex-1 relative overflow-hidden">
            <Viewer3D />
          </div>
          <PlaybackControls />
        </div>

        {/* Right: energy charts / equations */}
        <div className="w-[22rem] shrink-0 border-l border-border bg-surface flex flex-col overflow-hidden">
          <div className="flex shrink-0 border-b border-border">
            {([["energy", "Energy", TrendingUp], ["math", "Equations", Sigma]] as const).map(([key, label, Icon]) => (
              <button
                key={key}
                onClick={() => setRightTab(key)}
                className={`flex-1 flex items-center justify-center gap-1.5 py-2 text-xs font-medium transition-colors ${
                  rightTab === key ? "text-white border-b-2 border-indigo-500 bg-white/5" : "text-slate-500 hover:text-slate-300"
                }`}
              >
                <Icon size={13} /> {label}
              </button>
            ))}
          </div>
          <div className="flex-1 overflow-y-auto p-3">
            {rightTab === "energy" ? <EnergyCharts /> : <MathPanel />}
          </div>
        </div>
      </div>
    </div>
  );
}
