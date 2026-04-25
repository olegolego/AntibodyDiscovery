import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { PLDDTData } from "@/api/analysis";

interface Props {
  plddt: PLDDTData;
}

function confidenceColor(v: number) {
  if (v >= 90) return "#38bdf8";   // very high — sky blue
  if (v >= 70) return "#34d399";   // confident — emerald
  if (v >= 50) return "#fbbf24";   // low — amber
  return "#f87171";                 // very low — red
}

// Downsample to at most 500 points for performance
function downsample(nums: number[], scores: number[], max = 500) {
  if (scores.length <= max) return scores.map((v, i) => ({ res: nums[i], plddt: v }));
  const step = Math.ceil(scores.length / max);
  return scores
    .filter((_, i) => i % step === 0)
    .map((v, i) => ({ res: nums[i * step], plddt: v }));
}

const CustomDot = (props: { cx?: number; cy?: number; payload?: { plddt: number } }) => {
  const { cx = 0, cy = 0, payload } = props;
  if (!payload) return null;
  return <circle cx={cx} cy={cy} r={2} fill={confidenceColor(payload.plddt)} />;
};

export function PLDDTChart({ plddt }: Props) {
  const data = downsample(plddt.residue_numbers, plddt.plddt_per_residue);

  return (
    <ResponsiveContainer width="100%" height={200}>
      <LineChart data={data} margin={{ top: 4, right: 8, bottom: 4, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#1e2d54" />
        <XAxis
          dataKey="res"
          tick={{ fill: "#64748b", fontSize: 10 }}
          label={{ value: "Residue", position: "insideBottom", offset: -2, fill: "#64748b", fontSize: 11 }}
        />
        <YAxis
          domain={[0, 100]}
          tick={{ fill: "#64748b", fontSize: 10 }}
          width={32}
        />
        <Tooltip
          contentStyle={{ background: "#0e1425", border: "1px solid #1e2d54", borderRadius: 8, fontSize: 12 }}
          labelStyle={{ color: "#94a3b8" }}
          itemStyle={{ color: "#e2e8f0" }}
          formatter={(v) => [`${Number(v).toFixed(1)}`, "pLDDT"]}
          labelFormatter={(l) => `Residue ${l}`}
        />
        <ReferenceLine y={90} stroke="#38bdf8" strokeDasharray="4 2" strokeOpacity={0.5} />
        <ReferenceLine y={70} stroke="#34d399" strokeDasharray="4 2" strokeOpacity={0.5} />
        <ReferenceLine y={50} stroke="#fbbf24" strokeDasharray="4 2" strokeOpacity={0.5} />
        <Line
          type="monotone"
          dataKey="plddt"
          stroke="#a78bfa"
          strokeWidth={1.5}
          dot={<CustomDot />}
          activeDot={{ r: 4 }}
          isAnimationActive={false}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
