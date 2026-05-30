// Block definitions for the RL designer config panel.
// Each block corresponds to one RL concept (State, Action, Reward, Algorithm, Policy).
// These are rendered as collapsible sections — NOT as a node graph.

export type BlockId = "state" | "action" | "reward" | "algorithm" | "policy";

export interface BlockDef {
  id: BlockId;
  label: string;
  icon: string;              // Lucide icon name
  color: string;             // accent colour for the block header
  description: string;
}

export const BLOCKS: BlockDef[] = [
  {
    id: "state",
    label: "State Encoder",
    icon: "Layers",
    color: "#fb7185",        // rose
    description: "Protein embedding used as the RL state observation.",
  },
  {
    id: "action",
    label: "Action Space",
    icon: "Zap",
    color: "#34d399",        // emerald
    description: "Discrete actions: which CDR, what mutation strategy, how many mutations.",
  },
  {
    id: "reward",
    label: "Reward Function",
    icon: "Star",
    color: "#fbbf24",        // amber
    description: "Weighted combination of evaluation scores as the learning signal.",
  },
  {
    id: "algorithm",
    label: "Algorithm",
    icon: "Cpu",
    color: "#818cf8",        // indigo
    description: "DQN hyperparameters: ε-greedy exploration, replay buffer, discount.",
  },
  {
    id: "policy",
    label: "Policy Network",
    icon: "Network",
    color: "#a78bfa",        // violet
    description: "Q-network architecture. Click to open the DNN designer.",
  },
];

export const REPR_TYPE_OPTIONS = [
  { value: "abmap",   label: "AbMAP",   dim: 252,  description: "CDR-focused antibody embeddings" },
  { value: "esm2",    label: "ESM-2",   dim: 1280, description: "Protein language model (650M)" },
  { value: "ablang",  label: "AbLang",  dim: 768,  description: "Antibody-specific LM (OAS)" },
  { value: "cheap",   label: "CHEAP",   dim: 512,  description: "Compressed ESMFold latents" },
] as const;

export const CDR_OPTIONS: { value: string; label: string }[] = [
  { value: "H1", label: "CDR-H1" },
  { value: "H2", label: "CDR-H2" },
  { value: "H3", label: "CDR-H3" },
  { value: "L1", label: "CDR-L1" },
  { value: "L2", label: "CDR-L2" },
  { value: "L3", label: "CDR-L3" },
];

export const STRATEGY_OPTIONS: { value: string; label: string; description: string }[] = [
  { value: "random",       label: "Random",       description: "Uniform random amino acid substitution" },
  { value: "blosum62",     label: "BLOSUM62",     description: "Substitution weighted by log-odds matrix" },
  { value: "conservative", label: "Conservative", description: "Within biochemical property groups" },
  { value: "sapiens",      label: "Sapiens",      description: "Human antibody AA frequency (BioPhi)" },
];

export const ALGORITHM_OPTIONS: { value: string; label: string }[] = [
  { value: "dqn",          label: "DQN (Deep Q-Network)" },
  { value: "ppo",          label: "PPO (Proximal Policy Optimization)" },
  { value: "sac",          label: "SAC (Soft Actor-Critic)" },
];

export const DASHBOARD_TABS = [
  { id: "config",      label: "Config",          icon: "Settings2" },
  { id: "q_heatmap",  label: "Q-Heatmap",        icon: "Grid3x3" },
  { id: "rewards",    label: "Rewards",           icon: "TrendingUp" },
  { id: "exploration",label: "Exploration Map",   icon: "Map" },
  { id: "policy",     label: "Policy Arrows",     icon: "ArrowRight" },
  { id: "episodes",   label: "Episode History",   icon: "Table" },
] as const;
