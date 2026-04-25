#!/usr/bin/env python
"""BioPhi tool runner. Reads JSON inputs from stdin, writes JSON outputs to stdout.
Runs inside the 'biophi' conda env — do NOT run with backend venv python.
"""
import json
import sys


def _humanize(seq: str, scheme: str, humanize_cdrs: bool, iterations: int, chain_name: str) -> tuple[str, int, list]:
    from abnumber import Chain
    from biophi.humanization.methods.humanization import humanize_chain, SapiensHumanizationParams

    # Sapiens requires kabat CDR definition regardless of numbering scheme
    chain = Chain(seq.strip(), scheme=scheme, cdr_definition="kabat", name=chain_name)
    params = SapiensHumanizationParams(
        model_version="latest",
        humanize_cdrs=humanize_cdrs,
        iterations=iterations,
        cdr_definition="kabat",
    )
    result = humanize_chain(chain, params=params)
    humanized_seq = result.humanized_chain.seq
    n_mutations = result.num_mutations()

    # Build per-position mutation list by comparing original vs humanized sequence
    mutations = []
    orig_seq = seq.strip()
    for i, (o, h) in enumerate(zip(orig_seq, humanized_seq)):
        if o != h:
            mutations.append({"position": i + 1, "original": o, "humanized": h})

    return humanized_seq, n_mutations, mutations


def main() -> None:
    inputs = json.load(sys.stdin)

    heavy = str(inputs.get("heavy_chain", "")).strip()
    light = str(inputs.get("light_chain", "") or "").strip()
    humanize_cdrs = bool(inputs.get("humanize_cdrs", False))
    iterations = max(1, min(3, int(inputs.get("iterations", 1))))
    scheme = str(inputs.get("scheme", "imgt")).strip().lower()

    if not heavy:
        raise ValueError("heavy_chain is required")

    print(f"Humanizing VH (scheme={scheme}, iterations={iterations}, humanize_cdrs={humanize_cdrs})…", file=sys.stderr, flush=True)
    vh_humanized, vh_mutations, vh_mut_list = _humanize(heavy, scheme, humanize_cdrs, iterations, "VH")
    print(f"VH done — {vh_mutations} mutations", file=sys.stderr, flush=True)

    vl_humanized, vl_mutations, vl_mut_list = "", 0, []
    if light:
        print(f"Humanizing VL…", file=sys.stderr, flush=True)
        vl_humanized, vl_mutations, vl_mut_list = _humanize(light, scheme, humanize_cdrs, iterations, "VL")
        print(f"VL done — {vl_mutations} mutations", file=sys.stderr, flush=True)

    report = {
        "heavy_mutations": vh_mut_list,
        "light_mutations": vl_mut_list,
        "total_mutations": vh_mutations + vl_mutations,
    }

    json.dump({
        "heavy_chain_humanized": vh_humanized,
        "light_chain_humanized": vl_humanized,
        "heavy_mutations": vh_mutations,
        "light_mutations": vl_mutations,
        "report": report,
    }, sys.stdout)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        json.dump({"error": str(e)}, sys.stdout)
        sys.exit(1)
