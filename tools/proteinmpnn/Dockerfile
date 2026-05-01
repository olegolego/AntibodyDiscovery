# ProteinMPNN — CPU-only (fast enough, ~3s per design on CPU).
# Works on Apple Silicon via Docker Desktop or natively on amd64.
FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl && rm -rf /var/lib/apt/lists/*

# CPU-only PyTorch
RUN pip install --no-cache-dir \
    torch==2.2.0 --index-url https://download.pytorch.org/whl/cpu

RUN pip install --no-cache-dir \
    "numpy<2.0" \
    fastapi \
    "uvicorn[standard]" \
    biopython

# ProteinMPNN repo — weights (~130 MB) are checked in
RUN git clone --depth 1 https://github.com/dauparas/ProteinMPNN.git /proteinmpnn

ENV PROTEINMPNN_REPO=/proteinmpnn
ENV PROTEINMPNN_PYTHON=python

COPY server.py .

EXPOSE 8080
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080"]
