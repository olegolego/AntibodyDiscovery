"""Verification tests for the MD engine. Pure numpy, no FastAPI.

Run: cd backend && .venv/bin/python -m pytest tests/md -q
"""
import math

import numpy as np
import pytest

from app.md.engine import Simulation, SimulationError
from app.md.integrators import maxwell_boltzmann, temperature_of
from app.md.potential_eval import compile_potential, validate_formula
from app.md.presets import get_preset
from app.md.spec import Bond, Box, ForceTerm, ParticleType, SystemSpec


def _run(sim: Simulation, steps: int):
    for _ in range(steps):
        sim.step()


def test_energy_conservation_nve_lj():
    """NVE Lennard-Jones: total energy drift bounded and non-secular."""
    spec = get_preset("lj_gas")
    spec.n_particles = 256
    spec.dt = 0.004
    spec.thermostat = "none"
    sim = Simulation(spec)
    e0 = sim.total_energy()
    energies = []
    for _ in range(40):
        _run(sim, 100)  # 4000 steps total
        energies.append(sim.total_energy())
    drift = abs(energies[-1] - e0) / abs(e0)
    assert drift < 0.02, f"energy drift too large: {drift:.4f}"
    # Non-secular: the energy should not march monotonically away.
    fluctuation = (max(energies) - min(energies)) / abs(e0)
    assert fluctuation < 0.05, f"energy fluctuation too large: {fluctuation:.4f}"


def test_harmonic_oscillator_period():
    """Two bonded particles oscillate at T = 2π√(μ/k)."""
    k, r0, m = 50.0, 2.0, 1.0
    spec = SystemSpec(
        n_particles=2,
        particle_types=[ParticleType(mass=m)],
        positions=[[9.0, 10.0, 10.0], [12.0, 10.0, 10.0]],  # separation 3, stretched by 1 from r0=2
        velocities=[[0, 0, 0], [0, 0, 0]],
        box=Box(lengths=[20, 20, 20], boundary="open"),
        bonds=[Bond(i=0, j=1, r0=r0, k=k)],
        force_terms=[ForceTerm(kind="harmonic_bond")],
        dt=0.001, steps=20000, temperature=0.0,
    )
    sim = Simulation(spec)
    mu = m / 2.0  # reduced mass
    expected_period = 2 * math.pi * math.sqrt(mu / k)

    seps, times = [], []
    for _ in range(8000):
        sim.step()
        seps.append(float(np.linalg.norm(sim.pos[0] - sim.pos[1])))
        times.append(sim.time)
    seps = np.array(seps)
    times = np.array(times)
    # Find separation extrema crossings of the mean to estimate the period.
    centered = seps - seps.mean()
    sign = np.sign(centered)
    crossings = times[np.where(np.diff(sign) != 0)[0]]
    # Each full period has 2 mean-crossings; period = 2 * mean spacing.
    spacings = np.diff(crossings)
    measured = 2 * spacings.mean()
    rel_err = abs(measured - expected_period) / expected_period
    assert rel_err < 0.05, f"period {measured:.4f} vs expected {expected_period:.4f} ({rel_err:.3f})"


def test_formula_matches_analytic_lj():
    """U(r)=4*(1/r**12-1/r**6) force matches analytic LJ within numeric tolerance."""
    spec_analytic = SystemSpec(
        n_particles=64,
        box=Box(lengths=[10, 10, 10], boundary="periodic"),
        force_terms=[ForceTerm(kind="lennard_jones", epsilon=1.0, sigma=1.0, cutoff=None)],
        temperature=0.5, seed=3,
    )
    spec_formula = spec_analytic.model_copy(deep=True)
    spec_formula.force_terms = [ForceTerm(kind="formula", expression="4*(1/r**12 - 1/r**6)", cutoff=None)]

    sa = Simulation(spec_analytic)
    sf = Simulation(spec_formula)
    # Same initial positions (same seed → same lattice + MB).
    np.testing.assert_allclose(sa.pos, sf.pos)
    np.testing.assert_allclose(sa.forces, sf.forces, atol=1e-3, rtol=1e-3)
    assert abs(sa.potential - sf.potential) < 1e-4


def test_maxwell_boltzmann_init():
    """MB init: realised temperature matches target, COM velocity ≈ 0."""
    rng = np.random.default_rng(1)
    masses = np.ones(500)
    vel = maxwell_boltzmann(masses, temperature=1.5, rng=rng)
    assert abs(temperature_of(vel, masses) - 1.5) < 1e-6
    com_v = np.sum(masses[:, None] * vel, axis=0) / masses.sum()
    assert np.linalg.norm(com_v) < 1e-9


def test_thermostat_converges():
    """A hot start with a Berendsen thermostat relaxes toward the target T."""
    spec = get_preset("lj_liquid")
    spec.n_particles = 200
    spec.temperature = 3.0          # start hot
    spec.target_temperature = 1.0
    spec.thermostat = "berendsen"
    spec.thermostat_coupling = 0.05
    spec.dt = 0.002
    sim = Simulation(spec)
    _run(sim, 3000)
    assert sim.temperature() < 2.0, f"thermostat failed to cool: T={sim.temperature():.3f}"


def test_blowup_guard():
    """A huge dt triggers a SimulationError rather than NaN/hang."""
    spec = get_preset("lj_gas")
    spec.n_particles = 64
    spec.dt = 5.0  # absurd
    sim = Simulation(spec)
    with pytest.raises(SimulationError):
        _run(sim, 500)


def test_validate_formula_endpoint_logic():
    out = validate_formula("4*(1/r**12 - 1/r**6)")
    assert out["valid"] and len(out["samples"]) > 10

    from app.md.potential_eval import FormulaError
    with pytest.raises(FormulaError):
        compile_potential("__import__('os').system('ls')")
    with pytest.raises(FormulaError):
        compile_potential("r.real")
