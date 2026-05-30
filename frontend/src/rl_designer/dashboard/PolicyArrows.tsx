// Per-CDR dominant strategy visualisation with arrow direction and probability bars
// Inspired by TinyRL's policy-arrow display

import { useRLDesignerStore } from "../store";
import type { PolicyArrow } from "../store";

const STRATEGY_COLORS: Record<string, string> = {
  random:       "#94a3b8",
  blosum62:     "#818cf8",
  conservative: "#34d399",
  sapiens:      "#fbbf24",
};

const STRATEGY_ANGLES: Record<string, number> = {
  random:       0,
  blosum62:     45,
  conservative: -45,
  sapiens:      90,
};

function ArrowIcon({ strategy, size = 20 }: { strategy: string; size?: number }) {
  const angle = STRATEGY_ANGLES[strategy] ?? 0;
  const color = STRATEGY_COLORS[strategy] ?? "#94a3b8";
  const cx = size / 2, cy = size / 2, r = size * 0.35;
  const rad = (angle * Math.PI) / 180;
  const tx = cx + Math.cos(rad) * r;
  const ty = cy + Math.sin(rad) * r;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      <line x1={cx} y1={cy} x2={tx} y2={ty} stroke={color} strokeWidth={2.5} strokeLinecap="round" />
      <circle cx={cx} cy={cy} r={2} fill={color} />
    </svg>
  );
}

function StratBar({ label, prob, dominant }: { label: string; prob: number; dominant: boolean }) {
  const color = STRATEGY_COLORS[label] ?? "#94a3b8";
  return (
    <div className="flex items-center gap-2">
      <span className={`w-20 text-[9px] truncate ${dominant ? "text-slate-200 font-semibold" : "text-slate-500"}`}>{label}</span>
      <div className="flex-1 bg-slate-800 rounded-full h-1.5 overflow-hidden">
        <div className="h-full rounded-full transition-all" style={{ width: `${(prob * 100).toFixed(0)}%`, backgroundColor: color }} />
      </div>
      <span className="w-8 text-right text-[9px] font-mono" style={{ color }}>{(prob * 100).toFixed(0)}%</span>
    </div>
  );
}

function CDRRow({ arrow }: { arrow: PolicyArrow }) {
  const color = STRATEGY_COLORS[arrow.dominant_strategy] ?? "#94a3b8";
  return (
    <div className="bg-slate-800/60 rounded border border-slate-700 p-3 space-y-2">
      <div className="flex items-center gap-3">
        <ArrowIcon strategy={arrow.dominant_strategy} size={28} />
        <div>
          <p className="text-[12px] font-semibold text-slate-200">CDR-{arrow.cdr}</p>
          <p className="text-[10px]" style={{ color }}>
            {arrow.dominant_strategy}
            {arrow.confidence > 0.1 && (
              <span className="ml-2 text-slate-500 text-[9px]">
                +{arrow.confidence.toFixed(2)} vs random
              </span>
            )}
          </p>
        </div>
        {arrow.confidence < 0.05 && (
          <span className="ml-auto text-[9px] text-slate-600 italic">still exploring</span>
        )}
      </div>
      <div className="space-y-1">
        {Object.entries(arrow.distribution).map(([strat, prob]) => (
          <StratBar key={strat} label={strat} prob={prob} dominant={strat === arrow.dominant_strategy} />
        ))}
      </div>
    </div>
  );
}

export function PolicyArrows() {
  const { vizData } = useRLDesignerStore();
  const arrows = vizData?.policy_arrows ?? [];

  if (arrows.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-[11px] text-slate-600">
        No policy data yet — run at least one iteration.
      </div>
    );
  }

  return (
    <div className="p-4 h-full overflow-auto space-y-3">
      <p className="text-[10px] text-slate-500 font-semibold uppercase tracking-widest mb-1">
        Learned Policy — dominant action per CDR region
      </p>
      {arrows.map((arrow) => (
        <CDRRow key={arrow.cdr} arrow={arrow} />
      ))}
    </div>
  );
}
