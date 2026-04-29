"""MoleculeKey — deterministic multi-level hash for an antibody (VH, VL) pair.

Hash chain: h1 = SHA-256(vh:vl)
            h2 = SHA-256(h1)
            h3 = SHA-256(h2)  ...

h1 (primary)  — DB primary / cache lookup key (64-char hex, collision-resistant)
h2 (shard)    — used to distribute cache across N shard files
h3+ (bloom)   — k independent bits for a bloom-filter fast-check

All lookups into the embeddings DB use MoleculeKey.primary() so a single
(VH, VL) pair always maps to the same key across runs, pipelines, and restarts.
"""
import hashlib
from typing import Any


class MoleculeKey:
    def __init__(self, vh: str, vl: str = "") -> None:
        self.vh = self._normalize(vh)
        self.vl = self._normalize(vl)
        # Compute the chain lazily up to depth 3 eagerly
        seed = f"{self.vh}:{self.vl}".encode()
        h = hashlib.sha256(seed).hexdigest()
        self._chain: list[str] = [h]
        for _ in range(2):
            h = hashlib.sha256(h.encode()).hexdigest()
            self._chain.append(h)

    # ── Normalisation ─────────────────────────────────────────────────────────

    @staticmethod
    def _normalize(seq: str) -> str:
        """Strip FASTA header, whitespace, lowercase → uppercase."""
        lines = [ln.strip() for ln in seq.splitlines() if not ln.startswith(">")]
        return "".join(lines).upper().strip()

    # ── Hash accessors ────────────────────────────────────────────────────────

    def level(self, n: int) -> str:
        """Return the nth hash in the chain (1-indexed). Extends chain on demand."""
        while len(self._chain) < n:
            h = hashlib.sha256(self._chain[-1].encode()).hexdigest()
            self._chain.append(h)
        return self._chain[n - 1]

    def primary(self) -> str:
        """64-char hex SHA-256 of (VH:VL). Use as DB key and cache lookup key."""
        return self.level(1)

    def secondary(self) -> str:
        """SHA-256 of primary — for secondary index or two-level cache."""
        return self.level(2)

    def tertiary(self) -> str:
        """SHA-256 of secondary — for tertiary structures or bloom filter seed."""
        return self.level(3)

    def shard(self, n_shards: int = 256) -> int:
        """Shard index 0..n_shards-1 for distributing cache across files."""
        return int(self.secondary()[:8], 16) % n_shards

    def bloom_bits(self, n_bits: int = 1024, k: int = 3) -> list[int]:
        """k bit positions for a Bloom filter of n_bits using independent hash levels."""
        return [int(self.level(i + 1)[:8], 16) % n_bits for i in range(k)]

    def short(self) -> str:
        """12-char truncated primary key for human-readable display."""
        return self.primary()[:12]

    # ── Convenience constructors ──────────────────────────────────────────────

    @classmethod
    def from_inputs(cls, inputs: dict[str, Any]) -> "MoleculeKey | None":
        """Build from a pipeline node inputs dict (looks for heavy_chain / sequence)."""
        vh = str(
            inputs.get("heavy_chain") or inputs.get("sequence") or ""
        ).strip()
        vl = str(inputs.get("light_chain") or "").strip()
        if not vh:
            return None
        return cls(vh, vl)

    @classmethod
    def from_node_outputs(cls, node_outputs: dict[str, dict[str, Any]]) -> "MoleculeKey | None":
        """Scan all prior node outputs for heavy_chain / light_chain sequences."""
        vh = vl = ""
        for out in node_outputs.values():
            if not vh and out.get("heavy_chain"):
                vh = str(out["heavy_chain"]).strip()
            if not vl and out.get("light_chain"):
                vl = str(out["light_chain"]).strip()
        if not vh:
            return None
        return cls(vh, vl)

    def __repr__(self) -> str:
        return f"MoleculeKey(vh={self.vh[:8]}…, vl={self.vl[:8] if self.vl else '—'}, key={self.short()})"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, MoleculeKey) and self.primary() == other.primary()

    def __hash__(self) -> int:
        return int(self.primary()[:16], 16)
