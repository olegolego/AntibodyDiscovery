# ESMFold — CPU-only build using HuggingFace transformers (no openfold dep needed).
# Weights (~2.7 GB) download at first request and are cached in the esmfold-cache volume.
FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl && rm -rf /var/lib/apt/lists/*

# CPU-only PyTorch 2.5 (transformers >= 4.36 requires torch >= 2.4)
RUN pip install --no-cache-dir \
    torch==2.5.0 torchvision==0.20.0 --index-url https://download.pytorch.org/whl/cpu

# transformers includes its own openfold_utils — no separate openfold install needed
RUN pip install --no-cache-dir \
    "transformers>=4.36" \
    "numpy<2.0" \
    accelerate \
    fastapi \
    "uvicorn[standard]"

COPY server.py .

EXPOSE 8080
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080"]
