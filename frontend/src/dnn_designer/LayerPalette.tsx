import { useCallback } from "react";
import { LAYER_DEFS, CATEGORY_LABELS, CATEGORY_ORDER } from "./layers";
import type { LayerDef } from "./layers";

interface LayerPaletteProps {
  onDragStart?: (e: React.DragEvent, layerType: string) => void;
}

function PaletteItem({ def, onDragStart }: {
  def: LayerDef;
  onDragStart: (e: React.DragEvent, type: string) => void;
}) {
  return (
    <div
      draggable
      onDragStart={(e) => onDragStart(e, def.type)}
      className="flex items-center gap-2 px-3 py-[5px] cursor-grab active:cursor-grabbing
        hover:bg-white/[0.04] transition-colors group"
      title={`Drag to add ${def.label}`}
    >
      {/* Tiny left accent bar matching node style */}
      <span
        className="w-[2px] h-3 rounded-full shrink-0"
        style={{ background: def.color }}
      />
      <span className="text-[11px] text-slate-400 group-hover:text-slate-200 transition-colors truncate">
        {def.label}
      </span>
    </div>
  );
}

export function LayerPalette({ onDragStart }: LayerPaletteProps) {
  const handleDragStart = useCallback((e: React.DragEvent, layerType: string) => {
    e.dataTransfer.setData("application/dnn-layer-type", layerType);
    e.dataTransfer.effectAllowed = "copy";
    if (onDragStart) onDragStart(e, layerType);
  }, [onDragStart]);

  const grouped = CATEGORY_ORDER.map((cat) => ({
    cat,
    label: CATEGORY_LABELS[cat],
    items: LAYER_DEFS.filter((d) => d.category === cat && d.type !== "UpstreamInput"),
  })).filter((g) => g.items.length > 0);

  return (
    <div
      className="w-44 shrink-0 border-r flex flex-col overflow-hidden"
      style={{ background: "#080b10", borderColor: "#141b25" }}
    >
      {/* Header */}
      <div
        className="px-3 py-2 border-b"
        style={{ borderColor: "#141b25" }}
      >
        <span className="text-[9px] font-bold uppercase tracking-widest text-slate-600">
          Layers
        </span>
      </div>

      {/* Layer list */}
      <div className="flex-1 overflow-y-auto py-1">
        {grouped.map(({ cat, label, items }) => (
          <div key={cat} className="mb-1">
            {/* Category divider */}
            <div className="flex items-center gap-2 px-3 py-1">
              <span className="text-[8px] font-bold uppercase tracking-widest text-slate-700">
                {label}
              </span>
            </div>
            {items.map((def) => (
              <PaletteItem key={def.type} def={def} onDragStart={handleDragStart} />
            ))}
          </div>
        ))}
      </div>

      {/* Footer hint */}
      <div
        className="px-3 py-2 border-t"
        style={{ borderColor: "#141b25" }}
      >
        <p className="text-[9px] text-slate-700 leading-relaxed">
          Drag onto canvas · connect top→bottom
        </p>
      </div>
    </div>
  );
}
