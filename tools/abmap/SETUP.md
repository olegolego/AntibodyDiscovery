# AbMAP — Setup Guide

**What it does:** Antibody sequence embedding using AbMAP (CDR-focused mutagenesis augmentation + Bepler/Berger backbone). Returns a fixed-size embedding vector per sequence.

**Environment:** HTTP endpoint — AbMAP runs as an external server. The backend calls it via `httpx`.

---

## Requirements

- AbMAP server running and accessible (GPU recommended, CPU possible)
- `ABMAP_URL` environment variable pointing to the server

---

## Critical: ANARCI must be on PATH

AbMAP uses **ANARCI** for antibody CDR numbering. If ANARCI is not on PATH the
server starts fine but every `/embed` call fails with `"Region seems invalid"`.

ANARCI lives inside the `myenv` conda environment:
```
/Users/olegpresnyakov/opt/anaconda3/envs/myenv/bin/ANARCI
```

**Always start the server via `start.sh`**, which sets PATH correctly:
```bash
cd tools/abmap
bash start.sh
```

Do NOT start it with a bare `uvicorn server:app` unless the conda env is already
activated — the server will appear healthy but silently fail on every request.

---

## Running the AbMAP server

### Recommended — use start.sh

```bash
cd tools/abmap
bash start.sh          # starts on port 8005 by default
ABMAP_PORT=8010 bash start.sh   # custom port
```

### Option A — Local Python server (manual)

Set the env var:
```bash
export ABMAP_URL=http://localhost:8010
```

### Option B — Docker

```bash
docker build -t abmap-server tools/abmap/
docker run -p 8010:8010 --gpus all abmap-server
export ABMAP_URL=http://localhost:8010
```

*(Docker image not yet in this repo — coming soon)*

### Option C — Remote GPU instance

```bash
export ABMAP_URL=http://<gpu-instance-ip>:8010
```

---

## Backend configuration

The URL is read from `app.config.settings.abmap_url`.
Set in environment or `.env`:

```env
ABMAP_URL=http://localhost:8010
```

---

## Verify

```bash
curl -X POST $ABMAP_URL/embed \
  -H "Content-Type: application/json" \
  -d '{"sequence": "EVQLVESGGGLVQPGGSLRLSCAASGFTFS", "chain_type": "H"}'
```

Should return a JSON object with an `embedding` array.

---

## Known issues

| Issue | Fix |
|---|---|
| `Connection refused` | AbMAP server not running. Check `ABMAP_URL` and start the server |
| Timeout after 30 min | AbMAP is loading model weights on first request. Wait or pre-warm the server |
| `chain_type` errors | Valid values: `H` (heavy) or `L` (light) |
| `Region seems invalid` / 400 error | ANARCI ran but CDR numbering failed — usually means the sequence is too short (< ~100 AA) or is not a valid antibody VH/VL. Always feed a full Fv domain. Sequences from ImmuneBuilder or ProteinMPNN work fine. |
| `ANARCI: command not found` | Server started without conda env on PATH. Kill it and use `bash start.sh` instead. |
