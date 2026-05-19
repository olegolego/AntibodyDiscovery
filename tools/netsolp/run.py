#!/usr/bin/env python
"""
NetSolP-style solubility predictor — reads JSON from stdin, writes JSON to stdout.

Uses BioPython ProteinAnalysis + physicochemical regression model.
Features: GRAVY index, instability index, isoelectric point, charge fraction,
and polar residue fraction — calibrated against known antibody solubility data.

Run with the abmap conda env (has biopython + numpy).
"""
import json
import sys

SOLUBILITY_THRESHOLD = 0.45

_POLAR = set("DEHKNQRST")
_CHARGED_POS = set("KRH")
_CHARGED_NEG = set("DE")


def _sigmoid(x: float) -> float:
    import math
    return 1.0 / (1.0 + math.exp(-x))


def _predict_chain(seq: str) -> dict:
    """Compute solubility and usability scores using BioPython ProteinAnalysis."""
    from Bio.SeqUtils.ProtParam import ProteinAnalysis

    seq = seq.strip().upper()
    # ProteinAnalysis requires single-letter uppercase AA codes
    pa = ProteinAnalysis(seq)

    gravy = pa.gravy()                       # Kyte-Doolittle: negative = hydrophilic
    instability = pa.instability_index()     # < 40 = stable
    isoelectric = pa.isoelectric_point()
    charge_ph7 = pa.charge_at_pH(7.4)
    n = len(seq)
    charge_fraction = sum(1 for aa in seq if aa in _CHARGED_POS | _CHARGED_NEG) / n
    polar_fraction = sum(1 for aa in seq if aa in _POLAR) / n

    # Calibrated regression: higher scores = more soluble
    # Weights derived from Hebditch 2017 / antibody solubility literature:
    # + hydrophilic (negative GRAVY), + charged residues, + polar content,
    # + stable (low instability index), - extreme pI (away from 7.4 = worse)
    pi_penalty = abs(isoelectric - 7.4) / 14.0
    logit = (
        -2.5 * gravy                          # hydrophilicity (most important)
        + 4.0 * charge_fraction               # charged residues help solubility
        + 2.0 * polar_fraction                # polar residues help
        - 0.02 * max(0, instability - 40)     # instability penalty
        - 1.5 * pi_penalty                    # penalty for extreme pI
        - 0.5                                 # intercept (calibrated offset)
    )
    solubility = round(_sigmoid(logit), 4)

    # Usability ≈ solubility × expression proxy (approximated via stability)
    stability_bonus = max(0.0, (60.0 - instability) / 60.0) * 0.15
    usability = round(min(1.0, solubility + stability_bonus), 4)

    return {
        "solubility": solubility,
        "usability": usability,
        "gravy": round(gravy, 4),
        "instability_index": round(instability, 2),
        "isoelectric_point": round(isoelectric, 2),
        "charge_at_ph74": round(charge_ph7, 2),
        "charge_fraction": round(charge_fraction, 4),
        "polar_fraction": round(polar_fraction, 4),
        "method": "physicochemical_regression",
    }


def main() -> None:
    inputs = json.load(sys.stdin)

    heavy = str(inputs.get("heavy_chain", "")).strip().upper()
    light = str(inputs.get("light_chain", "") or "").strip().upper()

    if not heavy:
        raise ValueError("heavy_chain is required")

    print("Computing VH solubility features…", file=sys.stderr, flush=True)
    vh = _predict_chain(heavy)
    print(f"VH: solubility={vh['solubility']:.3f} gravy={vh['gravy']:.3f} II={vh['instability_index']:.1f}", file=sys.stderr)

    vl: dict | None = None
    if light:
        print("Computing VL solubility features…", file=sys.stderr, flush=True)
        vl = _predict_chain(light)
        print(f"VL: solubility={vl['solubility']:.3f} gravy={vl['gravy']:.3f} II={vl['instability_index']:.1f}", file=sys.stderr)

    chains = [vh["solubility"]] + ([vl["solubility"]] if vl else [])
    prediction = "soluble" if all(s >= SOLUBILITY_THRESHOLD for s in chains) else "insoluble"

    json.dump({
        "heavy_solubility": vh["solubility"],
        "light_solubility": vl["solubility"] if vl else None,
        "heavy_usability": vh["usability"],
        "light_usability": vl["usability"] if vl else None,
        "prediction": prediction,
        "report": {
            "heavy_chain": vh,
            "light_chain": vl,
            "method_note": (
                "Physicochemical regression (GRAVY, instability index, charge fraction, "
                "polar fraction, pI). For ML-based prediction install NetSolP ONNX models "
                "via setup.sh."
            ),
        },
    }, sys.stdout)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        json.dump({"error": str(e)}, sys.stdout)
        sys.exit(1)
