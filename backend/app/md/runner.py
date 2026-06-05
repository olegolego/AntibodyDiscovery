"""Simulation lifecycle: runs the numpy step loop off the event loop in batches,
decimates frames, and broadcasts them over the WebSocket manager keyed by sim_id.

The loop runs via ``run_in_executor`` in small batches so that cancellation and
socket I/O stay responsive even for long runs. Frames are decimated twice:
  1. ``frame_stride`` — only every Nth step is a candidate frame.
  2. ``max_fps`` — a wall-clock cap so a fast CPU can't flood the socket.
"""
from __future__ import annotations

import asyncio
import logging
import time

from app.core.events import manager

from .engine import Simulation, SimulationError
from .spec import SystemSpec

log = logging.getLogger(__name__)

# Cancellation: sim_ids signalled to stop. Checked between batches.
_cancelled_sims: set[str] = set()

# How many integration steps to run per executor hand-off. Small enough to stay
# responsive, large enough to amortise the thread round-trip.
_BATCH = 25


def request_cancel(sim_id: str) -> None:
    _cancelled_sims.add(sim_id)


def _make_summary(sim: Simulation, wall_seconds: float) -> dict:
    final = sim.energy_dict()
    e0 = sim.initial_energy
    drift = abs(final["total"] - e0) / abs(e0) if abs(e0) > 1e-12 else 0.0
    return {
        "steps_run": sim.step_index,
        "final_energy": final,
        "energy_drift": drift,
        "wall_seconds": wall_seconds,
    }


async def run_simulation(sim_id: str, spec: SystemSpec) -> dict:
    """Build, run and stream a simulation. Returns the summary dict.

    Broadcasts (via ``manager``):
      init   — particle metadata, total steps
      frame  — step, time, flat positions, energy
      done   — summary
      error  — message + step
      cancelled
    """
    _cancelled_sims.discard(sim_id)
    loop = asyncio.get_event_loop()

    try:
        sim = await loop.run_in_executor(None, Simulation, spec)
    except Exception as exc:  # noqa: BLE001 — surface setup errors to the client
        await manager.broadcast(sim_id, {"type": "error", "message": str(exc), "step": 0})
        raise

    await manager.broadcast(sim_id, {
        "type": "init",
        "n_particles": spec.n_particles,
        "particle_types": [t.model_dump() for t in sim.types],
        "type_index": sim.type_index.tolist(),
        "box": spec.box.model_dump(),
        "total_steps": spec.steps,
    })

    stride = max(1, spec.stream.frame_stride)
    min_frame_dt = 1.0 / spec.stream.max_fps if spec.stream.max_fps > 0 else 0.0
    start = time.monotonic()
    last_emit = 0.0

    # Emit the initial frame so the viewer has something before any stepping.
    await manager.broadcast(sim_id, {
        "type": "frame", "step": 0, "time": 0.0,
        "positions": sim.flat_positions(), "energy": sim.energy_dict(),
    })

    try:
        while sim.step_index < spec.steps:
            if sim_id in _cancelled_sims:
                _cancelled_sims.discard(sim_id)
                await manager.broadcast(sim_id, {"type": "cancelled"})
                return _make_summary(sim, time.monotonic() - start)

            remaining = spec.steps - sim.step_index
            batch = min(_BATCH, remaining)

            def _run_batch(s=sim, k=batch):
                for _ in range(k):
                    s.step()

            await loop.run_in_executor(None, _run_batch)

            # Frame decimation: stride gate + wall-clock fps cap.
            if sim.step_index % stride == 0 or sim.step_index >= spec.steps:
                now = time.monotonic()
                if now - last_emit >= min_frame_dt or sim.step_index >= spec.steps:
                    last_emit = now
                    await manager.broadcast(sim_id, {
                        "type": "frame",
                        "step": sim.step_index,
                        "time": sim.time,
                        "positions": sim.flat_positions(),
                        "energy": sim.energy_dict(),
                    })
            # Yield to the event loop so sockets/cancel stay responsive.
            await asyncio.sleep(0)

    except SimulationError as exc:
        await manager.broadcast(sim_id, {
            "type": "error", "message": str(exc), "step": sim.step_index,
        })
        return _make_summary(sim, time.monotonic() - start)
    except Exception as exc:  # noqa: BLE001
        log.exception("MD sim %s crashed", sim_id)
        await manager.broadcast(sim_id, {
            "type": "error", "message": f"Internal error: {exc}", "step": sim.step_index,
        })
        return _make_summary(sim, time.monotonic() - start)

    summary = _make_summary(sim, time.monotonic() - start)
    await manager.broadcast(sim_id, {"type": "done", "summary": summary})
    return summary
