import { useRLDesignerStore } from "./store";
import { REPR_TYPE_OPTIONS } from "./blocks";

export function StateBlock() {
  const { spec, updateState } = useRLDesignerStore();
  const { state } = spec;

  const selected = REPR_TYPE_OPTIONS.find((r) => r.value === state.repr_type);

  return (
    <div className="space-y-3">
      {/* Repr type selector */}
      <div>
        <label className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-1 block">
          Representation
        </label>
        <div className="grid grid-cols-2 gap-1.5">
          {REPR_TYPE_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => updateState({ repr_type: opt.value as typeof state.repr_type, dim: opt.dim })}
              className={`flex flex-col items-start px-2.5 py-2 rounded border text-left transition-colors ${
                state.repr_type === opt.value
                  ? "border-rose-500 bg-rose-500/10 text-rose-300"
                  : "border-slate-700 bg-slate-800/50 text-slate-400 hover:border-slate-500"
              }`}
            >
              <span className="text-[11px] font-semibold">{opt.label}</span>
              <span className="text-[9px] text-slate-500">{opt.dim}d</span>
            </button>
          ))}
        </div>
        {selected && (
          <p className="text-[10px] text-slate-500 mt-1.5">{selected.description}</p>
        )}
      </div>

      {/* Pipeline port name */}
      <div>
        <label className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-1 block">
          Input port
        </label>
        <input
          className="w-full bg-slate-800 border border-slate-700 rounded px-2 py-1.5 text-[11px] text-slate-300 font-mono focus:outline-none focus:border-rose-500"
          value={state.port}
          onChange={(e) => updateState({ port: e.target.value })}
          placeholder="state_embeddings"
        />
        <p className="text-[10px] text-slate-600 mt-1">
          Pipeline output port that carries the embedding (wired from AbMAP / ESM / AbLang).
        </p>
      </div>

      {/* Optional projection */}
      <div>
        <label className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-1 block">
          Projection dim <span className="text-slate-600 normal-case font-normal">(0 = passthrough)</span>
        </label>
        <input
          type="number"
          min={0}
          max={2048}
          step={32}
          className="w-full bg-slate-800 border border-slate-700 rounded px-2 py-1.5 text-[11px] text-slate-300 font-mono focus:outline-none focus:border-rose-500"
          value={state.projection_dim}
          onChange={(e) => updateState({ projection_dim: Number(e.target.value) })}
        />
      </div>

      {/* State dim summary */}
      <div className="bg-slate-800/60 rounded p-2 flex items-center gap-2">
        <span className="text-[10px] text-slate-500">Effective state dim</span>
        <span className="ml-auto font-mono text-[11px] text-rose-300">
          {state.projection_dim > 0 ? state.projection_dim : state.dim}d
        </span>
      </div>
    </div>
  );
}
