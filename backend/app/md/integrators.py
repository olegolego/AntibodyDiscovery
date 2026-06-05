"""Time integration, velocity initialisation and thermostats.

Reduced units throughout (kB = 1). Degrees of freedom are 3N - 3 because the
centre-of-mass drift is removed at initialisation.
"""
from __future__ import annotations

import numpy as np


def maxwell_boltzmann(masses: np.ndarray, temperature: float, rng: np.random.Generator) -> np.ndarray:
    """Draw velocities from Maxwell-Boltzmann, remove COM drift, rescale to T.

    Returns an (N, 3) velocity array whose instantaneous temperature equals
    ``temperature`` exactly (modulo the dof correction).
    """
    n = masses.shape[0]
    if temperature <= 0.0 or n == 0:
        return np.zeros((n, 3), dtype=np.float64)
    # sigma per component = sqrt(kT / m)
    sigma = np.sqrt(temperature / masses)[:, None]
    vel = rng.standard_normal((n, 3)) * sigma
    # Remove centre-of-mass velocity (momentum conservation).
    com_v = np.sum(masses[:, None] * vel, axis=0) / np.sum(masses)
    vel -= com_v
    # Rescale so the realised temperature matches the requested one.
    vel = rescale_to_temperature(vel, masses, temperature)
    return vel


def kinetic_energy(vel: np.ndarray, masses: np.ndarray) -> float:
    return float(0.5 * np.sum(masses[:, None] * vel * vel))


def temperature_of(vel: np.ndarray, masses: np.ndarray) -> float:
    """Instantaneous temperature from equipartition: 2 KE / (dof kB)."""
    n = vel.shape[0]
    dof = max(3 * n - 3, 1)
    return 2.0 * kinetic_energy(vel, masses) / dof


def rescale_to_temperature(vel: np.ndarray, masses: np.ndarray, target: float) -> np.ndarray:
    t = temperature_of(vel, masses)
    if t <= 0.0:
        return vel
    return vel * np.sqrt(target / t)


def berendsen_factor(current_t: float, target_t: float, dt: float, tau: float) -> float:
    """Berendsen velocity scaling factor lambda."""
    if current_t <= 0.0 or tau <= 0.0:
        return 1.0
    return float(np.sqrt(1.0 + (dt / tau) * (target_t / current_t - 1.0)))


def apply_thermostat(vel, masses, kind: str, target_t: float, dt: float, coupling: float):
    """Return rescaled velocities according to the chosen thermostat."""
    if kind == "none":
        return vel
    current_t = temperature_of(vel, masses)
    if kind == "berendsen":
        return vel * berendsen_factor(current_t, target_t, dt, coupling)
    if kind == "velocity_rescale":
        # Partial rescale toward target by `coupling` fraction each call.
        if current_t <= 0.0:
            return vel
        full = np.sqrt(target_t / current_t)
        lam = 1.0 + coupling * (full - 1.0)
        return vel * lam
    return vel
