# HADDOCK3 — Setup Guide

**What it does:** Antibody-antigen docking using HADDOCK3. Takes 15–90 min per run (CPU only).

**Environment:** Isolated venv at `tools/haddock3/.venv`. Uses Python 3.10.

---

## Requirements

- Python 3.10 (`python3.10 --version`)
- ~500 MB disk space
- macOS: `brew install openssl` recommended (needed for pip SSL cert fix)

---

## Install

```bash
# From repo root
bash tools/haddock3/setup.sh
```

The script:
1. Creates `tools/haddock3/.venv` with Python 3.10
2. Upgrades pip/setuptools/wheel
3. Fixes macOS SSL certificate issues (uses `certifi` CA bundle for pip downloads — HADDOCK3 downloads binary assets from GitHub during install)
4. Installs `haddock3==2026.3.0` and `pdb-tools==2.6.1` from `requirements.txt`
5. Verifies `haddock3 --version` and `import pdbtools`

### Manual steps (if the script fails)

```bash
python3.10 -m venv tools/haddock3/.venv
tools/haddock3/.venv/bin/pip install --upgrade pip setuptools wheel certifi

# macOS SSL fix — required for haddock-restraints binary download
CERT_PATH=$(tools/haddock3/.venv/bin/python -c "import certifi; print(certifi.where())")
SSL_CERT_FILE=$CERT_PATH REQUESTS_CA_BUNDLE=$CERT_PATH \
  tools/haddock3/.venv/bin/pip install -r tools/haddock3/requirements.txt

# Verify
tools/haddock3/.venv/bin/haddock3 --version
tools/haddock3/.venv/bin/python -c "import pdbtools; print('pdb-tools ok')"
```

---

## How it works

The backend adapter calls `tools/haddock3/run.py` via `subprocess_runner.py`:

```
backend adapter → run_tool_subprocess("haddock3", inputs, timeout)
              → tools/haddock3/.venv/bin/python tools/haddock3/run.py
              → stdin: JSON inputs
              → stdout: JSON outputs {best_complex, scores}
```

The `run.py` pipeline:
1. Clean antibody PDB with pdb-tools (renumber from 1, assign chain A)
2. Clean antigen PDB with pdb-tools (preserve original residue numbering for restraints)
3. Write CDR act-pass file from cdr1/cdr2/cdr3 residue ranges
4. Write antigen-rbm act-pass file from `antigen_active_residues` / `antigen_passive_residues`
5. Generate HADDOCK3 ambig restraints (`haddock3-restraints active_passive_to_ambig`)
6. Generate rigid-body restraints between antibody chains (`haddock3-restraints restrain_bodies`)
7. Write `docking.cfg` and run `haddock3 docking.cfg` (4 cores, local mode)
8. Parse `capri_ss.tsv` → scores dict + best complex PDB

---

## Default target (spike RBD)

The tool ships with pre-set defaults for SARS-CoV-2 spike RBD docking:
- **Antigen PDB**: `backend/app/tools/data/targets/spike_rbd.pdb` (chain B, residues 319–541)
- **Active residues**: RBM residues 438–506 (receptor binding motif)
- **Passive residues**: 345 346 347 348 351 352 405 417 420 421 422 436 437

These match `backend/app/tools/data/targets/spike_rbd.act-pass` exactly.

> **Important:** Antigen residue numbers in `antigen_active_residues` must match the PDB residue numbers *as-is*. The antigen is NOT renumbered internally (unlike the antibody which is renumbered from 1).

---

## Known issues

| Issue | Fix |
|---|---|
| `SSL: CERTIFICATE_VERIFY_FAILED` during install | Use the SSL cert fix in setup.sh. On macOS: `pip install certifi` and set `SSL_CERT_FILE` |
| `haddock3-restraints` not found | HADDOCK3 wasn't installed correctly. Re-run `setup.sh` |
| `pdb_tidy: command not found` | pdb-tools not in PATH — use full path `tools/haddock3/.venv/bin/pdb_tidy` |
| Run hangs > 90 min | Increase `timeout_seconds` in `tool.yaml` or reduce `rigid_sampling` |
| `capri_ss.tsv not found` | HADDOCK3 run failed silently. Check `run.py` stderr in backend logs |
| Antigen restraints don't match | Residue numbers in `antigen_active_residues` must match the antigen PDB *before* any renumbering |

---

## Cache

Results are cached in `tools/haddock3/cache.db` (SQLite).
HADDOCK3 runs take 15–90 min, so the cache is critical — identical inputs return instantly.
To clear: `rm tools/haddock3/cache.db`
