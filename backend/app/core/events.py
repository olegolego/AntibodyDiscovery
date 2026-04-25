"""WebSocket connection manager. One channel per run_id."""
from collections import defaultdict

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[str, list[WebSocket]] = defaultdict(list)

    async def connect(self, run_id: str, ws: WebSocket) -> None:
        await ws.accept()
        self._connections[run_id].append(ws)

    def disconnect(self, run_id: str, ws: WebSocket) -> None:
        try:
            self._connections[run_id].remove(ws)
        except ValueError:
            pass

    async def broadcast(self, run_id: str, payload: dict) -> None:
        dead: list[WebSocket] = []
        for ws in list(self._connections.get(run_id, [])):
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(run_id, ws)


manager = ConnectionManager()
