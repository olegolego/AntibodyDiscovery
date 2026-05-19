"""FASTA parsing helpers shared across embedding adapters."""


def is_multi_fasta(text: str) -> bool:
    return text.strip().startswith(">")


def parse_fasta(text: str) -> list[tuple[str, str]]:
    """Parse FASTA text into [(name, sequence), ...].

    Also handles plain sequences (no > header) — wraps them as a single entry.
    """
    text = text.strip()
    if not text:
        return []
    if not text.startswith(">"):
        return [("seq_1", text)]

    entries: list[tuple[str, str]] = []
    name = ""
    seq_parts: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(">"):
            if name:
                entries.append((name, "".join(seq_parts)))
            name = line[1:].strip() or f"seq_{len(entries) + 1}"
            seq_parts = []
        else:
            seq_parts.append(line)
    if name:
        entries.append((name, "".join(seq_parts)))
    return entries
