import { useRLDesignerStore, computeActionCount } from "./store";
import { CDR_OPTIONS, STRATEGY_OPTIONS } from "./blocks";
import type { CDR, MutationStrategy } from "./store";

function Toggle({
  checked,
  onChange,
  label,
  description,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
  description?: string;
}) {
  return (
    <button
      onClick={() => onChange(!checked)}
      className={`flex flex-col items-start px-2.5 py-2 rounded border text-left transition-colors ${
        checked
          ? "border-emerald-500 bg-emerald-500/10 text-emerald-300"
          : "border-slate-700 bg-slate-800/50 text-slate-400 hover:border-slate-500"
      }`}
    >
      <span className="text-[11px] font-semibold">{label}</span>
      {description && <span className="text-[9px] text-slate-500 mt-0.5 leading-tight">{description}</span>}
    </button>
  );
}

export function ActionBlock() {
  const { spec, updateAction } = useRLDesignerStore();
  const { action } = spec;

  function toggleCDR(cdr: CDR) {
    const next = action.cdrs.includes(cdr)
      ? action.cdrs.filter((c) => c !== cdr)
      : [...action.cdrs, cdr];
    if (next.length > 0) updateAction({ cdrs: next });
  }

  function toggleStrategy(s: MutationStrategy) {
    const next = action.strategies.includes(s)
      ? action.strategies.filter((x) => x !== s)
      : [...action.strategies, s];
    if (next.length > 0) updateAction({ strategies: next });
  }

  function toggleNMut(n: 1 | 2 | 3) {
    const next = action.n_mutations_choices.includes(n)
      ? action.n_mutations_choices.filter((x) => x !== n)
      : [...action.n_mutations_choices, n].sort() as (1 | 2 | 3)[];
    if (next.length > 0) updateAction({ n_mutations_choices: next });
  }

  const actionCount = computeActionCount(spec);

  return (
    <div className="space-y-4">
      {/* CDR regions */}
      <div>
        <label className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-1.5 block">
          CDR regions
        </label>
        <div className="grid grid-cols-3 gap-1.5">
          {CDR_OPTIONS.map((opt) => (
            <Toggle
              key={opt.value}
              checked={action.cdrs.includes(opt.value as CDR)}
              onChange={() => toggleCDR(opt.value as CDR)}
              label={opt.label}
            />
          ))}
        </div>
      </div>

      {/* Mutation strategies */}
      <div>
        <label className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-1.5 block">
          Mutation strategies
        </label>
        <div className="space-y-1">
          {STRATEGY_OPTIONS.map((opt) => (
            <Toggle
              key={opt.value}
              checked={action.strategies.includes(opt.value as MutationStrategy)}
              onChange={() => toggleStrategy(opt.value as MutationStrategy)}
              label={opt.label}
              description={opt.description}
            />
          ))}
        </div>
      </div>

      {/* N mutations */}
      <div>
        <label className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-1.5 block">
          Mutations per CDR
        </label>
        <div className="flex gap-1.5">
          {([1, 2, 3] as const).map((n) => (
            <button
              key={n}
              onClick={() => toggleNMut(n)}
              className={`flex-1 py-2 rounded border text-[12px] font-semibold transition-colors ${
                action.n_mutations_choices.includes(n)
                  ? "border-emerald-500 bg-emerald-500/10 text-emerald-300"
                  : "border-slate-700 bg-slate-800/50 text-slate-400 hover:border-slate-500"
              }`}
            >
              {n}
            </button>
          ))}
        </div>
      </div>

      {/* Action space size */}
      <div className="bg-slate-800/60 rounded p-2 flex items-center gap-2">
        <span className="text-[10px] text-slate-500">Total discrete actions</span>
        <span className="ml-auto font-mono text-[12px] text-emerald-300 font-bold">|A| = {actionCount}</span>
      </div>
      <p className="text-[10px] text-slate-600">
        {action.cdrs.length} CDRs × {action.strategies.length} strategies × {action.n_mutations_choices.length} n_mut = {actionCount}
      </p>
    </div>
  );
}
