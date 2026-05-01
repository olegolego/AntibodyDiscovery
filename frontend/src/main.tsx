import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import "./index.css";

class ErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { error: Error | null }
> {
  state = { error: null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  render() {
    if (this.state.error) {
      const err = this.state.error as Error;
      return (
        <div style={{
          color: "#f00", background: "#fff", padding: 24,
          position: "fixed", inset: 0, zIndex: 9999,
          overflow: "auto", fontFamily: "monospace",
        }}>
          <h1 style={{ fontSize: 20, marginBottom: 12 }}>React render error</h1>
          <pre style={{ whiteSpace: "pre-wrap", marginBottom: 12 }}>{String(err)}</pre>
          <pre style={{ whiteSpace: "pre-wrap", color: "#666" }}>{err.stack}</pre>
        </div>
      );
    }
    return this.props.children;
  }
}

window.addEventListener("error", (e) => {
  document.body.innerHTML = `<div style="color:red;background:white;padding:24px;font-family:monospace;position:fixed;inset:0;z-index:9999;overflow:auto"><h1>Global JS Error</h1><pre>${e.message}\n\n${e.error?.stack ?? ""}</pre></div>`;
});

window.addEventListener("unhandledrejection", (e) => {
  document.body.innerHTML = `<div style="color:red;background:white;padding:24px;font-family:monospace;position:fixed;inset:0;z-index:9999;overflow:auto"><h1>Unhandled Promise Rejection</h1><pre>${e.reason}</pre></div>`;
});

const queryClient = new QueryClient();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>
    </ErrorBoundary>
  </React.StrictMode>
);
