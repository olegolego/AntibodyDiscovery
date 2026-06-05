"""Turn a PDB structure into a runnable SystemSpec.

Full biomolecular MD needs a force field (OpenMM — a later phase). For the
sandbox we build an **Elastic Network Model (ENM)**: every pair of atoms within
a cutoff is connected by a harmonic spring whose rest length is the initial
distance. That holds the fold together and reproduces realistic low-frequency
vibrational motion, while staying numerically stable and cheap.

Large structures are coarse-grained to Cα atoms so the O(N^2) engine stays
responsive.
"""
from __future__ import annotations

import numpy as np

from .spec import Bond, Box, ForceTerm, ParticleType, StreamConfig, SystemSpec

# element → (mass amu, viz radius Å, CPK-ish colour)
_ELEMENTS: dict[str, tuple[float, float, str]] = {
    "H": (1.008, 0.30, "#ffffff"),
    "C": (12.011, 0.55, "#909090"),
    "N": (14.007, 0.52, "#3050f8"),
    "O": (15.999, 0.50, "#ff0d0d"),
    "S": (32.06, 0.70, "#ffff30"),
    "P": (30.974, 0.70, "#ff8000"),
    "FE": (55.845, 0.70, "#e06633"),
    "ZN": (65.38, 0.70, "#7d80b0"),
    "MG": (24.305, 0.60, "#8aff00"),
    "CA": (40.078, 0.70, "#3dff00"),  # calcium ion (distinct from Cα carbon)
}
_DEFAULT_ELEMENT = (12.0, 0.55, "#ff1493")

# Coarse-grain to Cα above this many atoms; subsample Cα above the second cap.
_ALL_ATOM_LIMIT = 1500
_HARD_CAP = 1200


class PDBImportError(ValueError):
    pass


def _element_of(atom_name: str, element_col: str) -> str:
    el = element_col.strip().upper()
    if el:
        return el
    # Guess from the atom name (first alpha chars), e.g. " CA " -> C, "FE" -> FE.
    name = atom_name.strip()
    if len(name) >= 2 and name[:2].upper() in _ELEMENTS:
        return name[:2].upper()
    for ch in name:
        if ch.isalpha():
            return ch.upper()
    return "C"


def parse_pdb(text: str) -> tuple[list[tuple[float, float, float]], list[str], list[bool]]:
    """Return (coords, elements, is_calpha) for all ATOM/HETATM records of the
    first model. Honours the fixed-column PDB format."""
    coords: list[tuple[float, float, float]] = []
    elements: list[str] = []
    is_ca: list[bool] = []
    for line in text.splitlines():
        rec = line[:6].strip()
        if rec not in ("ATOM", "HETATM"):
            if rec == "ENDMDL":
                break  # first model only
            continue
        try:
            x = float(line[30:38]); y = float(line[38:46]); z = float(line[46:54])
        except (ValueError, IndexError):
            continue
        atom_name = line[12:16]
        element = _element_of(atom_name, line[76:78] if len(line) >= 78 else "")
        coords.append((x, y, z))
        elements.append(element)
        is_ca.append(atom_name.strip() == "CA" and rec == "ATOM")
    if not coords:
        raise PDBImportError("No ATOM/HETATM records found in the PDB text")
    return coords, elements, is_ca


def build_enm_spec(
    text: str,
    name: str = "Imported structure",
    spring_k: float = 1.0,
    temperature: float = 0.6,
) -> SystemSpec:
    """Parse a PDB and build an elastic-network SystemSpec."""
    coords, elements, is_ca = parse_pdb(text)
    pos = np.array(coords, dtype=np.float64)
    elements = list(elements)
    ca_arr = np.array(is_ca, dtype=bool)

    if len(pos) > _ALL_ATOM_LIMIT and ca_arr.any():
        # Too big for all-atom — coarse-grain to Cα atoms.
        keep = np.where(ca_arr)[0]
        pos = pos[keep]
        elements = [elements[i] for i in keep]
        ca_arr = np.ones(len(pos), dtype=bool)
    if len(pos) > _HARD_CAP:
        # Still too many — uniformly subsample.
        idx = np.linspace(0, len(pos) - 1, _HARD_CAP).astype(int)
        pos = pos[idx]
        elements = [elements[i] for i in idx]
        ca_arr = ca_arr[idx]

    n = len(pos)

    # A predominantly-Cα set is a coarse representation: residue-spaced beads
    # (~3.8 Å apart) need a wide ENM radius; a true all-atom set uses a smaller
    # one that still cross-links beyond direct covalent neighbours.
    coarse = bool(ca_arr.mean() > 0.5)
    cutoff = 9.0 if coarse else 5.0

    # Distinct element types present → particle_types + per-atom index.
    type_keys = sorted(set(elements))
    type_for = {k: i for i, k in enumerate(type_keys)}
    particle_types = []
    for k in type_keys:
        mass, radius, color = _ELEMENTS.get(k, _DEFAULT_ELEMENT)
        # Cα coarse beads represent a whole residue — bump mass/radius for presence.
        if coarse:
            mass, radius = 110.0, 0.9
        particle_types.append(ParticleType(name=k, mass=mass, charge=0.0, radius=radius, color=color))
    type_index = [type_for[e] for e in elements]

    # Recentre into a padded box with open boundaries.
    pad = 6.0
    mins = pos.min(axis=0)
    pos = pos - mins + pad
    lengths = (pos.max(axis=0) + pad).tolist()

    # Build harmonic springs for every pair within the cutoff.
    bonds: list[Bond] = []
    d = pos[:, None, :] - pos[None, :, :]
    dist = np.sqrt(np.sum(d * d, axis=2))
    iu, ju = np.triu_indices(n, k=1)
    within = dist[iu, ju] < cutoff
    for i, j in zip(iu[within], ju[within]):
        bonds.append(Bond(i=int(i), j=int(j), r0=float(dist[i, j]), k=spring_k))

    if not bonds:
        raise PDBImportError("No atom pairs within the ENM cutoff — structure may be too sparse")

    return SystemSpec(
        name=name,
        n_particles=n,
        particle_types=particle_types,
        type_index=type_index,
        positions=pos.tolist(),
        box=Box(lengths=[float(l) for l in lengths], boundary="open"),
        bonds=bonds,
        force_terms=[ForceTerm(kind="harmonic_bond", enabled=True)],
        integrator="velocity_verlet",
        thermostat="berendsen",
        target_temperature=temperature,
        thermostat_coupling=0.1,
        dt=0.01,
        steps=20000,
        temperature=temperature,
        seed=0,
        stream=StreamConfig(frame_stride=10, max_fps=30),
    )


def _recolor(types: list[ParticleType], color: str) -> list[ParticleType]:
    """Return copies of particle types recoloured to one hue (per-body colouring)."""
    return [t.model_copy(update={"color": color}) for t in types]


def _normalised_type_index(spec: SystemSpec) -> list[int]:
    if spec.type_index and len(spec.type_index) == spec.n_particles:
        return list(spec.type_index)
    return [0] * spec.n_particles


# Distinct per-body colours so the two proteins are visually separable.
_BODY_COLORS = ["#6366f1", "#f59e0b", "#10b981", "#ec4899"]


def combine_with_target(
    base: SystemSpec,
    target_pdb: str,
    target_name: str = "Target",
    gap: float = 5.0,
    bind_epsilon: float = 0.4,
) -> SystemSpec:
    """Place a target protein next to an already-loaded structure for docking.

    Algorithm (guarantees the two structures fit but do NOT overlap):
      1. Build the target as its own elastic-network body.
      2. Centre A at the origin and slide B along +x until B's nearest face is
         `gap` beyond A's far face. Because the two bodies' x-projections are then
         disjoint (separated by `gap` > 0), every A–B atom pair differs in x by
         more than `gap` — so they cannot overlap, yet the surfaces start close
         enough for the non-bonded force to act (unlike bounding-sphere
         separation, which over-separates elongated shapes out of LJ range).
      3. Merge atoms, types (recoloured per body) and intra-body springs. No bonds
         are created between the bodies, so each stays folded but they move as
         independent rigid-ish bodies.
      4. Size an open box around the union (+padding).
      5. Add a Lennard-Jones term so the surfaces attract/repel — letting them
         drift together and settle into an approximate binding pose. Each body's
         shape is held by its much stronger ENM springs.
    """
    if not base.positions or len(base.positions) < 1:
        raise PDBImportError("Load a structure first, then add a target to dock against it.")

    target = build_enm_spec(target_pdb, name=target_name)

    posA = np.array(base.positions, dtype=np.float64)
    posB = np.array(target.positions, dtype=np.float64)

    # Centre A at origin; place B's −x face `gap` past A's +x face.
    posA = posA - posA.mean(axis=0)
    posB = posB - posB.mean(axis=0)
    shift_x = float(posA[:, 0].max()) + gap - float(posB[:, 0].min())
    posB = posB + np.array([shift_x, 0.0, 0.0])

    nA = len(posA)
    typesA = _recolor(base.particle_types or [ParticleType()], _BODY_COLORS[0])
    typesB = _recolor(target.particle_types or [ParticleType()], _BODY_COLORS[1])
    tiA = _normalised_type_index(base)
    tiB = [t + len(typesA) for t in _normalised_type_index(target)]

    # Merge bonds; target bond indices shift by nA. No A–B bonds.
    bonds = list(base.bonds)
    for b in target.bonds:
        bonds.append(Bond(i=b.i + nA, j=b.j + nA, r0=b.r0, k=b.k))

    pos = np.vstack([posA, posB])
    pad = 8.0
    pos = pos - pos.min(axis=0) + pad
    lengths = (pos.max(axis=0) + pad).tolist()

    # Preserve existing force terms; ensure a Lennard-Jones binding term exists.
    force_terms = [ft.model_copy() for ft in base.force_terms]
    if not any(ft.kind == "lennard_jones" for ft in force_terms):
        # sigma ~ a coarse bead diameter; wide cutoff so surfaces feel each other.
        force_terms.append(ForceTerm(
            kind="lennard_jones", enabled=True, epsilon=bind_epsilon, sigma=3.0, cutoff=4.0,
        ))
    if not any(ft.kind == "harmonic_bond" for ft in force_terms):
        force_terms.append(ForceTerm(kind="harmonic_bond", enabled=True))

    return SystemSpec(
        name=f"{base.name} + {target_name}",
        n_particles=nA + len(posB),
        particle_types=typesA + typesB,
        type_index=tiA + tiB,
        positions=pos.tolist(),
        box=Box(lengths=[float(l) for l in lengths], boundary="open"),
        bonds=bonds,
        force_terms=force_terms,
        integrator="velocity_verlet",
        thermostat="berendsen",
        target_temperature=base.target_temperature or 0.6,
        thermostat_coupling=0.1,
        dt=min(base.dt, 0.01),
        steps=max(base.steps, 30000),
        temperature=base.temperature or 0.6,
        seed=0,
        stream=StreamConfig(frame_stride=10, max_fps=30),
    )
