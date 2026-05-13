#!/usr/bin/env python3
"""
Import OAS (Observed Antibody Space) paired human antibody sequences into the
AntibodyDiscovery dataset database.

Source: Zenodo p-IgGen dataset (https://zenodo.org/records/13880874)
  - paired_oas_human_train.csv.gz  (~1.5M sequences, 59 MB compressed)
  - paired_oas_human_val.csv.gz    (~15K sequences,  1.5 MB compressed)
  - paired_oas_human_test.csv.gz   (~20K sequences,  2.5 MB compressed)

These are the exact sequences used to train antibody language models (p-IgGen,
IgLM, AbLang-2) and are a subset of the OAS database — the same corpus that
large protein language models like ESM are trained / benchmarked on.

Usage:
    python3 scripts/import_oas_paired.py [--splits train val test] [--batch-size 5000]

Writes directly to SQLite — the backend does NOT need to be running.
"""
import argparse
import csv
import gzip
import io
import sqlite3
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError

# ── Config ────────────────────────────────────────────────────────────────────

DB_PATH = Path(__file__).parent.parent / "backend" / "protein_design.db"

ZENODO_BASE = "https://zenodo.org/api/records/13880874/files"
SPLITS = {
    "train": f"{ZENODO_BASE}/paired_oas_human_train.csv.gz/content",
    "val":   f"{ZENODO_BASE}/paired_oas_human_val.csv.gz/content",
    "test":  f"{ZENODO_BASE}/paired_oas_human_test.csv.gz/content",
}

DATASET_NAME = "OAS Paired Human Antibodies"
DATASET_DESCRIPTION = (
    "Paired human VH/VL antibody sequences from the Observed Antibody Space (OAS) "
    "database. These sequences form the training corpus for antibody language models "
    "including p-IgGen, IgLM, and AbLang-2 — the same family of models as ESM. "
    "Source: Zenodo record 13880874 (p-IgGen, Gao et al. 2024). "
    "Columns: heavy_chain = VH variable region (IMGT-aligned), "
    "light_chain = VL variable region (IMGT-aligned)."
)

# ── DB helpers ────────────────────────────────────────────────────────────────

def get_or_create_dataset(conn: sqlite3.Connection) -> str:
    cur = conn.execute(
        "SELECT id FROM datasets WHERE name = ?", (DATASET_NAME,)
    )
    row = cur.fetchone()
    if row:
        print(f"Dataset already exists: {row[0]}")
        return row[0]

    ds_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO datasets (id, name, description, columns, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (ds_id, DATASET_NAME, DATASET_DESCRIPTION, "[]", now, now),
    )
    conn.commit()
    print(f"Created dataset: {ds_id}")
    return ds_id


def count_existing(conn: sqlite3.Connection, ds_id: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM dataset_entries WHERE dataset_id = ?", (ds_id,)
    ).fetchone()
    return row[0] if row else 0


def insert_batch(conn: sqlite3.Connection, ds_id: str, rows: list[tuple]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.executemany(
        "INSERT OR IGNORE INTO dataset_entries "
        "(id, dataset_id, name, heavy_chain, light_chain, source_molecule_id, data, created_at, updated_at) "
        "VALUES (?, ?, NULL, ?, ?, NULL, '{}', ?, ?)",
        [(str(uuid.uuid4()), ds_id, vh, vl, now, now) for vh, vl in rows],
    )
    conn.commit()


# ── Download + stream ─────────────────────────────────────────────────────────

def stream_csv_gz(url: str, split_name: str):
    """Yield (vh, vl) pairs from a remote gzipped CSV, printing progress."""
    print(f"\nDownloading {split_name} from Zenodo…")
    req = Request(url, headers={"User-Agent": "AntibodyDiscovery/1.0"})
    try:
        with urlopen(req, timeout=300) as resp:
            raw = resp.read()
    except URLError as e:
        print(f"  ERROR downloading {split_name}: {e}")
        return

    print(f"  Downloaded {len(raw)/1e6:.1f} MB, decompressing…")
    data = gzip.decompress(raw)
    print(f"  Decompressed to {len(data)/1e6:.1f} MB, parsing CSV…")

    reader = csv.DictReader(io.StringIO(data.decode("utf-8", errors="replace")))
    vh_col = "sequence_alignment_aa_heavy"
    vl_col = "sequence_alignment_aa_light"

    for row in reader:
        vh = (row.get(vh_col) or "").strip()
        vl = (row.get(vl_col) or "").strip()
        if vh and vl:
            yield vh, vl


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Import OAS paired sequences")
    parser.add_argument("--splits", nargs="+", default=["val", "test", "train"],
                        choices=list(SPLITS.keys()),
                        help="Which splits to import (default: val test train)")
    parser.add_argument("--batch-size", type=int, default=5000,
                        help="Rows per SQLite batch insert (default: 5000)")
    parser.add_argument("--limit", type=int, default=None,
                        help="Cap total sequences imported (useful for testing)")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"ERROR: Database not found at {DB_PATH}")
        print("Start the backend at least once to create the schema, then re-run.")
        sys.exit(1)

    print(f"Database: {DB_PATH}")
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-64000")  # 64 MB cache

    ds_id = get_or_create_dataset(conn)
    already = count_existing(conn, ds_id)
    print(f"Existing entries in dataset: {already:,}")

    total_inserted = 0
    t0 = time.time()

    for split in args.splits:
        url = SPLITS[split]
        batch: list[tuple] = []
        split_count = 0
        split_t0 = time.time()

        for vh, vl in stream_csv_gz(url, split):
            batch.append((vh, vl))
            split_count += 1
            total_inserted += 1

            if len(batch) >= args.batch_size:
                insert_batch(conn, ds_id, batch)
                batch = []
                elapsed = time.time() - split_t0
                rate = split_count / elapsed
                print(f"  {split}: {split_count:>8,} seqs  ({rate:.0f}/s)", end="\r")

            if args.limit and total_inserted >= args.limit:
                break

        if batch:
            insert_batch(conn, ds_id, batch)

        elapsed = time.time() - split_t0
        print(f"  {split}: {split_count:>8,} sequences in {elapsed:.1f}s")

        if args.limit and total_inserted >= args.limit:
            print(f"\nReached limit of {args.limit:,} sequences.")
            break

    conn.close()

    total_elapsed = time.time() - t0
    final_count = count_existing(sqlite3.connect(str(DB_PATH)), ds_id)
    print(f"\nDone in {total_elapsed:.1f}s")
    print(f"Total sequences in dataset: {final_count:,}")


if __name__ == "__main__":
    main()
