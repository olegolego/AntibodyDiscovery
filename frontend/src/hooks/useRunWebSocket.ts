import { useEffect, useRef } from "react";
import type { Run } from "@/types";

export function useRunWebSocket(
  runId: string | null,
  onUpdate: (run: Run) => void
) {
  const onUpdateRef = useRef(onUpdate);
  onUpdateRef.current = onUpdate;

  useEffect(() => {
    if (!runId) return;

    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const url = `${proto}//${window.location.host}/ws/runs/${runId}`;
    let ws: WebSocket;
    let closed = false;
    let retryTimeout: ReturnType<typeof setTimeout>;

    function connect() {
      ws = new WebSocket(url);

      ws.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data);
          if (msg.type === "run_update") onUpdateRef.current(msg.run as Run);
        } catch {}
      };

      ws.onclose = () => {
        if (closed) return;
        // Reconnect after 2s unless run is in a terminal state
        retryTimeout = setTimeout(connect, 2000);
      };
    }

    connect();

    return () => {
      closed = true;
      clearTimeout(retryTimeout);
      ws?.close();
    };
  }, [runId]);
}
