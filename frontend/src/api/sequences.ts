import { api } from "./client";

export interface SequenceCollection {
  id: string;
  name: string;
  description: string | null;
  entry_count: number;
  created_at: string;
}

export interface SequenceEntry {
  id: string;
  collection_id: string;
  name: string | null;
  heavy_chain: string;
  light_chain: string | null;
  source_molecule_id: string | null;
  notes: string | null;
  created_at: string;
}

export interface CollectionDetail extends SequenceCollection {
  entries: SequenceEntry[];
}

export async function listCollections(): Promise<SequenceCollection[]> {
  const { data } = await api.get<SequenceCollection[]>("/sequences/collections/");
  return data;
}

export async function getCollection(id: string): Promise<CollectionDetail> {
  const { data } = await api.get<CollectionDetail>(`/sequences/collections/${id}/`);
  return data;
}

export async function createCollection(name: string, description?: string): Promise<SequenceCollection> {
  const { data } = await api.post<SequenceCollection>("/sequences/collections/", { name, description });
  return data;
}

export async function updateCollection(
  id: string,
  patch: Partial<Pick<SequenceCollection, "name" | "description">>
): Promise<SequenceCollection> {
  const { data } = await api.put<SequenceCollection>(`/sequences/collections/${id}/`, patch);
  return data;
}

export async function deleteCollection(id: string): Promise<void> {
  await api.delete(`/sequences/collections/${id}/`);
}

export async function addEntry(
  collId: string,
  entry: { name?: string; heavy_chain: string; light_chain?: string; notes?: string; source_molecule_id?: string }
): Promise<SequenceEntry> {
  const { data } = await api.post<SequenceEntry>(`/sequences/collections/${collId}/entries/`, entry);
  return data;
}

export async function deleteEntry(entryId: string): Promise<void> {
  await api.delete(`/sequences/entries/${entryId}/`);
}

export async function importFromMolecules(collId: string, moleculeIds: string[]): Promise<SequenceEntry[]> {
  const { data } = await api.post<SequenceEntry[]>(`/sequences/collections/${collId}/import/`, { molecule_ids: moleculeIds });
  return data;
}

export async function searchEntries(collId: string, q: string): Promise<SequenceEntry[]> {
  const { data } = await api.get<SequenceEntry[]>(`/sequences/collections/${collId}/entries/`, { params: { q } });
  return data;
}
