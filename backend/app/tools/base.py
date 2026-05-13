import logging
import os
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from app.models.run import NodeRun
from app.models.tool_spec import ToolSpec

_LOG_DIR = Path(os.getenv("PDP_RUN_LOG_DIR", "/tmp/pdp-runs"))
_LOG_DIR.mkdir(parents=True, exist_ok=True)

_file_log = logging.getLogger("pdp.runlog")


def _write_run_log(run_id: str, node_id: str, message: str) -> None:
    try:
        with open(_LOG_DIR / f"{run_id}.log", "a") as f:
            f.write(f"[{node_id}] {message}\n")
    except Exception:
        pass


_ALOG_MIN_INTERVAL = 0.15  # max ~7 WS broadcasts/sec per node under rapid log output


class RunContext:
    def __init__(self, run_id: str, node_id: str, node_run: NodeRun) -> None:
        self.run_id = run_id
        self.node_id = node_id
        self.node_run = node_run
        self._emit_fn: Callable[[], Awaitable[None]] | None = None
        self._last_emit: float = 0.0

    def log(self, message: str) -> None:
        self.node_run.logs.append(message)
        _write_run_log(self.run_id, self.node_id, message)

    async def alog(self, message: str) -> None:
        """Append a log line and broadcast a WS update, rate-limited to avoid flooding.

        The executor always calls _emit() directly on node success/failure, so the
        final log lines are never lost even if this call is throttled.
        """
        self.node_run.logs.append(message)
        _write_run_log(self.run_id, self.node_id, message)
        if self._emit_fn is None:
            return
        now = time.monotonic()
        if now - self._last_emit >= _ALOG_MIN_INTERVAL:
            self._last_emit = now
            await self._emit_fn()


@runtime_checkable
class ToolAdapter(Protocol):
    spec: ToolSpec

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]: ...
