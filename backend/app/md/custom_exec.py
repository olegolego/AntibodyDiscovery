"""In-process execution of a user-authored Python force function.

The user defines a function::

    def force(pos, type_index, box, params):
        # pos: (N,3) float array, type_index: (N,) int array
        # return (forces (N,3), potential_energy float)
        ...

This is NOT sandboxed — same trust model as the Compute node. The UI warns the
user. We guard against the common failure modes: compile errors, exceptions per
step, and NaN / runaway forces. For stronger isolation a future version can run
the whole loop in the tool venv via subprocess_runner.
"""
from __future__ import annotations

from typing import Callable

import numpy as np


class CustomForceError(ValueError):
    pass


def compile_custom_force(code: str) -> Callable:
    """Exec user code, extract `force`, and return a guarded pairwise callable.

    The returned callable matches the engine's pairwise signature
    ``f(pos, type_index, types, box, pairs, term)`` and adapts it to the simpler
    user signature ``force(pos, type_index, box, params)``.
    """
    if not code or not code.strip():
        raise CustomForceError("No code provided")

    import math
    import scipy  # noqa: F401 — available to user code

    namespace: dict = {"np": np, "numpy": np, "math": math, "scipy": scipy}
    try:
        exec(compile(code, "<md-custom-force>", "exec"), namespace)  # noqa: S102
    except Exception as exc:  # noqa: BLE001
        raise CustomForceError(f"Compile/exec error: {exc}") from exc

    user_force = namespace.get("force")
    if not callable(user_force):
        raise CustomForceError("Code must define a callable named `force`")

    def force(pos, type_index, types, box, pairs, term):
        params = {}
        try:
            out = user_force(pos, type_index, box, params)
        except Exception as exc:  # noqa: BLE001
            raise CustomForceError(f"force() raised: {exc}") from exc
        if not isinstance(out, (tuple, list)) or len(out) != 2:
            raise CustomForceError("force() must return (forces, potential_energy)")
        forces, pe = out
        forces = np.asarray(forces, dtype=np.float64)
        if forces.shape != pos.shape:
            raise CustomForceError(
                f"force() returned shape {forces.shape}, expected {pos.shape}"
            )
        if not np.all(np.isfinite(forces)):
            raise CustomForceError("force() produced non-finite values")
        return forces, float(pe)

    return force


def smoke_test(code: str, n: int = 8) -> dict:
    """Validate a custom force by running it once on random positions."""
    f = compile_custom_force(code)
    rng = np.random.default_rng(0)
    pos = rng.standard_normal((n, 3))
    type_index = np.zeros(n, dtype=np.int64)
    from .spec import Box
    forces, pe = f(pos, type_index, [], Box(), np.empty((0, 2), dtype=np.int64), None)
    return {"valid": True, "force_shape": list(forces.shape), "potential_energy": pe}
