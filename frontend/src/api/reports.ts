import { api } from "./client";

export interface FeedbackPayload {
  message: string;
  email?: string;
  category?: "feedback" | "idea" | "bug" | "other";
  context?: Record<string, unknown>;
}

export async function submitFeedback(payload: FeedbackPayload): Promise<{ saved: string }> {
  const { data } = await api.post<{ saved: string }>("/reports/feedback", payload);
  return data;
}

export interface RunBugPayload {
  run_id: string;
  message?: string;
  email?: string;
  auto_fix?: boolean;
}

export interface RunBugResult {
  saved: string;
  summary: string;
  autofix_started: boolean;
  autofix_error: string | null;
}

export async function reportRunBug(payload: RunBugPayload): Promise<RunBugResult> {
  const { data } = await api.post<RunBugResult>("/reports/run-bug", payload);
  return data;
}

export type AutofixPhase =
  | "pending" | "starting" | "fixing" | "committing" | "testing"
  | "restarting" | "health_check" | "deployed" | "no_change"
  | "rolling_back" | "rolled_back" | "error";

export interface AutofixStatus {
  phase: AutofixPhase;
  message?: string;
  branch?: string;
  base_commit?: string;
  snapshot_commit?: string;
  fix_commit?: string;
  log_file?: string;
  updated_at?: string;
}

export async function getAutofixStatus(reportFile: string): Promise<AutofixStatus> {
  const { data } = await api.get<AutofixStatus>(`/reports/autofix/${encodeURIComponent(reportFile)}`);
  return data;
}
