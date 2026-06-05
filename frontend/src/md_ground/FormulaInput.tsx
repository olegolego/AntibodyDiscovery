import { useEffect, useState } from "react";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { validateFormula, type FormulaSample } from "./api";

interface Props {
  value: string;
  onChange: (expr: string) => void;
}

// Live editor for a pair potential U(r). Debounced validation hits the backend,
// which returns sampled U(r) and F(r)=-dU/dr for the preview chart.
export function FormulaInput({ value, onChange }: Props) {
  const [samples, setSamples] = useState<FormulaSample[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!value.trim()) {
      setSamples([]);
      setError(null);
      return;
    }
    const t = setTimeout(async () => {
      try {
        const out = await validateFormula(value);
        setSamples(out.samples);
        setError(null);
      } catch (e) {
        setError(String((e as Error).message));
        setSamples([]);
      }
    }, 350);
    return () => clearTimeout(t);
  }, [value]);

  return (
    <div className="space-y-2">
      <label className="text-[11px] text-slate-500">Potential U(r), variable r (reduced units)</label>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="4*(1/r**12 - 1/r**6)"
        className="w-full bg-canvas border border-border rounded-md px-2 py-1.5 text-sm text-slate-200 font-mono focus:outline-none focus:border-indigo-500/60"
      />
      {error && <div className="text-[11px] text-red-400">{error}</div>}
      {samples.length > 0 && (
        <ResponsiveContainer width="100%" height={120}>
          <LineChart data={samples} margin={{ top: 4, right: 8, bottom: 0, left: -20 }}>
            <XAxis dataKey="r" tick={{ fontSize: 9, fill: "#64748b" }} stroke="#334155"
              tickFormatter={(v) => Number(v).toFixed(1)} />
            <YAxis tick={{ fontSize: 9, fill: "#64748b" }} stroke="#334155" width={40}
              domain={[-4, 4]} allowDataOverflow />
            <Tooltip contentStyle={{ background: "#0e1425", border: "1px solid #1e293b", fontSize: 11 }} />
            <Line type="monotone" dataKey="U" stroke="#f59e0b" dot={false} strokeWidth={1.4} name="U(r)" isAnimationActive={false} />
            <Line type="monotone" dataKey="F" stroke="#22d3ee" dot={false} strokeWidth={1.4} name="F(r)" isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
