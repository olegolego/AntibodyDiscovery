// Per-iteration episode history table (inspired by RLHF-Blender's trajectory viewer)

import { useState } from "react";
import { useRLDesignerStore } from "../store";
import type { EpisodeEntry } from "../store";

type SortKey = keyof Pick<EpisodeEntry, "iteration" | "q_value" | "score_delta">;

export function EpisodeTable() {
  const { episodeHistory } = useRLDesignerStore();
  const [sortKey, setSortKey] = useState<SortKey>("iteration");
  const [sortAsc, setSortAsc] = useState(false);

  const sorted = [...episodeHistory].sort((a, b) => {
    const av = a[sortKey] ?? 0;
    const bv = b[sortKey] ?? 0;
    return sortAsc ? (av as number) - (bv as number) : (bv as number) - (av as number);
  });

  function toggleSort(key: SortKey) {
    if (sortKey === key) setSortAsc(!sortAsc);
    else { setSortKey(key); setSortAsc(false); }
  }

  function rowColor(entry: EpisodeEntry): string {
    if (entry.exploratory) return "bg-yellow-500/5 border-yellow-900/30";
    if ((entry.score_delta ?? 0) > 0) return "bg-emerald-500/5 border-emerald-900/30";
    if ((entry.score_delta ?? 0) < 0) return "bg-red-500/5 border-red-900/30";
    return "bg-slate-800/30 border-slate-800";
  }

  if (episodeHistory.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-[11px] text-slate-600">
        No episode history yet.
      </div>
    );
  }

  function SortTh({ label, k }: { label: string; k: SortKey }) {
    return (
      <th
        className="px-2 py-2 text-left text-[9px] font-bold uppercase tracking-widest text-slate-500 cursor-pointer hover:text-slate-300 select-none whitespace-nowrap"
        onClick={() => toggleSort(k)}
      >
        {label} {sortKey === k ? (sortAsc ? "↑" : "↓") : ""}
      </th>
    );
  }

  return (
    <div className="p-3 h-full overflow-auto">
      <p className="text-[10px] text-slate-500 font-semibold uppercase tracking-widest mb-2">
        Episode History ({episodeHistory.length} entries)
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-[11px] border-collapse">
          <thead className="sticky top-0 bg-slate-900 z-10">
            <tr>
              <SortTh label="Iter" k="iteration" />
              <th className="px-2 py-2 text-left text-[9px] font-bold uppercase tracking-widest text-slate-500">Seq</th>
              <th className="px-2 py-2 text-left text-[9px] font-bold uppercase tracking-widest text-slate-500">CDR</th>
              <th className="px-2 py-2 text-left text-[9px] font-bold uppercase tracking-widest text-slate-500">Strategy</th>
              <th className="px-2 py-2 text-left text-[9px] font-bold uppercase tracking-widest text-slate-500">N Mut</th>
              <SortTh label="Q-value" k="q_value" />
              <SortTh label="Δ Score" k="score_delta" />
              <th className="px-2 py-2 text-left text-[9px] font-bold uppercase tracking-widest text-slate-500">Mode</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((entry, i) => (
              <tr key={i} className={`border-b ${rowColor(entry)} hover:brightness-125 transition-colors`}>
                <td className="px-2 py-1.5 font-mono text-slate-400">{entry.iteration}</td>
                <td className="px-2 py-1.5 font-mono text-slate-500 max-w-[80px] truncate" title={entry.seq_id}>
                  {entry.seq_id.substring(0, 10)}
                </td>
                <td className="px-2 py-1.5 font-semibold text-slate-300">{entry.cdr}</td>
                <td className="px-2 py-1.5 text-slate-400">{entry.strategy}</td>
                <td className="px-2 py-1.5 text-slate-400">{entry.n_mutations}</td>
                <td className="px-2 py-1.5 font-mono text-indigo-300">{entry.q_value.toFixed(3)}</td>
                <td className="px-2 py-1.5 font-mono">
                  {entry.score_delta !== undefined ? (
                    <span className={entry.score_delta > 0 ? "text-emerald-400" : entry.score_delta < 0 ? "text-red-400" : "text-slate-500"}>
                      {entry.score_delta > 0 ? "+" : ""}{entry.score_delta.toFixed(2)}
                    </span>
                  ) : (
                    <span className="text-slate-700">—</span>
                  )}
                </td>
                <td className="px-2 py-1.5">
                  {entry.exploratory ? (
                    <span className="text-[9px] text-yellow-500 bg-yellow-500/10 px-1.5 py-0.5 rounded">explore</span>
                  ) : (
                    <span className="text-[9px] text-indigo-400 bg-indigo-500/10 px-1.5 py-0.5 rounded">exploit</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
