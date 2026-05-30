#!/usr/bin/env python3
"""DNA Encoder — codon-optimizes amino acid sequences for a target organism.

Reads JSON from stdin: {sequence: str (FASTA), organism: str}
Writes JSON to stdout: {dna_sequences: str (FASTA), gc_content: list[dict]}
Writes progress to stderr.

Supported organisms:
  EC = Escherichia coli K-12
  HS = Homo sapiens
  SC = Saccharomyces cerevisiae
  BS = Bacillus subtilis

Codon tables are the highest-frequency codon per amino acid per organism,
derived from CoCoPUTs (Alexaki et al. 2019) codon usage tables.
"""
import json
import sys

# ---------------------------------------------------------------------------
# Codon tables — most-frequent codon per amino acid per organism
# Source: CoCoPUTs database (cocoputs.codon.ncifcrf.gov)
# Each organism key maps amino-acid letter -> preferred codon
# ---------------------------------------------------------------------------

_CODON_TABLES: dict[str, dict[str, str]] = {
    # E. coli K-12 (high-expression preferred codons)
    "EC": {
        "A": "GCT", "R": "CGT", "N": "AAC", "D": "GAT", "C": "TGC",
        "Q": "CAG", "E": "GAA", "G": "GGT", "H": "CAT", "I": "ATT",
        "L": "CTG", "K": "AAA", "M": "ATG", "F": "TTT", "P": "CCG",
        "S": "AGC", "T": "ACC", "W": "TGG", "Y": "TAT", "V": "GTT",
        "*": "TAA",
    },
    # Homo sapiens (Kazusa human codon usage)
    "HS": {
        "A": "GCC", "R": "AGG", "N": "AAC", "D": "GAC", "C": "TGC",
        "Q": "CAG", "E": "GAG", "G": "GGC", "H": "CAC", "I": "ATC",
        "L": "CTG", "K": "AAG", "M": "ATG", "F": "TTC", "P": "CCC",
        "S": "AGC", "T": "ACC", "W": "TGG", "Y": "TAC", "V": "GTG",
        "*": "TGA",
    },
    # Saccharomyces cerevisiae
    "SC": {
        "A": "GCT", "R": "AGA", "N": "AAT", "D": "GAT", "C": "TGT",
        "Q": "CAA", "E": "GAA", "G": "GGT", "H": "CAT", "I": "ATT",
        "L": "TTG", "K": "AAA", "M": "ATG", "F": "TTT", "P": "CCA",
        "S": "TCT", "T": "ACT", "W": "TGG", "Y": "TAT", "V": "GTT",
        "*": "TAA",
    },
    # Bacillus subtilis
    "BS": {
        "A": "GCT", "R": "CGT", "N": "AAT", "D": "GAT", "C": "TGT",
        "Q": "CAA", "E": "GAA", "G": "GGT", "H": "CAT", "I": "ATT",
        "L": "TTG", "K": "AAA", "M": "ATG", "F": "TTT", "P": "CCT",
        "S": "AGC", "T": "ACA", "W": "TGG", "Y": "TAT", "V": "GTT",
        "*": "TAA",
    },
}


def _parse_fasta(text: str) -> list[tuple[str, str]]:
    """Return list of (header, sequence) from a FASTA string.

    If no '>' header is present the entire text is treated as a single
    unnamed sequence with header 'seq1'.
    """
    text = text.strip()
    if not text:
        return []
    if not text.startswith(">"):
        # Raw sequence — no headers
        seq = "".join(text.split()).upper()
        return [("seq1", seq)]

    records: list[tuple[str, str]] = []
    header: str | None = None
    parts: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith(">"):
            if header is not None:
                records.append((header, "".join(parts).upper()))
            header = line[1:].strip() or f"seq{len(records) + 1}"
            parts = []
        elif line:
            parts.append(line)
    if header is not None:
        records.append((header, "".join(parts).upper()))
    return records


def _codon_optimize(aa_seq: str, table: dict[str, str]) -> str:
    """Translate an amino-acid sequence to a codon-optimized DNA string."""
    codons: list[str] = []
    for aa in aa_seq:
        codon = table.get(aa)
        if codon is None:
            # Unknown / ambiguous residue — use NNN placeholder
            print(f"  Warning: unknown residue '{aa}' — using NNN", file=sys.stderr, flush=True)
            codons.append("NNN")
        else:
            codons.append(codon)
    return "".join(codons)


def _gc_percent(nt_seq: str) -> float:
    if not nt_seq:
        return 0.0
    gc = sum(1 for c in nt_seq.upper() if c in "GC")
    return round(100.0 * gc / len(nt_seq), 2)


def _run(inputs: dict) -> dict:
    fasta_input = str(inputs.get("sequence", "")).strip()
    organism = str(inputs.get("organism", "EC")).strip().upper()

    if not fasta_input:
        return {"error": "Input 'sequence' is required and must not be empty"}

    table = _CODON_TABLES.get(organism)
    if table is None:
        supported = ", ".join(sorted(_CODON_TABLES))
        return {"error": f"Unsupported organism '{organism}'. Supported: {supported}"}

    print(f"DNA Encoder: organism={organism}", file=sys.stderr, flush=True)

    records = _parse_fasta(fasta_input)
    if not records:
        return {"error": "Could not parse any sequences from the 'sequence' input"}

    print(f"  Encoding {len(records)} sequence(s)...", file=sys.stderr, flush=True)

    fasta_lines: list[str] = []
    gc_stats: list[dict] = []

    for header, aa_seq in records:
        if not aa_seq:
            print(f"  Warning: empty sequence for '{header}' — skipping", file=sys.stderr, flush=True)
            continue

        nt_seq = _codon_optimize(aa_seq, table)
        dna_header = f"{header}_dna"

        fasta_lines.append(f">{dna_header}")
        fasta_lines.append(nt_seq)

        gc_stats.append({
            "id": dna_header,
            "gc_percent": _gc_percent(nt_seq),
            "length_aa": len(aa_seq),
            "length_nt": len(nt_seq),
        })

        print(
            f"  {header}: {len(aa_seq)} aa → {len(nt_seq)} nt, GC={gc_stats[-1]['gc_percent']}%",
            file=sys.stderr,
            flush=True,
        )

    if not fasta_lines:
        return {"error": "All input sequences were empty"}

    print("DNA Encoder done.", file=sys.stderr, flush=True)

    return {
        "dna_sequences": "\n".join(fasta_lines),
        "gc_content": gc_stats,
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
