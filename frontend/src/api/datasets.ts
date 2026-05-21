import { api } from "./client";

export interface ColumnDef {
  id: string;
  name: string;
  type: "text" | "number" | "select" | "boolean" | "pdb";
  options?: string[];
  required?: boolean;
}

export interface Dataset {
  id: string;
  name: string;
  description: string | null;
  columns: ColumnDef[];
  entry_count: number;
  created_at: string;
  updated_at: string;
}

export interface DatasetEntry {
  id: string;
  dataset_id: string;
  name: string | null;
  heavy_chain: string | null;
  light_chain: string | null;
  source_molecule_id: string | null;
  data: Record<string, string | number | boolean | null>;
  created_at: string;
  updated_at: string;
}

export interface DatasetDetail extends Dataset {
  entries: DatasetEntry[];
  total_filtered: number;
}

export async function listDatasets(): Promise<Dataset[]> {
  const { data } = await api.get<Dataset[]>("/datasets/");
  return data;
}

export async function getDataset(
  id: string,
  opts: { q?: string; limit?: number; offset?: number } = {},
): Promise<DatasetDetail> {
  const params = new URLSearchParams();
  if (opts.q) params.set("q", opts.q);
  if (opts.limit !== undefined) params.set("limit", String(opts.limit));
  if (opts.offset !== undefined) params.set("offset", String(opts.offset));
  const qs = params.toString();
  const { data } = await api.get<DatasetDetail>(`/datasets/${id}/${qs ? `?${qs}` : ""}`);
  return data;
}

export async function createDataset(
  name: string,
  description?: string,
  columns?: ColumnDef[],
): Promise<Dataset> {
  const { data } = await api.post<Dataset>("/datasets/", { name, description, columns });
  return data;
}

export async function updateDataset(
  id: string,
  patch: { name?: string; description?: string; columns?: ColumnDef[] },
): Promise<Dataset> {
  const { data } = await api.patch<Dataset>(`/datasets/${id}/`, patch);
  return data;
}

export async function deleteDataset(id: string): Promise<void> {
  await api.delete(`/datasets/${id}/`);
}

export async function addEntry(
  dsId: string,
  entry: {
    name?: string;
    heavy_chain?: string;
    light_chain?: string;
    source_molecule_id?: string;
    data?: Record<string, unknown>;
  },
): Promise<DatasetEntry> {
  const { data } = await api.post<DatasetEntry>(`/datasets/${dsId}/entries/`, entry);
  return data;
}

export async function updateEntry(
  dsId: string,
  entryId: string,
  patch: {
    name?: string;
    heavy_chain?: string;
    light_chain?: string;
    data?: Record<string, unknown>;
  },
): Promise<DatasetEntry> {
  const { data } = await api.patch<DatasetEntry>(`/datasets/${dsId}/entries/${entryId}/`, patch);
  return data;
}

export async function deleteEntry(dsId: string, entryId: string): Promise<void> {
  await api.delete(`/datasets/${dsId}/entries/${entryId}/`);
}

export async function bulkAddEntries(
  dsId: string,
  entries: Array<{
    name?: string;
    heavy_chain?: string;
    light_chain?: string;
    data?: Record<string, unknown>;
  }>,
): Promise<DatasetEntry[]> {
  const { data } = await api.post<DatasetEntry[]>(`/datasets/${dsId}/entries/bulk/`, { entries });
  return data;
}

export async function createDatasetFromRun(opts: {
  run_id?: string | null;
  loop_run_id?: string | null;
  dataset_id?: string | null;
  name?: string;
}): Promise<Dataset & { added_count: number }> {
  const { data } = await api.post<Dataset & { added_count: number }>("/datasets/from_run/", opts);
  return data;
}

export async function importFromMolecules(
  dsId: string,
  moleculeIds: string[],
): Promise<DatasetEntry[]> {
  const { data } = await api.post<DatasetEntry[]>(`/datasets/${dsId}/import/molecules/`, {
    molecule_ids: moleculeIds,
  });
  return data;
}
