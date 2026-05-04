#!/usr/bin/env python3
"""PDBFixer subprocess entry point.

Reads JSON from stdin, writes JSON to stdout.
Progress lines go to stderr → forwarded live to the UI terminal.
"""
import io
import json
import sys
import tempfile
from pathlib import Path


def _progress(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def main() -> None:
    inputs = json.load(sys.stdin)

    pdb_text           = inputs.get("structure", "")
    fix_missing_res    = bool(inputs.get("fix_missing_residues", True))
    fix_missing_atoms  = bool(inputs.get("fix_missing_atoms", True))
    remove_heterogens  = bool(inputs.get("remove_heterogens", True))
    add_hydrogens      = bool(inputs.get("add_hydrogens", False))
    ph                 = float(inputs.get("ph", 7.0))

    if not pdb_text or "ATOM" not in pdb_text:
        print(json.dumps({"error": "structure input is empty or contains no ATOM records"}))
        sys.exit(1)

    try:
        from pdbfixer import PDBFixer
        from openmm.app import PDBFile
    except ImportError as e:
        print(json.dumps({"error": f"pdbfixer not installed: {e}"}))
        sys.exit(1)

    _progress("PDBFixer: parsing structure…")

    with tempfile.NamedTemporaryFile(suffix=".pdb", mode="w", delete=False) as f:
        f.write(pdb_text)
        tmp_path = f.name

    try:
        fixer = PDBFixer(filename=tmp_path)
    except Exception as e:
        print(json.dumps({"error": f"PDBFixer failed to parse PDB: {e}"}))
        sys.exit(1)
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    report: dict = {
        "chains": [str(c.id) for c in fixer.topology.chains()],
        "missing_residues_added": 0,
        "missing_atoms_added": 0,
        "heterogens_removed": 0,
        "hydrogens_added": add_hydrogens,
    }

    # Missing residues
    fixer.findMissingResidues()
    n_missing_res = sum(len(v) for v in fixer.missingResidues.values())
    if fix_missing_res and n_missing_res:
        _progress(f"PDBFixer: modelling {n_missing_res} missing residue segments…")
        fixer.addMissingResidues()
        report["missing_residues_added"] = n_missing_res
    else:
        if n_missing_res:
            _progress(f"PDBFixer: skipping {n_missing_res} missing residue segments (fix_missing_residues=false)")

    # Non-standard residues / heterogens
    fixer.findNonstandardResidues()
    if remove_heterogens:
        n_atoms_before = fixer.topology.getNumAtoms()
        fixer.removeHeterogens(keepWater=False)
        n_removed = n_atoms_before - fixer.topology.getNumAtoms()
        report["heterogens_removed"] = max(0, n_removed)
        if n_removed > 0:
            _progress(f"PDBFixer: removed {n_removed} HETATM atoms")

    # Missing atoms
    fixer.findMissingAtoms()
    n_missing_atoms = sum(len(v) for v in fixer.missingAtoms.values())
    if fix_missing_atoms and n_missing_atoms:
        _progress(f"PDBFixer: adding {n_missing_atoms} missing heavy atoms…")
        fixer.addMissingAtoms()
        report["missing_atoms_added"] = n_missing_atoms

    # Hydrogens
    if add_hydrogens:
        _progress(f"PDBFixer: adding hydrogens at pH {ph}…")
        fixer.addMissingHydrogens(pH=ph)

    _progress("PDBFixer: writing fixed structure…")
    out_buf = io.StringIO()
    PDBFile.writeFile(fixer.topology, fixer.positions, out_buf)
    fixed_pdb = out_buf.getvalue()

    _progress(
        f"PDBFixer: done — chains {report['chains']}, "
        f"+{report['missing_residues_added']} residues, "
        f"+{report['missing_atoms_added']} atoms, "
        f"-{report['heterogens_removed']} HETATM atoms"
    )

    print(json.dumps({"fixed_structure": fixed_pdb, "report": report}))


if __name__ == "__main__":
    main()
