import { useState } from "react";
import { useRLDesignerStore, computeActionCount, stateDimLabel } from "./store";
import type { RLSpec } from "./store";
import type { ArchitectureSpec } from "@/dnn_designer/store";
import type { DNNContext } from "@/canvas/ParamPanel";

import { BLOCKS, DASHBOARD_TABS } from "./blocks";

import { RLFlowDiagram } from "./RLFlowDiagram";
import { StateBlock } from "./StateBlock";
import { ActionBlock } from "./ActionBlock";
import { RewardBlock } from "./RewardBlock";
import { AlgorithmBlock } from "./AlgorithmBlock";
import { PolicyBlock } from "./PolicyBlock";

import { QHeatmap } from "./dashboard/QHeatmap";
import { RewardCurve } from "./dashboard/RewardCurve";
import { ExplorationMap } from "./dashboard/ExplorationMap";
import { PolicyArrows } from "./dashboard/PolicyArrows";
import { EpisodeTable } from "./dashboard/EpisodeTable";

interface RLDesignerPageProps {
  nodeId: string;
  initialSpec?: RLSpec | null;
  context?: DNNContext;
  onBack: () => void;
  onSave: (nodeId: string, spec: RLSpec) => void;
  onOpenDNNDesigner?: (spec: ArchitectureSpec | null, onSave: (arch: ArchitectureSpec) => void) => void;
}

const BLOCK_COMPONENTS: Record<string, React.ComponentType<{ onOpenDNNDesigner?: (s: ArchitectureSpec | null) => void }>> = {
  state:     StateBlock as React.ComponentType<{ onOpenDNNDesigner?: (s: ArchitectureSpec | null) => void }>,
  action:    ActionBlock as React.ComponentType<{ onOpenDNNDesigner?: (s: ArchitectureSpec | null) => void }>,
  reward:    RewardBlock as React.ComponentType<{ onOpenDNNDesigner?: (s: ArchitectureSpec | null) => void }>,
  algorithm: AlgorithmBlock as React.ComponentType<{ onOpenDNNDesigner?: (s: ArchitectureSpec | null) => void }>,
  policy:    PolicyBlock as React.ComponentType<{ onOpenDNNDesigner?: (s: ArchitectureSpec | null) => void }>,
};

export function RLDesignerPage({
  nodeId,
  initialSpec,
  onBack,
  onSave,
  onOpenDNNDesigner,
}: RLDesignerPageProps) {
  const { spec, loadSpec, toSpec, dirty, activeTab, setActiveTab, setPolicyNetwork } = useRLDesignerStore();
  const [expandedBlock, setExpandedBlock] = useState<string | null>("state");

  // Initialise from saved spec on mount
  useState(() => {
    if (initialSpec) loadSpec(initialSpec);
  });

  function handleSave() {
    onSave(nodeId, toSpec());
  }

  const actionCount = computeActionCount(spec);
  const stateLabel = stateDimLabel(spec);

  function renderDashboard() {
    switch (activeTab) {
      case "q_heatmap":   return <QHeatmap />;
      case "rewards":     return <RewardCurve />;
      case "exploration": return <ExplorationMap />;
      case "policy":      return <PolicyArrows />;
      case "episodes":    return <EpisodeTable />;
      default:            return null;
    }
  }

  return (
    <div className="h-screen flex flex-col bg-slate-950 text-slate-200 overflow-hidden">
      {/* ── Top bar ── */}
      <div className="flex items-center gap-3 px-4 h-11 border-b border-slate-800 shrink-0">
        <button
          onClick={onBack}
          className="text-slate-500 hover:text-slate-300 text-[11px] flex items-center gap-1 transition-colors"
        >
          ← Back
        </button>
        <div className="w-px h-4 bg-slate-800" />
        <span className="text-[13px] font-semibold text-slate-200">RL Policy Designer</span>
        <div className="w-px h-4 bg-slate-800" />

        {/* Quick stats */}
        <span className="text-[10px] text-slate-500 font-mono">
          |A|={actionCount} · D={stateLabel} · ε={spec.algorithm.epsilon_start}→{spec.algorithm.epsilon_end}
        </span>
        <span className="text-[10px] text-slate-500 font-mono">
          alg={spec.algorithm.kind.toUpperCase()}
        </span>

        <div className="ml-auto flex items-center gap-2">
          {dirty && <span className="text-[9px] text-amber-500">unsaved changes</span>}
          <button
            onClick={handleSave}
            className="px-3 py-1 bg-violet-600 hover:bg-violet-500 text-white text-[11px] font-semibold rounded transition-colors"
          >
            Save RL Config
          </button>
        </div>
      </div>

      {/* ── MDP flow diagram ── */}
      <div className="px-4 py-2 border-b border-slate-800 shrink-0 bg-slate-900/50">
        <RLFlowDiagram />
      </div>

      {/* ── Main body: config (left) + dashboard (right) ── */}
      <div className="flex flex-1 min-h-0">
        {/* ── Left: MDP Config Panel ── */}
        <div className="w-80 shrink-0 border-r border-slate-800 flex flex-col overflow-hidden">
          <div className="px-3 py-2 border-b border-slate-800">
            <p className="text-[9px] font-bold uppercase tracking-widest text-slate-600">MDP Configuration</p>
          </div>
          <div className="flex-1 overflow-y-auto py-2">
            {BLOCKS.map((block) => {
              const isOpen = expandedBlock === block.id;
              const BlockComponent = BLOCK_COMPONENTS[block.id];
              return (
                <div key={block.id} className="border-b border-slate-800/60">
                  {/* Block header */}
                  <button
                    className="w-full flex items-center gap-2 px-3 py-2 hover:bg-slate-800/40 transition-colors text-left"
                    onClick={() => setExpandedBlock(isOpen ? null : block.id)}
                  >
                    <div
                      className="w-2 h-5 rounded-sm shrink-0"
                      style={{ backgroundColor: block.color }}
                    />
                    <span className="text-[11px] font-semibold text-slate-300">{block.label}</span>
                    <span className="ml-auto text-[10px] text-slate-600">{isOpen ? "▲" : "▼"}</span>
                  </button>
                  {/* Block body */}
                  {isOpen && (
                    <div className="px-3 pb-3 pt-1">
                      {block.id === "policy" ? (
                        <PolicyBlock
                          onOpenDNNDesigner={(archSpec) => {
                            if (onOpenDNNDesigner) {
                              onOpenDNNDesigner(archSpec, (saved: ArchitectureSpec) => {
                                setPolicyNetwork(saved);
                              });
                            }
                          }}
                        />
                      ) : (
                        <BlockComponent />
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* ── Right: Live Dashboard ── */}
        <div className="flex-1 flex flex-col min-h-0">
          {/* Dashboard tab bar */}
          <div className="flex border-b border-slate-800 shrink-0">
            {DASHBOARD_TABS.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id as typeof activeTab)}
                className={`px-3 py-2 text-[10px] font-semibold transition-colors whitespace-nowrap ${
                  activeTab === tab.id
                    ? "text-violet-300 border-b-2 border-violet-500 -mb-px"
                    : "text-slate-500 hover:text-slate-300"
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {/* Dashboard content */}
          <div className="flex-1 min-h-0 overflow-hidden">
            {activeTab === "config" ? (
              <div className="p-6 space-y-4 h-full overflow-auto">
                <div>
                  <p className="text-[11px] font-semibold text-slate-300 mb-1">How this works</p>
                  <p className="text-[11px] text-slate-500 leading-relaxed">
                    The RL Designer trains a <strong className="text-slate-400">Deep Q-Network</strong> to learn
                    which CDR region + mutation strategy produces better antibodies. Each loop iteration, the
                    Q-network receives protein embeddings as its <em>state</em>, selects a (CDR, strategy,
                    n_mutations) <em>action</em>, and receives docking / pLDDT scores as its <em>reward</em>.
                  </p>
                </div>
                <div>
                  <p className="text-[11px] font-semibold text-slate-300 mb-1">Wiring in your pipeline</p>
                  <ol className="text-[11px] text-slate-500 space-y-1 list-decimal list-inside">
                    <li>Connect an embedding tool (AbMAP / ESM-2) → <code className="bg-slate-800 px-1 rounded">state_embeddings</code></li>
                    <li>Wire <code className="bg-slate-800 px-1 rounded">top_cdr</code> and <code className="bg-slate-800 px-1 rounded">top_strategy</code> → CDR Mutator params</li>
                    <li>Connect evaluation scores (HADDOCK3) → picked up automatically as reward signals</li>
                    <li>Use a Loop node — the policy state is accumulated automatically across iterations</li>
                  </ol>
                </div>
                <div className="bg-slate-800/60 rounded border border-slate-700 p-3 text-[10px] text-slate-500">
                  <p className="font-semibold text-slate-400 mb-1">Dashboard tabs (will populate after first run)</p>
                  <ul className="space-y-1">
                    <li>• <span className="text-indigo-400">Q-Heatmap</span> — which CDR × strategy has the highest Q-value</li>
                    <li>• <span className="text-amber-400">Rewards</span> — per-iteration reward curve with variance band</li>
                    <li>• <span className="text-orange-400">Exploration Map</span> — t-SNE of state embeddings, coloured by visit count</li>
                    <li>• <span className="text-emerald-400">Policy Arrows</span> — per-CDR dominant strategy with probability bars</li>
                    <li>• <span className="text-slate-400">Episode History</span> — sortable table of all actions and outcomes</li>
                  </ul>
                </div>
              </div>
            ) : (
              <div className="h-full overflow-hidden">{renderDashboard()}</div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
