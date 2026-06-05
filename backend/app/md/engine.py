"""The Simulation object: builds numpy state from a SystemSpec, computes the
total force from all enabled terms, and advances the system one step at a time.

Designed to be driven externally (the runner calls ``step()`` in batches) so the
event loop stays responsive and frames can be decimated.
"""
from __future__ import annotations

import numpy as np

from . import forces as F
from . import integrators as integ
from .spec import Box, ParticleType, SystemSpec


class SimulationError(RuntimeError):
    pass


class Simulation:
    def __init__(self, spec: SystemSpec):
        self.spec = spec
        self.box = spec.box
        self.dt = spec.dt
        self.step_index = 0
        self.time = 0.0
        rng = np.random.default_rng(spec.seed)

        n = spec.n_particles
        types = spec.particle_types or [ParticleType()]
        self.types = types

        # Per-particle type assignment.
        if spec.type_index and len(spec.type_index) == n:
            self.type_index = np.asarray(spec.type_index, dtype=np.int64)
        else:
            self.type_index = np.zeros(n, dtype=np.int64)
        self.type_index = np.clip(self.type_index, 0, len(types) - 1)

        self.masses = np.array([types[t].mass for t in self.type_index], dtype=np.float64)

        # Positions: provided, else a cubic lattice that fits the box.
        if spec.positions is not None and len(spec.positions) == n:
            self.pos = np.asarray(spec.positions, dtype=np.float64)
        else:
            self.pos = self._lattice(n, self.box)

        # Velocities: provided, else Maxwell-Boltzmann at the initial temperature.
        if spec.velocities is not None and len(spec.velocities) == n:
            self.vel = np.asarray(spec.velocities, dtype=np.float64)
        else:
            self.vel = integ.maxwell_boltzmann(self.masses, spec.temperature, rng)

        # Bonds (harmonic_bond term).
        if spec.bonds:
            self.bonds_ij = np.array([[b.i, b.j] for b in spec.bonds], dtype=np.int64)
            self.bonds_r0 = np.array([b.r0 for b in spec.bonds], dtype=np.float64)
            self.bonds_k = np.array([b.k for b in spec.bonds], dtype=np.float64)
        else:
            self.bonds_ij = np.empty((0, 2), dtype=np.int64)
            self.bonds_r0 = np.empty(0)
            self.bonds_k = np.empty(0)

        self.pairs = F.all_pairs(n)
        self._compiled = self._compile_terms()

        # Prime forces for the first velocity-Verlet half-kick.
        self.forces, self.potential = self._compute_forces()
        self.initial_energy = self.total_energy()

        # Blowup guard: a generous cap on per-particle speed.
        self.max_speed = 1e3

    # ── setup helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _lattice(n: int, box: Box) -> np.ndarray:
        """Place n particles on a cubic lattice centred in the box."""
        side = max(int(np.ceil(n ** (1.0 / 3.0))), 1)
        L = np.asarray(box.lengths, dtype=np.float64)
        spacing = L / (side + 1)
        coords = []
        for idx in range(n):
            x = idx % side
            y = (idx // side) % side
            z = idx // (side * side)
            coords.append([(x + 1) * spacing[0], (y + 1) * spacing[1], (z + 1) * spacing[2]])
        pos = np.array(coords, dtype=np.float64)
        # Centre about origin-ish (box is treated as [0, L)).
        return pos

    def _compile_terms(self) -> list:
        """Resolve each enabled force term to a callable + the term object."""
        from .potential_eval import make_formula_force
        from .custom_exec import compile_custom_force

        compiled = []
        for term in self.spec.force_terms:
            if not term.enabled:
                continue
            if term.kind in F.PAIRWISE:
                compiled.append((F.PAIRWISE[term.kind], term))
            elif term.kind == "harmonic_bond":
                continue  # handled separately via bond list
            elif term.kind == "formula":
                compiled.append((make_formula_force(term), term))
            elif term.kind == "python":
                if not term.code:
                    raise SimulationError("python force term has no code")
                compiled.append((compile_custom_force(term.code), term))
            else:
                raise SimulationError(f"Unknown force kind: {term.kind}")
        return compiled

    # ── dynamics ─────────────────────────────────────────────────────────────

    def _compute_forces(self):
        n = self.pos.shape[0]
        total_f = np.zeros((n, 3), dtype=np.float64)
        total_pe = 0.0
        for fn, term in self._compiled:
            f, pe = fn(self.pos, self.type_index, self.types, self.box, self.pairs, term)
            total_f += f
            total_pe += pe
        # Bonded term, if any harmonic_bond is enabled and bonds exist.
        if self.bonds_ij.shape[0] and any(
            t.kind == "harmonic_bond" and t.enabled for t in self.spec.force_terms
        ):
            fb, peb = F.harmonic_bond(
                self.pos, self.type_index, self.types, self.box,
                self.bonds_ij, self.bonds_r0, self.bonds_k,
            )
            total_f += fb
            total_pe += peb
        return total_f, total_pe

    def _apply_boundary(self) -> None:
        L = np.asarray(self.box.lengths, dtype=np.float64)
        if self.box.boundary == "periodic":
            self.pos = np.mod(self.pos, L)
        elif self.box.boundary == "reflective":
            below = self.pos < 0.0
            above = self.pos > L
            self.pos = np.where(below, -self.pos, self.pos)
            self.pos = np.where(above, 2.0 * L - self.pos, self.pos)
            self.vel = np.where(below | above, -self.vel, self.vel)
        # "open": no wrapping

    def step(self) -> None:
        dt = self.dt
        if self.spec.integrator == "leapfrog":
            self.vel += dt * self.forces / self.masses[:, None]
            self.pos += dt * self.vel
            self._apply_boundary()
            self.forces, self.potential = self._compute_forces()
        else:  # velocity_verlet
            acc = self.forces / self.masses[:, None]
            self.pos += self.vel * dt + 0.5 * acc * dt * dt
            self._apply_boundary()
            new_forces, self.potential = self._compute_forces()
            new_acc = new_forces / self.masses[:, None]
            self.vel += 0.5 * (acc + new_acc) * dt
            self.forces = new_forces

        # Thermostat.
        self.vel = integ.apply_thermostat(
            self.vel, self.masses, self.spec.thermostat,
            self.spec.target_temperature, dt, self.spec.thermostat_coupling,
        )

        self.step_index += 1
        self.time += dt

        # Blowup guard.
        if not np.all(np.isfinite(self.pos)) or not np.all(np.isfinite(self.vel)):
            raise SimulationError(f"Non-finite state at step {self.step_index} (dt too large?)")
        speeds = np.linalg.norm(self.vel, axis=1)
        if speeds.size and float(np.max(speeds)) > self.max_speed:
            raise SimulationError(
                f"Velocity blowup at step {self.step_index} "
                f"(max speed {float(np.max(speeds)):.1f} > {self.max_speed:.0f}); reduce dt"
            )

    # ── energy minimisation (preprocessing) ─────────────────────────────────────

    def setup_minimize(self) -> None:
        """Initialise steepest-descent state. Call once before minimize_step()."""
        # Characteristic length sets a sane per-atom displacement cap that works in
        # both reduced (sigma~1) and Ångström (bond r0~3.8) regimes.
        if self.bonds_ij.shape[0]:
            char = float(np.mean(self.bonds_r0))
        else:
            sigmas = [t.sigma for t in self.spec.force_terms if t.kind == "lennard_jones"]
            char = float(sigmas[0]) if sigmas else 1.0
        self._max_disp = 0.1 * char
        self._min_alpha = 0.01 * char
        self.forces, self.potential = self._compute_forces()

    def minimize_step(self) -> None:
        """One steepest-descent step with adaptive step size + energy backtracking.

        Moves atoms along the force (negative PE gradient), capped to _max_disp per
        atom. Accepts the move only if the potential energy decreases (otherwise it
        reverts and shrinks the step), so the potential energy is monotonically
        non-increasing — this removes clashes without ever blowing up.
        """
        f = self.forces
        fmax = float(np.max(np.linalg.norm(f, axis=1))) if f.size else 0.0
        if fmax < 1e-9:
            return
        disp = self._min_alpha * f
        dmag = np.linalg.norm(disp, axis=1)
        scale = np.where(dmag > self._max_disp, self._max_disp / np.maximum(dmag, 1e-12), 1.0)
        disp = disp * scale[:, None]

        old_pos, old_pe, old_f = self.pos.copy(), self.potential, self.forces
        self.pos = self.pos + disp
        self._apply_boundary()
        new_f, new_pe = self._compute_forces()
        if np.isfinite(new_pe) and new_pe < old_pe:
            self.forces, self.potential = new_f, new_pe
            self._min_alpha *= 1.1
        else:
            self.pos, self.forces, self.potential = old_pos, old_f, old_pe
            self._min_alpha *= 0.5

    def reset_velocities(self, temperature: float) -> None:
        """Re-draw Maxwell-Boltzmann velocities (used after minimisation)."""
        rng = np.random.default_rng(self.spec.seed + 1)
        self.vel = integ.maxwell_boltzmann(self.masses, temperature, rng)

    # ── observables ────────────────────────────────────────────────────────────

    def kinetic_energy(self) -> float:
        return integ.kinetic_energy(self.vel, self.masses)

    def temperature(self) -> float:
        return integ.temperature_of(self.vel, self.masses)

    def total_energy(self) -> float:
        return self.kinetic_energy() + self.potential

    def energy_dict(self) -> dict:
        ke = self.kinetic_energy()
        return {
            "kinetic": ke,
            "potential": self.potential,
            "total": ke + self.potential,
            "temperature": self.temperature(),
        }

    def flat_positions(self) -> list[float]:
        return self.pos.reshape(-1).tolist()
