#!/usr/bin/env python3
"""IgLM subprocess runner — reads JSON from stdin, writes JSON to stdout."""
import json
import sys

_MAX_VARIANTS = 10

SPECIES_TOKEN_MAP = {
    "human":  "[HUMAN]",
    "mouse":  "[MOUSE]",
    "rabbit": "[RABBIT]",
    "rat":    "[RAT]",
    "rhesus": "[RHESUS]",
}

# Chain token implied by each CDR region
_REGION_CHAIN_TOKEN = {
    "cdr_h1": "[HEAVY]", "cdr_h2": "[HEAVY]", "cdr_h3": "[HEAVY]",
    "cdr_l1": "[LIGHT]", "cdr_l2": "[LIGHT]", "cdr_l3": "[LIGHT]",
    "custom":  "[HEAVY]",  # default for custom; overridden by redesign_chain
}

# Auto-pair VH CDR → VL CDR when redesign_chain=both
_VH_TO_VL_REGION = {
    "cdr_h1": "cdr_l1",
    "cdr_h2": "cdr_l2",
    "cdr_h3": "cdr_l3",
}


def get_cdr_range(sequence: str, region: str, scheme: str = "imgt",
                  custom_start: int = 0, custom_end: int = 10):
    """Return (start, end) 0-indexed for the CDR in the original sequence."""
    if region == "custom":
        return custom_start, custom_end

    cdr_attr_map = {
        "cdr_h1": "cdr1_dict", "cdr_h2": "cdr2_dict", "cdr_h3": "cdr3_dict",
        "cdr_l1": "cdr1_dict", "cdr_l2": "cdr2_dict", "cdr_l3": "cdr3_dict",
    }
    try:
        from abnumber import Chain
        chain = Chain(sequence, scheme=scheme)
        cdr_dict = getattr(chain, cdr_attr_map[region])
        seq_idx = 0
        cdr_indices = []
        for pos, _ in chain:
            if pos in cdr_dict:
                cdr_indices.append(seq_idx)
            seq_idx += 1
        if not cdr_indices:
            raise ValueError(f"{region} empty in numbering result")
        return cdr_indices[0], cdr_indices[-1] + 1
    except Exception as exc:
        print(f"Warning: CDR detection failed ({exc}), using approximate positions", file=sys.stderr)
        L = len(sequence)
        approx = {
            "cdr_h1": (int(0.21 * L), int(0.29 * L)),
            "cdr_h2": (int(0.42 * L), int(0.51 * L)),
            "cdr_h3": (int(0.76 * L), int(0.88 * L)),
            "cdr_l1": (int(0.22 * L), int(0.31 * L)),
            "cdr_l2": (int(0.44 * L), int(0.51 * L)),
            "cdr_l3": (int(0.78 * L), int(0.90 * L)),
        }
        return approx.get(region, (0, min(10, L)))


def score_sequence(model, sequence: str, chain_token: str, species_token: str) -> float:
    try:
        return model.log_likelihood(sequence, chain_token, species_token)
    except Exception:
        return float("nan")


def infill_chain(model, sequence: str, chain_token: str, species_token: str,
                 region: str, scheme: str, custom_start: int, custom_end: int,
                 num_seqs: int, top_p: float, temperature: float):
    """Run IgLM infill on one chain; return list of generated sequences."""
    start, end = get_cdr_range(sequence, region, scheme, custom_start, custom_end)
    print(
        f"  Infilling {region} [{start},{end}) of {len(sequence)}-aa sequence "
        f"(chain={chain_token}, n={num_seqs})…",
        file=sys.stderr,
    )
    seqs = model.infill(
        sequence, chain_token, species_token,
        infill_range=(start, end),
        num_to_generate=num_seqs,
        top_p=top_p,
        temperature=temperature,
    )
    return seqs, (start, end)


def main():
    inputs = json.load(sys.stdin)

    mode          = str(inputs.get("mode", "infill"))
    heavy_chain   = str(inputs.get("heavy_chain") or inputs.get("sequence") or "").strip()
    light_chain   = str(inputs.get("light_chain") or "").strip()
    redesign      = str(inputs.get("redesign_chain", "vh")).lower()
    infill_region = str(inputs.get("infill_region", "cdr_h3"))
    scheme        = str(inputs.get("scheme", "imgt"))
    custom_start  = int(inputs.get("custom_start", 0))
    custom_end    = int(inputs.get("custom_end", 10))
    species       = str(inputs.get("species", "human")).lower()
    num_seqs      = min(int(inputs.get("num_sequences", 5)), _MAX_VARIANTS)
    temperature   = float(inputs.get("temperature", 1.0))
    top_p         = float(inputs.get("top_p", 1.0))
    model_name    = str(inputs.get("model_name", "IgLM"))

    # Derive chain tokens from region / redesign_chain — no chain_type param needed
    if redesign == "vl":
        vh_token = "[LIGHT]"
    else:
        vh_token = _REGION_CHAIN_TOKEN.get(infill_region, "[HEAVY]")
    vl_token = "[LIGHT]"

    # Auto-derive VL region when redesign_chain=both
    vl_region = _VH_TO_VL_REGION.get(infill_region, infill_region)
    # If infill_region is already a VL CDR, keep it for both chains
    if infill_region.startswith("cdr_l"):
        vl_region = infill_region

    sp_token = SPECIES_TOKEN_MAP.get(species, "[HUMAN]")

    print(f"Loading IgLM ({model_name})…", file=sys.stderr)
    from iglm import IgLM
    model = IgLM(model_name=model_name)
    print("Model loaded.", file=sys.stderr)

    # ── log_likelihood mode ────────────────────────────────────────────────
    if mode == "log_likelihood":
        seq = heavy_chain
        # Auto-detect chain type from sequence; default to heavy
        ct = "[HEAVY]"
        try:
            from abnumber import Chain as AbChain
            ac = AbChain(seq, scheme=scheme)
            ct = "[LIGHT]" if ac.chain_type == "L" else "[HEAVY]"
        except Exception:
            pass
        print(f"Scoring {len(seq)}-aa sequence (chain={ct}, species={sp_token})…", file=sys.stderr)
        ll = model.log_likelihood(seq, ct, sp_token)
        result = {
            "variant_1": None, "variant_2": None, "variant_3": None, "variant_4": None,
            "variant_5": None, "variant_6": None, "variant_7": None, "variant_8": None,
            "variant_9": None, "variant_10": None,
            "heavy_chain": seq, "light_chain": light_chain,
            "log_likelihood": ll,
            "metadata": {
                "mode": mode, "model": model_name,
                "chain_token": ct, "species": species,
                "sequence_length": len(seq),
            },
        }
        print(f"Done — log_likelihood={ll:.4f}", file=sys.stderr)
        json.dump(result, sys.stdout)
        return

    # ── generate mode ─────────────────────────────────────────────────────
    if mode == "generate":
        ct = "[LIGHT]" if redesign == "vl" else "[HEAVY]"
        prompt = heavy_chain if heavy_chain else None
        print(f"Generating {num_seqs} sequences (chain={ct}, species={sp_token})…", file=sys.stderr)
        seqs = model.generate(
            ct, sp_token,
            prompt_sequence=prompt,
            num_to_generate=num_seqs,
            top_p=top_p,
            temperature=temperature,
        )
        # Score each generated sequence
        variants = {}
        best_vh = seqs[0] if seqs else heavy_chain
        for i, seq in enumerate(seqs[:_MAX_VARIANTS], 1):
            ll = score_sequence(model, seq, ct, sp_token)
            variants[f"variant_{i}"] = {"heavy_chain": seq, "light_chain": light_chain, "log_likelihood": ll}
            print(f"  variant_{i}: ll={ll:.4f}", file=sys.stderr)

        result = {
            **{f"variant_{i}": None for i in range(1, _MAX_VARIANTS + 1)},
            **variants,
            "heavy_chain": best_vh,
            "light_chain": light_chain,
            "log_likelihood": None,
            "metadata": {
                "mode": mode, "model": model_name,
                "chain_token": ct, "species": species,
                "num_sequences": len(seqs), "temperature": temperature, "top_p": top_p,
            },
        }
        print(f"Done — generated {len(seqs)} sequences", file=sys.stderr)
        json.dump(result, sys.stdout)
        return

    # ── infill mode ────────────────────────────────────────────────────────
    vh_seqs = []
    vl_seqs = []
    vh_range = vl_range = None

    if redesign in ("vh", "both"):
        if not heavy_chain:
            raise ValueError("heavy_chain is required for redesign_chain=vh/both")
        vh_seqs, vh_range = infill_chain(
            model, heavy_chain, vh_token, sp_token,
            infill_region, scheme, custom_start, custom_end,
            num_seqs, top_p, temperature,
        )

    if redesign in ("vl", "both"):
        if not light_chain:
            raise ValueError("light_chain is required for redesign_chain=vl/both")
        vl_seqs, vl_range = infill_chain(
            model, light_chain, vl_token, sp_token,
            vl_region, scheme, custom_start, custom_end,
            num_seqs, top_p, temperature,
        )

    # Combine into variant bundles, scoring each sequence
    variants = {}
    n_variants = max(len(vh_seqs), len(vl_seqs), 1)
    for i in range(1, min(n_variants, _MAX_VARIANTS) + 1):
        vh = vh_seqs[i - 1] if redesign in ("vh", "both") and i <= len(vh_seqs) else heavy_chain
        vl = vl_seqs[i - 1] if redesign in ("vl", "both") and i <= len(vl_seqs) else light_chain
        ll_vh = score_sequence(model, vh, vh_token, sp_token) if vh else float("nan")
        print(f"  variant_{i}: vh_ll={ll_vh:.4f} vh_len={len(vh)} vl_len={len(vl)}", file=sys.stderr)
        variants[f"variant_{i}"] = {
            "heavy_chain": vh,
            "light_chain": vl,
            "log_likelihood": ll_vh,
        }

    best = variants.get("variant_1", {})
    result = {
        **{f"variant_{i}": None for i in range(1, _MAX_VARIANTS + 1)},
        **variants,
        "heavy_chain": best.get("heavy_chain", heavy_chain),
        "light_chain": best.get("light_chain", light_chain),
        "log_likelihood": None,
        "metadata": {
            "mode": mode, "model": model_name,
            "redesign_chain": redesign,
            "infill_region": infill_region,
            "vl_region": vl_region if redesign == "both" else None,
            "scheme": scheme,
            "vh_infill_range": list(vh_range) if vh_range else None,
            "vl_infill_range": list(vl_range) if vl_range else None,
            "species": species,
            "num_sequences": n_variants,
            "temperature": temperature,
            "top_p": top_p,
        },
    }
    print(f"Done — {n_variants} variant(s) generated", file=sys.stderr)
    json.dump(result, sys.stdout)


if __name__ == "__main__":
    main()
