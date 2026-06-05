"""Pydantic models describing an MD system and the streamed frame protocol.

These are the *only* serialised contract between the API layer and the numpy
engine. The engine consumes a ``SystemSpec`` and emits ``Frame`` dicts; nothing
in this module imports numpy so it stays cheap to load.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

# Reduced (Lennard-Jones) units are the default throughout: sigma = epsilon =
# mass = kB = 1. Temperature, energy and distance are therefore dimensionless.

Boundary = Literal["open", "periodic", "reflective"]
IntegratorKind = Literal["velocity_verlet", "leapfrog"]
ThermostatKind = Literal["none", "berendsen", "velocity_rescale"]
ForceKind = Literal["lennard_jones", "harmonic_bond", "coulomb", "gravity", "formula", "python"]


class ParticleType(BaseModel):
    """A species of particle. Parameters are looked up per-type by the force laws."""
    name: str = "A"
    mass: float = 1.0
    charge: float = 0.0
    radius: float = 0.5          # visual radius + LJ sigma fallback
    color: str = "#6366f1"


class Bond(BaseModel):
    """A harmonic bond between two particle indices (for harmonic_bond term)."""
    i: int
    j: int
    r0: float = 1.0              # equilibrium length
    k: float = 100.0            # spring constant


class ForceTerm(BaseModel):
    """One additive contribution to the total force.

    Only the fields relevant to ``kind`` are read. Keeping every term in one
    model (rather than a discriminated union) keeps the JSON flat and the
    frontend editor simple.
    """
    kind: ForceKind
    enabled: bool = True

    # lennard_jones
    epsilon: float = 1.0
    sigma: float = 1.0
    cutoff: Optional[float] = 2.5     # in units of sigma; None = no cutoff

    # coulomb
    k_coulomb: float = 1.0            # Coulomb constant in reduced units
    coulomb_cutoff: Optional[float] = None

    # gravity (softened 1/r^2 attraction; uses particle mass as "gravitational mass")
    g_constant: float = 1.0
    softening: float = 0.1

    # formula / python (resolved by potential_eval / custom_exec)
    expression: Optional[str] = None  # U(r) as a function of r
    script_id: Optional[str] = None   # reference to a saved MDForceScriptRow
    code: Optional[str] = None        # inline python force code (custom_exec)


class Box(BaseModel):
    """Simulation cell. lengths are the edge lengths of an axis-aligned box."""
    lengths: list[float] = Field(default_factory=lambda: [20.0, 20.0, 20.0])
    boundary: Boundary = "periodic"


class StreamConfig(BaseModel):
    frame_stride: int = 1        # emit every Nth step
    max_fps: float = 30.0        # wall-clock cap on frame emission


class SystemSpec(BaseModel):
    """Complete description of a runnable simulation."""
    name: str = "Untitled simulation"

    # Particle state, structure-of-arrays. If positions/velocities are omitted
    # the engine initialises them (lattice + Maxwell-Boltzmann at `temperature`).
    n_particles: int = 256
    particle_types: list[ParticleType] = Field(default_factory=lambda: [ParticleType()])
    type_index: list[int] = Field(default_factory=list)   # per-particle index into particle_types
    positions: Optional[list[list[float]]] = None         # [N,3]
    velocities: Optional[list[list[float]]] = None         # [N,3]

    box: Box = Field(default_factory=Box)
    bonds: list[Bond] = Field(default_factory=list)
    force_terms: list[ForceTerm] = Field(
        default_factory=lambda: [ForceTerm(kind="lennard_jones")]
    )

    integrator: IntegratorKind = "velocity_verlet"
    thermostat: ThermostatKind = "none"
    target_temperature: float = 1.0
    thermostat_coupling: float = 0.1     # tau for berendsen / fraction for rescale

    dt: float = 0.005
    steps: int = 5000
    temperature: float = 1.0             # initial MB temperature when velocities unset
    seed: int = 0

    stream: StreamConfig = Field(default_factory=StreamConfig)


# ── Streamed frame protocol ────────────────────────────────────────────────────

class Energy(BaseModel):
    kinetic: float
    potential: float
    total: float
    temperature: float


class Frame(BaseModel):
    step: int
    time: float
    positions: list[float]   # flat length-3N (x0,y0,z0,x1,...) for typed-array hydration
    energy: Energy


class Summary(BaseModel):
    steps_run: int
    final_energy: Energy
    energy_drift: float      # |E_final - E_initial| / |E_initial|
    wall_seconds: float
