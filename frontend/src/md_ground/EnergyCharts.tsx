import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useMDStore } from "./store";

// Downsample the energy history to keep the chart light during long runs.
function downsample<T>(arr: T[], maxPoints: number): T[] {
  if (arr.length <= maxPoints) return arr;
  const stride = Math.ceil(arr.length / maxPoints);
  return arr.filter((_, i) => i % stride === 0);
}

export function EnergyCharts() {
  const history = useMDStore((s) => s.energyHistory);
  const summary = useMDStore((s) => s.summary);
  const data = downsample(history, 300);

  if (data.length === 0) {
    return (
      <div className="text-xs text-slate-600 px-3 py-6 text-center">
        Energy traces appear once the simulation starts.
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div>
        <div className="text-[11px] text-slate-500 uppercase tracking-wider mb-1 px-1">
          Energy (KE / PE / total)
        </div>
        <ResponsiveContainer width="100%" height={130}>
          <LineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: -18 }}>
            <XAxis dataKey="step" tick={{ fontSize: 9, fill: "#64748b" }} stroke="#334155" />
            <YAxis tick={{ fontSize: 9, fill: "#64748b" }} stroke="#334155" width={42} />
            <Tooltip
              contentStyle={{ background: "#0e1425", border: "1px solid #1e293b", fontSize: 11 }}
              labelStyle={{ color: "#94a3b8" }}
            />
            <Line type="monotone" dataKey="kinetic" stroke="#22d3ee" dot={false} strokeWidth={1.4} name="KE" isAnimationActive={false} />
            <Line type="monotone" dataKey="potential" stroke="#f59e0b" dot={false} strokeWidth={1.4} name="PE" isAnimationActive={false} />
            <Line type="monotone" dataKey="total" stroke="#a78bfa" dot={false} strokeWidth={1.6} name="Total" isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div>
        <div className="text-[11px] text-slate-500 uppercase tracking-wider mb-1 px-1">
          Temperature
        </div>
        <ResponsiveContainer width="100%" height={90}>
          <LineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: -18 }}>
            <XAxis dataKey="step" tick={{ fontSize: 9, fill: "#64748b" }} stroke="#334155" />
            <YAxis tick={{ fontSize: 9, fill: "#64748b" }} stroke="#334155" width={42} />
            <Tooltip
              contentStyle={{ background: "#0e1425", border: "1px solid #1e293b", fontSize: 11 }}
              labelStyle={{ color: "#94a3b8" }}
            />
            <Line type="monotone" dataKey="temperature" stroke="#34d399" dot={false} strokeWidth={1.4} name="T" isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {summary && (
        <div className="text-[11px] text-slate-400 px-1 flex flex-wrap gap-x-4 gap-y-1">
          <span>steps: <b className="text-slate-200">{summary.steps_run}</b></span>
          <span>
            energy drift:{" "}
            <b className={summary.energy_drift < 0.01 ? "text-emerald-400" : summary.energy_drift < 0.05 ? "text-amber-400" : "text-red-400"}>
              {(summary.energy_drift * 100).toFixed(2)}%
            </b>
          </span>
          <span>wall: <b className="text-slate-200">{summary.wall_seconds.toFixed(1)}s</b></span>
        </div>
      )}
    </div>
  );
}
