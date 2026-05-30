import { create } from "zustand";
import type { ArchitectureSpec } from "@/dnn_designer/store";

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export type ReprType = "abmap" | "esm2" | "ablang" | "cheap";
export type CDR = "H1" | "H2" | "H3" | "L1" | "L2" | "L3";
export type MutationStrategy = "random" | "blosum62" | "conservative" | "sapiens";
export type AlgorithmKind = "dqn" | "ppo" | "sac";
export type EpsilonDecay = "linear" | "exponential";
export type Normalization = "none" | "z_score" | "min_max";
export type RewardShaping = "sparse" | "dense";

export interface RewardSignal {
  port: string;
  weight: number;
  lower_is_better: boolean;
  normalization: Normalization;
}

export interface RLSpec {
  version: "1.0";

  state: {
    repr_type: ReprType;
    dim: number;
    projection_dim: number;
    port: string;
  };

  action: {
    cdrs: CDR[];
    strategies: MutationStrategy[];
    n_mutations_choices: (1 | 2 | 3)[];
  };

  reward: {
    signals: RewardSignal[];
    shaping: RewardShaping;
  };

  algorithm: {
    kind: AlgorithmKind;
    double_dqn: boolean;
    target_update_freq: number;
    gamma: number;
    epsilon_start: number;
    epsilon_end: number;
    epsilon_decay: EpsilonDecay;
    epsilon_decay_steps: number;
    learning_rate: number;
    batch_size: number;
    replay_buffer_size: number;
    n_train_steps: number;
    warmup_steps: number;
    tau: number;
  };

  policy_network: ArchitectureSpec;
}

// Default spec — sensible starting point for a CDR mutation loop
export const DEFAULT_RL_SPEC: RLSpec = {
  version: "1.0",
  state: { repr_type: "abmap", dim: 252, projection_dim: 0, port: "state_embeddings" },
  action: {
    cdrs: ["H3"],
    strategies: ["blosum62", "conservative"],
    n_mutations_choices: [1, 2],
  },
  reward: {
    signals: [{ port: "haddock_score", weight: 1.0, lower_is_better: true, normalization: "z_score" }],
    shaping: "sparse",
  },
  algorithm: {
    kind: "dqn",
    double_dqn: true,
    target_update_freq: 10,
    gamma: 0.99,
    epsilon_start: 1.0,
    epsilon_end: 0.05,
    epsilon_decay: "linear",
    epsilon_decay_steps: 50,
    learning_rate: 0.001,
    batch_size: 32,
    replay_buffer_size: 5000,
    n_train_steps: 20,
    warmup_steps: 32,
    tau: 1.0,
  },
  policy_network: { version: "1.0", nodes: [], edges: [] },
};

// ─────────────────────────────────────────────────────────────────────────────
// Computed action count
// ─────────────────────────────────────────────────────────────────────────────

export function computeActionCount(spec: RLSpec): number {
  return spec.action.cdrs.length * spec.action.strategies.length * spec.action.n_mutations_choices.length;
}

export function stateDimLabel(spec: RLSpec): string {
  const pd = spec.state.projection_dim;
  if (pd > 0) return `${spec.state.dim}→${pd}`;
  return String(spec.state.dim);
}

// ─────────────────────────────────────────────────────────────────────────────
// Viz data types (from backend viz_data output)
// ─────────────────────────────────────────────────────────────────────────────

export interface QHeatmapData {
  cdrs: string[];
  strategies: string[];
  values: Record<string, Record<string, number>>;
}

export interface PolicyArrow {
  cdr: string;
  dominant_strategy: string;
  distribution: Record<string, number>;
  confidence: number;
}

export interface EpisodeEntry {
  iteration: number;
  seq_id: string;
  cdr: string;
  strategy: string;
  n_mutations: number;
  q_value: number;
  exploratory: boolean;
  score_delta?: number;
}

export interface VizData {
  q_heatmap: QHeatmapData;
  tsne_coords: Record<string, [number, number]>;
  visit_counts: Record<string, number>;
  episode_rewards: number[];
  policy_arrows: PolicyArrow[];
}

// ─────────────────────────────────────────────────────────────────────────────
// Store
// ─────────────────────────────────────────────────────────────────────────────

interface RLDesignerState {
  spec: RLSpec;
  dirty: boolean;
  specName: string;
  activeTab: "config" | "q_heatmap" | "rewards" | "exploration" | "policy" | "episodes";

  // Live viz data (populated from the last run's node outputs)
  vizData: VizData | null;
  metrics: Record<string, number> | null;
  episodeHistory: EpisodeEntry[];

  // Actions
  updateSpec: (patch: Partial<RLSpec>) => void;
  updateState: (patch: Partial<RLSpec["state"]>) => void;
  updateAction: (patch: Partial<RLSpec["action"]>) => void;
  updateReward: (patch: Partial<RLSpec["reward"]>) => void;
  updateAlgorithm: (patch: Partial<RLSpec["algorithm"]>) => void;
  setPolicyNetwork: (arch: ArchitectureSpec) => void;
  loadSpec: (spec: RLSpec) => void;
  toSpec: () => RLSpec;
  setActiveTab: (tab: RLDesignerState["activeTab"]) => void;
  setVizData: (viz: VizData, metrics: Record<string, number>, actions: EpisodeEntry[]) => void;
  reset: () => void;
}

export const useRLDesignerStore = create<RLDesignerState>((set, get) => ({
  spec: DEFAULT_RL_SPEC,
  dirty: false,
  specName: "RL Policy",
  activeTab: "config",
  vizData: null,
  metrics: null,
  episodeHistory: [],

  updateSpec: (patch) => set((s) => ({ spec: { ...s.spec, ...patch }, dirty: true })),

  updateState: (patch) =>
    set((s) => ({ spec: { ...s.spec, state: { ...s.spec.state, ...patch } }, dirty: true })),

  updateAction: (patch) =>
    set((s) => ({ spec: { ...s.spec, action: { ...s.spec.action, ...patch } }, dirty: true })),

  updateReward: (patch) =>
    set((s) => ({ spec: { ...s.spec, reward: { ...s.spec.reward, ...patch } }, dirty: true })),

  updateAlgorithm: (patch) =>
    set((s) => ({ spec: { ...s.spec, algorithm: { ...s.spec.algorithm, ...patch } }, dirty: true })),

  setPolicyNetwork: (arch) =>
    set((s) => ({ spec: { ...s.spec, policy_network: arch }, dirty: true })),

  loadSpec: (spec) => set({ spec, dirty: false }),

  toSpec: () => get().spec,

  setActiveTab: (tab) => set({ activeTab: tab }),

  setVizData: (viz, metrics, actions) =>
    set((s) => ({
      vizData: viz,
      metrics,
      episodeHistory: [...s.episodeHistory, ...actions].slice(-500),
    })),

  reset: () => set({ spec: DEFAULT_RL_SPEC, dirty: false, vizData: null, metrics: null, episodeHistory: [] }),
}));
