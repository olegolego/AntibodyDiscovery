import { useRLDesignerStore } from "./store";
import { ALGORITHM_OPTIONS } from "./blocks";
import type { AlgorithmKind, EpsilonDecay } from "./store";

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-3">
      <span className="text-[10px] text-slate-500 w-36 shrink-0">{label}</span>
      <div className="flex-1">{children}</div>
    </div>
  );
}

function NumberInput({
  value,
  onChange,
  min,
  max,
  step,
}: {
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
  step?: number;
}) {
  return (
    <input
      type="number"
      min={min}
      max={max}
      step={step}
      value={value}
      onChange={(e) => onChange(Number(e.target.value))}
      className="w-full bg-slate-800 border border-slate-700 rounded px-2 py-1 text-[11px] text-slate-300 font-mono focus:outline-none focus:border-indigo-500"
    />
  );
}

export function AlgorithmBlock() {
  const { spec, updateAlgorithm } = useRLDesignerStore();
  const { algorithm: algo } = spec;

  return (
    <div className="space-y-4">
      {/* Algorithm picker */}
      <div>
        <label className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-1.5 block">
          Algorithm
        </label>
        <div className="space-y-1">
          {ALGORITHM_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => updateAlgorithm({ kind: opt.value as AlgorithmKind })}
              className={`w-full flex items-center px-3 py-2 rounded border text-left text-[11px] transition-colors ${
                algo.kind === opt.value
                  ? "border-indigo-500 bg-indigo-500/10 text-indigo-300"
                  : "border-slate-700 bg-slate-800/50 text-slate-400 hover:border-slate-600"
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
        {algo.kind !== "dqn" && (
          <p className="text-[10px] text-amber-600 mt-1.5">
            Only DQN is fully implemented. PPO/SAC configs are saved but run.py will fall back to DQN.
          </p>
        )}
      </div>

      {/* Exploration */}
      <div>
        <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-2">Exploration (ε-greedy)</p>
        <div className="space-y-2">
          <Row label="ε start">
            <NumberInput value={algo.epsilon_start} onChange={(v) => updateAlgorithm({ epsilon_start: v })} min={0} max={1} step={0.05} />
          </Row>
          <Row label="ε end">
            <NumberInput value={algo.epsilon_end} onChange={(v) => updateAlgorithm({ epsilon_end: v })} min={0} max={1} step={0.01} />
          </Row>
          <Row label="Decay steps">
            <NumberInput value={algo.epsilon_decay_steps} onChange={(v) => updateAlgorithm({ epsilon_decay_steps: v })} min={1} max={1000} step={10} />
          </Row>
          <Row label="Decay type">
            <select
              value={algo.epsilon_decay}
              onChange={(e) => updateAlgorithm({ epsilon_decay: e.target.value as EpsilonDecay })}
              className="w-full bg-slate-800 border border-slate-700 rounded px-2 py-1 text-[11px] text-slate-300 focus:outline-none focus:border-indigo-500"
            >
              <option value="linear">Linear</option>
              <option value="exponential">Exponential</option>
            </select>
          </Row>
        </div>
      </div>

      {/* Replay & training */}
      <div>
        <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-2">Replay & Training</p>
        <div className="space-y-2">
          <Row label="Buffer size">
            <NumberInput value={algo.replay_buffer_size} onChange={(v) => updateAlgorithm({ replay_buffer_size: v })} min={100} max={50000} step={1000} />
          </Row>
          <Row label="Batch size">
            <NumberInput value={algo.batch_size} onChange={(v) => updateAlgorithm({ batch_size: v })} min={8} max={512} step={8} />
          </Row>
          <Row label="Train steps / iter">
            <NumberInput value={algo.n_train_steps} onChange={(v) => updateAlgorithm({ n_train_steps: v })} min={1} max={500} step={5} />
          </Row>
          <Row label="Warmup steps">
            <NumberInput value={algo.warmup_steps} onChange={(v) => updateAlgorithm({ warmup_steps: v })} min={0} max={1000} step={8} />
          </Row>
        </div>
      </div>

      {/* Q-learning params */}
      <div>
        <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-2">Q-Learning</p>
        <div className="space-y-2">
          <Row label="Learning rate">
            <NumberInput value={algo.learning_rate} onChange={(v) => updateAlgorithm({ learning_rate: v })} min={0.00001} max={0.1} step={0.0001} />
          </Row>
          <Row label="Discount γ">
            <NumberInput value={algo.gamma} onChange={(v) => updateAlgorithm({ gamma: v })} min={0} max={1} step={0.01} />
          </Row>
          <Row label="Target update freq">
            <NumberInput value={algo.target_update_freq} onChange={(v) => updateAlgorithm({ target_update_freq: v })} min={1} max={100} step={1} />
          </Row>
          <Row label="Double DQN">
            <button
              onClick={() => updateAlgorithm({ double_dqn: !algo.double_dqn })}
              className={`px-3 py-1 rounded border text-[11px] font-semibold transition-colors ${
                algo.double_dqn
                  ? "border-indigo-500 bg-indigo-500/10 text-indigo-300"
                  : "border-slate-700 text-slate-500 hover:border-slate-500"
              }`}
            >
              {algo.double_dqn ? "Enabled" : "Disabled"}
            </button>
          </Row>
        </div>
      </div>
    </div>
  );
}
