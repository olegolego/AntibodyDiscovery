import { useEffect, useRef, useState } from "react";
import {
  Bug, CheckCircle2, Loader2, MessageSquare, Send, Wrench, X, AlertTriangle, RotateCcw,
  type LucideIcon,
} from "lucide-react";
import {
  submitFeedback, reportRunBug, getAutofixStatus,
  type FeedbackPayload, type AutofixStatus, type AutofixPhase,
} from "@/api/reports";

type Mode = "feedback" | "run-bug";

interface FeedbackModalProps {
  mode: Mode;
  /** Required when mode === "run-bug" — the run whose context gets auto-attached. */
  runId?: string | null;
  onClose: () => void;
}

const CATEGORIES: Array<{ value: NonNullable<FeedbackPayload["category"]>; label: string }> = [
  { value: "feedback", label: "Feedback" },
  { value: "idea", label: "Idea" },
  { value: "bug", label: "Bug" },
  { value: "other", label: "Other" },
];

const EMAIL_KEY = "pdp_reporter_email";

const TERMINAL_PHASES: AutofixPhase[] = ["deployed", "no_change", "rolled_back", "error"];

const PHASE_LABEL: Record<AutofixPhase, string> = {
  pending: "Queued…",
  starting: "Preparing isolated fix branch…",
  fixing: "Claude is diagnosing & fixing the bug…",
  committing: "Recording the fix…",
  testing: "Running backend tests…",
  restarting: "Restarting backend with the fix…",
  health_check: "Health-checking the backend…",
  deployed: "Fix deployed — backend healthy ✓",
  no_change: "Claude made no code changes",
  rolling_back: "Health check failed — reverting…",
  rolled_back: "Fix reverted; backend healthy again",
  error: "Auto-fix failed",
};

function phaseTone(phase: AutofixPhase): string {
  if (phase === "deployed") return "text-emerald-300";
  if (phase === "error" || phase === "rolling_back") return "text-red-300";
  if (phase === "rolled_back" || phase === "no_change") return "text-amber-300";
  return "text-sky-300";
}

export function FeedbackModal({ mode, runId, onClose }: FeedbackModalProps) {
  const isBug = mode === "run-bug";
  const [message, setMessage] = useState("");
  const [email, setEmail] = useState(() => localStorage.getItem(EMAIL_KEY) ?? "");
  const [category, setCategory] = useState<NonNullable<FeedbackPayload["category"]>>("feedback");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState<{ saved: string; summary?: string } | null>(null);
  const [showSummary, setShowSummary] = useState(false);

  // Autonomous fix state
  const [confirmingAutofix, setConfirmingAutofix] = useState(false);
  const [autofixFile, setAutofixFile] = useState<string | null>(null);
  const [autofixStatus, setAutofixStatus] = useState<AutofixStatus | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Poll the autofix status file until a terminal phase is reached.
  useEffect(() => {
    if (!autofixFile) return;
    let stopped = false;
    const tick = async () => {
      try {
        const s = await getAutofixStatus(autofixFile);
        if (stopped) return;
        setAutofixStatus(s);
        if (TERMINAL_PHASES.includes(s.phase) && pollRef.current) {
          clearInterval(pollRef.current);
          pollRef.current = null;
        }
      } catch {
        /* transient — keep polling */
      }
    };
    tick();
    pollRef.current = setInterval(tick, 2000);
    return () => {
      stopped = true;
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = null;
    };
  }, [autofixFile]);

  async function handleSubmit(autoFix: boolean) {
    setSubmitting(true);
    setError("");
    try {
      if (email.trim()) localStorage.setItem(EMAIL_KEY, email.trim());
      if (isBug) {
        if (!runId) throw new Error("No run selected");
        const res = await reportRunBug({
          run_id: runId,
          message: message.trim() || undefined,
          email: email.trim() || undefined,
          auto_fix: autoFix,
        });
        if (autoFix) {
          if (res.autofix_error) throw new Error(res.autofix_error);
          setAutofixFile(res.saved);  // begins polling
        } else {
          setDone({ saved: res.saved, summary: res.summary });
        }
      } else {
        if (!message.trim()) throw new Error("Please describe your feedback");
        const res = await submitFeedback({
          message: message.trim(),
          email: email.trim() || undefined,
          category,
          context: { page: window.location.pathname, ua: navigator.userAgent },
        });
        setDone({ saved: res.saved });
      }
    } catch (e: unknown) {
      const anyErr = e as { response?: { data?: { detail?: string } }; message?: string };
      setError(anyErr?.response?.data?.detail ?? anyErr?.message ?? "Failed to submit");
      setConfirmingAutofix(false);
    } finally {
      setSubmitting(false);
    }
  }

  const Icon = isBug ? Bug : MessageSquare;

  // ── Autofix live view ────────────────────────────────────────────────────────
  if (autofixFile) {
    const phase = autofixStatus?.phase ?? "pending";
    const isTerminal = TERMINAL_PHASES.includes(phase);
    return (
      <Shell title="Auto-fix & Deploy" icon={Wrench} iconClass="text-red-400" onClose={onClose}>
        <div className="p-5 space-y-4">
          <div className="flex items-start gap-2.5">
            {isTerminal
              ? (phase === "deployed"
                  ? <CheckCircle2 size={18} className="text-emerald-400 mt-0.5 shrink-0" />
                  : phase === "rolled_back" || phase === "no_change"
                    ? <RotateCcw size={18} className="text-amber-400 mt-0.5 shrink-0" />
                    : <AlertTriangle size={18} className="text-red-400 mt-0.5 shrink-0" />)
              : <Loader2 size={18} className="text-sky-400 mt-0.5 shrink-0 animate-spin" />}
            <div className="min-w-0">
              <div className={`text-sm font-medium ${phaseTone(phase)}`}>{PHASE_LABEL[phase]}</div>
              {autofixStatus?.message && (
                <div className="text-xs text-slate-400 mt-1 leading-relaxed">{autofixStatus.message}</div>
              )}
            </div>
          </div>

          {autofixStatus?.branch && (
            <div className="text-[11px] text-slate-500 font-mono bg-canvas border border-border rounded-lg p-2.5 space-y-0.5">
              <div>branch: <span className="text-slate-300">{autofixStatus.branch}</span></div>
              {autofixStatus.fix_commit && (
                <div>fix: <span className="text-slate-300">{autofixStatus.fix_commit.slice(0, 10)}</span></div>
              )}
            </div>
          )}

          {!isTerminal && (
            <p className="text-[11px] text-slate-500 leading-relaxed">
              Your current work was snapshotted to the fix branch first, so a rollback never
              loses it. The backend will restart automatically — this panel keeps updating.
            </p>
          )}

          <button
            onClick={onClose}
            className="w-full py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-sm font-medium text-white transition-colors"
          >
            {isTerminal ? "Close" : "Run in background"}
          </button>
        </div>
      </Shell>
    );
  }

  // ── Success (manual report / feedback) ────────────────────────────────────────
  if (done) {
    return (
      <Shell title={isBug ? "Report Run Issue" : "Send Feedback"} icon={Icon}
        iconClass={isBug ? "text-amber-400" : "text-indigo-400"} onClose={onClose}>
        <div className="p-5 space-y-4">
          <div className="flex items-start gap-2 text-sm text-emerald-300">
            <CheckCircle2 size={16} className="mt-0.5 flex-shrink-0" />
            <span>
              {isBug
                ? "Run issue captured — Claude can now read it and fix the bug."
                : "Thanks! Your feedback was saved."}
              <span className="block text-xs text-slate-500 mt-1 font-mono">{done.saved}</span>
            </span>
          </div>
          {done.summary && (
            <div>
              <button onClick={() => setShowSummary((v) => !v)}
                className="text-xs text-slate-400 hover:text-white transition-colors">
                {showSummary ? "Hide" : "Show"} captured context
              </button>
              {showSummary && (
                <pre className="mt-2 max-h-72 overflow-auto bg-canvas border border-border rounded-lg
                  p-3 text-[11px] leading-relaxed text-slate-300 whitespace-pre-wrap">
                  {done.summary}
                </pre>
              )}
            </div>
          )}
          <button onClick={onClose}
            className="w-full py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-sm font-medium text-white transition-colors">
            Close
          </button>
        </div>
      </Shell>
    );
  }

  // ── Form ──────────────────────────────────────────────────────────────────────
  return (
    <Shell title={isBug ? "Report Run Issue" : "Send Feedback"} icon={Icon}
      iconClass={isBug ? "text-amber-400" : "text-indigo-400"} onClose={onClose}>
      <div className="p-5 space-y-4">
        {isBug && (
          <p className="text-xs text-slate-400 leading-relaxed bg-amber-950/20 border border-amber-800/30 rounded-lg p-2.5">
            The failing run's context (failed node, error, recent logs, tool params and input
            shapes) is attached automatically. Just add anything you noticed below.
          </p>
        )}

        {!isBug && (
          <div className="flex gap-1.5">
            {CATEGORIES.map((c) => (
              <button key={c.value} onClick={() => setCategory(c.value)}
                className={`flex-1 py-1.5 rounded-lg text-xs font-medium border transition-colors
                  ${category === c.value
                    ? "bg-indigo-500/15 border-indigo-500/40 text-indigo-300"
                    : "text-slate-400 bg-white/5 border-border hover:text-white"}`}>
                {c.label}
              </button>
            ))}
          </div>
        )}

        <textarea
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          placeholder={isBug
            ? "What went wrong / what did you expect? (optional)"
            : "Tell us what's on your mind…"}
          rows={isBug ? 3 : 4}
          className="w-full bg-canvas border border-border rounded-lg px-3 py-2 text-sm
            text-white placeholder-slate-600 focus:outline-none focus:border-indigo-500/60 resize-none"
        />

        <input
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="your-email@example.com (optional)"
          className="w-full bg-canvas border border-border rounded-lg px-3 py-2 text-sm
            text-white placeholder-slate-600 focus:outline-none focus:border-indigo-500/60"
        />

        {isBug && confirmingAutofix && (
          <div className="text-xs text-red-300 bg-red-950/30 border border-red-800/40 rounded-lg p-3 leading-relaxed space-y-2">
            <div className="flex items-center gap-1.5 font-semibold">
              <AlertTriangle size={13} /> Autonomous fix &amp; deploy
            </div>
            <p className="text-red-300/90">
              Claude will edit source files and restart the backend on its own. Your current work
              is snapshotted first and the fix auto-rolls-back if the backend fails to come up.
              Proceed?
            </p>
          </div>
        )}

        {error && (
          <div className="text-xs text-red-400 bg-red-950/30 border border-red-800/40 rounded-lg p-2 whitespace-pre-wrap">
            {error}
          </div>
        )}
      </div>

      <div className="flex gap-2 px-5 pb-5">
        <button onClick={onClose}
          className="flex-1 py-2 rounded-lg border border-border text-sm text-slate-400
            hover:text-white hover:border-slate-500 transition-colors">
          Cancel
        </button>

        {!isBug && (
          <button onClick={() => handleSubmit(false)} disabled={submitting || !message.trim()}
            className="flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg disabled:opacity-50
              text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-500 transition-colors">
            {submitting ? <><Loader2 size={13} className="animate-spin" /> Submitting…</>
                        : <><Send size={13} /> Send Feedback</>}
          </button>
        )}

        {isBug && !confirmingAutofix && (
          <>
            <button onClick={() => handleSubmit(false)} disabled={submitting}
              className="flex items-center justify-center gap-1.5 py-2 px-3 rounded-lg disabled:opacity-50
                text-sm font-medium text-white bg-amber-600 hover:bg-amber-500 transition-colors whitespace-nowrap"
              title="Just file the report — I'll fix it manually">
              {submitting ? <Loader2 size={13} className="animate-spin" /> : <Send size={13} />}
              Send Report
            </button>
            <button onClick={() => { setError(""); setConfirmingAutofix(true); }} disabled={submitting}
              className="flex items-center justify-center gap-1.5 py-2 px-3 rounded-lg disabled:opacity-50
                text-sm font-semibold text-white bg-red-600 hover:bg-red-500 transition-colors whitespace-nowrap"
              title="Let Claude fix the bug and redeploy automatically">
              <Wrench size={13} /> Auto-fix &amp; Deploy
            </button>
          </>
        )}

        {isBug && confirmingAutofix && (
          <>
            <button onClick={() => setConfirmingAutofix(false)} disabled={submitting}
              className="flex-1 py-2 rounded-lg border border-border text-sm text-slate-400 hover:text-white transition-colors">
              Back
            </button>
            <button onClick={() => handleSubmit(true)} disabled={submitting}
              className="flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg disabled:opacity-50
                text-sm font-semibold text-white bg-red-600 hover:bg-red-500 transition-colors">
              {submitting ? <><Loader2 size={13} className="animate-spin" /> Starting…</>
                          : <><Wrench size={13} /> Confirm &amp; Deploy</>}
            </button>
          </>
        )}
      </div>
    </Shell>
  );
}

// ── Shared modal shell ──────────────────────────────────────────────────────────

function Shell({ title, icon: Icon, iconClass, onClose, children }: {
  title: string;
  icon: LucideIcon;
  iconClass: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50">
      <div className="bg-[#13151f] border border-border rounded-xl w-[30rem] max-w-[92vw] shadow-2xl">
        <div className="flex items-center justify-between px-5 py-4 border-b border-border">
          <span className="font-semibold text-white flex items-center gap-2">
            <Icon size={15} className={iconClass} />
            {title}
          </span>
          <button onClick={onClose} className="text-slate-500 hover:text-white transition-colors">
            <X size={16} />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
