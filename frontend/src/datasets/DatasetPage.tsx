import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  Check,
  CheckSquare,
  ChevronDown,
  Download,
  Hash,
  List,
  Pencil,
  Plus,
  Trash2,
  Type,
  Upload,
  X,
} from "lucide-react";
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
};

const COL_TYPE_LABELS: Record<ColType, string> = {
  text: "Text",
  number: "Number",
  select: "Select",
  boolean: "Checkbox",
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
  onClose: () => void;
}

function ColEditorModal({ initial, onSave, onClose }: ColEditorProps) {
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
            {(["text", "number", "select", "boolean"] as ColType[]).map((t) => (
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

// ── CSV import modal ──────────────────────────────────────────────────────────

interface CsvImportProps {
  ds: DatasetDetail;
  onClose: () => void;
  onImported: () => void;
}

function CsvImportModal({ ds, onClose, onImported }: CsvImportProps) {
  const [rows, setRows] = useState<string[][]>([]);
  const [headers, setHeaders] = useState<string[]>([]);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [importing, setImporting] = useState(false);

  const builtins = ["name", "heavy_chain", "light_chain"];
  const allTargetCols = [
    ...builtins.map((b) => ({ id: b, name: b === "heavy_chain" ? "VH" : b === "light_chain" ? "VL" : "Name" })),
    ...ds.columns.map((c) => ({ id: c.id, name: c.name })),
    { id: "__skip__", name: "(skip)" },
  ];

  function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      const text = ev.target?.result as string;
      const lines = text.split(/\r?\n/).filter(Boolean);
      if (!lines.length) return;
      const parsed = lines.map((l) => l.split(",").map((c) => c.trim().replace(/^"|"$/g, "")));
      const [hdrs, ...data] = parsed;
      setHeaders(hdrs);
      setRows(data.slice(0, 5));
      // Auto-map by name
      const auto: Record<string, string> = {};
      hdrs.forEach((h) => {
        const hl = h.toLowerCase();
        if (hl === "name") auto[h] = "name";
        else if (hl === "vh" || hl === "heavy_chain" || hl === "heavy chain") auto[h] = "heavy_chain";
        else if (hl === "vl" || hl === "light_chain" || hl === "light chain") auto[h] = "light_chain";
        else {
          const match = ds.columns.find(
            (c) => c.name.toLowerCase() === hl || c.id === h,
          );
          auto[h] = match ? match.id : "__skip__";
        }
      });
      setMapping(auto);
    };
    reader.readAsText(file);
  }

  async function handleImport() {
    setImporting(true);
    try {
      const file = (document.getElementById("csv-upload") as HTMLInputElement).files?.[0];
      if (!file) return;

      const text = await file.text();
      const lines = text.split(/\r?\n/).filter(Boolean);
      const [hdrs, ...dataLines] = lines.map((l) =>
        l.split(",").map((c) => c.trim().replace(/^"|"$/g, "")),
      );

      const entries = dataLines.map((row) => {
        const entry: Record<string, unknown> = { data: {} };
        hdrs.forEach((h, i) => {
          const target = mapping[h] ?? "__skip__";
          if (target === "__skip__") return;
          if (target === "name") entry.name = row[i];
          else if (target === "heavy_chain") entry.heavy_chain = row[i];
          else if (target === "light_chain") entry.light_chain = row[i];
          else (entry.data as Record<string, unknown>)[target] = row[i];
        });
        return entry;
      });

      await bulkAddEntries(ds.id, entries as Parameters<typeof bulkAddEntries>[1]);
      onImported();
    } finally {
      setImporting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-[#131a2e] border border-[#2a3555] rounded-2xl shadow-2xl w-[600px] max-h-[80vh] flex flex-col">
        <div className="flex items-center justify-between px-6 pt-6 pb-4 border-b border-[#2a3555]">
          <h3 className="text-sm font-semibold text-white">Import from CSV</h3>
          <button onClick={onClose} className="text-slate-500 hover:text-white transition-colors">
            <X size={15} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-6">
          <label className="flex flex-col items-center justify-center gap-3 border-2 border-dashed
            border-[#2a3555] rounded-xl p-8 cursor-pointer hover:border-indigo-500/60 transition-colors mb-6">
            <Upload size={24} className="text-slate-500" />
            <span className="text-sm text-slate-400">Click to pick a CSV file</span>
            <input id="csv-upload" type="file" accept=".csv" className="hidden" onChange={handleFile} />
          </label>

          {headers.length > 0 && (
            <>
              <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
                Column mapping
              </p>
              <div className="space-y-2 mb-5">
                {headers.map((h) => (
                  <div key={h} className="flex items-center gap-3">
                    <span className="w-40 text-sm text-slate-300 truncate">{h}</span>
                    <ChevronDown size={13} className="text-slate-600 shrink-0" />
                    <select
                      value={mapping[h] ?? "__skip__"}
                      onChange={(e) => setMapping((m) => ({ ...m, [h]: e.target.value }))}
                      className="flex-1 bg-[#0e1425] border border-[#2a3555] rounded-lg px-2 py-1.5
                        text-sm text-white focus:outline-none focus:border-indigo-500"
                    >
                      {allTargetCols.map((c) => (
                        <option key={c.id} value={c.id}>{c.name}</option>
                      ))}
                    </select>
                  </div>
                ))}
              </div>

              {rows.length > 0 && (
                <>
                  <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">
                    Preview (first 5 rows)
                  </p>
                  <div className="overflow-x-auto rounded-lg border border-[#2a3555]">
                    <table className="text-xs text-slate-300 w-full">
                      <thead>
                        <tr className="bg-[#0e1425]">
                          {headers.map((h) => (
                            <th key={h} className="px-3 py-2 text-left text-slate-500 font-medium">
                              {h}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {rows.map((row, i) => (
                          <tr key={i} className="border-t border-[#2a3555]">
                            {row.map((cell, j) => (
                              <td key={j} className="px-3 py-2 max-w-[120px] truncate">
                                {cell}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              )}
            </>
          )}
        </div>

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
            disabled={!headers.length || importing}
            className="flex-1 px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-sm
              text-white font-medium transition-all disabled:opacity-40"
          >
            {importing ? "Importing…" : "Import"}
          </button>
        </div>
      </div>
    </div>
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

interface SheetProps {
  ds: DatasetDetail;
  onUpdateCols: (cols: ColumnDef[]) => void;
}

function DatasetSheet({ ds, onUpdateCols }: SheetProps) {
  const [editingCol, setEditingCol] = useState<ColumnDef | null | "new">(null);
  const [addingRow, setAddingRow] = useState(false);
  const [csvModal, setCsvModal] = useState(false);
  const [savingEntry, setSavingEntry] = useState<string | null>(null);

  const qc = useQueryClient();

  async function handleCellSave(
    entry: DatasetEntry,
    field: "name" | "heavy_chain" | "light_chain" | string,
    val: string,
  ) {
    setSavingEntry(entry.id);
    try {
      if (field === "name" || field === "heavy_chain" || field === "light_chain") {
        await updateEntry(ds.id, entry.id, { [field]: val || undefined });
      } else {
        await updateEntry(ds.id, entry.id, { data: { [field]: val } });
      }
      qc.invalidateQueries({ queryKey: ["dataset", ds.id] });
    } finally {
      setSavingEntry(null);
    }
  }

  async function handleAddRow() {
    setAddingRow(true);
    try {
      await addEntry(ds.id, {});
      qc.invalidateQueries({ queryKey: ["dataset", ds.id] });
    } finally {
      setAddingRow(false);
    }
  }

  async function handleDeleteRow(entryId: string) {
    await deleteEntry(ds.id, entryId);
    qc.invalidateQueries({ queryKey: ["dataset", ds.id] });
  }

  function handleColSave(col: ColumnDef) {
    const cols = ds.columns;
    if (editingCol === "new") {
      onUpdateCols([...cols, col]);
    } else {
      onUpdateCols(cols.map((c) => (c.id === col.id ? col : c)));
    }
    setEditingCol(null);
  }

  async function handleDeleteCol(colId: string) {
    onUpdateCols(ds.columns.filter((c) => c.id !== colId));
  }

  const exportUrl = `/api/datasets/${ds.id}/export.csv`;

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* Dataset header */}
      <div className="px-6 pt-5 pb-4 border-b border-[#1e2d4a] flex items-start justify-between gap-4 shrink-0">
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

      {/* Table */}
      <div className="flex-1 overflow-auto">
        <table className="w-full border-collapse text-sm" style={{ minWidth: "max-content" }}>
          <thead className="sticky top-0 z-10">
            <tr className="bg-[#0d1628] border-b border-[#1e2d4a]">
              {/* Built-in cols */}
              {[
                { key: "name", label: "Name" },
                { key: "heavy_chain", label: "VH" },
                { key: "light_chain", label: "VL" },
              ].map((col) => (
                <th
                  key={col.key}
                  className="px-3 py-2 text-left text-xs font-semibold text-slate-400 border-r
                    border-[#1e2d4a] whitespace-nowrap min-w-[140px]"
                >
                  {col.label}
                </th>
              ))}

              {/* User-defined cols */}
              {ds.columns.map((col) => {
                const pct = completeness(ds.entries, col.id);
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
                    {ds.entries.length > 0 && (
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
            {ds.entries.map((entry) => (
              <tr
                key={entry.id}
                className={`border-b border-[#1a2540] hover:bg-white/[0.02] transition-colors group
                  ${savingEntry === entry.id ? "opacity-60" : ""}`}
              >
                <Cell
                  value={entry.name ?? ""}
                  onSave={(v) => handleCellSave(entry, "name", v)}
                />
                <Cell
                  value={entry.heavy_chain ?? ""}
                  onSave={(v) => handleCellSave(entry, "heavy_chain", v)}
                  mono
                />
                <Cell
                  value={entry.light_chain ?? ""}
                  onSave={(v) => handleCellSave(entry, "light_chain", v)}
                  mono
                />
                {ds.columns.map((col) => (
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
            {ds.entries.length === 0 && (
              <tr>
                <td
                  colSpan={3 + ds.columns.length + 2}
                  className="px-6 py-16 text-center text-sm text-slate-600"
                >
                  No rows yet — click <strong className="text-slate-500">+ Add row</strong> or import a CSV
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Add row footer */}
      <div className="px-4 py-2.5 border-t border-[#1e2d4a] shrink-0">
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
      </div>

      {/* Modals */}
      {editingCol !== null && (
        <ColEditorModal
          initial={editingCol === "new" ? undefined : editingCol}
          onSave={handleColSave}
          onClose={() => setEditingCol(null)}
        />
      )}

      {csvModal && (
        <CsvImportModal
          ds={ds}
          onClose={() => setCsvModal(false)}
          onImported={() => {
            setCsvModal(false);
            qc.invalidateQueries({ queryKey: ["dataset", ds.id] });
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
        <button
          onClick={() => setCreating(true)}
          className="p-1 rounded text-slate-500 hover:text-indigo-400 hover:bg-indigo-500/10
            transition-all"
          title="New dataset"
        >
          <Plus size={14} />
        </button>
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
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export function DatasetPage({ onBack }: { onBack: () => void }) {
  const [selectedId, setSelectedId] = useState<string>("");
  const qc = useQueryClient();

  const { data: ds } = useQuery({
    queryKey: ["dataset", selectedId],
    queryFn: () => getDataset(selectedId),
    enabled: !!selectedId,
  });

  async function handleUpdateCols(cols: ColumnDef[]) {
    if (!ds) return;
    await updateDataset(ds.id, { columns: cols });
    qc.invalidateQueries({ queryKey: ["datasets"] });
    qc.invalidateQueries({ queryKey: ["dataset", ds.id] });
  }

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
        {ds && (
          <>
            <span className="text-slate-600">/</span>
            <span className="text-sm text-slate-400">{ds.name}</span>
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

        {selectedId && !ds && (
          <div className="flex-1 flex items-center justify-center text-slate-600 text-sm">
            Loading…
          </div>
        )}

        {ds && (
          <DatasetSheet
            key={ds.id}
            ds={ds}
            onUpdateCols={handleUpdateCols}
          />
        )}
      </div>
    </div>
  );
}
