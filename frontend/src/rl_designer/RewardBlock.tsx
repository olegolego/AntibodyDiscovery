import { useState } from "react";
import { useRLDesignerStore } from "./store";
import type { RewardSignal, Normalization, RewardShaping } from "./store";

const NORMALIZATION_OPTS: { value: Normalization; label: string }[] = [
  { value: "none",    label: "None" },
  { value: "z_score", label: "Z-score" },
  { value: "min_max", label: "Min-max" },
];

export function RewardBlock() {
  const { spec, updateReward } = useRLDesignerStore();
  const { reward } = spec;
  const [newPort, setNewPort] = useState("");

  function addSignal() {
    const port = newPort.trim();
    if (!port) return;
    const next: RewardSignal[] = [
      ...reward.signals,
      { port, weight: 1.0, lower_is_better: true, normalization: "z_score" },
    ];
    updateReward({ signals: next });
    setNewPort("");
  }

  function removeSignal(i: number) {
    updateReward({ signals: reward.signals.filter((_, idx) => idx !== i) });
  }

  function patchSignal(i: number, patch: Partial<RewardSignal>) {
    const next = reward.signals.map((s, idx) => (idx === i ? { ...s, ...patch } : s));
    updateReward({ signals: next });
  }

  return (
    <div className="space-y-4">
      {/* Reward signals list */}
      <div>
        <label className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-2 block">
          Score signals
        </label>
        {reward.signals.length === 0 && (
          <p className="text-[10px] text-slate-600 mb-2">No signals configured. Add a pipeline output port below.</p>
        )}
        <div className="space-y-2">
          {reward.signals.map((sig, i) => (
            <div key={i} className="bg-slate-800/60 rounded border border-slate-700 p-2 space-y-2">
              <div className="flex items-center gap-2">
                <span className="font-mono text-[11px] text-amber-300 flex-1 truncate">{sig.port}</span>
                <button
                  onClick={() => removeSignal(i)}
                  className="text-slate-600 hover:text-red-400 text-[11px] transition-colors"
                >
                  ✕
                </button>
              </div>
              <div className="grid grid-cols-3 gap-2">
                {/* Weight */}
                <div>
                  <label className="text-[9px] text-slate-600 block mb-0.5">Weight</label>
                  <input
                    type="number"
                    min={0}
                    max={10}
                    step={0.1}
                    className="w-full bg-slate-900 border border-slate-700 rounded px-1.5 py-1 text-[11px] text-slate-300 font-mono focus:outline-none focus:border-amber-500"
                    value={sig.weight}
                    onChange={(e) => patchSignal(i, { weight: Number(e.target.value) })}
                  />
                </div>
                {/* Normalization */}
                <div>
                  <label className="text-[9px] text-slate-600 block mb-0.5">Norm</label>
                  <select
                    className="w-full bg-slate-900 border border-slate-700 rounded px-1.5 py-1 text-[11px] text-slate-300 focus:outline-none focus:border-amber-500"
                    value={sig.normalization}
                    onChange={(e) => patchSignal(i, { normalization: e.target.value as Normalization })}
                  >
                    {NORMALIZATION_OPTS.map((o) => (
                      <option key={o.value} value={o.value}>{o.label}</option>
                    ))}
                  </select>
                </div>
                {/* Lower is better */}
                <div>
                  <label className="text-[9px] text-slate-600 block mb-0.5">Direction</label>
                  <button
                    onClick={() => patchSignal(i, { lower_is_better: !sig.lower_is_better })}
                    className={`w-full py-1 rounded border text-[9px] font-semibold transition-colors ${
                      sig.lower_is_better
                        ? "border-blue-500 bg-blue-500/10 text-blue-300"
                        : "border-green-500 bg-green-500/10 text-green-300"
                    }`}
                  >
                    {sig.lower_is_better ? "↓ lower" : "↑ higher"}
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Add new signal */}
      <div className="flex gap-2">
        <input
          className="flex-1 bg-slate-800 border border-slate-700 rounded px-2 py-1.5 text-[11px] text-slate-300 font-mono focus:outline-none focus:border-amber-500"
          placeholder="haddock_score"
          value={newPort}
          onChange={(e) => setNewPort(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && addSignal()}
        />
        <button
          onClick={addSignal}
          className="px-3 py-1.5 bg-amber-500/20 border border-amber-500/50 text-amber-300 rounded text-[11px] font-semibold hover:bg-amber-500/30 transition-colors"
        >
          + Add
        </button>
      </div>

      {/* Reward shaping */}
      <div>
        <label className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-1.5 block">
          Reward shaping
        </label>
        <div className="flex gap-2">
          {(["sparse", "dense"] as RewardShaping[]).map((s) => (
            <button
              key={s}
              onClick={() => updateReward({ shaping: s })}
              className={`flex-1 py-2 rounded border text-[11px] font-semibold capitalize transition-colors ${
                reward.shaping === s
                  ? "border-amber-500 bg-amber-500/10 text-amber-300"
                  : "border-slate-700 bg-slate-800/50 text-slate-400 hover:border-slate-500"
              }`}
            >
              {s}
            </button>
          ))}
        </div>
        <p className="text-[10px] text-slate-600 mt-1">
          {reward.shaping === "sparse"
            ? "Reward only from final evaluation scores (docking, pLDDT)."
            : "Dense: intermediate proxy signals (embedding quality, diversity) supplement sparse rewards."}
        </p>
      </div>
    </div>
  );
}
