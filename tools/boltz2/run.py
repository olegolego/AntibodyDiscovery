#!/usr/bin/env python3
"""Boltz2 stub subprocess entry point.

Reads JSON from stdin, writes JSON to stdout.
Progress lines go to stderr -> forwarded live to the UI terminal.

Stub behaviour:
- Accepts sequence (FASTA) OR structure (PDB string).
- Generates a synthetic alpha-helix PDB from the sequence (CA atoms only, helix geometry).
- Appends a mock LIG HETATM residue if ligand_smiles is provided.
- Returns mock binding_probability, binding_affinity, and plddt.
- Results are deterministic: seeded with hash(sequence) so same input -> same output.
"""
import json
import math
import sys


def _progress(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# One-letter AA code -> full residue name (for PDB ATOM records)
_AA3 = {
    "A": "ALA", "C": "CYS", "D": "ASP", "E": "GLU", "F": "PHE",
    "G": "GLY", "H": "HIS", "I": "ILE", "K": "LYS", "L": "LEU",
    "M": "MET", "N": "ASN", "P": "PRO", "Q": "GLN", "R": "ARG",
    "S": "SER", "T": "THR", "V": "VAL", "W": "TRP", "Y": "TYR",
}
_DEFAULT_AA3 = "ALA"

# Alpha-helix CA geometry: 100 deg rotation per residue, 1.5 A rise, 2.3 A radius
_HELIX_ROTATION_DEG = 100.0
_HELIX_RISE_A = 1.5
_HELIX_RADIUS_A = 2.3


def _extract_sequence_from_pdb(pdb_text: str) -> str:
    """Extract protein sequence from ATOM CA records."""
    seq_chars: list[str] = []
    seen: set[tuple[str, int]] = set()
    _aa3to1 = {v: k for k, v in _AA3.items()}
    for line in pdb_text.splitlines():
        if line.startswith("ATOM") and line[12:16].strip() == "CA":
            chain = line[21:22].strip() or "A"
            try:
                resnum = int(line[22:26].strip())
            except ValueError:
                continue
            key = (chain, resnum)
            if key in seen:
                continue
            seen.add(key)
            resname = line[17:20].strip()
            seq_chars.append(_aa3to1.get(resname, "X"))
    return "".join(seq_chars)


def _clean_sequence(raw: str) -> str:
    """Strip FASTA headers and whitespace, uppercase."""
    lines = [ln.strip() for ln in raw.splitlines() if not ln.startswith(">")]
    return "".join(lines).upper().replace(" ", "")


def _build_helix_pdb(sequence: str, ligand_name: str, add_ligand: bool) -> str:
    """Build a synthetic alpha-helix PDB from a protein sequence.

    Uses CA-only ATOM records. Helix geometry:
        x(i) = radius * cos(i * rotation_rad)
        y(i) = radius * sin(i * rotation_rad)
        z(i) = i * rise

    If add_ligand is True, appends a single HETATM for the ligand
    near the C-terminus (offset by ~5 A from the last CA).
    """
    rot_rad = math.radians(_HELIX_ROTATION_DEG)
    lines: list[str] = []
    atom_serial = 1
    last_x, last_y, last_z = 0.0, 0.0, 0.0

    for i, aa in enumerate(sequence):
        x = _HELIX_RADIUS_A * math.cos(i * rot_rad)
        y = _HELIX_RADIUS_A * math.sin(i * rot_rad)
        z = i * _HELIX_RISE_A
        resname = _AA3.get(aa, _DEFAULT_AA3)
        # PDB ATOM format (columns 1-80)
        line = (
            f"ATOM  {atom_serial:5d}  CA  {resname} A{i + 1:4d}    "
            f"{x:8.3f}{y:8.3f}{z:8.3f}  1.00 80.00           C  "
        )
        lines.append(line)
        atom_serial += 1
        last_x, last_y, last_z = x, y, z

    if add_ligand:
        lig_x = last_x + 5.0
        lig_y = last_y
        lig_z = last_z
        lig_resnum = len(sequence) + 1
        lig_name = (ligand_name[:3].upper()).ljust(3)
        line = (
            f"HETATM{atom_serial:5d}  C1  {lig_name} A{lig_resnum:4d}    "
            f"{lig_x:8.3f}{lig_y:8.3f}{lig_z:8.3f}  1.00 50.00           C  "
        )
        lines.append(line)

    lines.append("END")
    return "\n".join(lines) + "\n"


def _mock_values(sequence: str) -> tuple[float, float, list[float]]:
    """Generate reproducible mock affinity values seeded by sequence hash."""
    import random
    rng = random.Random(hash(sequence))
    binding_prob = round(rng.uniform(0.2, 0.9), 4)
    binding_aff = round(rng.uniform(5.0, 100.0), 2)
    plddt = [round(rng.uniform(0.7, 0.95), 4) for _ in sequence]
    return binding_prob, binding_aff, plddt


def _run(inputs: dict) -> dict:
    sequence_raw = str(inputs.get("sequence", "") or "").strip()
    structure_raw = str(inputs.get("structure", "") or "").strip()
    ligand_smiles = str(inputs.get("ligand_smiles", "") or "").strip()
    ligand_name = str(inputs.get("ligand_name", "LIG") or "LIG").strip()[:3].upper() or "LIG"

    add_ligand = bool(ligand_smiles)

    # Determine working sequence and PDB
    if structure_raw and "ATOM" in structure_raw:
        _progress("Boltz2 stub: using provided PDB structure.")
        sequence = _extract_sequence_from_pdb(structure_raw) or "MAQQSPYSAAMA"
        _progress(f"Boltz2 stub: extracted {len(sequence)} residues from PDB.")
        if add_ligand:
            # Append mock LIG HETATM after the last ATOM record
            _progress(f"Boltz2 stub: appending mock {ligand_name} HETATM to input structure.")
            # Find last ATOM/HETATM coordinates
            last_x, last_y, last_z = 0.0, 0.0, 50.0
            for line in structure_raw.splitlines():
                if line.startswith(("ATOM", "HETATM")):
                    try:
                        last_x = float(line[30:38])
                        last_y = float(line[38:46])
                        last_z = float(line[46:54])
                    except ValueError:
                        pass
            lig_resnum = len(sequence) + 1
            lig_x = last_x + 5.0
            lig_line = (
                f"HETATM    1  C1  {ligand_name} A{lig_resnum:4d}    "
                f"{lig_x:8.3f}{last_y:8.3f}{last_z:8.3f}  1.00 50.00           C  "
            )
            pdb_out = structure_raw.rstrip()
            if pdb_out.endswith("END"):
                pdb_out = pdb_out[:-3].rstrip()
            pdb_out = pdb_out + "\n" + lig_line + "\nEND\n"
        else:
            pdb_out = structure_raw
    else:
        # Build from sequence
        sequence = _clean_sequence(sequence_raw) if sequence_raw else "MAQQSPYSAAMA"
        if not sequence:
            sequence = "MAQQSPYSAAMA"
        _progress(f"Boltz2 stub: building synthetic helix for {len(sequence)}-residue sequence.")
        pdb_out = _build_helix_pdb(sequence, ligand_name, add_ligand)

    binding_prob, binding_aff, plddt = _mock_values(sequence)

    if add_ligand:
        _progress(f"Boltz2 stub: ligand {ligand_name} added (mock binding prob={binding_prob}, aff={binding_aff} µM).")
    else:
        _progress(f"Boltz2 stub: mock binding prob={binding_prob}, aff={binding_aff} µM.")
    _progress("Boltz2 stub: done.")

    return {
        "structure": pdb_out,
        "binding_probability": binding_prob,
        "binding_affinity": binding_aff,
        "plddt": plddt,
    }


if __name__ == "__main__":
    inputs = json.load(sys.stdin)
    try:
        outputs = _run(inputs)
    except Exception as exc:
        json.dump({"error": str(exc)}, sys.stdout)
        sys.stdout.flush()
        sys.exit(1)
    json.dump(outputs, sys.stdout)
    sys.stdout.flush()
