// SVG line chart of per-iteration mean reward + rolling-average band
// Inspired by RL Coach's multi-signal training dashboard with Bollinger bands

import { useRLDesignerStore } from "../store";

function rollingAvg(arr: number[], window: number): number[] {
  return arr.map((_, i) => {
    const slice = arr.slice(Math.max(0, i - window + 1), i + 1);
    return slice.reduce((a, b) => a + b, 0) / slice.length;
  });
}

function rollingStd(arr: number[], window: number, avgs: number[]): number[] {
  return arr.map((_, i) => {
    const slice = arr.slice(Math.max(0, i - window + 1), i + 1);
    const mu = avgs[i];
    const variance = slice.reduce((a, v) => a + (v - mu) ** 2, 0) / slice.length;
    return Math.sqrt(variance);
  });
}

export function RewardCurve() {
  const { vizData, metrics } = useRLDesignerStore();

  const rewards = vizData?.episode_rewards ?? [];

  if (rewards.length < 2) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-2 text-[11px] text-slate-600">
        <span>No reward history yet.</span>
        {metrics && (
          <span className="text-slate-500">Last reward: <span className="font-mono text-amber-400">{metrics.mean_reward?.toFixed(3)}</span></span>
        )}
      </div>
    );
  }

  const W = 500;
  const H = 200;
  const pad = { top: 20, right: 20, bottom: 30, left: 45 };
  const iW = W - pad.left - pad.right;
  const iH = H - pad.top - pad.bottom;

  const WINDOW = 3;
  const avgs = rollingAvg(rewards, WINDOW);
  const stds = rollingStd(rewards, WINDOW, avgs);

  const minY = Math.min(...rewards) - 0.1;
  const maxY = Math.max(...rewards) + 0.1;
  const range = maxY - minY || 1;

  function px(i: number): number {
    return pad.left + (i / (rewards.length - 1)) * iW;
  }
  function py(v: number): number {
    return pad.top + iH - ((v - minY) / range) * iH;
  }

  // Raw line path
  const rawPath = rewards.map((v, i) => `${i === 0 ? "M" : "L"}${px(i).toFixed(1)},${py(v).toFixed(1)}`).join(" ");
  // Rolling avg path
  const avgPath = avgs.map((v, i) => `${i === 0 ? "M" : "L"}${px(i).toFixed(1)},${py(v).toFixed(1)}`).join(" ");
  // Std band (upper + lower)
  const bandTop = avgs.map((v, i) => ({ x: px(i), y: py(v + stds[i]) }));
  const bandBot = avgs.map((v, i) => ({ x: px(i), y: py(v - stds[i]) }));
  const bandPath =
    bandTop.map((p, i) => `${i === 0 ? "M" : "L"}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ") +
    " " +
    [...bandBot].reverse().map((p, i) => `${i === 0 ? "L" : "L"}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ") +
    " Z";

  // Y axis ticks
  const nTicks = 5;
  const ticks = Array.from({ length: nTicks }, (_, i) => minY + (i / (nTicks - 1)) * range);

  return (
    <div className="p-4 h-full overflow-auto">
      <div className="flex items-center gap-3 mb-3">
        <p className="text-[10px] text-slate-500 font-semibold uppercase tracking-widest">
          Reward History
        </p>
        {metrics && (
          <span className="ml-auto text-[10px] font-mono text-amber-300">
            ε={metrics.epsilon?.toFixed(3)} · reward={metrics.mean_reward?.toFixed(3)} · loss={metrics.mean_loss?.toFixed(4)}
          </span>
        )}
      </div>
      <svg width="100%" viewBox={`0 0 ${W} ${H}`}>
        {/* Std band */}
        <path d={bandPath} fill="#f59e0b22" />
        {/* Raw reward line */}
        <path d={rawPath} fill="none" stroke="#475569" strokeWidth={1} strokeDasharray="3 2" />
        {/* Rolling avg line */}
        <path d={avgPath} fill="none" stroke="#f59e0b" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />

        {/* Y axis */}
        <line x1={pad.left} y1={pad.top} x2={pad.left} y2={pad.top + iH} stroke="#334155" strokeWidth={1} />
        {ticks.map((v, i) => (
          <g key={i}>
            <line x1={pad.left - 3} y1={py(v)} x2={pad.left} y2={py(v)} stroke="#334155" strokeWidth={1} />
            <text x={pad.left - 5} y={py(v)} textAnchor="end" dominantBaseline="middle"
              fill="#64748b" fontSize={8} fontFamily="monospace">
              {v.toFixed(1)}
            </text>
          </g>
        ))}

        {/* X axis */}
        <line x1={pad.left} y1={pad.top + iH} x2={pad.left + iW} y2={pad.top + iH} stroke="#334155" strokeWidth={1} />
        <text x={pad.left + iW / 2} y={H - 4} textAnchor="middle" fill="#475569" fontSize={9} fontFamily="system-ui">
          Loop iteration
        </text>

        {/* Legend */}
        <g transform={`translate(${pad.left + iW - 110},${pad.top + 4})`}>
          <line x1={0} y1={6} x2={16} y2={6} stroke="#f59e0b" strokeWidth={2} />
          <text x={20} y={9} fill="#f59e0b" fontSize={8}>rolling avg (±1σ)</text>
          <line x1={0} y1={18} x2={16} y2={18} stroke="#475569" strokeWidth={1} strokeDasharray="3 2" />
          <text x={20} y={21} fill="#64748b" fontSize={8}>per-iteration</text>
        </g>
      </svg>
    </div>
  );
}
