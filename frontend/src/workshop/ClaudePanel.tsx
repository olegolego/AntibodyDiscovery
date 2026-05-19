import { useRef, useState } from "react";
import { Sparkles, Loader2, Check } from "lucide-react";
import { workshopApi, type CustomTool } from "../api/workshop";

interface Message {
  role: "user" | "assistant";
  text: string;
  code?: string;
}

interface ClaudePanelProps {
  tool: CustomTool;
  lastError: string;
  onApply: (code: string) => void;
}

export function ClaudePanel({ tool, lastError, onApply }: ClaudePanelProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [prompt, setPrompt] = useState("");
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  async function handleSend(overridePrompt?: string) {
    const text = (overridePrompt ?? prompt).trim();
    if (!text || loading) return;

    setMessages((prev) => [...prev, { role: "user", text }]);
    setPrompt("");
    setLoading(true);

    try {
      const { code } = await workshopApi.claudeHelp(tool.id, text, tool.run_py);
      setMessages((prev) => [...prev, { role: "assistant", text: "Here's the updated code:", code }]);
    } catch (e: unknown) {
      const errText = e instanceof Error ? e.message : String(e);
      setMessages((prev) => [...prev, { role: "assistant", text: `Error: ${errText}` }]);
    } finally {
      setLoading(false);
      setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: "smooth" }), 30);
    }
  }

  function handleApply(code: string) {
    onApply(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  return (
    <div className="flex flex-col h-full">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-3 space-y-3 text-xs">
        {messages.length === 0 && (
          <p className="text-slate-600 text-center py-4 leading-relaxed">
            Ask Claude to generate, fix, or improve your tool code.
          </p>
        )}

        {/* Quick actions */}
        {messages.length === 0 && (
          <div className="flex flex-col gap-1.5">
            <button
              onClick={() => handleSend("Review this code and fix any bugs or edge cases.")}
              className="text-left px-2 py-1.5 rounded-lg border border-border text-slate-400
                hover:text-white hover:border-slate-500 transition-colors text-xs"
            >
              Review & fix bugs
            </button>
            {lastError && (
              <button
                onClick={() =>
                  handleSend(`Fix this error:\n${lastError}`)
                }
                className="text-left px-2 py-1.5 rounded-lg border border-red-800/40
                  text-red-400 hover:text-red-300 transition-colors text-xs"
              >
                Fix last error
              </button>
            )}
            <button
              onClick={() =>
                handleSend(
                  "Add proper error handling, input validation, and type hints to this code."
                )
              }
              className="text-left px-2 py-1.5 rounded-lg border border-border text-slate-400
                hover:text-white hover:border-slate-500 transition-colors text-xs"
            >
              Improve robustness
            </button>
          </div>
        )}

        {messages.map((m, i) => (
          <div key={i} className={m.role === "user" ? "text-right" : "text-left"}>
            <div
              className={`inline-block max-w-full rounded-lg px-2.5 py-1.5 text-xs
                ${m.role === "user"
                  ? "bg-indigo-600/30 text-indigo-200"
                  : "bg-white/5 text-slate-300"
                }`}
            >
              {m.text}
            </div>
            {m.code && (
              <div className="mt-1.5">
                <pre className="bg-[#1e2030] border border-border rounded-lg p-2
                  text-[11px] font-mono text-slate-300 overflow-x-auto whitespace-pre-wrap
                  max-h-48 overflow-y-auto">
                  {m.code}
                </pre>
                <button
                  onClick={() => handleApply(m.code!)}
                  className="mt-1 flex items-center gap-1 text-xs text-emerald-400
                    hover:text-emerald-300 transition-colors"
                >
                  {copied ? <><Check size={11} /> Applied</> : "↑ Apply to editor"}
                </button>
              </div>
            )}
          </div>
        ))}

        {loading && (
          <div className="flex items-center gap-2 text-slate-500">
            <Loader2 size={12} className="animate-spin" />
            <span>Thinking…</span>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="border-t border-border p-2 flex-shrink-0">
        <div className="flex gap-1.5">
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
            placeholder="Ask Claude anything… (Enter to send)"
            rows={2}
            className="flex-1 bg-[#1e2030] border border-border rounded-lg px-2 py-1.5
              text-xs text-white placeholder-slate-600 resize-none focus:outline-none
              focus:border-indigo-500 transition-colors"
          />
          <button
            onClick={() => handleSend()}
            disabled={loading || !prompt.trim()}
            className="px-2 py-1 rounded-lg bg-indigo-600 hover:bg-indigo-500
              disabled:opacity-40 text-white transition-colors flex-shrink-0"
          >
            <Sparkles size={13} />
          </button>
        </div>
      </div>
    </div>
  );
}
