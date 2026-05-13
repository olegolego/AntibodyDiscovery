import { useEffect, useState } from "react";
import { CheckCircle2, AlertTriangle, Loader2, X } from "lucide-react";
import { workshopApi, type CustomTool } from "../api/workshop";

interface PublishModalProps {
  tool: CustomTool;
  onClose: () => void;
  onPublished: () => void;
}

interface ParsedSpec {
  id?: string;
  name?: string;
  category?: string;
  inputs?: Array<{ name: string; type: string }>;
  outputs?: Array<{ name: string; type: string }>;
}

export function PublishModal({ tool, onClose, onPublished }: PublishModalProps) {
  const [spec, setSpec] = useState<ParsedSpec | null>(null);
  const [parseError, setParseError] = useState("");
  const [publishing, setPublishing] = useState(false);
  const [publishError, setPublishError] = useState("");

  useEffect(() => {
    try {
      // Basic YAML preview — parse key/value lines only
      const parsed: Record<string, unknown> = {};
      tool.tool_yaml.split("\n").forEach((line) => {
        const m = line.match(/^(\w+):\s*(.+)/);
        if (m) parsed[m[1]] = m[2].replace(/^["']|["']$/g, "");
      });
      setSpec(parsed as ParsedSpec);
      setParseError("");
    } catch {
      setParseError("Could not parse tool.yaml");
    }
  }, [tool.tool_yaml]);

  async function handlePublish() {
    setPublishing(true);
    setPublishError("");
    try {
      await workshopApi.publishTool(tool.id);
      onPublished();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setPublishError(msg);
    } finally {
      setPublishing(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50">
      <div className="bg-[#13151f] border border-border rounded-xl w-96 shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-border">
          <span className="font-semibold text-white">Publish Tool to Pipeline</span>
          <button onClick={onClose} className="text-slate-500 hover:text-white transition-colors">
            <X size={16} />
          </button>
        </div>

        <div className="p-5 space-y-4">
          {parseError ? (
            <div className="flex items-start gap-2 text-sm text-yellow-400">
              <AlertTriangle size={14} className="mt-0.5 flex-shrink-0" />
              <span>{parseError}</span>
            </div>
          ) : spec ? (
            <div className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-slate-500">Tool ID</span>
                <span className="text-white font-mono text-xs">{spec.id ?? "—"}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500">Name</span>
                <span className="text-white">{spec.name ?? tool.name}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500">Category</span>
                <span className="text-white">{spec.category ?? "—"}</span>
              </div>
            </div>
          ) : null}

          <p className="text-xs text-slate-500 leading-relaxed">
            Publishing writes your tool to the pipeline system. It will appear in the
            tool palette and can be dragged onto the canvas immediately.
          </p>

          {publishError && (
            <div className="text-xs text-red-400 bg-red-950/30 border border-red-800/40
              rounded-lg p-2 whitespace-pre-wrap">
              {publishError}
            </div>
          )}
        </div>

        <div className="flex gap-2 px-5 pb-5">
          <button
            onClick={onClose}
            className="flex-1 py-2 rounded-lg border border-border text-sm text-slate-400
              hover:text-white hover:border-slate-500 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handlePublish}
            disabled={publishing || !!parseError}
            className="flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg
              bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-sm font-medium
              text-white transition-colors"
          >
            {publishing
              ? <><Loader2 size={13} className="animate-spin" /> Publishing…</>
              : <><CheckCircle2 size={13} /> Publish</>
            }
          </button>
        </div>
      </div>
    </div>
  );
}
