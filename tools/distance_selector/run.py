#!/usr/bin/env python3
"""Distance Selector subprocess entry point.

Selects protein residues within a given distance of a ligand in a PDB file.
Used in BioPipelines Application 5 (Quargnali & Rivera-Fuentes 2026).

Input (stdin, JSON):
  structure: str   — PDB text
  ligand:    str   — residue name of the ligand (default "LIG")
  distance:  float — cutoff in Angstroms (default 5.0)

Output (stdout, JSON):
  selections:      {within: [{chain, resnum, resname, min_dist_A}, ...], n_residues: int}
  residue_indices: [[chain, resnum], ...]
"""
import json
import math
import sys


def _progress(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def parse_pdb(pdb_text: str) -> list[dict]:
    """Minimal stdlib PDB parser — extracts ATOM and HETATM records."""
    atoms = []
    for line in pdb_text.splitlines():
        if not line.startswith(("ATOM", "HETATM")):
            continue
        try:
            atoms.append({
                "record":  line[:6].strip(),
                "serial":  int(line[6:11]),
                "name":    line[12:16].strip(),
                "resname": line[17:20].strip(),
                "chain":   line[21].strip(),
                "resnum":  int(line[22:26]),
                "x":       float(line[30:38]),
                "y":       float(line[38:46]),
                "z":       float(line[46:54]),
            })
        except (ValueError, IndexError):
            # Skip malformed lines
            continue
    return atoms


def dist(a: dict, b: dict) -> float:
    return math.sqrt(
        (a["x"] - b["x"]) ** 2 +
        (a["y"] - b["y"]) ** 2 +
        (a["z"] - b["z"]) ** 2
    )


def main() -> None:
    inputs = json.load(sys.stdin)

    pdb_text = inputs.get("structure", "")
    ligand   = str(inputs.get("ligand", "LIG")).strip().upper()
    cutoff   = float(inputs.get("distance", 5.0))

    # Empty / invalid structure — return empty selection with warning
    if not pdb_text or "ATOM" not in pdb_text:
        _progress(f"Warning: structure is empty or contains no ATOM records. Returning empty selection.")
        result = {
            "selections": {"within": [], "n_residues": 0},
            "residue_indices": [],
        }
        json.dump(result, sys.stdout)
        sys.stdout.flush()
        return

    _progress(f"Distance Selector: parsing PDB…")
    atoms = parse_pdb(pdb_text)

    if not atoms:
        _progress("Warning: no valid ATOM/HETATM records found. Returning empty selection.")
        result = {
            "selections": {"within": [], "n_residues": 0},
            "residue_indices": [],
        }
        json.dump(result, sys.stdout)
        sys.stdout.flush()
        return

    # Separate ligand atoms from protein atoms
    ligand_atoms = [a for a in atoms if a["record"] == "HETATM" and a["resname"] == ligand]
    protein_atoms = [a for a in atoms if a["record"] == "ATOM"]

    if not ligand_atoms:
        _progress(
            f"Warning: ligand '{ligand}' not found in HETATM records. "
            f"Returning empty selection."
        )
        result = {
            "selections": {"within": [], "n_residues": 0},
            "residue_indices": [],
        }
        json.dump(result, sys.stdout)
        sys.stdout.flush()
        return

    _progress(
        f"Distance Selector: {len(protein_atoms)} protein atoms, "
        f"{len(ligand_atoms)} ligand atoms ('{ligand}'), cutoff={cutoff} Å"
    )

    # For each protein residue, compute minimum distance to any ligand atom
    # Group protein atoms by (chain, resnum, resname)
    residue_map: dict[tuple, dict] = {}
    for a in protein_atoms:
        key = (a["chain"], a["resnum"], a["resname"])
        if key not in residue_map:
            residue_map[key] = {"atoms": [], "chain": a["chain"], "resnum": a["resnum"], "resname": a["resname"]}
        residue_map[key]["atoms"].append(a)

    selected = []
    for key, res_data in residue_map.items():
        min_d = min(
            dist(pa, la)
            for pa in res_data["atoms"]
            for la in ligand_atoms
        )
        if min_d <= cutoff:
            selected.append({
                "chain":      res_data["chain"],
                "resnum":     res_data["resnum"],
                "resname":    res_data["resname"],
                "min_dist_A": round(min_d, 3),
            })

    # Sort by resnum (then chain for multi-chain structures)
    selected.sort(key=lambda r: (r["chain"], r["resnum"]))

    residue_indices = [[r["chain"], r["resnum"]] for r in selected]

    _progress(
        f"Distance Selector: found {len(selected)} pocket residue(s) within {cutoff} Å of '{ligand}'"
    )

    result = {
        "selections": {
            "within": selected,
            "n_residues": len(selected),
        },
        "residue_indices": residue_indices,
    }
    json.dump(result, sys.stdout)
    sys.stdout.flush()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        import traceback
        json.dump({"error": str(exc), "traceback": traceback.format_exc()}, sys.stdout)
        sys.stdout.flush()
        sys.exit(1)
