// Q-value heatmap: rows = CDR region, cols = mutation strategy
// Cell color: blue (low Q) → red (high Q), inspired by TinyRL's value-function heatmap

import { useRLDesignerStore } from "../store";

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

function qToColor(q: number, minQ: number, maxQ: number): string {
  const range = maxQ - minQ;
  const t = range < 0.001 ? 0.5 : (q - minQ) / range;
  // blue → indigo → violet → rose → red
  const r = Math.round(lerp(59, 239, t));
  const g = Math.round(lerp(130, 68, t));
  const b = Math.round(lerp(246, 68, t));
  return `rgb(${r},${g},${b})`;
}

export function QHeatmap() {
  const { vizData } = useRLDesignerStore();

  if (!vizData?.q_heatmap?.cdrs?.length) {
    return (
      <div className="flex items-center justify-center h-full text-[11px] text-slate-600">
        No Q-values yet — run the pipeline with an rl_designer node first.
      </div>
    );
  }

  const { cdrs, strategies, values } = vizData.q_heatmap;

  // Flatten all values to get global min/max for colour scale
  const allVals = cdrs.flatMap((c) => strategies.map((s) => values[c]?.[s] ?? 0));
  const minQ = Math.min(...allVals);
  const maxQ = Math.max(...allVals);

  return (
    <div className="p-4 h-full overflow-auto">
      <p className="text-[10px] text-slate-500 mb-3 font-semibold uppercase tracking-widest">
        Q-Value Heatmap — max Q(s,a) per (CDR × strategy)
      </p>
      <div className="overflow-x-auto">
        <table className="border-collapse text-[11px]">
          <thead>
            <tr>
              <th className="w-16 text-slate-600 font-normal text-left pb-1 pr-3"></th>
              {strategies.map((s) => (
                <th key={s} className="px-3 pb-2 text-slate-400 font-semibold text-[10px] uppercase tracking-wide text-center whitespace-nowrap">
                  {s}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {cdrs.map((cdr) => (
              <tr key={cdr}>
                <td className="text-slate-400 font-semibold pr-3 py-1 text-[11px]">CDR-{cdr}</td>
                {strategies.map((strat) => {
                  const q = values[cdr]?.[strat] ?? 0;
                  const bg = qToColor(q, minQ, maxQ);
                  return (
                    <td key={strat} className="px-1 py-0.5">
                      <div
                        className="w-20 h-10 rounded flex items-center justify-center font-mono text-[10px] font-bold text-white/90 transition-all"
                        style={{ backgroundColor: bg }}
                        title={`CDR-${cdr} / ${strat}: Q=${q.toFixed(3)}`}
                      >
                        {q.toFixed(2)}
                      </div>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Colour scale legend */}
      <div className="flex items-center gap-2 mt-4">
        <span className="text-[9px] text-slate-600">{minQ.toFixed(2)}</span>
        <div
          className="flex-1 h-2 rounded"
          style={{ background: "linear-gradient(to right, rgb(59,130,246), rgb(239,68,68))" }}
        />
        <span className="text-[9px] text-slate-600">{maxQ.toFixed(2)}</span>
      </div>
    </div>
  );
}
