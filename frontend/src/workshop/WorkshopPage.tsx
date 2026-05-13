import { useRef, useState } from "react";
import { ToolList } from "./ToolList";
import { ToolEditor } from "./ToolEditor";
import { TestPanel } from "./TestPanel";
import { BenchmarkPanel } from "./BenchmarkPanel";
import { ClaudePanel } from "./ClaudePanel";
import { PublishModal } from "./PublishModal";
import { workshopApi, type CustomTool } from "../api/workshop";

type RightTab = "claude" | "benchmark";

interface WorkshopPageProps {
  onBack: () => void;
  onGoToCanvas: () => void;
}

export function WorkshopPage({ onBack, onGoToCanvas }: WorkshopPageProps) {
  const [selectedTool, setSelectedTool] = useState<CustomTool | null>(null);
  const [rightTab, setRightTab] = useState<RightTab>("claude");
  const [showPublish, setShowPublish] = useState(false);
  const [lastError, setLastError] = useState<string>("");
  const [editingName, setEditingName] = useState(false);
  const [nameValue, setNameValue] = useState("");
  const [listRefreshKey, setListRefreshKey] = useState(0);
  const nameInputRef = useRef<HTMLInputElement>(null);

  function handleToolChange(tool: CustomTool) {
    setSelectedTool(tool);
    setLastError("");
  }

  function handleRunError(err: string) {
    setLastError(err);
  }

  function handleApplyCode(code: string) {
    if (!selectedTool) return;
    setSelectedTool({ ...selectedTool, run_py: code });
  }

  function startEditingName() {
    if (!selectedTool) return;
    setNameValue(selectedTool.name);
    setEditingName(true);
    setTimeout(() => nameInputRef.current?.select(), 0);
  }

  async function commitNameEdit() {
    if (!selectedTool || !editingName) return;
    setEditingName(false);
    const trimmed = nameValue.trim();
    if (!trimmed || trimmed === selectedTool.name) return;
    const updated = await workshopApi.updateTool(selectedTool.id, { name: trimmed });
    setSelectedTool(updated);
    setListRefreshKey((k) => k + 1);
  }

  function handleNameKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter") nameInputRef.current?.blur();
    if (e.key === "Escape") { setEditingName(false); setNameValue(selectedTool?.name ?? ""); }
  }

  return (
    <div className="flex flex-col h-screen bg-[#0f1117] text-white overflow-hidden">
      {/* Top bar */}
      <div className="flex items-center gap-3 px-4 h-11 border-b border-border flex-shrink-0">
        <button
          onClick={onBack}
          className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-white transition-colors"
        >
          ← Back to Canvas
        </button>
        <div className="w-px h-4 bg-border" />
        <span className="text-sm font-bold text-white">Workshop</span>
        {selectedTool ? (
          <>
            <div className="w-px h-4 bg-border" />
            {editingName ? (
              <input
                ref={nameInputRef}
                value={nameValue}
                onChange={(e) => setNameValue(e.target.value)}
                onBlur={commitNameEdit}
                onKeyDown={handleNameKeyDown}
                className="bg-[#1e2030] border border-indigo-500 rounded px-2 py-0.5
                  text-sm text-white focus:outline-none w-48"
                autoFocus
              />
            ) : (
              <button
                onClick={startEditingName}
                className="text-sm text-slate-200 hover:text-white hover:underline
                  decoration-dashed decoration-slate-500 underline-offset-2 transition-colors"
                title="Click to rename"
              >
                {selectedTool.name}
              </button>
            )}
            <div className="flex-1" />
            <button
              onClick={() => setShowPublish(true)}
              className="flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-medium
                bg-emerald-600 hover:bg-emerald-500 text-white transition-colors"
            >
              Publish to Pipeline →
            </button>
          </>
        ) : (
          <span className="text-xs text-slate-600">
            Build, test, and publish custom pipeline tools
          </span>
        )}
      </div>

      {/* Main 3-panel layout */}
      <div className="flex flex-1 min-h-0">
        {/* Left: Tool list */}
        <div className="w-52 flex-shrink-0 border-r border-border flex flex-col">
          <ToolList
            selectedId={selectedTool?.id ?? null}
            onSelect={handleToolChange}
            refreshKey={listRefreshKey}
          />
        </div>

        {/* Center: Editor + Test output */}
        {selectedTool ? (
          <div className="flex flex-col flex-1 min-w-0">
            {/* Code editor (top ~60%) */}
            <div className="flex-[3] min-h-0 border-b border-border overflow-hidden">
              <ToolEditor
                tool={selectedTool}
                onChange={handleToolChange}
              />
            </div>
            {/* Test panel (bottom ~40%) */}
            <div className="flex-[2] min-h-0 overflow-hidden">
              <TestPanel tool={selectedTool} onError={handleRunError} />
            </div>
          </div>
        ) : (
          <div className="flex-1 flex items-center justify-center">
            <p className="text-slate-600 text-sm">
              Select a tool from the left, or create a new one
            </p>
          </div>
        )}

        {/* Right: Claude / Benchmark tabs */}
        {selectedTool && (
          <div className="w-80 flex-shrink-0 border-l border-border flex flex-col">
            {/* Tab switcher */}
            <div className="flex border-b border-border flex-shrink-0">
              {(["claude", "benchmark"] as RightTab[]).map((tab) => (
                <button
                  key={tab}
                  onClick={() => setRightTab(tab)}
                  className={`flex-1 py-2 text-xs font-medium capitalize transition-colors
                    ${rightTab === tab
                      ? "text-white border-b-2 border-indigo-500"
                      : "text-slate-500 hover:text-slate-300"
                    }`}
                >
                  {tab === "claude" ? "Claude AI" : "Benchmarks"}
                </button>
              ))}
            </div>

            <div className="flex-1 min-h-0 overflow-hidden">
              {rightTab === "claude" ? (
                <ClaudePanel
                  tool={selectedTool}
                  lastError={lastError}
                  onApply={handleApplyCode}
                />
              ) : (
                <BenchmarkPanel tool={selectedTool} />
              )}
            </div>
          </div>
        )}
      </div>

      {/* Publish modal */}
      {showPublish && selectedTool && (
        <PublishModal
          tool={selectedTool}
          onClose={() => setShowPublish(false)}
          onPublished={() => {
            setShowPublish(false);
            onGoToCanvas();
          }}
        />
      )}
    </div>
  );
}
