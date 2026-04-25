import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

interface Props {
  rmsd: number[];
}

function rmsdColor(v: number) {
  if (v < 0.5) return "#34d399";   // confident — emerald
  if (v < 1.0) return "#fbbf24";   // moderate — amber
  return "#f87171";                 // uncertain — red
}

const CustomDot = (props: { cx?: number; cy?: number; payload?: { rmsd: number } }) => {
  const { cx = 0, cy = 0, payload } = props;
  if (!payload) return null;
  return <circle cx={cx} cy={cy} r={2} fill={rmsdColor(payload.rmsd)} />;
};

// Downsample to at most 500 points for performance
function toChartData(rmsd: number[]) {
  const step = rmsd.length > 500 ? Math.ceil(rmsd.length / 500) : 1;
  return rmsd
    .filter((_, i) => i % step === 0)
    .map((v, i) => ({ res: i * step + 1, rmsd: parseFloat(v.toFixed(3)) }));
}

export function RMSDChart({ rmsd }: Props) {
  if (!rmsd || rmsd.length === 0) return null;

  const data = toChartData(rmsd);
  const maxVal = Math.max(...rmsd);
  const yMax = Math.max(1.5, parseFloat((maxVal * 1.1).toFixed(1)));

  return (
    <ResponsiveContainer width="100%" height={180}>
      <LineChart data={data} margin={{ top: 4, right: 8, bottom: 16, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#1e2d54" />
        <XAxis
          dataKey="res"
          tick={{ fill: "#64748b", fontSize: 10 }}
          label={{ value: "Residue", position: "insideBottom", offset: -4, fill: "#64748b", fontSize: 11 }}
        />
        <YAxis
          domain={[0, yMax]}
          tick={{ fill: "#64748b", fontSize: 10 }}
          width={36}
          tickFormatter={(v) => v.toFixed(1)}
          label={{ value: "RMSD (Å)", angle: -90, position: "insideLeft", offset: 12, fill: "#64748b", fontSize: 11 }}
        />
        <Tooltip
          contentStyle={{ background: "#0e1425", border: "1px solid #1e2d54", borderRadius: 8, fontSize: 12 }}
          labelStyle={{ color: "#94a3b8" }}
          itemStyle={{ color: "#e2e8f0" }}
          formatter={(v) => [`${Number(v).toFixed(3)} Å`, "RMSD"]}
          labelFormatter={(l) => `Residue ${l}`}
        />
        <Line
          type="monotone"
          dataKey="rmsd"
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
