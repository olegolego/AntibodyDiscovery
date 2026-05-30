#!/usr/bin/env python3
"""Compound Library subprocess entry point.

Creates a compound library from a SMILES dictionary or list.
Used in BioPipelines Application 3 (Compound Screening,
Quargnali & Rivera-Fuentes 2026).

Input (stdin, JSON):
  smiles_dict:    dict  — {name: smiles, ...}  (optional)
  compounds_list: list  — [{name, smiles}, ...]  (optional)
  Both can be provided; they are merged (compounds_list appended after smiles_dict).

Output (stdout, JSON):
  compounds:   [{name, smiles, index}, ...]
  n_compounds: int
  table:       same as compounds (flat list for downstream tools)
"""
import json
import sys


def _progress(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _parse_input(raw) -> dict | list | None:
    """Accept already-parsed value or JSON string."""
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    if isinstance(raw, str):
        s = raw.strip()
        if not s or s in ("null", "{}","[]"):
            return None
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            return None
    return None


def main() -> None:
    inputs = json.load(sys.stdin)

    raw_dict = _parse_input(inputs.get("smiles_dict"))
    raw_list = _parse_input(inputs.get("compounds_list"))

    compounds: list[dict] = []

    # Collect from smiles_dict
    if isinstance(raw_dict, dict) and raw_dict:
        for name, smiles in raw_dict.items():
            if not smiles:
                _progress(f"Warning: compound '{name}' has empty SMILES — skipping.")
                continue
            compounds.append({"name": str(name), "smiles": str(smiles)})

    # Collect from compounds_list
    if isinstance(raw_list, list) and raw_list:
        for entry in raw_list:
            if not isinstance(entry, dict):
                _progress(f"Warning: ignoring non-dict entry in compounds_list: {entry!r}")
                continue
            name  = entry.get("name", "")
            smiles = entry.get("smiles", "")
            if not smiles:
                _progress(f"Warning: compound '{name}' has empty SMILES — skipping.")
                continue
            compounds.append({"name": str(name), "smiles": str(smiles)})

    # Assign indices
    for i, c in enumerate(compounds):
        c["index"] = i

    n = len(compounds)
    _progress(f"Compound Library: {n} compound(s) assembled.")

    if n == 0:
        _progress(
            "Warning: compound library is empty. "
            "Provide 'smiles_dict' or 'compounds_list' with valid SMILES entries."
        )

    result = {
        "compounds":   compounds,
        "n_compounds": n,
        "table":       compounds,  # same object — downstream tools may use either key
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
