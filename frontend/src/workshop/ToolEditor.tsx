import { useCallback, useRef, useState } from "react";
import CodeMirror from "@uiw/react-codemirror";
import { python } from "@codemirror/lang-python";
import { oneDark } from "@codemirror/theme-one-dark";
import { workshopApi, type CustomTool } from "../api/workshop";

type FileTab = "run.py" | "tool.yaml";

interface ToolEditorProps {
  tool: CustomTool;
  onChange: (updated: CustomTool) => void;
}

export function ToolEditor({ tool, onChange }: ToolEditorProps) {
  const [tab, setTab] = useState<FileTab>("run.py");
  const [saving, setSaving] = useState(false);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const scheduleAutoSave = useCallback(
    (patch: Partial<Pick<CustomTool, "tool_yaml" | "run_py">>) => {
      if (saveTimer.current) clearTimeout(saveTimer.current);
      saveTimer.current = setTimeout(async () => {
        setSaving(true);
        try {
          const updated = await workshopApi.updateTool(tool.id, patch);
          onChange(updated);
        } finally {
          setSaving(false);
        }
      }, 800);
    },
    [tool.id, onChange]
  );

  function handleCodeChange(value: string) {
    if (tab === "run.py") {
      onChange({ ...tool, run_py: value });
      scheduleAutoSave({ run_py: value });
    } else {
      onChange({ ...tool, tool_yaml: value });
      scheduleAutoSave({ tool_yaml: value });
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* File tabs + save indicator */}
      <div className="flex items-center gap-1 px-2 pt-1 border-b border-border flex-shrink-0">
        {(["run.py", "tool.yaml"] as FileTab[]).map((f) => (
          <button
            key={f}
            onClick={() => setTab(f)}
            className={`px-3 py-1.5 text-xs rounded-t transition-colors
              ${tab === f
                ? "bg-[#1e2030] text-white border border-b-0 border-border"
                : "text-slate-500 hover:text-slate-300"
              }`}
          >
            {f}
          </button>
        ))}
        <div className="flex-1" />
        {saving && (
          <span className="text-[10px] text-slate-600 pr-2">saving…</span>
        )}
      </div>

      {/* Editor */}
      <div className="flex-1 overflow-auto">
        <CodeMirror
          value={tab === "run.py" ? tool.run_py : tool.tool_yaml}
          height="100%"
          extensions={tab === "run.py" ? [python()] : []}
          theme={oneDark}
          onChange={handleCodeChange}
          style={{ fontSize: 13, height: "100%" }}
          basicSetup={{
            lineNumbers: true,
            foldGutter: true,
            autocompletion: true,
            indentOnInput: true,
          }}
        />
      </div>
    </div>
  );
}
