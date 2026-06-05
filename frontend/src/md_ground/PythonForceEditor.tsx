import { useState } from "react";
import CodeMirror from "@uiw/react-codemirror";
import { python } from "@codemirror/lang-python";
import { oneDark } from "@codemirror/theme-one-dark";
import { AlertTriangle, CheckCircle2, Loader2, Sparkles } from "lucide-react";
import { codegen, validatePython } from "./api";

interface Props {
  value: string;
  onChange: (code: string) => void;
}

const TEMPLATE = `def force(pos, type_index, box, params):
    # pos: (N,3) positions, type_index: (N,) species
    # return (forces (N,3), potential_energy float)
    import numpy as np
    n = pos.shape[0]
    forces = np.zeros_like(pos)
    pe = 0.0
    return forces, pe
`;

// In-process Python force editor with AI codegen + a one-shot validation smoke
// test. NOT sandboxed — same trust model as the Compute node (warning shown).
export function PythonForceEditor({ value, onChange }: Props) {
  const [prompt, setPrompt] = useState("");
  const [gen, setGen] = useState(false);
  const [validating, setValidating] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; msg: string } | null>(null);

  async function generate() {
    if (!prompt.trim()) return;
    setGen(true);
    setResult(null);
    try {
      const code = await codegen(prompt);
      onChange(code);
    } catch (e) {
      setResult({ ok: false, msg: String((e as Error).message) });
    } finally {
      setGen(false);
    }
  }

  async function validate() {
    setValidating(true);
    setResult(null);
    try {
      const out = await validatePython(value);
      setResult({ ok: true, msg: `OK — force shape ${out.force_shape.join("×")}, PE=${out.potential_energy.toFixed(3)}` });
    } catch (e) {
      setResult({ ok: false, msg: String((e as Error).message) });
    } finally {
      setValidating(false);
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex items-start gap-2 text-[11px] text-amber-300/90 bg-amber-500/10 border border-amber-500/20 rounded-md px-2 py-1.5">
        <AlertTriangle size={13} className="shrink-0 mt-0.5" />
        <span>Custom Python runs in-process, unsandboxed. Only run code you trust.</span>
      </div>

      <div className="flex gap-1.5">
        <input
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && generate()}
          placeholder="Describe a force law (e.g. soft repulsive Gaussian)…"
          className="flex-1 bg-canvas border border-border rounded-md px-2 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-indigo-500/60"
        />
        <button
          onClick={generate}
          disabled={gen || !prompt.trim()}
          className="flex items-center gap-1 px-2.5 py-1.5 rounded-md text-xs font-medium text-white bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-500 hover:to-purple-500 disabled:opacity-40"
        >
          {gen ? <Loader2 size={12} className="animate-spin" /> : <Sparkles size={12} />}
          AI
        </button>
      </div>

      <CodeMirror
        value={value || TEMPLATE}
        height="220px"
        extensions={[python()]}
        theme={oneDark}
        onChange={onChange}
        basicSetup={{ lineNumbers: true, foldGutter: false }}
      />

      <div className="flex items-center gap-2">
        <button
          onClick={validate}
          disabled={validating}
          className="px-2.5 py-1 rounded-md text-xs font-medium text-slate-200 border border-border hover:bg-white/5 disabled:opacity-40"
        >
          {validating ? "Validating…" : "Validate"}
        </button>
        {result && (
          <span className={`flex items-center gap-1 text-[11px] ${result.ok ? "text-emerald-400" : "text-red-400"}`}>
            {result.ok ? <CheckCircle2 size={12} /> : <AlertTriangle size={12} />}
            {result.msg}
          </span>
        )}
      </div>
    </div>
  );
}
