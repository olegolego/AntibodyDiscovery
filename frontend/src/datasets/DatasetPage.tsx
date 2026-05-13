import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  Box,
  Check,
  CheckSquare,
  Download,
  Eye,
  Hash,
  List,
  Pencil,
  Plus,
  Search,
  Trash2,
  Type,
  Upload,
  X,
} from "lucide-react";
import { StructureViewer } from "@/analysis/StructureViewer";
import {
  addEntry,
  bulkAddEntries,
  createDataset,
  deleteDataset,
  deleteEntry,
  getDataset,
  listDatasets,
  updateDataset,
  updateEntry,
  type ColumnDef,
  type DatasetDetail,
  type DatasetEntry,
} from "@/api/datasets";
import { randomUUID } from "@/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

type ColType = ColumnDef["type"];

const COL_TYPE_ICONS: Record<ColType, React.ReactNode> = {
  text: <Type size={11} />,
  number: <Hash size={11} />,
  select: <List size={11} />,
  boolean: <CheckSquare size={11} />,
  pdb: <Box size={11} />,
};

const COL_TYPE_LABELS: Record<ColType, string> = {
  text: "Text",
  number: "Number",
  select: "Select",
  boolean: "Checkbox",
  pdb: "PDB Structure",
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function seqPreview(seq: string | null | undefined, len = 20): string {
  if (!seq) return "";
  return seq.length <= len ? seq : `${seq.slice(0, 8)}…${seq.slice(-6)}`;
}

function completeness(entries: DatasetEntry[], colId: string): number {
  if (!entries.length) return 0;
  const filled = entries.filter((e) => {
    const v = e.data[colId];
    return v !== null && v !== undefined && v !== "";
  }).length;
  return Math.round((filled / entries.length) * 100);
}

// ── Col editor modal ──────────────────────────────────────────────────────────

interface ColEditorProps {
  initial?: ColumnDef;
  onSave: (col: ColumnDef) => void;
  onDelete?: (colId: string) => void;
  onClose: () => void;
}

function ColEditorModal({ initial, onSave, onDelete, onClose }: ColEditorProps) {
  const [name, setName] = useState(initial?.name ?? "");
  const [type, setType] = useState<ColType>(initial?.type ?? "text");
  const [options, setOptions] = useState<string>((initial?.options ?? []).join("\n"));

  function handleSave() {
    const trimmed = name.trim();
    if (!trimmed) return;
    onSave({
      id: initial?.id ?? randomUUID(),
      name: trimmed,
      type,
      options: type === "select" ? options.split("\n").map((s) => s.trim()).filter(Boolean) : undefined,
    });
  }

  function handleDelete() {
    if (!initial || !onDelete) return;
    if (!window.confirm(`Delete column "${initial.name}" and all its data? This cannot be undone.`)) return;
    onDelete(initial.id);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-[#131a2e] border border-[#2a3555] rounded-2xl shadow-2xl w-96 p-6">
        <div className="flex items-center justify-between mb-5">
          <h3 className="text-sm font-semibold text-white">
            {initial ? "Edit column" : "Add column"}
          </h3>
          <button onClick={onClose} className="text-slate-500 hover:text-white transition-colors">
            <X size={15} />
          </button>
        </div>

        <label className="block mb-4">
          <span className="text-xs font-medium text-slate-400 mb-1 block">Column name</span>
          <input
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSave()}
            placeholder="e.g. Affinity (KD)"
            className="w-full bg-[#0e1425] border border-[#2a3555] rounded-lg px-3 py-2
              text-sm text-white placeholder-slate-600 focus:outline-none focus:border-indigo-500"
          />
        </label>

        <label className="block mb-4">
          <span className="text-xs font-medium text-slate-400 mb-1 block">Type</span>
          <div className="grid grid-cols-2 gap-2">
            {(["text", "number", "select", "boolean", "pdb"] as ColType[]).map((t) => (
              <button
                key={t}
                onClick={() => setType(t)}
                className={`flex items-center gap-2 px-3 py-2 rounded-lg border text-sm transition-all
                  ${type === t
                    ? "border-indigo-500 bg-indigo-500/15 text-indigo-300"
                    : "border-[#2a3555] text-slate-400 hover:border-slate-500 hover:text-white"
                  }`}
              >
                {COL_TYPE_ICONS[t]}
                <span>{COL_TYPE_LABELS[t]}</span>
              </button>
            ))}
          </div>
        </label>

        {type === "select" && (
          <label className="block mb-4">
            <span className="text-xs font-medium text-slate-400 mb-1 block">
              Options (one per line)
            </span>
            <textarea
              value={options}
              onChange={(e) => setOptions(e.target.value)}
              rows={4}
              placeholder={"Low\nMedium\nHigh"}
              className="w-full bg-[#0e1425] border border-[#2a3555] rounded-lg px-3 py-2
                text-sm text-white placeholder-slate-600 focus:outline-none focus:border-indigo-500
                resize-none"
            />
          </label>
        )}

        <div className="flex gap-2 mt-2">
          {initial && onDelete && (
            <button
              onClick={handleDelete}
              className="px-3 py-2 rounded-lg border border-red-500/30 text-sm text-red-400
                hover:bg-red-500/10 hover:border-red-400/50 transition-all"
              title="Delete column"
            >
              <Trash2 size={14} />
            </button>
          )}
          <button
            onClick={onClose}
            className="flex-1 px-4 py-2 rounded-lg border border-[#2a3555] text-sm text-slate-400
              hover:text-white hover:border-slate-500 transition-all"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={!name.trim()}
            className="flex-1 px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-sm
              text-white font-medium transition-all disabled:opacity-40"
          >
            {initial ? "Save" : "Add column"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── CSV parsing helpers ───────────────────────────────────────────────────────

function parseCsvText(text: string): { headers: string[]; rows: string[][] } {
  const lines = text.split(/\r?\n/).filter(Boolean);
  if (!lines.length) return { headers: [], rows: [] };
  const parseRow = (line: string): string[] => {
    const fields: string[] = [];
    let cur = "";
    let inQ = false;
    for (let i = 0; i < line.length; i++) {
      if (line[i] === '"') { inQ = !inQ; }
      else if (line[i] === "," && !inQ) { fields.push(cur.trim()); cur = ""; }
      else { cur += line[i]; }
    }
    fields.push(cur.trim());
    return fields;
  };
  const [hdrLine, ...dataLines] = lines;
  return { headers: parseRow(hdrLine), rows: dataLines.map(parseRow) };
}

type BuiltinKey = "name" | "heavy_chain" | "light_chain";

function detectBuiltin(h: string): BuiltinKey | null {
  const l = h.toLowerCase().trim();
  if (l === "name" || l === "ab_name" || l === "antibody_name" || l === "clone") return "name";
  if (
    l === "vh" || l === "vh_sequence" || l === "vh sequence" || l === "vh_seq" ||
    l === "heavy_chain" || l === "heavy chain" || l === "heavy" ||
    l === "hc" || l === "hc_sequence" || l === "h_sequence" ||
    l.startsWith("vh_") || l.startsWith("heavy_") ||
    l.includes("heavy chain") || l.includes("heavy_chain") ||
    (l.includes("vh") && l.includes("seq"))
  ) return "heavy_chain";
  if (
    l === "vl" || l === "vl_sequence" || l === "vl sequence" || l === "vl_seq" ||
    l === "light_chain" || l === "light chain" || l === "light" ||
    l === "lc" || l === "lc_sequence" || l === "l_sequence" ||
    l.startsWith("vl_") || l.startsWith("light_") ||
    l.includes("light chain") || l.includes("light_chain") ||
    (l.includes("vl") && l.includes("seq"))
  ) return "light_chain";
  return null;
}

function inferColType(colName: string, values: string[]): ColType {
  const l = colName.toLowerCase();
  if (l.includes("pdb") || l.includes("structure")) return "pdb";
  const nonEmpty = values.filter(Boolean);
  if (!nonEmpty.length) return "text";
  if (nonEmpty.every((v) => !isNaN(Number(v)) && v !== "")) return "number";
  const uniq = new Set(nonEmpty);
  if (uniq.size <= 6 && nonEmpty.length >= 4) return "select";
  return "text";
}

// ── CSV import modal ──────────────────────────────────────────────────────────

interface CsvImportProps {
  /** When provided, import rows into this existing dataset (adding any missing columns). */
  existingDs?: DatasetDetail;
  onClose: () => void;
  /** Called with the dataset id that was created/updated. */
  onDone: (dsId: string) => void;
}

function CsvImportModal({ existingDs, onClose, onDone }: CsvImportProps) {
  const [headers, setHeaders] = useState<string[]>([]);
  const [previewRows, setPreviewRows] = useState<string[][]>([]);
  const [allRows, setAllRows] = useState<string[][]>([]);
  const [dsName, setDsName] = useState(existingDs?.name ?? "");
  const [importing, setImporting] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  // User-controlled mapping of builtin fields to column names (empty string = skip)
  const [mapping, setMapping] = useState<Record<BuiltinKey, string>>({
    name: "", heavy_chain: "", light_chain: "",
  });

  // Stable UUIDs per column header across renders
  const colIdsRef = useRef<Record<string, string>>({});
  function getColId(h: string) {
    if (!colIdsRef.current[h]) colIdsRef.current[h] = randomUUID();
    return colIdsRef.current[h];
  }

  // Custom columns: every header not assigned to a builtin
  const assignedHeaders = new Set(Object.values(mapping).filter(Boolean));
  const customHeaders = headers.filter((h) => !assignedHeaders.has(h));

  const inferredCols: ColumnDef[] = customHeaders.map((h) => ({
    id: getColId(h),
    name: h,
    type: inferColType(h, allRows.map((r) => r[headers.indexOf(h)] ?? "")),
  }));

  // colMap: header → builtin key or custom col id
  const colMap: Record<string, BuiltinKey | string> = {};
  headers.forEach((h) => {
    const builtin = (Object.entries(mapping) as [BuiltinKey, string][]).find(([, v]) => v === h)?.[0];
    if (builtin) {
      colMap[h] = builtin;
    } else {
      colMap[h] = inferredCols.find((c) => c.name === h)?.id ?? "__skip__";
    }
  });

  function loadFile(file: File) {
    if (!file.name.endsWith(".csv") && file.type !== "text/csv") return;
    if (!existingDs) setDsName(file.name.replace(/\.csv$/i, ""));
    const reader = new FileReader();
    reader.onload = (ev) => {
      const { headers: h, rows } = parseCsvText(ev.target?.result as string);
      colIdsRef.current = {};  // reset so new file gets fresh column IDs
      setHeaders(h);
      setAllRows(rows);
      setPreviewRows(rows.slice(0, 4));
      // Auto-detect builtins for initial mapping — user can override via dropdowns
      const auto: Record<BuiltinKey, string> = { name: "", heavy_chain: "", light_chain: "" };
      h.forEach((hdr) => {
        const b = detectBuiltin(hdr);
        if (b && !auto[b]) auto[b] = hdr;
      });
      setMapping(auto);
    };
    reader.readAsText(file);
  }

  function handleFileInput(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (f) loadFile(f);
    e.target.value = "";
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    const f = e.dataTransfer.files[0];
    if (f) loadFile(f);
  }

  async function handleImport() {
    if (!headers.length || !dsName.trim()) return;
    setImporting(true);
    try {
      let targetId = existingDs?.id ?? "";
      let existingColIds = new Set((existingDs?.columns ?? []).map((c) => c.id));

      if (!existingDs) {
        const created = await createDataset(dsName.trim(), undefined, inferredCols);
        targetId = created.id;
        existingColIds = new Set(inferredCols.map((c) => c.id));
      } else {
        const newCols = inferredCols.filter((c) => {
          return !existingDs.columns.some((ec) => ec.name.toLowerCase() === c.name.toLowerCase());
        });
        if (newCols.length) {
          await updateDataset(existingDs.id, { columns: [...existingDs.columns, ...newCols] });
          newCols.forEach((c) => existingColIds.add(c.id));
        }
        inferredCols.forEach((ic) => {
          const existing = existingDs.columns.find(
            (ec) => ec.name.toLowerCase() === ic.name.toLowerCase(),
          );
          if (existing) {
            const h = headers.find((hh) => !assignedHeaders.has(hh) && hh === ic.name);
            if (h) colMap[h] = existing.id;
          }
        });
      }

      const entries = allRows
        .filter((r) => r.some(Boolean))
        .map((row) => {
          const entry: Record<string, unknown> = { data: {} };
          headers.forEach((h, i) => {
            const target = colMap[h];
            const val = row[i] ?? "";
            if (!val || target === "__skip__") return;
            if (target === "name") entry.name = val;
            else if (target === "heavy_chain") entry.heavy_chain = val;
            else if (target === "light_chain") entry.light_chain = val;
            else (entry.data as Record<string, unknown>)[target] = val;
          });
          return entry;
        });

      await bulkAddEntries(targetId, entries as Parameters<typeof bulkAddEntries>[1]);
      onDone(targetId);
    } finally {
      setImporting(false);
    }
  }

  const hasFile = headers.length > 0;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-[#131a2e] border border-[#2a3555] rounded-2xl shadow-2xl w-[560px] max-h-[85vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 pt-5 pb-4 border-b border-[#2a3555]">
          <h3 className="text-sm font-semibold text-white">
            {existingDs ? `Import CSV into "${existingDs.name}"` : "Create dataset from CSV"}
          </h3>
          <button onClick={onClose} className="text-slate-500 hover:text-white transition-colors">
            <X size={15} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-6 space-y-5">
          {/* Drop zone */}
          <label
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
            className={`flex flex-col items-center justify-center gap-2 border-2 border-dashed rounded-xl
              p-8 cursor-pointer transition-all
              ${dragOver
                ? "border-indigo-400 bg-indigo-500/10"
                : hasFile
                  ? "border-emerald-500/40 bg-emerald-500/5"
                  : "border-[#2a3555] hover:border-indigo-500/60 hover:bg-white/[0.02]"
              }`}
          >
            {hasFile ? (
              <>
                <Check size={22} className="text-emerald-400" />
                <span className="text-sm font-medium text-emerald-300">
                  {allRows.length} rows · {headers.length} columns detected
                </span>
                <span className="text-xs text-slate-500">Drop another file to replace</span>
              </>
            ) : (
              <>
                <Upload size={22} className="text-slate-500" />
                <span className="text-sm text-slate-300 font-medium">Drop a CSV file here</span>
                <span className="text-xs text-slate-500">or click to browse</span>
              </>
            )}
            <input type="file" accept=".csv,text/csv" className="hidden" onChange={handleFileInput} />
          </label>

          {hasFile && (
            <>
              {/* Dataset name (only for new) */}
              {!existingDs && (
                <div>
                  <label className="text-xs font-medium text-slate-400 block mb-1">Dataset name</label>
                  <input
                    value={dsName}
                    onChange={(e) => setDsName(e.target.value)}
                    className="w-full bg-[#0e1425] border border-[#2a3555] rounded-lg px-3 py-2
                      text-sm text-white focus:outline-none focus:border-indigo-500"
                  />
                </div>
              )}

              {/* Sequence column mapping */}
              <div>
                <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">
                  Sequence columns
                </p>
                <div className="grid grid-cols-3 gap-3">
                  {([
                    { key: "name" as BuiltinKey, label: "Name" },
                    { key: "heavy_chain" as BuiltinKey, label: "VH (heavy)" },
                    { key: "light_chain" as BuiltinKey, label: "VL (light)" },
                  ]).map(({ key, label }) => (
                    <div key={key}>
                      <label className="text-[10px] text-slate-500 block mb-1">{label}</label>
                      <select
                        value={mapping[key]}
                        onChange={(e) => setMapping((m) => ({ ...m, [key]: e.target.value }))}
                        className="w-full bg-[#0e1425] border border-[#2a3555] rounded-lg px-2 py-1.5
                          text-xs text-white focus:outline-none focus:border-indigo-500 cursor-pointer"
                      >
                        <option value="">— skip</option>
                        {headers.map((h) => (
                          <option key={h} value={h}>{h}</option>
                        ))}
                      </select>
                    </div>
                  ))}
                </div>
              </div>

              {/* Custom columns summary */}
              {customHeaders.length > 0 && (
                <div>
                  <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">
                    Custom columns
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {customHeaders.map((h) => {
                      const col = inferredCols.find((c) => c.name === h);
                      return (
                        <span key={h} className="flex items-center gap-1 px-2 py-0.5 rounded-md text-xs
                          bg-indigo-500/10 border border-indigo-500/20 text-indigo-300">
                          {COL_TYPE_ICONS[col?.type ?? "text"]}
                          {h}
                        </span>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Preview table */}
              {previewRows.length > 0 && (
                <div>
                  <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">
                    Preview — first {previewRows.length} rows
                  </p>
                  <div className="overflow-x-auto rounded-lg border border-[#2a3555]">
                    <table className="text-xs text-slate-300 w-full">
                      <thead>
                        <tr className="bg-[#0e1425]">
                          {headers.map((h) => (
                            <th key={h} className="px-3 py-1.5 text-left font-medium whitespace-nowrap"
                              style={{ color: assignedHeaders.has(h) ? "#fbbf24" : "#64748b" }}>
                              {h}
                              {assignedHeaders.has(h) && (
                                <span className="ml-1 text-[9px] text-amber-600">
                                  ({(Object.entries(mapping) as [BuiltinKey, string][]).find(([,v]) => v === h)?.[0] === "heavy_chain" ? "VH" :
                                    (Object.entries(mapping) as [BuiltinKey, string][]).find(([,v]) => v === h)?.[0] === "light_chain" ? "VL" : "name"})
                                </span>
                              )}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {previewRows.map((row, i) => (
                          <tr key={i} className="border-t border-[#2a3555]">
                            {row.map((cell, j) => (
                              <td key={j} className="px-3 py-1.5 max-w-[140px] truncate font-mono text-slate-400">
                                {cell || <span className="text-slate-700">—</span>}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </>
          )}
        </div>

        {/* Footer */}
        <div className="flex gap-2 px-6 py-4 border-t border-[#2a3555]">
          <button
            onClick={onClose}
            className="flex-1 px-4 py-2 rounded-lg border border-[#2a3555] text-sm text-slate-400
              hover:text-white hover:border-slate-500 transition-all"
          >
            Cancel
          </button>
          <button
            onClick={handleImport}
            disabled={!hasFile || !dsName.trim() || importing}
            className="flex-1 px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-sm
              text-white font-medium transition-all disabled:opacity-40"
          >
            {importing
              ? "Importing…"
              : existingDs
                ? `Add ${allRows.length} rows`
                : `Create dataset (${allRows.length} rows)`}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── PDB viewer modal ──────────────────────────────────────────────────────────

function PdbViewerModal({ pdbText, onClose }: { pdbText: string; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm">
      <div
        className="w-full max-w-3xl flex flex-col rounded-2xl overflow-hidden border border-border shadow-2xl"
        style={{ background: "#0e1425", height: "70vh" }}
      >
        <div className="flex items-center gap-3 px-5 py-3 border-b border-border shrink-0">
          <Box size={15} className="text-indigo-400" />
          <span className="text-sm font-semibold text-white">PDB Structure Viewer</span>
          <button
            onClick={onClose}
            className="ml-auto text-slate-500 hover:text-white transition-colors p-1 rounded-lg hover:bg-white/5"
          >
            <X size={15} />
          </button>
        </div>
        <div className="flex-1 overflow-hidden">
          <StructureViewer pdbText={pdbText} />
        </div>
      </div>
    </div>
  );
}

// ── PDB cell ──────────────────────────────────────────────────────────────────

function PdbCell({ value, onSave }: { value: string; onSave: (v: string) => void }) {
  const [viewing, setViewing] = useState(false);

  function countAtoms(pdb: string) {
    return pdb.split("\n").filter((l) => l.startsWith("ATOM") || l.startsWith("HETATM")).length;
  }

  function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => onSave(reader.result as string);
    reader.readAsText(file);
    e.target.value = "";
  }

  const hasValue = value.trim().length > 0;
  const atoms = hasValue ? countAtoms(value) : 0;

  return (
    <>
      <td className="px-2 py-0 h-9 border-r border-[#1e2d4a] last:border-r-0 align-middle">
        <div className="flex items-center gap-1.5">
          {hasValue ? (
            <>
              <span className="flex items-center gap-1 text-xs font-medium text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 rounded px-2 py-0.5">
                <Box size={10} /> PDB
              </span>
              <span className="text-xs text-slate-500">{atoms} atoms</span>
              <button
                onClick={() => setViewing(true)}
                className="ml-1 p-0.5 rounded text-slate-500 hover:text-indigo-300 transition-colors"
                title="View structure"
              >
                <Eye size={13} />
              </button>
              <label className="p-0.5 rounded text-slate-500 hover:text-slate-300 transition-colors cursor-pointer" title="Replace PDB">
                <Upload size={13} />
                <input type="file" accept=".pdb,.ent" className="hidden" onChange={handleFile} />
              </label>
            </>
          ) : (
            <label className="flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-300 cursor-pointer transition-colors">
              <Upload size={12} />
              <span>Upload PDB</span>
              <input type="file" accept=".pdb,.ent" className="hidden" onChange={handleFile} />
            </label>
          )}
        </div>
      </td>
      {viewing && <PdbViewerModal pdbText={value} onClose={() => setViewing(false)} />}
    </>
  );
}

// ── Editable cell ─────────────────────────────────────────────────────────────

interface CellProps {
  value: string;
  col?: ColumnDef;
  onSave: (v: string) => void;
  mono?: boolean;
}

function Cell({ value, col, onSave, mono }: CellProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);

  function commit() {
    setEditing(false);
    if (draft !== value) onSave(draft);
  }

  if (col?.type === "pdb") {
    return <PdbCell value={value} onSave={onSave} />;
  }

  if (col?.type === "boolean") {
    const checked = value === "true" || value === "1";
    return (
      <td
        className="px-3 py-0 h-9 border-r border-[#1e2d4a] last:border-r-0 text-center align-middle"
        onClick={() => onSave(checked ? "false" : "true")}
      >
        <div className={`inline-flex items-center justify-center w-4 h-4 rounded border cursor-pointer transition-all
          ${checked
            ? "bg-indigo-600 border-indigo-500"
            : "border-[#2a3555] hover:border-slate-400"
          }`}
        >
          {checked && <Check size={10} className="text-white" />}
        </div>
      </td>
    );
  }

  if (col?.type === "select" && col.options?.length) {
    return (
      <td className="px-0 py-0 h-9 border-r border-[#1e2d4a] last:border-r-0 align-middle">
        <select
          value={value}
          onChange={(e) => onSave(e.target.value)}
          className="w-full h-full bg-transparent px-3 text-sm text-white
            focus:outline-none focus:bg-indigo-500/10 cursor-pointer"
        >
          <option value="">—</option>
          {col.options.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
      </td>
    );
  }

  if (editing) {
    return (
      <td className="px-0 py-0 h-9 border-r border-[#1e2d4a] last:border-r-0 align-middle">
        <input
          autoFocus
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === "Enter") commit();
            if (e.key === "Escape") { setEditing(false); setDraft(value); }
          }}
          className={`w-full h-full bg-indigo-500/10 border-0 border-b-2 border-indigo-500 px-3
            text-sm text-white focus:outline-none ${mono ? "font-mono" : ""}`}
        />
      </td>
    );
  }

  return (
    <td
      className="px-3 py-0 h-9 border-r border-[#1e2d4a] last:border-r-0 align-middle
        hover:bg-white/[0.03] cursor-text group/cell"
      onClick={() => { setDraft(value); setEditing(true); }}
    >
      <span className={`text-sm ${mono ? "font-mono text-slate-400" : "text-slate-200"} truncate block max-w-[200px]`}>
        {mono ? seqPreview(value) : (value || <span className="text-slate-700">—</span>)}
      </span>
    </td>
  );
}

// ── Spreadsheet grid ──────────────────────────────────────────────────────────

const PAGE_SIZE = 100;

interface SheetProps {
  dsId: string;
}

function DatasetSheet({ dsId }: SheetProps) {
  const [editingCol, setEditingCol] = useState<ColumnDef | null | "new">(null);
  const [addingRow, setAddingRow] = useState(false);
  const [csvModal, setCsvModal] = useState(false);
  const [savingEntry, setSavingEntry] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [offset, setOffset] = useState(0);

  // Debounce search input
  useEffect(() => {
    const t = setTimeout(() => { setSearch(searchInput); setOffset(0); }, 300);
    return () => clearTimeout(t);
  }, [searchInput]);

  const qc = useQueryClient();

  const { data: ds, isLoading } = useQuery({
    queryKey: ["dataset", dsId, search, offset],
    queryFn: () => getDataset(dsId, { q: search, limit: PAGE_SIZE, offset }),
    enabled: !!dsId,
    staleTime: 10_000,
  });

  async function handleCellSave(
    entry: DatasetEntry,
    field: "name" | "heavy_chain" | "light_chain" | string,
    val: string,
  ) {
    if (!ds) return;
    setSavingEntry(entry.id);
    try {
      if (field === "name" || field === "heavy_chain" || field === "light_chain") {
        await updateEntry(ds.id, entry.id, { [field]: val || undefined });
      } else {
        await updateEntry(ds.id, entry.id, { data: { [field]: val } });
      }
      qc.invalidateQueries({ queryKey: ["dataset", dsId] });
    } finally {
      setSavingEntry(null);
    }
  }

  async function handleAddRow() {
    if (!ds) return;
    setAddingRow(true);
    try {
      await addEntry(ds.id, {});
      qc.invalidateQueries({ queryKey: ["dataset", dsId] });
    } finally {
      setAddingRow(false);
    }
  }

  async function handleDeleteRow(entryId: string) {
    if (!ds) return;
    await deleteEntry(ds.id, entryId);
    qc.invalidateQueries({ queryKey: ["dataset", dsId] });
  }

  async function handleUpdateCols(cols: ColumnDef[]) {
    if (!ds) return;
    await updateDataset(ds.id, { columns: cols });
    qc.invalidateQueries({ queryKey: ["datasets"] });
    qc.invalidateQueries({ queryKey: ["dataset", dsId] });
  }

  function handleColSave(col: ColumnDef) {
    if (editingCol === "new") {
      handleUpdateCols([...columns, col]);
    } else {
      handleUpdateCols(columns.map((c) => (c.id === col.id ? col : c)));
    }
    setEditingCol(null);
  }

  async function handleDeleteCol(colId: string) {
    const col = columns.find((c) => c.id === colId);
    if (!window.confirm(`Delete column "${col?.name ?? colId}" and all its data? This cannot be undone.`)) return;
    handleUpdateCols(columns.filter((c) => c.id !== colId));
  }

  const entries = ds?.entries ?? [];
  const totalFiltered = ds?.total_filtered ?? 0;
  const totalAll = ds?.entry_count ?? 0;
  const columns = ds?.columns ?? [];

  // Only show a built-in column when at least one entry has data for it.
  const noEntries = totalAll === 0;
  const showName  = noEntries || entries.some((e) => e.name);
  const showVH    = noEntries || entries.some((e) => e.heavy_chain);
  const showVL    = noEntries || entries.some((e) => e.light_chain);
  const builtinCount = [showName, showVH, showVL].filter(Boolean).length;

  const showingStart = offset + 1;
  const showingEnd = offset + entries.length;
  const hasMore = offset + entries.length < totalFiltered;
  const isLarge = totalAll > PAGE_SIZE;
  const exportUrl = ds ? `/api/datasets/${ds.id}/export.csv` : "#";

  if (isLoading && !ds) {
    return (
      <div className="flex-1 flex items-center justify-center text-slate-600 text-sm">
        Loading…
      </div>
    );
  }

  if (!ds) return null;

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* Dataset header */}
      <div className="px-6 pt-5 pb-3 border-b border-[#1e2d4a] flex flex-col gap-3 shrink-0">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <EditableTitle ds={ds} />
            <EditableDescription ds={ds} />
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <button
              onClick={() => setCsvModal(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium
                text-slate-400 hover:text-white border border-[#2a3555] hover:border-slate-500
                transition-all"
            >
              <Upload size={12} />
              <span>Import CSV</span>
            </button>
            <a
              href={exportUrl}
              download
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium
                text-slate-400 hover:text-white border border-[#2a3555] hover:border-slate-500
                transition-all"
            >
              <Download size={12} />
              <span>Export CSV</span>
            </a>
          </div>
        </div>

        {/* Search bar — only shown for large datasets */}
        {isLarge && (
          <div className="flex items-center gap-3">
            <div className="relative flex-1 max-w-sm">
              <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500 pointer-events-none" />
              <input
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                placeholder="Search name, VH, VL…"
                className="w-full bg-[#0e1425] border border-[#2a3555] rounded-lg pl-8 pr-3 py-1.5
                  text-sm text-white placeholder-slate-600 focus:outline-none focus:border-indigo-500"
              />
              {searchInput && (
                <button
                  onClick={() => setSearchInput("")}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-500 hover:text-white"
                >
                  <X size={12} />
                </button>
              )}
            </div>
            <span className="text-xs text-slate-500 whitespace-nowrap">
              {search
                ? `${totalFiltered.toLocaleString()} match${totalFiltered !== 1 ? "es" : ""} · showing ${showingStart}–${showingEnd}`
                : `Showing ${showingStart}–${showingEnd} of ${totalAll.toLocaleString()}`
              }
            </span>
          </div>
        )}
      </div>

      {/* Table */}
      <div className="flex-1 overflow-auto">
        <table className="w-full border-collapse text-sm" style={{ minWidth: "max-content" }}>
          <thead className="sticky top-0 z-10">
            <tr className="bg-[#0d1628] border-b border-[#1e2d4a]">
              {/* Built-in cols — only shown when at least one entry has data */}
              {showName && (
                <th className="px-3 py-2 text-left text-xs font-semibold text-slate-400 border-r
                  border-[#1e2d4a] whitespace-nowrap min-w-[140px]">Name</th>
              )}
              {showVH && (
                <th className="px-3 py-2 text-left text-xs font-semibold text-slate-400 border-r
                  border-[#1e2d4a] whitespace-nowrap min-w-[140px]">VH</th>
              )}
              {showVL && (
                <th className="px-3 py-2 text-left text-xs font-semibold text-slate-400 border-r
                  border-[#1e2d4a] whitespace-nowrap min-w-[140px]">VL</th>
              )}

              {/* User-defined cols */}
              {columns.map((col) => {
                const pct = completeness(entries, col.id);
                return (
                  <th
                    key={col.id}
                    className="px-3 py-2 text-left border-r border-[#1e2d4a] min-w-[140px] group/th"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-1.5 min-w-0">
                        <span className="text-slate-500 shrink-0">{COL_TYPE_ICONS[col.type]}</span>
                        <span className="text-xs font-semibold text-slate-300 truncate">
                          {col.name}
                        </span>
                      </div>
                      <div className="flex items-center gap-1 opacity-0 group-hover/th:opacity-100 transition-opacity shrink-0">
                        <button
                          onClick={() => setEditingCol(col)}
                          className="p-0.5 rounded text-slate-600 hover:text-indigo-400 transition-colors"
                        >
                          <Pencil size={10} />
                        </button>
                        <button
                          onClick={() => handleDeleteCol(col.id)}
                          className="p-0.5 rounded text-slate-600 hover:text-red-400 transition-colors"
                        >
                          <X size={10} />
                        </button>
                      </div>
                    </div>
                    {/* Completeness bar */}
                    {entries.length > 0 && (
                      <div className="mt-1 flex items-center gap-1.5">
                        <div className="flex-1 h-0.5 bg-[#1e2d4a] rounded-full overflow-hidden">
                          <div
                            className={`h-full rounded-full transition-all ${
                              pct === 100
                                ? "bg-emerald-500"
                                : pct > 50
                                ? "bg-amber-500"
                                : "bg-slate-600"
                            }`}
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                        <span className="text-[10px] text-slate-600 tabular-nums">{pct}%</span>
                      </div>
                    )}
                  </th>
                );
              })}

              {/* Add column */}
              <th className="px-2 py-2 border-r border-[#1e2d4a]">
                <button
                  onClick={() => setEditingCol("new")}
                  className="flex items-center gap-1 px-2 py-1 rounded-lg text-xs text-slate-500
                    hover:text-indigo-400 hover:bg-indigo-500/10 border border-dashed border-[#2a3555]
                    hover:border-indigo-500/50 transition-all whitespace-nowrap"
                >
                  <Plus size={11} />
                  <span>Add column</span>
                </button>
              </th>

              {/* Row delete spacer */}
              <th className="w-8" />
            </tr>
          </thead>

          <tbody>
            {entries.map((entry) => (
              <tr
                key={entry.id}
                className={`border-b border-[#1a2540] hover:bg-white/[0.02] transition-colors group
                  ${savingEntry === entry.id ? "opacity-60" : ""}`}
              >
                {showName && (
                  <Cell
                    value={entry.name ?? ""}
                    onSave={(v) => handleCellSave(entry, "name", v)}
                  />
                )}
                {showVH && (
                  <Cell
                    value={entry.heavy_chain ?? ""}
                    onSave={(v) => handleCellSave(entry, "heavy_chain", v)}
                    mono
                  />
                )}
                {showVL && (
                  <Cell
                    value={entry.light_chain ?? ""}
                    onSave={(v) => handleCellSave(entry, "light_chain", v)}
                    mono
                  />
                )}
                {columns.map((col) => (
                  <Cell
                    key={col.id}
                    value={String(entry.data[col.id] ?? "")}
                    col={col}
                    onSave={(v) => handleCellSave(entry, col.id, v)}
                  />
                ))}
                {/* spacer for add-col button column */}
                <td className="border-r border-[#1e2d4a]" />
                {/* delete row */}
                <td className="px-1 align-middle">
                  <button
                    onClick={() => handleDeleteRow(entry.id)}
                    className="p-1 rounded text-slate-700 hover:text-red-400 hover:bg-red-400/10
                      opacity-0 group-hover:opacity-100 transition-all"
                  >
                    <Trash2 size={12} />
                  </button>
                </td>
              </tr>
            ))}

            {/* Empty state */}
            {entries.length === 0 && (
              <tr>
                <td
                  colSpan={builtinCount + columns.length + 2}
                  className="px-6 py-16 text-center text-sm text-slate-600"
                >
                  {search
                    ? `No rows match "${search}"`
                    : <>No rows yet — click <strong className="text-slate-500">+ Add row</strong> or import a CSV</>
                  }
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Footer: add row + pagination */}
      <div className="px-4 py-2.5 border-t border-[#1e2d4a] shrink-0 flex items-center gap-3">
        <button
          onClick={handleAddRow}
          disabled={addingRow}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs text-slate-500
            hover:text-white hover:bg-white/5 border border-dashed border-[#2a3555]
            hover:border-slate-500 transition-all disabled:opacity-40"
        >
          <Plus size={12} />
          <span>{addingRow ? "Adding…" : "Add row"}</span>
        </button>

        {(offset > 0 || hasMore) && (
          <div className="flex items-center gap-2 ml-auto">
            {offset > 0 && (
              <button
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                className="px-3 py-1.5 rounded-lg text-xs text-slate-400 hover:text-white
                  border border-[#2a3555] hover:border-slate-500 transition-all"
              >
                ← Previous
              </button>
            )}
            {hasMore && (
              <button
                onClick={() => setOffset(offset + PAGE_SIZE)}
                className="px-3 py-1.5 rounded-lg text-xs text-slate-400 hover:text-white
                  border border-[#2a3555] hover:border-slate-500 transition-all"
              >
                Next {Math.min(PAGE_SIZE, totalFiltered - offset - entries.length).toLocaleString()} →
              </button>
            )}
          </div>
        )}
      </div>

      {/* Modals */}
      {editingCol !== null && (
        <ColEditorModal
          initial={editingCol === "new" ? undefined : editingCol}
          onSave={handleColSave}
          onDelete={editingCol !== "new" ? (colId) => { handleDeleteCol(colId); setEditingCol(null); } : undefined}
          onClose={() => setEditingCol(null)}
        />
      )}

      {csvModal && (
        <CsvImportModal
          existingDs={ds}
          onClose={() => setCsvModal(false)}
          onDone={(id) => {
            setCsvModal(false);
            qc.invalidateQueries({ queryKey: ["dataset", id] });
          }}
        />
      )}
    </div>
  );
}

// ── Editable dataset name / description ───────────────────────────────────────

function EditableTitle({ ds }: { ds: DatasetDetail }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(ds.name);
  const qc = useQueryClient();

  async function commit() {
    setEditing(false);
    if (draft.trim() && draft !== ds.name) {
      await updateDataset(ds.id, { name: draft.trim() });
      qc.invalidateQueries({ queryKey: ["datasets"] });
      qc.invalidateQueries({ queryKey: ["dataset", ds.id] });
    }
  }

  if (editing) {
    return (
      <input
        autoFocus
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => { if (e.key === "Enter") commit(); if (e.key === "Escape") setEditing(false); }}
        className="text-lg font-bold text-white bg-transparent border-b border-indigo-500
          focus:outline-none w-full mb-1"
      />
    );
  }

  return (
    <h2
      className="text-lg font-bold text-white mb-0.5 cursor-text hover:text-indigo-300 transition-colors"
      onClick={() => { setDraft(ds.name); setEditing(true); }}
    >
      {ds.name}
    </h2>
  );
}

function EditableDescription({ ds }: { ds: DatasetDetail }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(ds.description ?? "");
  const qc = useQueryClient();

  async function commit() {
    setEditing(false);
    if (draft !== (ds.description ?? "")) {
      await updateDataset(ds.id, { description: draft || undefined });
      qc.invalidateQueries({ queryKey: ["dataset", ds.id] });
    }
  }

  if (editing) {
    return (
      <input
        autoFocus
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => { if (e.key === "Enter") commit(); if (e.key === "Escape") setEditing(false); }}
        placeholder="Add a description…"
        className="text-xs text-slate-400 bg-transparent border-b border-slate-600
          focus:outline-none w-full"
      />
    );
  }

  return (
    <p
      className="text-xs text-slate-500 cursor-text hover:text-slate-400 transition-colors"
      onClick={() => { setDraft(ds.description ?? ""); setEditing(true); }}
    >
      {ds.description || <span className="italic text-slate-700">No description — click to add</span>}
    </p>
  );
}

// ── Dataset sidebar ───────────────────────────────────────────────────────────

interface SidebarProps {
  selected: string | null;
  onSelect: (id: string) => void;
}

function DatasetSidebar({ selected, onSelect }: SidebarProps) {
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [deleting, setDeleting] = useState<string | null>(null);
  const [csvImport, setCsvImport] = useState(false);
  const qc = useQueryClient();

  const { data: datasets = [], isLoading } = useQuery({
    queryKey: ["datasets"],
    queryFn: listDatasets,
  });

  async function handleCreate() {
    if (!newName.trim()) return;
    const ds = await createDataset(newName.trim());
    qc.invalidateQueries({ queryKey: ["datasets"] });
    setCreating(false);
    setNewName("");
    onSelect(ds.id);
  }

  async function handleDelete(e: React.MouseEvent, id: string) {
    e.stopPropagation();
    if (!window.confirm("Delete this dataset and all its rows?")) return;
    setDeleting(id);
    try {
      await deleteDataset(id);
      qc.invalidateQueries({ queryKey: ["datasets"] });
      if (selected === id) onSelect("");
    } finally {
      setDeleting(null);
    }
  }

  return (
    <div className="w-56 shrink-0 border-r border-[#1e2d4a] flex flex-col bg-[#0c1320]">
      <div className="px-4 py-3 border-b border-[#1e2d4a] flex items-center justify-between">
        <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Datasets</span>
        <div className="flex items-center gap-1">
          <button
            onClick={() => setCsvImport(true)}
            className="p-1 rounded text-slate-500 hover:text-indigo-400 hover:bg-indigo-500/10
              transition-all"
            title="Import CSV as new dataset"
          >
            <Upload size={14} />
          </button>
          <button
            onClick={() => setCreating(true)}
            className="p-1 rounded text-slate-500 hover:text-indigo-400 hover:bg-indigo-500/10
              transition-all"
            title="New dataset"
          >
            <Plus size={14} />
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto py-1">
        {isLoading && (
          <div className="px-4 py-4 text-xs text-slate-600 text-center">Loading…</div>
        )}
        {!isLoading && datasets.length === 0 && !creating && (
          <div className="px-4 py-6 text-xs text-slate-600 text-center">
            No datasets yet
          </div>
        )}
        {datasets.map((ds) => (
          <button
            key={ds.id}
            onClick={() => onSelect(ds.id)}
            className={`w-full text-left px-4 py-2.5 border-b border-[#1a2540] last:border-0
              hover:bg-white/[0.03] transition-colors group flex items-center justify-between
              ${selected === ds.id ? "bg-indigo-500/10 border-l-2 border-l-indigo-500" : ""}`}
          >
            <div className="min-w-0">
              <div className="text-sm font-medium text-slate-200 truncate">{ds.name}</div>
              <div className="text-[10px] text-slate-600 mt-0.5">
                {ds.entry_count} row{ds.entry_count !== 1 ? "s" : ""}
                {ds.columns.length > 0 && ` · ${ds.columns.length} col${ds.columns.length !== 1 ? "s" : ""}`}
              </div>
            </div>
            <button
              onClick={(e) => handleDelete(e, ds.id)}
              disabled={deleting === ds.id}
              className="shrink-0 p-1 rounded text-slate-700 hover:text-red-400 hover:bg-red-400/10
                opacity-0 group-hover:opacity-100 transition-all disabled:opacity-30 ml-1"
            >
              <Trash2 size={11} />
            </button>
          </button>
        ))}
      </div>

      {/* Create form */}
      {creating && (
        <div className="px-3 py-3 border-t border-[#1e2d4a]">
          <input
            autoFocus
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleCreate();
              if (e.key === "Escape") { setCreating(false); setNewName(""); }
            }}
            placeholder="Dataset name…"
            className="w-full bg-[#0e1425] border border-[#2a3555] rounded-lg px-3 py-1.5
              text-sm text-white placeholder-slate-600 focus:outline-none focus:border-indigo-500 mb-2"
          />
          <div className="flex gap-1.5">
            <button
              onClick={() => { setCreating(false); setNewName(""); }}
              className="flex-1 px-2 py-1 rounded text-xs text-slate-500 hover:text-white
                border border-[#2a3555] transition-all"
            >
              Cancel
            </button>
            <button
              onClick={handleCreate}
              disabled={!newName.trim()}
              className="flex-1 px-2 py-1 rounded text-xs text-white bg-indigo-600 hover:bg-indigo-500
                transition-all disabled:opacity-40"
            >
              Create
            </button>
          </div>
        </div>
      )}

      {csvImport && (
        <CsvImportModal
          onClose={() => setCsvImport(false)}
          onDone={(dsId) => {
            setCsvImport(false);
            qc.invalidateQueries({ queryKey: ["datasets"] });
            onSelect(dsId);
          }}
        />
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export function DatasetPage({ onBack }: { onBack: () => void }) {
  const [selectedId, setSelectedId] = useState<string>("");
  const { data: datasets } = useQuery({ queryKey: ["datasets"], queryFn: listDatasets });
  const selectedName = datasets?.find((d) => d.id === selectedId)?.name;

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-[#0a1120]">
      {/* Top bar */}
      <div
        className="h-12 border-b border-[#1e2d4a] flex items-center px-4 gap-3 shrink-0"
        style={{ background: "linear-gradient(90deg, #0e1425 0%, #111830 100%)" }}
      >
        <button
          onClick={onBack}
          className="flex items-center gap-1.5 text-slate-400 hover:text-white transition-colors text-sm"
        >
          <ArrowLeft size={15} />
          <span>Back</span>
        </button>
        <div className="w-px h-5 bg-[#2a3555] mx-1" />
        <span className="text-sm font-semibold text-white">Datasets</span>
        {selectedName && (
          <>
            <span className="text-slate-600">/</span>
            <span className="text-sm text-slate-400">{selectedName}</span>
          </>
        )}
      </div>

      {/* Body */}
      <div className="flex flex-1 overflow-hidden">
        <DatasetSidebar selected={selectedId} onSelect={setSelectedId} />

        {!selectedId && (
          <div className="flex-1 flex items-center justify-center text-slate-600 text-sm">
            Select or create a dataset
          </div>
        )}

        {selectedId && (
          <DatasetSheet key={selectedId} dsId={selectedId} />
        )}
      </div>
    </div>
  );
}
