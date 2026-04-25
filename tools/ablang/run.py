#!/usr/bin/env python3
"""AbLang subprocess entry point. Reads JSON from stdin, writes JSON to stdout."""
import json
import sys

_ALLOWED_AA = set("ACDEFGHIKLMNPQRSTVWY*")
_VALID_MODES = {"seqcoding", "rescoding", "likelihood", "restore"}


def _progress(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _clean_sequence(raw: str) -> str:
    lines = [l.strip() for l in raw.splitlines() if not l.startswith(">")]
    seq = "".join(lines).replace(" ", "").upper()
    invalid = sorted(set(seq) - _ALLOWED_AA)
    if invalid:
        raise ValueError(f"Unexpected characters in sequence: {invalid}")
    if not seq:
        raise ValueError("sequence is required")
    return seq


def _run(inputs: dict) -> dict:
    import ablang
    import numpy as np

    sequence = _clean_sequence(str(inputs.get("sequence", "")))
    chain_type = str(inputs.get("chain_type", "H")).strip().upper()
    mode = str(inputs.get("mode", "seqcoding")).strip().lower()

    if chain_type not in {"H", "L"}:
        raise ValueError("chain_type must be 'H' or 'L'")
    if mode not in _VALID_MODES:
        raise ValueError(f"mode must be one of {sorted(_VALID_MODES)}")

    chain_name = "heavy" if chain_type == "H" else "light"
    _progress(f"Loading AbLang {chain_name}-chain model…")
    model = ablang.pretrained(chain_name)
    model.freeze()

    _progress(f"Running AbLang (mode={mode}, len={len(sequence)})…")
    result = model((sequence,), mode=mode)

    outputs: dict = {
        "embedding": None,
        "res_embeddings": None,
        "likelihoods": None,
        "restored_sequence": None,
    }

    if mode == "seqcoding":
        # result: numpy array (1, 768) → squeeze to (768,)
        vec = np.asarray(result).squeeze(0)
        outputs["embedding"] = vec.tolist()
        shape = list(vec.shape)

    elif mode == "rescoding":
        # result: numpy array (1, seq_len, 768) → squeeze to (seq_len, 768)
        arr = np.asarray(result).squeeze(0)
        outputs["res_embeddings"] = arr.tolist()
        shape = list(arr.shape)

    elif mode == "likelihood":
        # result: numpy array (1, seq_len, 21) → squeeze to (seq_len, 21)
        arr = np.asarray(result).squeeze(0)
        outputs["likelihoods"] = arr.tolist()
        shape = list(arr.shape)

    elif mode == "restore":
        # AbLang returns a list-of-lists of characters, e.g. [['G','G','L',…]]
        # Join to string and keep only valid amino acid characters
        raw = result[0] if isinstance(result, (list, tuple, np.ndarray)) else result
        if hasattr(raw, "__iter__") and not isinstance(raw, str):
            restored = "".join(str(c) for c in raw if str(c) in _ALLOWED_AA)
        else:
            restored = "".join(c for c in str(raw) if c in _ALLOWED_AA)
        outputs["restored_sequence"] = restored
        shape = [len(restored)]

    outputs["metadata"] = {
        "chain_type": chain_type,
        "mode": mode,
        "sequence_length": len(sequence),
        "output_shape": shape,
    }

    _progress(f"AbLang done — shape {shape}")
    return outputs


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
