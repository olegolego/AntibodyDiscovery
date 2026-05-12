import axios from "axios";

export interface PLDDTData {
  uniprot_id: string;
  entry_id: string;
  gene: string;
  description: string;
  organism: string;
  sequence_length: number;
  mean_plddt: number;
  high_confidence_pct: number;
  very_high_confidence_pct: number;
  residue_numbers: number[];
  plddt_per_residue: number[];
}

export interface PAEData {
  predicted_aligned_error: number[][];
  max_predicted_aligned_error: number;
}

export interface MegadockScore {
  rank: number;
  score: number;
}

export interface MegadockMetadata {
  num_predictions: number;
  rotational_sampling: number;
  elapsed_seconds: number;
  best_score: number;
}

export interface NodeAnalysis {
  run_id: string;
  node_id: string;
  tool_id: string;
  created_at: string;
  structure: string | null;
  plddt: PLDDTData | null;
  pae: PAEData | null;
  water_count: { waters_placed?: number } | null;
  // megadock-specific
  top_scores: MegadockScore[] | null;
  complex_pdbs: Record<string, string> | null;
  docking_metadata: MegadockMetadata | null;
  image: string | null;
  // gromacs_mmpbsa-specific
  delta_g_bind: number | null;
  energy_decomposition: Record<string, number> | null;
  md_convergence: Record<string, number | string> | null;
  // generic fallback — all stored keys for non-structure tools
  raw_outputs: Record<string, unknown> | null;
}

export async function fetchNodeAnalysis(runId: string, nodeId: string): Promise<NodeAnalysis> {
  const res = await axios.get<NodeAnalysis>(`/api/analysis/runs/${runId}/nodes/${nodeId}/`);
  return res.data;
}
