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

from difflib import SequenceMatcher

import numpy as np

from .spec import Bond, Box, ForceTerm, ParticleType, StreamConfig, SystemSpec

# 3-letter → 1-letter residue codes for reading chain sequences from a PDB.
_AA3TO1 = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C", "GLN": "Q",
    "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I", "LEU": "L", "LYS": "K",
    "MET": "M", "PHE": "F", "PRO": "P", "SER": "S", "THR": "T", "TRP": "W",
    "TYR": "Y", "VAL": "V", "MSE": "M", "SEC": "U", "PYL": "O",
}

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


def parse_gro(text: str) -> tuple[list[tuple[float, float, float]], list[str], list[bool]]:
    """Parse a GROMACS .gro coordinate file. Positions are in nm → converted to Å.

    Fixed-format columns: residue name [5:10], atom name [10:15], then x/y/z in
    8.3f fields starting at column 20 (nm). The second line is the atom count.
    """
    lines = text.splitlines()
    if len(lines) < 3:
        raise PDBImportError("GRO file too short")
    try:
        n = int(lines[1].strip())
    except ValueError:
        raise PDBImportError("GRO second line is not an atom count")
    coords: list[tuple[float, float, float]] = []
    elements: list[str] = []
    is_ca: list[bool] = []
    for line in lines[2 : 2 + n]:
        if len(line) < 44:
            continue
        atom_name = line[10:15].strip()
        try:
            x = float(line[20:28]) * 10.0  # nm → Å
            y = float(line[28:36]) * 10.0
            z = float(line[36:44]) * 10.0
        except ValueError:
            continue
        coords.append((x, y, z))
        elements.append(_element_of(atom_name, ""))
        is_ca.append(atom_name == "CA")
    if not coords:
        raise PDBImportError("No atoms parsed from GRO file")
    return coords, elements, is_ca


def _parse_structure(text: str):
    """Dispatch on file format: PDB (ATOM/HETATM records) vs GROMACS .gro."""
    head = text.lstrip()[:6]
    if head.startswith(("ATOM", "HETATM")) or "\nATOM" in text[:4000] or "\nHETATM" in text[:4000]:
        return parse_pdb(text)
    # GRO: second line is a bare integer atom count.
    lines = text.splitlines()
    if len(lines) >= 2 and lines[1].strip().isdigit():
        return parse_gro(text)
    # Default to PDB parsing (raises a clear error if there are no records).
    return parse_pdb(text)


def build_enm_spec(
    text: str,
    name: str = "Imported structure",
    spring_k: float = 1.0,
    temperature: float = 0.6,
) -> SystemSpec:
    """Parse a PDB or GROMACS .gro file and build an elastic-network SystemSpec."""
    coords, elements, is_ca = _parse_structure(text)
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


# ── Docked-complex import (split into antibody + antigen) ──────────────────────

def _parse_pdb_chains(text: str):
    """Parse ATOM/HETATM of the first model, keeping chain id + residue for each atom.

    Returns (atoms, chain_ca_seq) where atoms is a list of
    (chain, x, y, z, element, is_ca) and chain_ca_seq maps chain → 1-letter Cα
    sequence (used to identify which chains are the antibody).
    """
    atoms: list[tuple[str, float, float, float, str, bool]] = []
    chain_seq: dict[str, list[str]] = {}
    for line in text.splitlines():
        rec = line[:6].strip()
        if rec == "ENDMDL":
            break
        if rec not in ("ATOM", "HETATM"):
            continue
        try:
            x = float(line[30:38]); y = float(line[38:46]); z = float(line[46:54])
        except (ValueError, IndexError):
            continue
        chain = (line[21:22] or " ").strip() or "_"
        atom_name = line[12:16]
        element = _element_of(atom_name, line[76:78] if len(line) >= 78 else "")
        is_ca = atom_name.strip() == "CA" and rec == "ATOM"
        atoms.append((chain, x, y, z, element, is_ca))
        if is_ca:
            res = line[17:20].strip().upper()
            chain_seq.setdefault(chain, []).append(_AA3TO1.get(res, "X"))
    if not atoms:
        raise PDBImportError("No ATOM/HETATM records found in the complex PDB")
    return atoms, {c: "".join(s) for c, s in chain_seq.items()}


def _classify_chains(chain_seq: dict[str, list[str]], vh: str, vl: str) -> set[str]:
    """Return the set of chain ids that belong to the antibody.

    Primary signal: sequence similarity to the known VH / VL. Falls back to the
    conventional H/L chain ids, then to the best-matching single chain.
    """
    chains = list(chain_seq.keys())
    vh = (vh or "").strip().upper()
    vl = (vl or "").strip().upper()

    def best_ratio(seq: str) -> float:
        r = 0.0
        for ref in (vh, vl):
            if ref:
                r = max(r, SequenceMatcher(None, seq, ref).ratio())
        return r

    scores = {c: best_ratio(seq) for c, seq in chain_seq.items()}
    ab = {c for c, s in scores.items() if s > 0.6}
    if not ab:
        ab = {c for c in chains if c.upper() in ("H", "L")}
    if not ab and scores:
        ab = {max(scores, key=scores.get)}
    # Guarantee both groups are non-empty when there are ≥2 chains.
    if len(chains) >= 2 and len(ab) == len(chains):
        ab.discard(min(scores, key=scores.get))
    return ab


def build_docked_complex_spec(
    pdb: str,
    vh: str = "",
    vl: str = "",
    name: str = "Docked complex",
    spring_k: float = 1.0,
    temperature: float = 0.5,
    bind_epsilon: float = 0.5,
) -> SystemSpec:
    """Build a two-colour elastic-network model from an *already-docked* complex.

    Atoms are split into antibody (chains matching VH/VL) and antigen (the rest),
    coloured distinctly. Springs are built only WITHIN each group, so the bound
    pose is preserved but the two bodies can flex at the interface; a Lennard-Jones
    term models the inter-body contact. Coordinates are kept as-is (the complex is
    already in its docked pose).
    """
    atoms, chain_seq = _parse_pdb_chains(pdb)
    ab_chains = _classify_chains(chain_seq, vh, vl)

    chains = np.array([a[0] for a in atoms])
    pos_all = np.array([[a[1], a[2], a[3]] for a in atoms], dtype=np.float64)
    is_ca_all = np.array([a[5] for a in atoms], dtype=bool)

    # Coarse-grain to Cα for large complexes (keeps O(N^2) responsive + clean view).
    if len(pos_all) > _ALL_ATOM_LIMIT and is_ca_all.any():
        keep = np.where(is_ca_all)[0]
        pos_all = pos_all[keep]
        chains = chains[keep]
        coarse = True
    else:
        coarse = bool(is_ca_all.mean() > 0.5)
    if len(pos_all) > _HARD_CAP:
        idx = np.linspace(0, len(pos_all) - 1, _HARD_CAP).astype(int)
        pos_all = pos_all[idx]
        chains = chains[idx]

    n = len(pos_all)
    # group 0 = antibody, 1 = antigen
    group = np.array([0 if c in ab_chains else 1 for c in chains], dtype=np.int64)
    n_ab = int((group == 0).sum())
    n_ag = int((group == 1).sum())
    if n_ab == 0 or n_ag == 0:
        # Couldn't split — fall back to a single-body ENM so the run still opens.
        return build_enm_spec(pdb, name=name, spring_k=spring_k, temperature=temperature)

    cutoff = 9.0 if coarse else 5.0
    bead_mass, bead_r = (110.0, 0.9) if coarse else (12.0, 0.5)
    particle_types = [
        ParticleType(name="Antibody", mass=bead_mass, radius=bead_r, color=_BODY_COLORS[0]),
        ParticleType(name="Antigen", mass=bead_mass, radius=bead_r, color=_BODY_COLORS[1]),
    ]

    # Keep docked coordinates; just shift into a positive, padded open box.
    pad = 8.0
    pos = pos_all - pos_all.min(axis=0) + pad
    lengths = (pos.max(axis=0) + pad).tolist()

    # Springs only between atoms of the SAME group (intra-body), within cutoff.
    d = pos[:, None, :] - pos[None, :, :]
    dist = np.sqrt(np.sum(d * d, axis=2))
    iu, ju = np.triu_indices(n, k=1)
    same_group = group[iu] == group[ju]
    within = (dist[iu, ju] < cutoff) & same_group
    bonds = [Bond(i=int(i), j=int(j), r0=float(dist[i, j]), k=spring_k) for i, j in zip(iu[within], ju[within])]

    force_terms = [
        ForceTerm(kind="harmonic_bond", enabled=True),
        ForceTerm(kind="lennard_jones", enabled=True, epsilon=bind_epsilon, sigma=3.0, cutoff=4.0),
    ]

    return SystemSpec(
        name=name,
        n_particles=n,
        particle_types=particle_types,
        type_index=group.tolist(),
        positions=pos.tolist(),
        box=Box(lengths=[float(l) for l in lengths], boundary="open"),
        bonds=bonds,
        force_terms=force_terms,
        integrator="velocity_verlet",
        thermostat="berendsen",
        target_temperature=temperature,
        thermostat_coupling=0.1,
        dt=0.01,
        steps=30000,
        temperature=temperature,
        seed=0,
        stream=StreamConfig(frame_stride=10, max_fps=30),
    )
