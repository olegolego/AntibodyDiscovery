import { useEffect, useRef } from "react";
import { useMDStore } from "./store";
import type { Energy, InitMessage, Summary, SystemSpec } from "./types";

// Opens a persistent WebSocket to /ws/md-ground/{simId} and wires incoming
// frames into the store. Returns imperative start()/cancel() controls.
export function useMDSocket(simId: string) {
  const wsRef = useRef<WebSocket | null>(null);
  const openRef = useRef(false);
  const pendingSpec = useRef<SystemSpec | null>(null);

  const applyInit = useMDStore((s) => s.applyInit);
  const pushFrame = useMDStore((s) => s.pushFrame);
  const setStatus = useMDStore((s) => s.setStatus);
  const setSummary = useMDStore((s) => s.setSummary);

  useEffect(() => {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const url = `${proto}//${window.location.host}/ws/md-ground/${simId}`;
    let closed = false;
    let retry: ReturnType<typeof setTimeout>;

    function connect() {
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        openRef.current = true;
        // If a run was requested before the socket opened, flush it now.
        if (pendingSpec.current) {
          ws.send(JSON.stringify({ type: "start", spec: pendingSpec.current }));
          pendingSpec.current = null;
        }
      };

      ws.onmessage = (e) => {
        let msg: Record<string, unknown>;
        try {
          msg = JSON.parse(e.data);
        } catch {
          return;
        }
        switch (msg.type) {
          case "init":
            setStatus("running");
            applyInit(msg as unknown as InitMessage);
            break;
          case "frame":
            pushFrame(
              msg.step as number,
              msg.time as number,
              msg.positions as number[],
              msg.energy as Energy
            );
            break;
          case "done":
            setStatus("done");
            setSummary(msg.summary as Summary);
            break;
          case "error":
            setStatus("error", String(msg.message ?? "Simulation error"));
            break;
          case "cancelled":
            setStatus("cancelled");
            break;
        }
      };

      ws.onclose = () => {
        openRef.current = false;
        if (closed) return;
        retry = setTimeout(connect, 500);
      };
    }

    connect();
    return () => {
      closed = true;
      clearTimeout(retry);
      wsRef.current?.close();
    };
  }, [simId, applyInit, pushFrame, setStatus, setSummary]);

  function start(spec: SystemSpec) {
    setStatus("connecting");
    const ws = wsRef.current;
    if (ws && openRef.current && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "start", spec }));
    } else {
      pendingSpec.current = spec; // flushed on open
    }
  }

  function cancel() {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "cancel" }));
    }
  }

  return { start, cancel };
}
