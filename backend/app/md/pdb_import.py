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
