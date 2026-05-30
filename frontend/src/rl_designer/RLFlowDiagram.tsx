// Static SVG diagram showing the MDP flow: State → Policy → Action → Environment → Reward ↺
// Inspired by TinyRL's visual MDP layout — gives orientation without requiring node-wiring.

import { useRLDesignerStore, computeActionCount } from "./store";

interface BoxProps {
  x: number;
  y: number;
  w: number;
  h: number;
  color: string;
  label: string;
  sublabel?: string;
}

function Box({ x, y, w, h, color, label, sublabel }: BoxProps) {
  return (
    <g>
      <rect x={x} y={y} width={w} height={h} rx={6} fill={color + "22"} stroke={color} strokeWidth={1.5} />
      <text x={x + w / 2} y={y + h / 2 - (sublabel ? 6 : 0)} textAnchor="middle" dominantBaseline="middle"
        fill={color} fontSize={11} fontWeight={600} fontFamily="system-ui">
        {label}
      </text>
      {sublabel && (
        <text x={x + w / 2} y={y + h / 2 + 9} textAnchor="middle" dominantBaseline="middle"
          fill={color + "99"} fontSize={9} fontFamily="monospace">
          {sublabel}
        </text>
      )}
    </g>
  );
}

function Arrow({ x1, y1, x2, y2, color = "#475569" }: { x1: number; y1: number; x2: number; y2: number; color?: string }) {
  return (
    <g>
      <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={color} strokeWidth={1.5} markerEnd="url(#arrowhead)" />
    </g>
  );
}

export function RLFlowDiagram() {
  const { spec } = useRLDesignerStore();
  const n_actions = computeActionCount(spec);
  const state_dim = spec.state.projection_dim > 0 ? spec.state.projection_dim : spec.state.dim;

  const W = 540;
  const H = 100;
  const bw = 88;
  const bh = 52;
  const gap = 18;
  const top = (H - bh) / 2;

  // Box x positions
  const xs = [10, 10 + bw + gap, 10 + (bw + gap) * 2, 10 + (bw + gap) * 3, 10 + (bw + gap) * 4];

  return (
    <svg width="100%" viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ maxHeight: 100 }}>
      <defs>
        <marker id="arrowhead" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">
          <path d="M0,0 L0,6 L8,3 z" fill="#475569" />
        </marker>
        <marker id="arrowhead-loop" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">
          <path d="M0,0 L0,6 L8,3 z" fill="#6366f1" />
        </marker>
      </defs>

      {/* Boxes */}
      <Box x={xs[0]} y={top} w={bw} h={bh} color="#fb7185" label="State" sublabel={`${state_dim}d emb`} />
      <Box x={xs[1]} y={top} w={bw} h={bh} color="#a78bfa" label="Q-Network" sublabel="DQN" />
      <Box x={xs[2]} y={top} w={bw} h={bh} color="#34d399" label="Action" sublabel={`|A|=${n_actions}`} />
      <Box x={xs[3]} y={top} w={bw} h={bh} color="#94a3b8" label="CDR Mutator" sublabel="evaluate" />
      <Box x={xs[4]} y={top} w={bw} h={bh} color="#fbbf24" label="Reward" sublabel="docking score" />

      {/* Forward arrows */}
      <Arrow x1={xs[0] + bw} y1={top + bh / 2} x2={xs[1]} y2={top + bh / 2} />
      <Arrow x1={xs[1] + bw} y1={top + bh / 2} x2={xs[2]} y2={top + bh / 2} />
      <Arrow x1={xs[2] + bw} y1={top + bh / 2} x2={xs[3]} y2={top + bh / 2} />
      <Arrow x1={xs[3] + bw} y1={top + bh / 2} x2={xs[4]} y2={top + bh / 2} />

      {/* Feedback loop: Reward → Q-Network (bottom arc) */}
      <path
        d={`M ${xs[4] + bw / 2} ${top + bh} Q ${W / 2} ${H - 4} ${xs[1] + bw / 2} ${top + bh}`}
        fill="none" stroke="#6366f1" strokeWidth={1.5} strokeDasharray="4 3"
        markerEnd="url(#arrowhead-loop)"
      />
      <text x={W / 2} y={H - 3} textAnchor="middle" fontSize={8} fill="#6366f180" fontFamily="system-ui">
        experience replay ↺
      </text>
    </svg>
  );
}
