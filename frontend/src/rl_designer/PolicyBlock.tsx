import { useRLDesignerStore, computeActionCount, stateDimLabel } from "./store";
import type { ArchitectureSpec } from "@/dnn_designer/store";

interface PolicyBlockProps {
  onOpenDNNDesigner: (spec: ArchitectureSpec | null) => void;
}

export function PolicyBlock({ onOpenDNNDesigner }: PolicyBlockProps) {
  const { spec } = useRLDesignerStore();
  const { policy_network } = spec;

  const hasNetwork = policy_network.nodes.length > 0;
  const actionCount = computeActionCount(spec);
  const stateDim = stateDimLabel(spec);

  return (
    <div className="space-y-4">
      {/* Network summary */}
      <div className="bg-slate-800/60 rounded border border-slate-700 p-3 space-y-2">
        <p className="text-[10px] text-slate-500 font-semibold uppercase tracking-widest">Q-Network shape</p>
        <div className="flex items-center gap-2">
          <div className="flex-1 text-center">
            <p className="text-[9px] text-slate-600">Input</p>
            <p className="text-[12px] font-mono text-violet-300">[B, {stateDim}]</p>
          </div>
          <span className="text-slate-600">→</span>
          <div className="flex-1 text-center">
            <p className="text-[9px] text-slate-600">Backbone</p>
            <p className="text-[12px] font-mono text-violet-300">
              {hasNetwork ? `${policy_network.nodes.length} layers` : "default MLP"}
            </p>
          </div>
          <span className="text-slate-600">→</span>
          <div className="flex-1 text-center">
            <p className="text-[9px] text-slate-600">Q-head</p>
            <p className="text-[12px] font-mono text-violet-300">[B, {actionCount}]</p>
          </div>
        </div>
      </div>

      {/* Note about the output head */}
      <p className="text-[10px] text-slate-500 leading-relaxed">
        The Q-network backbone is built using the DNN Designer. A linear Q-head
        (<span className="font-mono text-slate-400">hidden → |A|={actionCount}</span>) is automatically appended.
        Leave empty to use a default 2-layer MLP.
      </p>

      {/* Design button */}
      <button
        onClick={() => onOpenDNNDesigner(hasNetwork ? policy_network : null)}
        className="w-full py-2.5 rounded border border-violet-500/50 bg-violet-500/10 text-violet-300 text-[12px] font-semibold hover:bg-violet-500/20 transition-colors"
      >
        {hasNetwork ? "Edit Q-Network →" : "Design Q-Network →"}
      </button>

      {hasNetwork && (
        <div className="text-[10px] text-slate-500 space-y-1">
          <p className="font-semibold text-slate-400">{policy_network.nodes.length} layers configured</p>
          {policy_network.nodes.map((n) => (
            <div key={n.id} className="flex gap-2">
              <span className="text-slate-600 w-20 truncate font-mono">{n.id}</span>
              <span className="text-slate-500">{n.type}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
