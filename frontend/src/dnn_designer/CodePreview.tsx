import { useState } from "react";
import { ChevronDown, ChevronUp, Copy, Check } from "lucide-react";
import CodeMirror from "@uiw/react-codemirror";
import { python } from "@codemirror/lang-python";
import { oneDark } from "@codemirror/theme-one-dark";

interface CodePreviewProps {
  code: string;
}

export function CodePreview({ code }: CodePreviewProps) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  function handleCopy() {
    navigator.clipboard.writeText(code).catch(() => {});
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  return (
    <div
      className="border-t border-border bg-surface shrink-0 flex flex-col"
      style={{ height: open ? 220 : 36 }}
    >
      {/* Toggle bar */}
      <div className="flex items-center justify-between px-3 h-9 shrink-0">
        <button
          onClick={() => setOpen((v) => !v)}
          className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-white transition-colors"
        >
          {open ? <ChevronDown size={13} /> : <ChevronUp size={13} />}
          <span className="font-mono">PyTorch Code</span>
          <span className="text-[10px] text-slate-600 ml-1">
            {code.split("\n").length} lines
          </span>
        </button>
        <button
          onClick={handleCopy}
          className="flex items-center gap-1 text-[10px] text-slate-500 hover:text-white
            transition-colors px-2 py-1 rounded hover:bg-white/5"
        >
          {copied ? <Check size={12} className="text-emerald-400" /> : <Copy size={12} />}
          {copied ? "Copied!" : "Copy"}
        </button>
      </div>

      {/* Code editor (read-only) */}
      {open && (
        <div className="flex-1 overflow-hidden">
          <CodeMirror
            value={code}
            height="180px"
            theme={oneDark}
            extensions={[python()]}
            editable={false}
            basicSetup={{ lineNumbers: true, foldGutter: false, highlightActiveLine: false }}
            style={{ fontSize: 11, height: "100%" }}
          />
        </div>
      )}
    </div>
  );
}
