"""Built-in starter systems. Each returns a SystemSpec the UI can load + tune."""
from __future__ import annotations

from .spec import Bond, Box, ForceTerm, ParticleType, StreamConfig, SystemSpec


def lj_gas() -> SystemSpec:
    return SystemSpec(
        name="Lennard-Jones gas",
        n_particles=256,
        particle_types=[ParticleType(name="Ar", mass=1.0, radius=0.5, color="#6366f1")],
        box=Box(lengths=[12.0, 12.0, 12.0], boundary="periodic"),
        force_terms=[ForceTerm(kind="lennard_jones", epsilon=1.0, sigma=1.0, cutoff=2.5)],
        integrator="velocity_verlet",
        thermostat="none",
        dt=0.004,
        steps=8000,
        temperature=1.2,
        stream=StreamConfig(frame_stride=4, max_fps=30),
    )


def lj_liquid() -> SystemSpec:
    return SystemSpec(
        name="Lennard-Jones liquid (thermostatted)",
        n_particles=500,
        particle_types=[ParticleType(name="Ar", mass=1.0, radius=0.5, color="#22d3ee")],
        box=Box(lengths=[8.5, 8.5, 8.5], boundary="periodic"),
        force_terms=[ForceTerm(kind="lennard_jones", epsilon=1.0, sigma=1.0, cutoff=2.5)],
        integrator="velocity_verlet",
        thermostat="berendsen",
        target_temperature=0.9,
        thermostat_coupling=0.1,
        dt=0.003,
        steps=10000,
        temperature=0.9,
        stream=StreamConfig(frame_stride=5, max_fps=30),
    )


def harmonic_pair() -> SystemSpec:
    """Two bonded particles — the canonical harmonic-oscillator verification case."""
    return SystemSpec(
        name="Harmonic oscillator (bonded pair)",
        n_particles=2,
        particle_types=[ParticleType(name="A", mass=1.0, radius=0.4, color="#f59e0b")],
        positions=[[8.0, 10.0, 10.0], [12.0, 10.0, 10.0]],
        velocities=[[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
        box=Box(lengths=[20.0, 20.0, 20.0], boundary="open"),
        bonds=[Bond(i=0, j=1, r0=2.0, k=50.0)],
        force_terms=[ForceTerm(kind="harmonic_bond")],
        integrator="velocity_verlet",
        thermostat="none",
        dt=0.005,
        steps=4000,
        temperature=0.0,
        stream=StreamConfig(frame_stride=2, max_fps=60),
    )


def coulomb_plasma() -> SystemSpec:
    """Equal mix of + and - charges in a box (screened by reflective walls)."""
    n = 128
    types = [
        ParticleType(name="+", mass=1.0, charge=1.0, radius=0.4, color="#ef4444"),
        ParticleType(name="-", mass=1.0, charge=-1.0, radius=0.4, color="#3b82f6"),
    ]
    type_index = [i % 2 for i in range(n)]
    return SystemSpec(
        name="Coulomb plasma",
        n_particles=n,
        particle_types=types,
        type_index=type_index,
        box=Box(lengths=[14.0, 14.0, 14.0], boundary="reflective"),
        force_terms=[
            ForceTerm(kind="lennard_jones", epsilon=0.5, sigma=0.8, cutoff=2.5),
            ForceTerm(kind="coulomb", k_coulomb=2.0, coulomb_cutoff=6.0),
        ],
        integrator="velocity_verlet",
        thermostat="velocity_rescale",
        target_temperature=1.0,
        thermostat_coupling=0.05,
        dt=0.002,
        steps=8000,
        temperature=1.0,
        stream=StreamConfig(frame_stride=4, max_fps=30),
    )


def gravity_cluster() -> SystemSpec:
    """A small N-body gravitational cluster (softened)."""
    return SystemSpec(
        name="Gravity cluster (N-body)",
        n_particles=80,
        particle_types=[ParticleType(name="star", mass=1.0, radius=0.3, color="#fbbf24")],
        box=Box(lengths=[40.0, 40.0, 40.0], boundary="open"),
        force_terms=[ForceTerm(kind="gravity", g_constant=1.0, softening=0.4)],
        integrator="velocity_verlet",
        thermostat="none",
        dt=0.005,
        steps=10000,
        temperature=0.2,
        stream=StreamConfig(frame_stride=4, max_fps=30),
    )


_PRESETS = {
    "lj_gas": lj_gas,
    "lj_liquid": lj_liquid,
    "harmonic_pair": harmonic_pair,
    "coulomb_plasma": coulomb_plasma,
    "gravity_cluster": gravity_cluster,
}

_PRESET_META = {
    "lj_gas": {"label": "Lennard-Jones gas", "description": "256 LJ particles, NVE — watch energy stay flat."},
    "lj_liquid": {"label": "LJ liquid", "description": "Dense LJ fluid with a Berendsen thermostat."},
    "harmonic_pair": {"label": "Harmonic oscillator", "description": "Two bonded particles oscillating at 2π√(μ/k)."},
    "coulomb_plasma": {"label": "Coulomb plasma", "description": "Mixed +/- charges with LJ cores."},
    "gravity_cluster": {"label": "Gravity cluster", "description": "80-body softened-gravity cluster."},
}


def get_preset(key: str) -> SystemSpec:
    if key not in _PRESETS:
        raise KeyError(key)
    return _PRESETS[key]()


def list_presets() -> list[dict]:
    return [{"key": k, **_PRESET_META[k]} for k in _PRESETS]
