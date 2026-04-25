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

export interface NodeAnalysis {
  run_id: string;
  node_id: string;
  tool_id: string;
  created_at: string;
  structure: string | null;
  plddt: PLDDTData | null;
  pae: PAEData | null;
}

export async function fetchNodeAnalysis(runId: string, nodeId: string): Promise<NodeAnalysis> {
  const res = await axios.get<NodeAnalysis>(`/api/analysis/runs/${runId}/nodes/${nodeId}`);
  return res.data;
}
