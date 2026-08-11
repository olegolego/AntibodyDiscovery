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

    min_steps = max(0, spec.minimize_steps)
    eq_steps = max(0, spec.equilibrate_steps)
    total_steps = min_steps + eq_steps + spec.steps

    await manager.broadcast(sim_id, {
        "type": "init",
        "n_particles": spec.n_particles,
        "particle_types": [t.model_dump() for t in sim.types],
        "type_index": sim.type_index.tolist(),
        "box": spec.box.model_dump(),
        "total_steps": total_steps,
        "phases": {"minimize": min_steps, "equilibrate": eq_steps, "production": spec.steps},
    })

    stride = max(1, spec.stream.frame_stride)
    min_frame_dt = 1.0 / spec.stream.max_fps if spec.stream.max_fps > 0 else 0.0
    start = time.monotonic()
    ctr = {"gstep": 0, "last_emit": 0.0}

    async def _emit(phase: str, force: bool = False) -> None:
        now = time.monotonic()
        if force or (ctr["gstep"] % stride == 0 and now - ctr["last_emit"] >= min_frame_dt):
            ctr["last_emit"] = now
            await manager.broadcast(sim_id, {
                "type": "frame", "phase": phase,
                "step": ctr["gstep"], "time": sim.time,
                "positions": sim.flat_positions(), "energy": sim.energy_dict(),
            })

    async def _run_phase(phase: str, n: int, step_fn) -> bool:
        """Run n steps of step_fn in batches, emitting frames. Returns False if
        cancelled (caller should stop)."""
        done = 0
        while done < n:
            if sim_id in _cancelled_sims:
                _cancelled_sims.discard(sim_id)
                await manager.broadcast(sim_id, {"type": "cancelled"})
                return False
            batch = min(_BATCH, n - done)

            def _run_batch(k=batch, fn=step_fn):
                for _ in range(k):
                    fn()

            await loop.run_in_executor(None, _run_batch)
            done += batch
            ctr["gstep"] += batch
            await _emit(phase)
            await asyncio.sleep(0)
        return True

    await _emit("minimize" if min_steps else ("equilibrate" if eq_steps else "production"), force=True)

    try:
        # ── Phase 1: energy minimisation (steepest descent) ──
        if min_steps:
            sim.setup_minimize()
            if not await _run_phase("minimize", min_steps, sim.minimize_step):
                return _make_summary(sim, time.monotonic() - start)
            # Fresh velocities for the dynamics phases after minimisation.
            sim.reset_velocities(spec.target_temperature or spec.temperature)
            sim.forces, sim.potential = sim._compute_forces()
            sim.initial_energy = sim.total_energy()

        # ── Phase 2: equilibration (force a Berendsen thermostat at target T) ──
        if eq_steps:
            saved_thermo = spec.thermostat
            spec.thermostat = "berendsen" if saved_thermo == "none" else saved_thermo
            try:
                ok = await _run_phase("equilibrate", eq_steps, sim.step)
            finally:
                spec.thermostat = saved_thermo
            if not ok:
                return _make_summary(sim, time.monotonic() - start)
            sim.initial_energy = sim.total_energy()  # drift measured over production

        # ── Phase 3: production ──
        if not await _run_phase("production", spec.steps, sim.step):
            return _make_summary(sim, time.monotonic() - start)
        await _emit("production", force=True)

    except SimulationError as exc:
        await manager.broadcast(sim_id, {"type": "error", "message": str(exc), "step": ctr["gstep"]})
        return _make_summary(sim, time.monotonic() - start)
    except Exception as exc:  # noqa: BLE001
        log.exception("MD sim %s crashed", sim_id)
        await manager.broadcast(sim_id, {"type": "error", "message": f"Internal error: {exc}", "step": ctr["gstep"]})
        return _make_summary(sim, time.monotonic() - start)

    summary = _make_summary(sim, time.monotonic() - start)
    # Ship the full final state so the client can persist it and resume later.
    await manager.broadcast(sim_id, {
        "type": "done", "summary": summary, "checkpoint": sim.checkpoint(),
    })
    return summary
