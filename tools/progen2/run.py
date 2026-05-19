#!/usr/bin/env python3
"""ProGen2 subprocess runner — reads JSON from stdin, writes JSON to stdout.

Requires:
  - progen_src/ cloned from github.com/salesforce/progen (model source)
  - checkpoints/<model_name>/ with config.json + pytorch_model.bin
Both placed relative to this script by setup.sh.

Loads model weights directly with torch.load to avoid huggingface_hub
path-validation issues in newer transformers versions.
"""
import json
import os
import sys
from pathlib import Path

_SCRIPT_DIR  = Path(__file__).resolve().parent
_PROGEN_SRC  = _SCRIPT_DIR / "progen_src" / "progen2"
_CKPT_DIR    = _SCRIPT_DIR / "checkpoints"
_TOKENIZER   = _PROGEN_SRC / "tokenizer.json"

_MAX_VARIANTS = 10
_AA = set("ACDEFGHIKLMNPQRSTVWYacdefghiklmnpqrstvwy")


def _setup_path() -> None:
    src = str(_PROGEN_SRC)
    if src not in sys.path:
        sys.path.insert(0, src)


def _load_model_and_tokenizer(ckpt_dir: Path):
    """Load ProGen2 model directly from checkpoint files."""
    import torch
    from tokenizers import Tokenizer
    from models.progen.modeling_progen import ProGenForCausalLM
    from models.progen.configuration_progen import ProGenConfig

    # Load tokenizer
    tok_path = ckpt_dir / "tokenizer.json"
    if not tok_path.exists():
        tok_path = _TOKENIZER
    if not tok_path.exists():
        raise FileNotFoundError(f"tokenizer.json not found at {tok_path}")
    tokenizer = Tokenizer.from_file(str(tok_path))

    # Load config
    config_path = ckpt_dir / "config.json"
    with open(config_path) as f:
        cfg_dict = json.load(f)
    cfg_dict.pop("architectures", None)
    cfg_dict.pop("model_type", None)
    config = ProGenConfig(**cfg_dict)

    # Load model weights directly (bypasses huggingface_hub path validation)
    print(f"Loading ProGen2 weights from {ckpt_dir}…", file=sys.stderr)
    model = ProGenForCausalLM(config)
    weights_path = ckpt_dir / "pytorch_model.bin"
    state_dict = torch.load(str(weights_path), map_location="cpu")
    model.load_state_dict(state_dict)
    model.eval()
    print("Model loaded.", file=sys.stderr)

    return model, tokenizer


def _clean_sequence(raw: str) -> str:
    """Extract amino acid sequence from decoded output (strip BOS/EOS markers)."""
    # BOS=1, EOS=2 appear as literal characters in the decoded string
    seq = raw.lstrip("1").split("2")[0]
    return "".join(c for c in seq if c in _AA)


def _compute_log_likelihood(model, token_ids: list) -> float:
    """Mean per-token cross-entropy log-likelihood (higher = more natural)."""
    import torch
    input_ids = torch.tensor([token_ids])
    with torch.no_grad():
        out = model(input_ids, labels=input_ids)
    return -out.loss.item()


def _generate_sequence(model, tokenizer, prompt_ids: list, max_length: int,
                        temperature: float, top_p: float, top_k: int) -> list:
    import torch
    eos_id = tokenizer.token_to_id("2")
    input_ids = torch.tensor([prompt_ids])
    with torch.no_grad():
        out = model.generate(
            input_ids,
            do_sample=True,
            temperature=max(temperature, 1e-6),
            top_p=top_p if top_p < 1.0 else None,
            top_k=top_k if top_k > 0 else None,
            max_new_tokens=max_length,
            eos_token_id=eos_id,
            pad_token_id=eos_id,
        )
    return out[0].tolist()


def main() -> None:
    inputs = json.load(sys.stdin)

    mode        = str(inputs.get("mode", "generate"))
    sequence    = str(inputs.get("sequence") or inputs.get("heavy_chain") or "").strip()
    light_chain = str(inputs.get("light_chain") or "").strip()
    num_seqs    = min(int(inputs.get("num_sequences", 5)), _MAX_VARIANTS)
    max_length  = int(inputs.get("max_length", 150))
    temperature = float(inputs.get("temperature", 1.0))
    top_p       = float(inputs.get("top_p", 0.9))
    top_k       = int(inputs.get("top_k", 0))
    model_name  = str(inputs.get("model_name", "progen2-oas"))

    ckpt_dir = _CKPT_DIR / model_name
    if not ckpt_dir.exists():
        raise FileNotFoundError(
            f"Checkpoint not found: {ckpt_dir}\n"
            f"Run: bash tools/progen2/setup.sh"
        )

    _setup_path()
    model, tokenizer = _load_model_and_tokenizer(ckpt_dir)

    # ── log_likelihood mode ────────────────────────────────────────────────────
    if mode == "log_likelihood":
        if not sequence:
            raise ValueError("sequence is required for log_likelihood mode")
        print(f"Scoring {len(sequence)}-aa sequence ({model_name})…", file=sys.stderr)
        token_ids = tokenizer.encode("1" + sequence + "2").ids
        ll = _compute_log_likelihood(model, token_ids)
        print(f"Done — log_likelihood={ll:.4f}", file=sys.stderr)

        result = {
            **{f"variant_{i}": None for i in range(1, _MAX_VARIANTS + 1)},
            "sequence":       sequence,
            "heavy_chain":    sequence,
            "light_chain":    light_chain,
            "log_likelihood": ll,
            "metadata": {
                "mode":       mode,
                "model":      model_name,
                "seq_length": len(sequence),
            },
        }
        json.dump(result, sys.stdout)
        return

    # ── generate mode ─────────────────────────────────────────────────────────
    prompt_str = "1" + sequence if sequence else "1"
    if sequence:
        print(
            f"ProGen2 generate: {num_seqs} seqs, prompt={len(sequence)}-aa prefix, "
            f"model={model_name}, T={temperature}",
            file=sys.stderr,
        )
    else:
        print(
            f"ProGen2 generate: {num_seqs} seqs de novo, model={model_name}, T={temperature}",
            file=sys.stderr,
        )

    prompt_ids = tokenizer.encode(prompt_str).ids

    variants: dict = {}
    for i in range(1, num_seqs + 1):
        print(f"  Generating variant {i}/{num_seqs}…", file=sys.stderr)
        try:
            generated_ids = _generate_sequence(
                model, tokenizer, prompt_ids, max_length, temperature, top_p, top_k
            )
            decoded = tokenizer.decode(generated_ids)
            seq = _clean_sequence(decoded)
            if not seq:
                print(f"  variant_{i}: empty sequence, skipping", file=sys.stderr)
                continue
            full_ids = tokenizer.encode("1" + seq + "2").ids
            ll = _compute_log_likelihood(model, full_ids)
            print(f"  variant_{i}: len={len(seq)}, ll={ll:.4f}", file=sys.stderr)
            variants[f"variant_{i}"] = {
                "sequence":       seq,
                "heavy_chain":    seq,
                "light_chain":    light_chain,
                "log_likelihood": ll,
            }
        except Exception as exc:
            print(f"  variant_{i} failed: {exc}", file=sys.stderr)

    best = variants.get("variant_1", {})
    best_seq = best.get("sequence", sequence)

    result = {
        **{f"variant_{i}": None for i in range(1, _MAX_VARIANTS + 1)},
        **variants,
        "sequence":       best_seq,
        "heavy_chain":    best_seq,
        "light_chain":    light_chain,
        "log_likelihood": None,
        "metadata": {
            "mode":          mode,
            "model":         model_name,
            "num_sequences": len(variants),
            "temperature":   temperature,
            "top_p":         top_p,
            "top_k":         top_k,
            "max_length":    max_length,
            "prompt_len":    len(sequence),
        },
    }
    print(f"Done — {len(variants)} variant(s) generated", file=sys.stderr)
    json.dump(result, sys.stdout)


if __name__ == "__main__":
    main()
